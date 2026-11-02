"""Offline fixed-source matrix construction; never recompute upstream analyses."""
from app.domain.bio_insights.evidence_contracts import EvidenceMatrixConfig
from app.domain.bio_insights.external_matrix import build_matrix
import json
from pathlib import Path

def document(member):
    raw=Path(member['path']).read_bytes()
    import hashlib
    if len(raw)!=member['size_bytes'] or hashlib.sha256(raw).hexdigest()!=member['sha256']:raise ValueError('evidence_upstream_hash_mismatch')
    return json.loads(raw)


def evidence_result(payload):
    config=EvidenceMatrixConfig.model_validate(payload['config']);sources={s['source_id']:s for s in payload['sources']}
    data=build_matrix([c.model_dump(mode='json') for c in config.candidates],[sources[s] for s in config.evidence_source_ids],[r.model_dump(mode='json') for r in config.independent_support_requests],payload['sources'])
    data['integration_results']=[dict(source_id=sid,sha256=sources[sid]['sha256'],data=document(sources[sid]['members']['integration_data'])) for sid in config.integration_result_source_ids]
    matrix_id='matrix:fixed-evidence-cross-product'
    data['nodes'].append(dict(id=matrix_id,kind='matrix_operation',label='候选×证据矩阵整理',biological_claims_recomputed=False))
    def edge(source,target,relation,**extra):data['edges'].append(dict(source=source,target=target,relation=relation,directed=True,causal=False,**extra))
    for sid in sorted({c.source_id for c in config.candidates}):
        data['nodes'].append(dict(id='processed:'+sid,kind='processed_source',label='固定处理层 '+sid[:8],source_id=sid,sha256=sources.get(sid,{}).get('sha256')))
    for c in config.candidates:
        edge('processed:'+c.source_id,'candidate:'+c.object_id,'fixed_axis_selection',locator={'feature_id':c.feature_id,'namespace':c.namespace,'reference_version':c.reference_version},mapping_basis={'source_id':c.mapping_evidence_source_id,'locator':c.mapping_locator,'quote':c.mapping_quote})
        edge('candidate:'+c.object_id,matrix_id,'candidate_input')
    original_nodes=set()
    for sid in config.evidence_source_ids:
        meta=sources[sid]['metadata']
        for fid in meta.get('source_file_ids',[]):
            node='original:'+fid
            if node not in original_nodes:
                data['nodes'].append(dict(id=node,kind='original_file',label=meta.get('filename',fid),source_id=fid,sha256=meta.get('original_sha256')));original_nodes.add(node)
            edge(node,'evidence:'+sid,'fixed_original_locator',locators=meta['typed_evidence']['locators'])
        edge('evidence:'+sid,matrix_id,'external_statement_input')
    for item in data['integration_results']:
        data['nodes'].append(dict(id='integration:'+item['source_id'],kind='integration_result',label='固定整合结果',source_id=item['source_id'],sha256=item['sha256']))
        edge('integration:'+item['source_id'],matrix_id,'saved_result_reference',analysis_recomputed=False,validates_candidate=False)

    data['gaps']=['未登记的证据类型保持缺失；没有真实 KO 原始实验不能补成敲除证据。','缺少独立材料、设计、实际 run、对象/对照及完整供体重叠核查时，不标独立支持。','原文条件、正常组织图谱和回顾队列不直接验证当前相关对；参考版本未知不补猜。']
    return data


def run_external_evidence(payload,writer):
    data=evidence_result(payload)
    for key,rows in [('candidate_results',data['candidates']),('candidate_evidence',data['matrix']),('evidence_nodes',data['nodes']),('evidence_edges',data['edges'])]:
        fields=list(dict.fromkeys(k for r in rows for k in r))
        writer.table(key,rows,fields)
    writer.json('evidence_data',data)
    methods=dict(recipe=payload['config'],ranking='distinct dependency-group comparable support DESC, conflict ASC, stable object ID ASC; no confidence score',source_claim_status='source_reported; never system_verified by matrix computation',human_review='separate from original locator matching and independent analysis',independence='actual completed comparison + fixed result row + distinct materials + frozen design/object/control + donor identities and overlap audit; not a checkbox',missing_policy=data['missing_policy'],dependency_groups=data['dependency_groups'],gaps=data['gaps'],upstream_analysis_recomputed=False)
    return dict(summary=dict(candidate_count=len(data['candidates']),evidence_count=len(payload['config']['evidence_source_ids']),matrix_row_count=len(data['matrix']),dependency_group_count=len(data['dependency_groups']),independent_support_count=sum(r['independent_data_support'] for r in data['matrix']),real_knockout_record_count=sum(s['metadata']['typed_evidence']['evidence_type']=='knockout' for s in payload['sources'] if s['source_kind']=='external_evidence_version')),methods=methods,inference_scope='derived',provenance='system_computed')
