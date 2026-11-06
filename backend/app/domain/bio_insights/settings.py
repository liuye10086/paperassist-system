"""B04-only ceilings. Overrides may tighten, never expand approved budgets."""
from pydantic import BaseModel, ConfigDict, Field
import hashlib
import json
import os
from pathlib import Path


class BioInsightsLimits(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    compute_wall_seconds: int = Field(default=1800, gt=0, le=1800)
    cpu_seconds: int = Field(default=1500, gt=0, le=1500)
    warmup_seconds: int = Field(default=180, gt=0, le=180)
    memory_bytes: int = Field(default=2147483648, gt=0, le=2147483648)
    address_space_bytes: int = Field(default=3221225472, gt=0, le=3221225472)
    numeric_threads: int = Field(default=1, ge=1, le=1)
    max_input_members: int = Field(default=514, gt=0, le=514)
    max_output_json_bytes: int = Field(default=2097152, gt=0, le=2097152)


INTERPRETER = '/opt/paperassist-bio-insights/bin/python'
RUNTIME_MANIFEST_ENV = 'PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST'
STAGING_DIRECTORY_ENV = 'PAPERASSIST_BIO_INSIGHTS_STAGING_DIR'


def engine_code_files():
    """All first-party code directly executable in the fixed scientific child."""
    root = Path(__file__).resolve().parents[2]
    paths=list((root/'adapters'/'bio_insights_engine').glob('*.py'))
    paths += list((root/'adapters'/'single_cell_r').glob('*.py'))+list((root/'adapters'/'single_cell_r').glob('*.R'))
    paths += [root/name for name in ('__init__.py','adapters/__init__.py','domain/__init__.py',
        'adapters/bio_engine/__init__.py','adapters/bio_engine/manifest.py','adapters/excel_sandbox.py',
        'domain/bio_insights/__init__.py','domain/bio_insights/contracts.py','domain/bio_insights/design.py','domain/bio_insights/settings.py',
        'domain/bio_insights/single_cell_composition_contracts.py','domain/bio_insights/single_cell_composition.py',
        'domain/bio_insights/single_cell_topic_contracts.py','domain/bio_insights/single_cell_topics.py',
        'adapters/single_cell_r/topics_resource.json',
        'domain/bio_insights/quantitative_contracts.py','domain/bio_insights/quantitative_design.py','domain/comparison/kernel.py',
        'domain/bio_insights/qpcr_contracts.py','domain/bio_insights/qpcr_design.py',
        'domain/bio_insights/microbiome_contracts.py','domain/bio_insights/microbiome_design.py','domain/bio_insights/feature_contracts.py','domain/bio_insights/integration_contracts.py','domain/bio_insights/evidence_contracts.py','domain/bio_insights/external_matrix.py','domain/bio_insights/evidence_graph.py','domain/bio_insights/integration_matching.py','domain/bio_insights/integration_graph.py',
        'domain/correlation/kernel.py',
        'adapters/bio_engine/tabular_assays.py','domain/bioinformatics/__init__.py','domain/bioinformatics/tabular_contracts.py',
        'domain/bioinformatics/contracts.py','domain/bioinformatics/analysis_contracts.py','domain/bioinformatics/settings.py','domain/bioinformatics/parser_contracts.py',
        'core/__init__.py','core/exceptions.py')]
    return sorted(paths,key=lambda path:path.relative_to(root).as_posix())


def engine_code_digest():
    root=Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for path in engine_code_files():
        digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def engine_lock_digest():
    path = Path(__file__).resolve().parents[3] / 'requirements-bio-insights.lock.txt'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_identity():
    """Only a fresh, complete actual Linux gate admits numerical methods."""
    blocked = {'available': False, 'reason': 'bio_insights_environment_unavailable'}
    try:
        path = Path(os.environ[RUNTIME_MANIFEST_ENV])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024**2:
            return blocked
        report = json.loads(path.read_bytes())
        if (report['schema_version'] != 1 or report['status'] != 'passed'
                or report['engine_version'] != 'bio_insights_v1.0.0'
                or report['interpreter'] != INTERPRETER or report['numeric_threads'] != 1
                or report['lock_sha256'] != engine_lock_digest()
                or report['code_digest'] != engine_code_digest()
                or report['packages']['pydeseq2'] != '0.5.4' or report['packages']['gseapy'] != '1.3.1'
                or report['isolation'] != {'network': 'denied', 'file': 'denied', 'fork': 'denied', 'subprocess': 'denied'}
                or any(report['checks'][key] is not True for key in ['aggregation', 'deseq2_fit', 'gsea'])
                or report['peak_rss_kib'] >= BioInsightsLimits().memory_bytes // 1024
                or report['limits'] != BioInsightsLimits().model_dump()):
            return blocked
        identity = {key: report[key] for key in ['engine_version', 'code_digest', 'lock_sha256']}
        environment = {key: report[key] for key in ['python', 'packages', 'native_libraries', 'lock_sha256', 'limits']}
        identity['environment_digest'] = hashlib.sha256(json.dumps(environment, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return {'available': True, **identity}
    except (KeyError, TypeError, ValueError, OSError):
        return blocked


def quantitative_runtime_identity():
    actual=runtime_identity()
    if not actual.get('available'):return actual
    try:
        checks=json.loads(Path(os.environ[RUNTIME_MANIFEST_ENV]).read_bytes())['checks']
        if all(checks.get(k) is True for k in ('quantitative_continuous','quantitative_counts')):return actual
    except (KeyError,TypeError,ValueError,OSError):pass
    return {'available':False,'reason':'bio_insights_environment_unavailable'}


def qpcr_runtime_identity():
    actual=runtime_identity()
    if not actual.get('available'):return actual
    try:
        checks=json.loads(Path(os.environ[RUNTIME_MANIFEST_ENV]).read_bytes())['checks']
        if all(checks.get(k) is True for k in ('qpcr_relative_quantification','qpcr_paired_figure','qpcr_parent_validation')):return actual
    except (KeyError,TypeError,ValueError,OSError):pass
    return {'available':False,'reason':'bio_insights_environment_unavailable'}


def microbiome_runtime_identity():
    actual=runtime_identity()
    if not actual.get('available'):return actual
    try:
        checks=json.loads(Path(os.environ[RUNTIME_MANIFEST_ENV]).read_bytes())['checks']
        if all(checks.get(k) is True for k in ('microbiome_diversity','microbiome_beta','microbiome_figures','microbiome_parent_validation')):return actual
    except (KeyError,TypeError,ValueError,OSError):pass
    return {'available':False,'reason':'bio_insights_environment_unavailable'}


def feature_runtime_identity():
    actual=runtime_identity()
    if not actual.get('available'):return actual
    try:
        report=json.loads(Path(os.environ[RUNTIME_MANIFEST_ENV]).read_bytes())
        if report['packages'].get('biopython')=='1.86' and all(report['checks'].get(k) is True for k in ('feature_sequence','feature_structure','feature_figures','feature_parent_validation')):return actual
    except (KeyError,TypeError,ValueError,OSError):pass
    return {'available':False,'reason':'bio_insights_environment_unavailable'}


def integration_runtime_identity():
    actual=runtime_identity()
    if not actual.get('available'):return actual
    try:
        checks=json.loads(Path(os.environ[RUNTIME_MANIFEST_ENV]).read_bytes())['checks']
        if all(checks.get(k) is True for k in ('integration_matching','integration_correlation','integration_concordance','integration_figures','integration_parent_validation')):return actual
    except (KeyError,TypeError,ValueError,OSError):pass
    return {'available':False,'reason':'bio_insights_environment_unavailable'}


def composition_runtime_identity():
    actual=runtime_identity()
    if not actual.get('available'):return actual
    try:
        report=json.loads(Path(os.environ[RUNTIME_MANIFEST_ENV]).read_bytes())
        if (report['checks'].get('single_cell_propeller') is True and report.get('propeller_versions')==
            {'R':'4.4.3','speckle':'1.6.0','limma':'3.62.1','statmod':'1.5.2'}):return actual
    except (KeyError,TypeError,ValueError,OSError):pass
    return {'available':False,'reason':'bio_insights_environment_unavailable'}


def topic_runtime_identity(method):
    actual=runtime_identity()
    if not actual.get('available'):return actual
    try:
        checks=json.loads(Path(os.environ[RUNTIME_MANIFEST_ENV]).read_bytes())['checks']
        if method in ('slingshot','genie3','cellchat') and checks.get('topic_'+method) is True:return actual
    except (KeyError,TypeError,ValueError,OSError):pass
    return {'available':False,'reason':'single_cell_topic_environment_unavailable'}
