"""Immutable plans, CAS confirmation and six-task offline publication protocol."""
import json
from app.domain.source_byte_verification import VerificationPhase, require_phase, phase_guard

from app.adapters.bio_insights_store import BioInsightsStore,base,insert,identity,invalid,now
from app.adapters.bio_analysis_store import scoped_object,object_by_key
from app.adapters.analysis_request_receipts import read_receipt,bind_receipt,target
from app.domain.bioinformatics.contracts import digest
from app.domain.bioinformatics.service import require_key,append_checkpoint
from .contracts import (BULK_CONTRAST_FIGURES, BULK_HEATMAPS, BULK_ORA_ELIGIBLE_BACKGROUND, BULK_PROCESSED_FIGURES,
                        FrozenInsightPlanRequest, InsightPlanRequest, InsightRunRequest, OraConfig, ResourceImportRequest,
                        InsightSourceSelection, SourceLocator)
from .task_contracts import InsightTaskSnapshot,input_version
from .sources import InsightSourceReader,_truth
from .design import validate_design,DesignPreview,ResourceEstimate,DesignReason

TASK_FOR_KIND={'comparison':'bio_comparison','result_import':'bio_result_import','ora':'bio_enrichment',
               'gsea_prerank':'bio_enrichment','candidate':'bio_candidate','figure':'bio_insight_figure','feature_extract':'bio_feature_extract','integration':'bio_integration'}


def portable(value):
    if isinstance(value,dict):return {key:portable(item) for key,item in value.items() if key!='path'}
    if isinstance(value,list):return [portable(item) for item in value]
    return value


def frozen_envelope_projection(envelope,frozen):
    """Compare historical derived metadata without rewriting saved sources.

    B05 added two derived axis labels to the existing Visium source projection.
    An old envelope omitted both; all original identities and other metadata
    still have to match exactly. B06 added cell_clusters/retained_feature_ids
    to single-cell projections; omit only fields absent from that old envelope.
    Already frozen fields, source identities and member hashes remain strict.
    """
    projected=portable(envelope)
    for current,previous in zip(projected.get('sources',[]),frozen.get('sources',[])):
        metadata=current.get('metadata',{});old=previous.get('metadata',{})
        identity_fields=('source_kind','source_id','role','sha256','project_id','locator')
        if (current.get('source_kind')=='bio_processed_dataset_version'
                and all(current.get(key)==previous.get(key) for key in identity_fields)
                and 'assay' not in old and 'observation_level' not in old
                and metadata.get('assay')=='visium' and metadata.get('observation_level')=='spot'):
            metadata.pop('assay');metadata.pop('observation_level')
        if (current.get('source_kind')=='bio_processed_dataset_version'
                and all(current.get(key)==previous.get(key) for key in identity_fields)
                and metadata.get('assay')==old.get('assay')=='single_cell'
                and metadata.get('observation_level')==old.get('observation_level')=='cell'):
            for field in ('cell_clusters','retained_feature_ids'):
                if field not in old:metadata.pop(field,None)
    return projected


def frozen_sources(sources):
    return [{key:source[key] for key in ('source_kind','source_id','role','sha256','project_id','locator')} for source in sources]


def source_digest(sources):return digest(frozen_sources(sources))


def reviewed_design_digest(config, design, sources):
    return digest(dict(config=config.model_dump(mode='json'), design=design.model_dump(mode='json'), sources=source_digest(sources)))


def inherit_heatmap_metadata(config,sources):
    """Only an established canonical lineage can supply missing declarations."""
    if config.kind!='figure' or config.figure_type not in ('heatmap','distribution'):return
    processed=next(s for s in sources if s['source_kind']=='bio_processed_dataset_version' and s['source_id']==config.processed_source_id)
    result=next(s for s in sources if s['source_kind']=='bio_insight_result_version' and s['source_id']==config.result_source_id)
    meta=processed['metadata'];upstream=result['metadata']
    if meta.get('canonical_dataset_id') not in upstream.get('canonical_dataset_ids',[]):
        raise invalid('bio_insight_source_conflict',422)
    for field in ('species_taxon_id','namespace','reference_version'):
        declared=upstream.get(field)
        if (declared is None and not (meta.get('observation_level')=='sample' and field=='species_taxon_id' and meta.get(field) is None)) or meta.get(field) is not None and meta[field]!=declared:
            raise invalid('bio_insight_source_conflict',422)
        if meta.get(field) is None:meta[field]=declared
    meta['reference_metadata_origin']='linked_frozen_comparison'


def preview_bulk_display(config, source):
    from .bulk_results import is_reviewed_bulk

    metadata = source['metadata']
    members = source['members']
    reasons = []
    selection = config.bulk_selection
    if config.kind == 'figure' and config.figure_type in BULK_PROCESSED_FIGURES:
        if (source['source_kind'] != 'bio_processed_dataset_version' or metadata.get('assay') != 'bulk_rna_counts'
                or metadata.get('observation_level') != 'sample' or metadata.get('manifest', {}).get('schema_version') != 2):
            reasons.append(DesignReason(code='bulk_processed_source_required', message='重绘需要固定的 Bulk 样本质控结果。'))
        else:
            panel = config.bulk_panel
            required = {
                'qc_missing': {'qc_missing_data'}, 'qc_expression': {'expression_distribution_data'},
                'sample_clustering': set(), 'sample_correlation': {'sample_correlation'},
                'sample_distance': {'sample_distance'}, 'pca_scores': {'pca_scores', 'pca_variance_ratio'},
                'pca_variance': {'pca_variance_ratio'},
            }[panel]
            has_values = required <= members.keys()
            if panel == 'sample_clustering':
                has_values = 'sample_clustering_data' in members or (
                    'sample_clustering' in members and not any(InsightSourceReader.read_rows(members['sample_clustering'])))
            if panel == 'pca_scores' and has_values and 'pca_data' not in members:
                has_values = not any(InsightSourceReader.read_rows(members['pca_scores']))
            if not has_values:
                reasons.append(DesignReason(code='bulk_plot_data_unavailable', message='这个固定版本缺少该图所需的保存数值。'))
    elif source['source_kind'] != 'bio_insight_result_version' or not is_reviewed_bulk(metadata):
        reasons.append(DesignReason(code='bulk_comparison_source_required', message='请选择已发布的 Bulk 共享模型差异结果。'))
    else:
        contrasts = {contrast['contrast_id'] for contrast in metadata['plan_config']['contrasts']}
        if selection.contrast_id not in contrasts:
            reasons.append(DesignReason(code='contrast_not_found', message='所选比较 ID 不存在于该固定结果版本。'))
        required = {'comparison_results'}
        if config.kind == 'figure' and (config.figure_type in BULK_HEATMAPS or config.figure_type == 'bulk_expression'):
            required.update(('comparison_design', 'model_normalized_counts', 'model_sample_metadata'))
        if not required <= members.keys():
            reasons.append(DesignReason(code='bulk_plot_data_unavailable', message='这个固定版本缺少所需的完整比较表或模型数值。'))
        elif config.kind == 'figure' and config.figure_type == 'bulk_expression' and not reasons:
            feature = config.feature_ids[0]
            if not any(row['contrast_id'] == selection.contrast_id and row['feature_id'] == feature
                       for row in InsightSourceReader.read_rows(members['comparison_results'])):
                reasons.append(DesignReason(code='bulk_plot_feature_not_found', message='该基因 ID 不在所选固定比较中。'))
    estimate = ResourceEstimate(observations=0, features=0, contrasts=int(selection is not None), estimated_working_bytes=0)
    return DesignPreview(executable=not reasons, blocking_reasons=reasons, resource_estimate=estimate)


class BioInsightsService(BioInsightsStore):
    def reader(self):return InsightSourceReader(self.assets)

    def _resolve(self,db,project,request,progress=None,*,phase=None,lineage_only=False):
        selections=list(request.sources)
        if request.kind=='result_import' or getattr(request.config,'schema_version',None)==3:
            for index,selection in enumerate(selections):
                if selection.source_kind=='original_file' and selection.source_id==request.config.file_source_id:
                    data=selection.model_dump(mode='json');data['locator']['parse_version_id']=request.config.parse_version_id
                    selections[index]=InsightSourceSelection.model_validate(data)
        if phase is None:sources=self.reader().resolve_many(db,project,selections,request.config,progress)
        else:
            require_phase(phase,db,self.assets,project)
            sources=self.reader()._resolve_many_in_phase(db,project,selections,request.config,progress,phase=phase,lineage_only=lineage_only)
        inherit_heatmap_metadata(request.config,sources)
        if request.kind=='result_import' or getattr(request.config,'schema_version',None)==3:
            source=next(s for s in sources if s['source_kind']=='original_file' and s['source_id']==request.config.file_source_id)
            source['metadata']['sheet']=request.config.sheet
            parsed_headers=source['metadata'].get('parse_summary',{}).get('headers')
            if parsed_headers and not {v for v in request.config.columns.model_dump().values() if v}<=set(parsed_headers):
                raise invalid('bio_insight_column_mapping_invalid',422)
            if source['members']['original_file']['format']=='xlsx':
                from openpyxl import load_workbook
                workbook=load_workbook(source['members']['original_file']['path'],read_only=True,data_only=False,keep_links=False)
                try:
                    if request.config.sheet not in workbook.sheetnames:raise invalid('bio_insight_sheet_invalid',422)
                    header=next(workbook[request.config.sheet].iter_rows(min_row=1,max_row=1,values_only=True),())
                    if not {v for v in request.config.columns.model_dump().values() if v}<=set(header):raise invalid('bio_insight_column_mapping_invalid',422)
                finally:workbook.close()
        if request.kind=='candidate' and getattr(request.config,'schema_version',None)==2:
            for source in sources:
                if source['source_kind']=='bio_insight_result_version':
                    row=self.require(db,'bio_insight_result_versions',project,source['source_id'])
                    source['metadata'].update(run_id=row['run_id'],task_status=self.store.require_task(db,row['task_id'])['status'])
        return sources

    def _design(self,config,sources):
        if getattr(config, 'bulk_enrichment', None) is not None:
            from .bulk_enrichment import preview_bulk_enrichment
            return preview_bulk_enrichment(config, sources)
        if config.kind == 'figure' and config.figure_type in BULK_CONTRAST_FIGURES | BULK_PROCESSED_FIGURES:
            return preview_bulk_display(config, sources[0])
        if config.kind == 'candidate' and getattr(config, 'bulk_selection', None) is not None:
            return preview_bulk_display(config, sources[0])
        if config.kind=='integration' and getattr(config,'schema_version',None)==2:
            from .single_cell_topics import validate_topic_design
            return validate_topic_design(config,sources)
        if config.kind=='candidate' and getattr(config,'schema_version',None)==2:
            from .evidence_design import validate_evidence_design
            return validate_evidence_design(config,sources)
        if config.kind=='figure' and config.figure_type.startswith('evidence_'):
            source=next(s for s in sources if s['source_id']==config.result_source_id)
            reasons=[] if 'evidence_data' in source['members'] else [DesignReason(code='fixed_evidence_matrix_required',message='需要固定候选证据矩阵。')]
            return DesignPreview(executable=not reasons,blocking_reasons=reasons,resource_estimate=ResourceEstimate(observations=0,features=0,contrasts=0,estimated_working_bytes=0))
        if config.kind=='comparison' and getattr(config,'schema_version',None)==5:
            from .single_cell_composition import validate_composition_design
            return validate_composition_design(config,sources)
        if config.kind=='comparison' and getattr(config,'schema_version',None)==4:
            from .microbiome_design import validate_microbiome_design
            return validate_microbiome_design(config,sources)
        if config.kind=='comparison' and getattr(config,'schema_version',None)==3:
            from .qpcr_design import validate_qpcr_design
            return validate_qpcr_design(config,sources)
        if config.kind=='comparison' and getattr(config,'schema_version',None)==2:
            from .quantitative_design import validate_quantitative_design
            return validate_quantitative_design(config,sources)
        if config.kind=='comparison':
            if config.single_cell_selection:
                from .single_cell_composition import validate_de_selection
                try:validate_de_selection(config,sources)
                except ValueError as exc:
                    return DesignPreview(executable=False,blocking_reasons=[DesignReason(code=str(exc),message='同类型供者比较必须来自固定人工标签的保留细胞。')],resource_estimate=ResourceEstimate(observations=0,features=0,contrasts=len(config.contrasts),estimated_working_bytes=0))
            observations=[];features=[];resolved=[]
            for source in sources:
                if source['source_kind']!='bio_processed_dataset_version':continue
                meta=source['metadata'];observations.extend(meta['observations'])
                feature_rows=list(self.reader().read_rows(source['members']['features']))
                genes=[r for r in feature_rows if r.get('feature_type')=='Gene Expression']
                eligible=[r for r in genes if _truth(r.get('kept'))] if config.mode=='spot_exploratory' else genes
                axis={r['feature_id'] for r in eligible}
                if any(not isinstance(r['feature_id'],str) or not r['feature_id'] for r in eligible) or len(axis)!=len(eligible):
                    raise invalid('bio_insight_source_conflict',422)
                resolved.append((source,eligible,axis))
            # Metadata carries the raw common axis for other consumers. Admission
            # must mirror the actual mode: filtered processed genes for spot,
            # all raw Gene Expression genes for donor pseudobulk.
            common=set.intersection(*(axis for _,_,axis in resolved)) if resolved else set()
            for source,feature_rows,axis in resolved:
                meta=source['metadata'];nfeatures=len(axis)
                # An admission upper bound, independently recomputed on selected
                # raw counts by the engine; never a substitute for actual filtering.
                potentially_tested=(nfeatures if config.mode=='spot_exploratory' else
                    sum(int(r.get('total_counts') or '0')>=config.minimum_total_counts for r in feature_rows))
                features.append(dict(processed_version_id=source['source_id'],species_taxon_id=meta['species_taxon_id'],namespace=meta['namespace'],
                    reference_version=meta['reference_version'],canonical_dataset_id=meta['canonical_dataset_id'],feature_count=nfeatures,
                    counts_nonnegative_integer=True,counts_provenance='raw_gene_expression',filtered_feature_count=potentially_tested,
                    common_feature_count=len(common)))
            preview=validate_design(config,observations,features)
            axis_warning=('空间探索使用固定处理结果已保留的 Gene Expression 共同特征轴，不重跑预处理或应用供体 counts 预过滤。'
                if config.mode=='spot_exploratory' else
                '元数据特征预过滤数量为全输入上界；引擎仍将按选定观测检查真实counts及可计算特征。')
            warnings=list(preview.warnings)+[axis_warning]
            if any(s.get('metadata',{}).get('reference_metadata_origin') for s in sources):
                warnings.append('上游缺少的物种/命名空间/参考版本使用当前计划显式声明；软件不据基因名称猜测物种。')
            if config.mode=='spot_exploratory' and any(s.get('metadata',{}).get('assay')=='single_cell' for s in sources):
                return preview.model_copy(update={'executable':False,'blocking_reasons':list(preview.blocking_reasons)+[DesignReason(code='single_cell_requires_donor_contrast',message='单细胞比较请选择明确供体设计；QC/聚类/marker 探索仍可用。')],'warnings':warnings})
            return preview.model_copy(update={'warnings':warnings})
        reasons=[]
        if config.kind=='integration':
            from .integration_design import validate_integration_design
            return validate_integration_design(config,sources)
        if config.kind=='feature_extract':
            selected={s.resource_source_id for s in config.structure_selections}
            for source in sources:
                if source['source_id'] not in config.resource_source_ids:continue
                kind=source['metadata'].get('kind')
                if kind not in ('sequence','structure') or (kind=='structure')!=(source['source_id'] in selected):
                    reasons.append(DesignReason(code='feature_input_selection_required',message='FASTA 需要序列资源；结构资源需显式选择单个 model 和 author chain。'))
            return DesignPreview(executable=not reasons,blocking_reasons=reasons,resource_estimate=ResourceEstimate(observations=0,features=0,contrasts=0,estimated_working_bytes=0),warnings=['提取为描述性特征；不推断功能、P 值、疾病效应或生物学验证。'])
        results=[s['metadata'] for s in sources if s['source_kind']=='bio_insight_result_version']
        resources=[s['metadata'] for s in sources if s['source_kind']=='bio_resource_version']
        if config.kind in ('ora','gsea_prerank','candidate'):
            taxa={s.get('species_taxon_id') for s in results+resources}-{None}
            exact_sample_identity=config.kind=='candidate' and not resources and all(s.get('inference_scope') in ('sample_inference','sample_exploratory') for s in results) and len({(s.get('species_taxon_id'),s.get('namespace'),s.get('reference_version')) for s in results})==1
            if not exact_sample_identity and (any(s.get('species_taxon_id') is None for s in results+resources) or len(taxa)!=1):
                reasons.append(DesignReason(code='incompatible_species',message='所选结果和资源必须具有明确且相同的物种 taxon ID。'))
            for result in results:
                for resource in [r for r in resources if r.get('kind')=='gene_sets']:
                    if result.get('namespace')!=resource.get('namespace'):
                        mappings=[r for r in resources if r.get('kind')=='id_mapping' and r.get('mapping_source_namespace')==result.get('namespace') and r.get('mapping_target_namespace')==resource.get('namespace')]
                        if not mappings:reasons.append(DesignReason(code='namespace_mapping_required',message='结果和基因集命名空间不同，需要固定且方向匹配的 ID 映射资源。'))
            for source in [s for s in sources if s['source_kind']=='bio_insight_result_version']:
                meta=source['metadata'];plan=meta.get('plan_config',{})
                if config.kind=='candidate' and source['source_id'] in config.annotation_source_ids:
                    if meta['kind']!='feature_extract' or 'resource' not in source['members']:
                        reasons.append(DesignReason(code='feature_annotation_result_required',message='结果型注释来源必须是已发布的实际特征提取结果。'))
                    continue
                if meta['kind'] not in ('comparison','result_import'):
                    reasons.append(DesignReason(code='incompatible_result_kind',message='该计算需要完整差异或外部差异结果，不能把其他结果当作差异全集。'))
                    continue
                available={c['contrast_id'] for c in plan.get('contrasts',[])} if meta['kind']=='comparison' else {plan.get('contrast_id')}
                wanted=([config.source_contrasts[source['source_id']]] if config.kind=='candidate' else
                        [config.contrast_id] if config.kind=='gsea_prerank' else list(config.contrast_ids))
                if not set(wanted)<=available:reasons.append(DesignReason(code='contrast_not_found',message='所选比较 ID 不存在于该固定结果版本。'))
        if config.kind=='figure' and config.figure_type.startswith('topic_'):
            selected=next(s for s in sources if s['source_id']==config.result_source_id)
            plan=selected['metadata'].get('plan_config',{})
            if selected['metadata'].get('kind')!='integration' or plan.get('schema_version')!=2 or plan.get('method')!=config.figure_type.removeprefix('topic_') or 'topic_plot_data' not in selected['members']:
                reasons.append(DesignReason(code='topic_result_required',message='专题重绘需要匹配方法及保存绘图数值的固定结果。'))
        if config.kind=='figure' and config.figure_type.startswith('integration_'):
            selected=next(s for s in sources if s['source_id']==config.result_source_id)
            if selected['metadata'].get('kind')!='integration':reasons.append(DesignReason(code='integration_result_required',message='来源图需要固定的整合结果。'))
        if config.kind=='figure' and config.figure_type.startswith('feature_'):
            selected=next(s for s in sources if s['source_id']==config.result_source_id)
            if selected['metadata'].get('kind')!='feature_extract':reasons.append(DesignReason(code='feature_result_required',message='特征图需要固定的实际提取结果。'))
        if config.kind=='figure' and config.figure_type.startswith('microbiome_'):
            selected=next(s for s in sources if s['source_kind']=='bio_insight_result_version' and s['source_id']==config.result_source_id)
            if selected['metadata'].get('plan_config',{}).get('schema_version')!=4:reasons.append(DesignReason(code='microbiome_result_required',message='微生物组图件仅承接固定微生物组配方结果。'))
        if config.kind=='figure' and config.figure_type=='volcano':
            selected=next(s for s in sources if s['source_kind']=='bio_insight_result_version' and s['source_id']==config.result_source_id)
            upstream=selected['metadata'].get('plan_config',{})
            if upstream.get('design')=='multiple' and not upstream.get('bulk_model'):
                reasons.append(DesignReason(code='omnibus_has_no_direction',message='多组 omnibus 没有单一方向效应，不能绘制方向火山图。'))
        if config.kind == 'figure' and config.bulk_enrichment_render:
            selected = next(s for s in sources if s['source_id'] == config.result_source_id)
            meta = selected['metadata']
            if (meta.get('kind') not in ('ora', 'gsea_prerank')
                    or meta.get('plan_config', {}).get('bulk_enrichment') is None
                    or 'enrichment_results' not in selected['members']):
                reasons.append(DesignReason(code='bulk_enrichment_result_required',
                                            message='请从固定 Bulk ORA 或 GSEA 结果打开重绘。'))
            elif config.figure_type == 'enrichment':
                audit = meta['methods_json']['bulk_enrichment']
                eligible = {row['contrast_id'] for row in audit['coverage']
                            if row.get('eligible_term_count', 0) > 0
                            or any(item['eligible_term_count'] > 0 for item in row.get('resources', {}).values())}
                if config.contrast_id not in eligible and (config.contrast_id is not None or len(eligible) != 1):
                    reasons.append(DesignReason(code='bulk_enrichment_figure_contrast_unavailable',
                                                message='请选择有已计算富集条目的固定比较绘图。'))
        if config.kind=='figure' and config.figure_type=='gsea':
            selected=next(s for s in sources if s['source_kind']=='bio_insight_result_version' and s['source_id']==config.result_source_id)
            member=selected['members'].get('enrichment_results')
            frozen_contrast = selected['metadata'].get('plan_config', {}).get('contrast_id')
            if selected['metadata'].get('kind')!='gsea_prerank' or not member:
                reasons.append(DesignReason(code='incompatible_result_kind',message='GSEA 曲线需要固定的 GSEA prerank 结果与完整 term 表。'))
            elif config.bulk_enrichment_render and (
                    not {'gsea_ranking', 'gsea_curves'} <= selected['members'].keys()
                    or config.contrast_id not in (None, frozen_contrast)):
                reasons.append(DesignReason(code='bulk_enrichment_figure_contrast_unavailable',
                                            message='GSEA 曲线需要所属比较及完整排名和曲线数据。'))
            elif not any(row.get('row_key') == config.term_row_key
                         and (not config.bulk_enrichment_render or row.get('contrast_id') == frozen_contrast)
                         for row in InsightSourceReader.read_rows(member)):
                reasons.append(DesignReason(code='term_not_found',message='所选 term 稳定行键不存在于该固定 GSEA 结果。'))
        return DesignPreview(executable=not reasons,blocking_reasons=reasons,resource_estimate=ResourceEstimate(observations=0,features=0,contrasts=0,estimated_working_bytes=0))

    def _authoring_design(self, config, sources):
        if config.kind in ('ora', 'gsea_prerank') and config.bulk_enrichment is None:
            from .bulk_results import is_reviewed_bulk
            if any(source['source_kind'] == 'bio_insight_result_version' and is_reviewed_bulk(source['metadata'])
                   for source in sources):
                return DesignPreview(executable=False, blocking_reasons=[DesignReason(
                    code='bulk_enrichment_use_fixed_entry', message='请从固定 Bulk 差异结果打开 ORA 或 GSEA。')],
                    resource_estimate=ResourceEstimate(observations=0, features=0, contrasts=0, estimated_working_bytes=0))
        return self._design(config, sources)

    @staticmethod
    def _authoring_transform(request):
        config = request.config
        if getattr(config, 'bulk_model', None):
            transform = ('centered_range_v2'
                if any(c.kind == 'continuous' for c in config.covariates) else None)
            request = request.model_copy(update={'config': config.model_copy(update={'continuous_transform': transform})})
        elif isinstance(config, OraConfig) and config.bulk_enrichment is not None:
            config = config.model_copy(update={'bulk_background': BULK_ORA_ELIGIBLE_BACKGROUND})
            request = request.model_copy(update={'config': config})
        return request

    def preview(self,project,request):
        request=self._authoring_transform(InsightPlanRequest.model_validate(request))
        with self.store.connection() as db:
            sources=self._resolve(db,project,request)
            design=self._authoring_design(request.config,sources)
        review = {}
        if getattr(request.config,'bulk_model',None) and design.executable:
            review['reviewed_design_sha256'] = reviewed_design_digest(request.config, design, sources)
        return {**design.model_dump(mode='json'),**review,'source_digest':source_digest(sources),'sources':frozen_sources(sources),
                'output_language':request.config.output_language,'real_model_calls':False,'real_network_calls':False}

    def create_plan(self,project,request,key,plan_id=None):
        request=InsightPlanRequest.model_validate(request);require_key(key)
        material=request.model_dump(mode='json');sha=digest(dict(operation='plan',plan_id=plan_id,request=material))
        identifier=identity(project,'plan-version',key)
        with self.store.connection(write=True) as db:
            self.lock(db,project,'plan:'+str(plan_id or key))
            replay=db.execute('SELECT * FROM bio_insight_plan_versions WHERE project_id=%s AND user_id=%s AND request_key=%s',
                (project,self.store.user_id,key)).fetchone()
            if replay:
                if replay['request_digest']!=sha:raise invalid('bio_insight_idempotency_conflict')
                selected=replay['id'];root=replay['plan_id'];status=200
            else:
                request=self._authoring_transform(request)
                sources=self._resolve(db,project,request);design=self._authoring_design(request.config,sources)
                review={}
                if request.decision=='confirmed':
                    if not design.executable:raise invalid('bio_insight_design_blocked',422)
                    if getattr(request.config,'bulk_model',None):
                        if not request.reviewed_design_sha256:raise invalid('bio_insight_plan_unconfirmed',422)
                        if request.reviewed_design_sha256!=reviewed_design_digest(request.config,design,sources):
                            raise invalid('bio_insight_revision_conflict')
                        review['reviewed_design_sha256']=request.reviewed_design_sha256
                if plan_id:
                    rootrow=self.require(db,'bio_insight_plans',project,plan_id)
                    if rootrow['revision']!=request.expected_revision or rootrow['kind']!=request.kind:raise invalid('bio_insight_revision_conflict')
                    version=rootrow['revision']+1;parent=rootrow['current_version_id'];root=plan_id
                else:
                    if request.expected_revision!=0:raise invalid('bio_insight_revision_conflict')
                    root=identity(project,'plan-root',key);version=1;parent=None
                    insert(db,'bio_insight_plans',{**base(root,project,self.store.user_id),'kind':request.kind,'name':request.name,
                        'revision':1,'current_version_id':None,'updated_at':now()})
                insert(db,'bio_insight_plan_versions',{**base(identifier,project,self.store.user_id),'plan_id':root,'version':version,'parent_id':parent,
                    'kind':request.kind,'decision':request.decision,'config_json':request.config.model_dump(mode='json'),
                    'config_sha256':digest(request.config.model_dump(mode='json')),'design_checks_json':{**design.model_dump(mode='json'),**review,'plan_name':request.name},
                    'confirmed_by':self.store.user_id if request.decision=='confirmed' else None,'confirmed_at':now() if request.decision=='confirmed' else None,
                    'request_key':key,'request_digest':sha})
                for ordinal,source in enumerate(sources):self.bind(db,project,identifier,source,ordinal)
                changed=db.execute('UPDATE bio_insight_plans SET current_version_id=%s,revision=%s,name=%s,updated_at=%s WHERE id=%s AND revision=%s',
                    (identifier,version,request.name,now(),root,request.expected_revision if plan_id else 1))
                if changed.rowcount!=1:raise invalid('bio_insight_revision_conflict')
                selected=identifier;status=201
        return self.get_plan(project,root,selected),status

    def _plan_request(self,db,project,row):
        if digest(row['config_json'])!=row['config_sha256']:raise invalid()
        root=self.require(db,'bio_insight_plans',project,row['plan_id'])
        bindings=db.execute('SELECT * FROM bio_insight_plan_sources WHERE plan_version_id=%s AND project_id=%s AND user_id=%s ORDER BY ordinal',
            (row['id'],project,self.store.user_id)).fetchall()
        selections=[dict(source_kind=b['source_kind'],source_id=b['source_id'],role=b['role'],sha256=b['source_sha256'],locator=b['locator_json']) for b in bindings]
        return FrozenInsightPlanRequest(name=row['design_checks_json'].get('plan_name',root['name']),kind=row['kind'],decision=row['decision'],expected_revision=root['revision'],sources=selections,config=row['config_json']),root

    def get_plan(self,project,plan_id,version_id):
        with self.store.connection() as db:
            row=self.require(db,'bio_insight_plan_versions',project,version_id)
            if row['plan_id']!=plan_id:raise invalid('bio_insight_not_found',404)
            request,root=self._plan_request(db,project,row)
            sources=self._resolve(db,project,request)
            return dict(id=row['id'],plan_id=plan_id,version=row['version'],revision=row['version'],current_revision=root['revision'],
                parent_id=row['parent_id'],kind=row['kind'],name=request.name,decision=row['decision'],config=row['config_json'],
                config_sha256=row['config_sha256'],sources=frozen_sources(sources),source_digest=source_digest(sources),
                design=row['design_checks_json'],design_checks=row['design_checks_json'],confirmed_by=row['confirmed_by'],confirmed_at=row['confirmed_at'])

    def list_plans(self,project,page=1,page_size=20):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            total=db.execute('SELECT count(*) AS n FROM bio_insight_plans WHERE project_id=%s AND user_id=%s',(project,self.store.user_id)).fetchone()['n']
            rows=db.execute('SELECT id,current_version_id FROM bio_insight_plans WHERE project_id=%s AND user_id=%s ORDER BY updated_at DESC,id LIMIT %s OFFSET %s',
                (project,self.store.user_id,page_size,(page-1)*page_size)).fetchall()
        return dict(items=[self.get_plan(project,r['id'],r['current_version_id']) for r in rows],total=total,page=page,page_size=page_size)

    def _runtime(self):
        from .settings import runtime_identity
        runtime=runtime_identity()
        if not runtime['available']:raise invalid('bio_insights_environment_unavailable',422)
        return {key:runtime[key] for key in ('engine_version','environment_digest','code_digest','lock_sha256')}

    def _runtime_for(self,config):
        if config.kind=='integration' and getattr(config,'schema_version',None)==2:
            from .settings import topic_runtime_identity
            runtime=topic_runtime_identity(config.method)
            if not runtime.get('available'):raise invalid('bio_insights_environment_unavailable',422)
            return {key:runtime[key] for key in ('engine_version','environment_digest','code_digest','lock_sha256')}
        if config.kind=='figure' and 'pdf' in config.formats:
            raise invalid('bio_figure_pdf_export_retired',422)
        from .settings import runtime_identity, uses_bulk_display_runtime, uses_bulk_enrichment_runtime
        wire = config.model_dump(mode='json')
        bulk_enrichment = uses_bulk_enrichment_runtime(wire)
        if bulk_enrichment or uses_bulk_display_runtime(wire):
            runtime = runtime_identity(bulk_enrichment=True) if bulk_enrichment else runtime_identity(bulk_display=True)
            if not runtime.get('available'):
                raise invalid('bio_insights_environment_unavailable', 422)
            return {key: runtime[key] for key in ('engine_version','environment_digest','code_digest','lock_sha256')}
        if config.kind in ('integration','sample_correspondence','object_correspondence') or config.kind=='figure' and config.figure_type.startswith('integration_'):
            from .settings import integration_runtime_identity
            runtime=integration_runtime_identity()
            if not runtime.get('available'):raise invalid('bio_insights_environment_unavailable',422)
            return {key:runtime[key] for key in ('engine_version','environment_digest','code_digest','lock_sha256')}
        elif config.kind in ('feature_extract','sequence','structure') or config.kind=='figure' and config.figure_type.startswith('feature_'):
            from .settings import feature_runtime_identity
            runtime=feature_runtime_identity()
            if not runtime.get('available'):raise invalid('bio_insights_environment_unavailable',422)
            return {key:runtime[key] for key in ('engine_version','environment_digest','code_digest','lock_sha256')}
        if config.kind=='comparison' and getattr(config,'schema_version',None)==5:
            from .settings import composition_runtime_identity
            runtime=composition_runtime_identity()
            if not runtime.get('available'):raise invalid('bio_insights_environment_unavailable',422)
            return {key:runtime[key] for key in ('engine_version','environment_digest','code_digest','lock_sha256')}
        if config.kind=='comparison' and getattr(config,'schema_version',None)==4 or config.kind=='figure' and config.figure_type.startswith('microbiome_'):
            from .settings import microbiome_runtime_identity
            runtime=microbiome_runtime_identity()
            if not runtime.get('available'):raise invalid('bio_insights_environment_unavailable',422)
            return {key:runtime[key] for key in ('engine_version','environment_digest','code_digest','lock_sha256')}
        if config.kind=='comparison' and getattr(config,'schema_version',None)==3 or config.kind=='figure' and config.figure_type=='qpcr_samples':
            from .settings import qpcr_runtime_identity
            runtime=qpcr_runtime_identity()
            if not runtime.get('available'):raise invalid('bio_insights_environment_unavailable',422)
            return {key:runtime[key] for key in ('engine_version','environment_digest','code_digest','lock_sha256')}
        if config.kind=='comparison' and getattr(config,'schema_version',None)==2:
            from .settings import quantitative_runtime_identity
            runtime=runtime_identity(bulk_model=True) if config.bulk_model else quantitative_runtime_identity()
            if not runtime.get('available'):raise invalid('bio_insights_environment_unavailable',422)
            return {key:runtime[key] for key in ('engine_version','environment_digest','code_digest','lock_sha256')}
        return self._runtime()

    def _new_task(self,db,project,task_id,task_type,snapshot,file_ids):
        task=dict(id=task_id,project_id=project,user_id=self.store.user_id,task_type=task_type,idempotency_key=task_type+':'+task_id,
            input_digest=digest(snapshot),input_snapshot=snapshot,workflow_version=snapshot['workflow_version'],status='queued',phase='compute',revision=1,
            current_attempt=0,reason_code=None,created_at=now(),updated_at=now())
        self.store.insert_task(db,task,validated_file_ids=file_ids)
        append_checkpoint(db,task,'check','check',dict(input_version=input_version(task),stage='check'))
        self.store.append_event(db,task,'created');self.store.enqueue(db,task,validated_file_ids=file_ids)
        return task

    def create_run(self,project,request,key):
        request=InsightRunRequest.model_validate(request);require_key(key)
        sha=digest(request.model_dump(mode='json'));identifier=identity(project,'run',key)
        with self.store.connection(write=True) as db:
            self.lock(db,project,'run:'+key)
            replay=db.execute('SELECT * FROM bio_insight_runs WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            if not replay:
                receipt=read_receipt(db,user_id=self.store.user_id,project_id=project,kind='bio_insight_run',key=key,request_digest=sha)
                if receipt:
                    replay=target(db,user_id=self.store.user_id,project_id=project,kind='bio_insight_run',target_id=receipt['target_id'])
                    replay['request_digest']=receipt['request_digest']
            if replay:
                if replay['request_digest']!=sha:raise invalid('bio_insight_idempotency_conflict')
                selected=replay['id'];status=200
            else:
                row=self.require(db,'bio_insight_plan_versions',project,request.plan_version_id)
                planned,root=self._plan_request(db,project,row)
                if planned.config.kind=='figure' and 'pdf' in planned.config.formats:
                    raise invalid('bio_figure_pdf_export_retired',422)
                if row['decision']!='confirmed':raise invalid('bio_insight_plan_unconfirmed',422)
                if root['revision']!=request.expected_plan_revision:raise invalid('bio_insight_revision_conflict')
                sources=self._resolve(db,project,planned);source_sha=source_digest(sources)
                if source_sha!=request.source_digest:raise invalid()
                design=self._design(planned.config,sources)
                if not design.executable:raise invalid('bio_insight_design_blocked',422)
                if getattr(planned.config,'bulk_model',None) and (
                    root['current_version_id']!=row['id'] or
                    row['design_checks_json'].get('reviewed_design_sha256')!=reviewed_design_digest(planned.config,design,sources)
                ):raise invalid('bio_insight_revision_conflict')
                runtime=self._runtime_for(planned.config);task_type=TASK_FOR_KIND[row['kind']];task_id=identity(project,'run-task',key)
                from .settings import BioInsightsLimits
                limits=BioInsightsLimits().model_dump()
                signature=dict(plan_version_id=row['id'],source_digest=source_sha,config=planned.config.model_dump(mode='json'),runtime=runtime,limits=limits)
                self.lock(db,project,'run-content:'+digest(signature))
                reused=self._reusable_run(db,project,row,sources,runtime,limits)
                if reused:
                    bind_receipt(db,user_id=self.store.user_id,project_id=project,kind='bio_insight_run',key=key,request_digest=sha,target_id=reused['id'])
                    selected=reused['id'];status=200
                else:
                    selected=None
                envelope=dict(schema_version=1,kind=task_type,config=planned.config.model_dump(mode='json'),
                    identity=dict(project_id=project,task_id=task_id,run_id=identifier,plan_version_id=row['id'],source_digest=source_sha,
                        config_sha256=row['config_sha256'],execution_limits=limits,**runtime),sources=sources)
                if selected is None:
                    obj=self.write_document(db,project,identifier,'execution_snapshot',portable(envelope))
                    snapshot=InsightTaskSnapshot(kind=task_type,workflow_version='bio_comparison_microbiome_v1' if getattr(planned.config,'schema_version',None)==4 else 'bio_comparison_qpcr_v1' if getattr(planned.config,'schema_version',None)==3 else 'bio_comparison_v2' if row['kind']=='comparison' and getattr(planned.config,'schema_version',None)==2 else task_type+'_v1',project_id=project,plan_version_id=row['id'],
                        run_id=identifier,source_digest=source_sha,output_language=planned.config.output_language).model_dump(mode='json',exclude_none=True)
                    file_ids=sorted({s['source_id'] for s in sources if s['source_kind']=='original_file'}|{fid for s in sources for fid in s.get('metadata',{}).get('source_file_ids',[])})
                    task=self._new_task(db,project,task_id,task_type,snapshot,file_ids)
                    insert(db,'bio_insight_runs',{**base(identifier,project,self.store.user_id),'plan_version_id':row['id'],'kind':row['kind'],'decision':'confirmed',
                        'task_id':task_id,'task_type':task_type,'source_digest':source_sha,'execution_snapshot_object_id':obj['id'],
                        'execution_snapshot_sha256':obj['sha256'],'expected_plan_revision':request.expected_plan_revision,'result_version_id':None,
                        'request_key':key,'request_digest':sha})
                    selected=identifier;status=202
        return self.get_run(project,selected),status

    def _reusable_run(self,db,project,plan,sources,runtime,limits):
        rows=db.execute("""SELECT r.* FROM bio_insight_runs r JOIN tasks t ON t.id=r.task_id
            WHERE r.project_id=%s AND r.user_id=%s AND r.plan_version_id=%s
            AND t.status IN ('queued','running','succeeded') ORDER BY r.created_at DESC,r.id""",(project,self.store.user_id,plan['id'])).fetchall()
        for run in rows:
            obj=scoped_object(db,project,self.store.user_id,run['execution_snapshot_object_id'])
            if obj['sha256']!=run['execution_snapshot_sha256']:raise invalid()
            frozen=json.loads(self.objects.read(obj));saved=frozen.get('identity',{})
            # Historical environments already hash the complete effective limits.
            # New envelopes also retain them explicitly; never rewrite history.
            if any(saved.get(k)!=v for k,v in runtime.items()) or saved.get('execution_limits',limits)!=limits:continue
            task=self.store.require_task(db,run['task_id'])
            # Full fixed-source and execution-snapshot verification still applies.
            self.require_sources(db,task,runtime=False)
            if task['status']=='succeeded':
                if not run['result_version_id']:raise invalid()
                result=self.require(db,'bio_insight_result_versions',project,run['result_version_id'])
                if result['run_id']!=run['id'] or result['task_id']!=task['id']:raise invalid()
                from .results import checked_members
                checked_members(self,db,project,result)
            return dict(run)

    def get_run(self,project,identifier):
        with self.store.connection() as db:
            row=self.require(db,'bio_insight_runs',project,identifier);task=self.store.require_task(db,row['task_id'])
            version=self.require(db,'bio_insight_plan_versions',project,row['plan_version_id'])
            return dict(id=row['id'],run_id=row['id'],kind=row['kind'],plan_id=version['plan_id'],plan_version_id=row['plan_version_id'],source_digest=row['source_digest'],
                result_version_id=row['result_version_id'],task_id=task['id'],task_revision=task['revision'],task=self.store.public_task(task),request_key=row['request_key'])

    def list_runs(self,project,page=1,page_size=20):
        with self.store.connection() as db:
            self.store.require_project(db,project)
            total=db.execute('SELECT count(*) AS n FROM bio_insight_runs WHERE project_id=%s AND user_id=%s',(project,self.store.user_id)).fetchone()['n']
            rows=db.execute('SELECT id FROM bio_insight_runs WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC,id LIMIT %s OFFSET %s',
                (project,self.store.user_id,page_size,(page-1)*page_size)).fetchall()
        return dict(items=[self.get_run(project,r['id']) for r in rows],total=total,page=page,page_size=page_size)

    def require_sources(self,db,task,*,runtime=True,progress=None):
        with VerificationPhase(db,self.assets,task['project_id']) as phase:
            return self._require_sources_in_phase(db,task,phase=phase,runtime=runtime,progress=progress)

    @phase_guard
    def _require_sources_in_phase(self,db,task,*,phase,runtime=True,progress=None):
        require_phase(phase,db,self.assets,task['project_id'])
        input_version(task);snapshot=task['input_snapshot'];project=task['project_id']
        if task['task_type']=='bio_resource_import':
            from .resources import BioResourceService
            return BioResourceService(self.assets)._require_resource_sources(db,task,runtime=runtime,progress=progress)
        run=self.require(db,'bio_insight_runs',project,snapshot['run_id'])
        row=self.require(db,'bio_insight_plan_versions',project,snapshot['plan_version_id'])
        if run['task_id']!=task['id'] or run['kind']!=row['kind'] or row['decision']!='confirmed' or run['source_digest']!=snapshot['source_digest']:raise invalid()
        planned,_=self._plan_request(db,project,row);sources=self._resolve(db,project,planned,progress,phase=phase,lineage_only=not runtime)
        expected_workflow='bio_comparison_microbiome_v1' if getattr(planned.config,'schema_version',None)==4 else 'bio_comparison_qpcr_v1' if getattr(planned.config,'schema_version',None)==3 else 'bio_comparison_v2' if planned.config.kind=='comparison' and getattr(planned.config,'schema_version',None)==2 else task['task_type']+'_v1'
        if task['workflow_version']!=expected_workflow or snapshot['workflow_version']!=expected_workflow:raise invalid()
        if source_digest(sources)!=run['source_digest']:raise invalid()
        obj=scoped_object(db,project,self.store.user_id,run['execution_snapshot_object_id'])
        if obj['sha256']!=run['execution_snapshot_sha256']:raise invalid()
        frozen=json.loads(self.objects.read(obj))
        envelope=dict(schema_version=1,kind=task['task_type'],config=planned.config.model_dump(mode='json'),identity=frozen['identity'],sources=sources)
        if frozen_envelope_projection(envelope,frozen)!=frozen:raise invalid()
        if frozen['identity'].get('task_id')!=task['id'] or frozen['identity'].get('project_id')!=project:raise invalid()
        if runtime:
            current=self._runtime_for(planned.config)
            if any(frozen['identity'].get(key)!=value for key,value in current.items()):raise invalid('bio_insights_environment_unavailable',422)
            if 'execution_limits' in frozen['identity']:
                from .settings import BioInsightsLimits
                if frozen['identity']['execution_limits']!=BioInsightsLimits().model_dump():raise invalid('bio_insights_environment_unavailable',422)
        design=self._design(planned.config,sources)
        if not design.executable:raise invalid('bio_insight_design_blocked',422)
        if getattr(planned.config,'bulk_model',None) and (
            row['design_checks_json'].get('reviewed_design_sha256')!=reviewed_design_digest(planned.config,design,sources)
        ):raise invalid('bio_insight_revision_conflict')
        return envelope

    def publish(self,db,task,checkpoint,moment,prepared,*,progress):
        from app.domain.bioinformatics.analysis_service import finish
        if task['task_type']=='bio_resource_import':
            from .resources import BioResourceService
            return BioResourceService(self.assets)._publish_resource(db,task,checkpoint,moment,prepared,progress=progress)
        payload=self.require_sources(db,task,progress=progress)
        snapshot=task['input_snapshot'];run=self.require(db,'bio_insight_runs',task['project_id'],snapshot['run_id'])
        if run['result_version_id']:raise invalid()
        identifier=identity(task['project_id'],'result',run['id']);manifest=prepared['manifest']
        manifest_ref=object_by_key(db,task['project_id'],task['user_id'],prepared['manifest_ref'])
        kind=run['kind'];provenance='external_result' if kind=='result_import' else 'system_computed'
        scope='external_result' if kind=='result_import' else ('spot_exploratory' if payload['config']['mode']=='spot_exploratory' else 'donor_inference') if kind=='comparison' else 'visualization' if kind=='figure' else 'derived'
        if kind=='comparison' and payload['config'].get('schema_version')==2:
            from .quantitative_contracts import QuantitativeComparisonConfig,quantitative_scope
            scope=quantitative_scope(QuantitativeComparisonConfig.model_validate(payload['config']),[s['metadata']['assay'] for s in payload['sources'] if s['source_kind']=='bio_processed_dataset_version'])
        if kind=='comparison' and payload['config'].get('schema_version')==5:scope='sample_exploratory' if payload['config']['mode']=='descriptive' else 'donor_inference'
        if kind=='comparison' and payload['config'].get('schema_version')==3:scope='sample_inference'
        if kind=='comparison' and payload['config'].get('schema_version')==4:scope='sample_inference' if payload['config']['contrasts'] or payload['config']['beta_inference'] else 'sample_exploratory'
        if kind=='integration' and payload['config'].get('schema_version')==2:
            scope='donor_inference' if payload['config']['method']=='cellchat' and payload['config']['communication_mode']!='per_donor' else 'sample_exploratory'
        if manifest.get('inference_scope')!=scope or manifest.get('identity')!=payload['identity']:raise invalid()
        methods=manifest.get('methods') or prepared.get('methods') or {}
        if isinstance(methods,list):methods={'steps':methods}
        insert(db,'bio_insight_result_versions',{**base(identifier,task['project_id'],task['user_id']),'run_id':run['id'],'task_id':task['id'],
            'plan_version_id':run['plan_version_id'],'kind':kind,'provenance':provenance,'inference_scope':scope,
            'manifest_object_id':manifest_ref['id'],'manifest_sha256':manifest_ref['sha256'],'summary_json':manifest.get('summary',prepared.get('summary',{})),
            'methods_json':methods,'environment_digest':payload['identity']['environment_digest'],'code_digest':payload['identity']['code_digest']})
        for member in prepared['members']:
            progress();obj=object_by_key(db,task['project_id'],task['user_id'],member)
            insert(db,'bio_insight_result_members',{**base(member['id'],task['project_id'],task['user_id']),'result_version_id':identifier,
                **{k:member[k] for k in ('key','role','format','sha256','size_bytes')},'storage_object_id':obj['id'],'shape_json':member.get('shape',{})})
        db.execute('UPDATE bio_insight_runs SET result_version_id=%s WHERE id=%s AND result_version_id IS NULL',(identifier,run['id']))
        progress();return finish(db,task,checkpoint,moment,'result_bio_insight_result_version_id',identifier)

    def recover(self,project,kind,key):
        require_key(key)
        with self.store.connection() as db:
            self.store.require_project(db,project)
            table={'plan':'bio_insight_plan_versions','run':'bio_insight_runs','resource':'bio_resource_versions'}[kind]
            row=db.execute('SELECT * FROM '+table+' WHERE project_id=%s AND user_id=%s AND request_key=%s',(project,self.store.user_id,key)).fetchone()
            if not row and kind=='run':
                receipt=read_receipt(db,user_id=self.store.user_id,project_id=project,kind='bio_insight_run',key=key)
                if receipt:row=target(db,user_id=self.store.user_id,project_id=project,kind='bio_insight_run',target_id=receipt['target_id'])
            if not row:raise invalid('bio_insight_not_found',404)
        if kind=='plan':return self.get_plan(project,row['plan_id'],row['id'])
        if kind=='run':return self.get_run(project,row['id'])
        from .resources import BioResourceService
        return BioResourceService(self.assets).get(project,row['id'])
