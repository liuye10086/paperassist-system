"""An assigned analyst can read the plot values of a successful frozen Bulk run."""

from typing import Annotated, Literal

from pydantic import Field

from app.adapters.bio_analysis_store import BioAnalysisStore
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import conflict
from app.domain.bioinformatics.settings import BioLimits
from app.domain.runtime_skills.runtime import BULK_FIXED_PREVIEW, SkillTrace, is_enabled, load_step

from .contracts import BulkPcaPanel, FigureConfig, Hash, Identifier, StrictModel, TabularFeatureId as TabularAxisId

LIMITS = BioLimits()
BulkFixedPanel = Literal['qc_missing'] | BulkPcaPanel
Fraction = Annotated[float, Field(ge=0, le=1)]
SampleAxis = Annotated[list[TabularAxisId], Field(max_length=LIMITS.max_bulk_observations)]
MEMBER_FORMATS = {
    'qc_missing_data': 'json',
    'pca_data': 'json',
    'pca_scores': 'tsv',
    'pca_variance_ratio': 'tsv',
}
PANEL_MEMBERS = {
    'qc_missing': ('qc_missing_data',),
    'pca_scores': ('pca_scores', 'pca_variance_ratio'),
    'pca_variance': ('pca_variance_ratio',),
}


class FixedPlot(StrictModel):
    schema_version: Literal[1]
    axes: dict[str, str]
    input_member: str
    source_id: Identifier
    source_sha256: Hash
    source_members: dict[str, Hash]
    displayed_count: int = Field(ge=0)
    omitted_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    empty_reason: str | None


class QcMissing(FixedPlot):
    figure_type: Literal['bulk_qc']
    panel: Literal['qc_missing']
    sample_ids: SampleAxis | None = None
    missing_fraction: list[Fraction | None] | None = None
    status: Literal['not_computable'] | None = None
    reason: str | None = None


class PcaPlot(FixedPlot):
    figure_type: Literal['bulk_pca']
    components: list[int] = Field(max_length=100)
    variance_ratio: list[Fraction] = Field(max_length=100)


class PcaVariance(PcaPlot):
    panel: Literal['pca_variance']


class PcaScores(PcaPlot):
    panel: Literal['pca_scores']
    sample_ids: SampleAxis
    scores: list[list[float]] = Field(max_length=LIMITS.max_bulk_observations)
    condition: list[str] | None = None
    batch: list[str] | None = None
    layer: str | None = None
    semantic: str | None = None


class BulkFixedPreview(StrictModel):
    schema_version: Literal[1]
    project_id: Identifier
    processed_version_id: Identifier
    trace: SkillTrace
    plot: Annotated[QcMissing | PcaScores | PcaVariance, Field(discriminator='panel')]


def available_on_fixed_result(result):
    if not is_enabled(BULK_FIXED_PREVIEW) or result['manifest'].get('assay') != 'bulk_rna_counts':
        return False
    present = {member['key'] for member in result['members'] if member['format'] == MEMBER_FORMATS.get(member['key'])}
    return {'qc_missing_data', 'pca_scores', 'pca_variance_ratio'} <= present


def read_fixed_bulk_preview(assets, project_id, version_id, panel: BulkFixedPanel) -> BulkFixedPreview:
    bio = BioAnalysisStore(assets)
    if bio.store.assignment is None:
        raise StorageError('project_not_found', '项目不存在，请刷新项目列表。', 404)
    with bio.store.connection() as db:
        # The plots use frozen processed members. Verify raw lineage metadata
        # through the same store without reading the unused matrix bytes.
        row, manifest, records = bio.processed_record(db, project_id, version_id, verify_raw_bytes=False)
        if manifest.get('assay') != 'bulk_rna_counts':
            raise StorageError('bio_insight_source_unsupported', '请选择已完成的 Bulk RNA-seq 处理版本。', 422)
        if bio.store.require_task(db, row['task_id'])['status'] != 'succeeded':
            raise StorageError('bio_insight_source_incomplete', '此 Bulk 处理版本尚未发布。', 422)
        trace = load_step(BULK_FIXED_PREVIEW, 'qc_pca').trace
        if trace.tool.id != 'bulk_plot_data':
            raise StorageError('runtime_skills_unavailable', '固定结果读取工具无法校验，请联系管理员。', 503)
        members = _plot_members(bio, records, panel)
        source = dict(source_kind='bio_processed_dataset_version', source_id=version_id,
                      sha256=row['manifest_sha256'], metadata={'assay': manifest['assay']}, members=members)
        config = FigureConfig(result_source_id=version_id, bulk_panel=panel,
                              figure_type='bulk_qc' if panel == 'qc_missing' else 'bulk_pca')
        from app.adapters.bio_insights_engine.bulk_figures import bulk_plot_data

        try:
            plot = bulk_plot_data(source, config)
            return BulkFixedPreview.model_validate(dict(
                schema_version=1, project_id=project_id, processed_version_id=version_id, trace=trace, plot=plot,
            ))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise conflict('bio_input_integrity_changed') from exc


def _plot_members(bio, records, panel):
    by_key = {record['key']: record for record in records}
    keys = PANEL_MEMBERS[panel]
    if not all(key in by_key and by_key[key]['format'] == MEMBER_FORMATS[key] for key in keys):
        raise StorageError('bio_insight_source_incomplete', '此版本缺少固定 QC/PCA 成员，请核对原结果。', 422)
    if panel == 'pca_scores' and 'pca_data' in by_key:
        keys += ('pca_data',)
    leaves = {}
    for key in keys:
        record = by_key[key]
        if record['format'] != MEMBER_FORMATS[key]:
            raise conflict('bio_input_integrity_changed')
        if record['size_bytes'] > LIMITS.max_output_json_bytes:
            raise StorageError('bio_insight_limit_exceeded', '固定预览超过读取上限，请下载原结果。', 422)
        leaves[key] = dict(path=str(bio.objects.path(record['object_key'])),
                           sha256=record['sha256'], size_bytes=record['size_bytes'])
    return leaves
