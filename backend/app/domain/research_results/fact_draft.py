"""Deterministic partial fact prose; adopted claims never become computed facts."""
from copy import deepcopy
from pathlib import Path
import json
from app.domain.bioinformatics.contracts import canonical,digest
from app.domain.manuscripts.research_sources import numeric
from app.domain.manuscripts.contracts import WORKFLOW
from app.adapters.research_method_text import presentation_enabled,present_method,method_fingerprint

FACT_PROJECTION_VERSION=2


def compose(payload):
    projection=payload.get('fact_projection_version',1)
    if type(projection) is not int or projection not in (1,FACT_PROJECTION_VERSION):raise ValueError('Unsupported fact projection version')
    merge_exact=projection==FACT_PROJECTION_VERSION
    en=payload['output_language']=='en';base=payload['base_snapshot'];sources=payload['sources']
    notice=('Partial Results/Methods fact draft. No model call; researcher verification required.' if en else '仅限结果与方法的部分章节事实稿；未调用模型，须由研究人员核对。')
    result=deepcopy(base) if base else dict(schema_version=1,project_id=payload['project_id'],workflow_version=WORKFLOW,
        title='Research fact draft' if en else '研究成果事实稿',output_language=payload['output_language'],methods=[],results_groups=[],
        references=[],issues=[],citation_snapshot=None)
    # A new deterministic selection cannot inherit approval of earlier wording.
    if payload['thesis_context'] and result.get('writing_provenance',{}).get('school_export_options') is not None:
        result['research_school_export_defaults']=deepcopy(result['writing_provenance']['school_export_options'])
    historical={key:result.pop(key) for key in ('writing_provenance','review_provenance','school_change_provenance','journal_adaptation_provenance','review_revision_provenance','user_return_provenance') if key in result}
    if historical:result.setdefault('research_provenance_history',[]).append(historical)
    selected=[s for s in sources if s['id'] in payload['selected_source_ids']]
    paragraphs=[];methods=[];warnings=[];gaps=[];conflicts=[];claims=[];figures=[]
    readable=presentation_enabled(payload);method_seen={};exact_facts={};exact_methods={}
    def paragraph(identity,text,source,origin='user_provided',bindings=None):
        return dict(id=identity,text=text,origin=origin,source_ids=[source['id']],citations=[],numeric_bindings=bindings or [])
    for source in selected:
        content=source['content'];warnings.extend(content.get('warnings',[])+content.get('limitations',[]));gaps.extend(content.get('gaps',[]))
        conflicts.extend(content.get('conflicts',[]));claims.extend(content.get('claims',[]))
        blocked={f for c in content.get('conflicts',[]) if c['decision']=='unresolved' for f in c['fact_ids']}
        values={f['research_fact_id']:f for f in numeric(source)}
        for fact in content.get('facts',[]):
            if fact['id'] in blocked or fact['verification_status'] in ('missing','conflict'):
                gaps.append(('Unresolved fact: ' if en else '待核对事实：')+fact['id']);continue
            # A finding and its report may carry the same complete fact record.
            # Identity, original source, locator and every value/qualification
            # must all match; equal text or numeric value alone is insufficient.
            key=canonical(fact) if merge_exact else None
            if merge_exact and key in exact_facts:
                previous=exact_facts[key]
                if source['id'] not in previous['source_ids']:previous['source_ids'].append(source['id'])
                continue
            calculated=fact['origin'] in ('system_computed','public_reanalysis')
            prefix=('Computed/public reanalysis' if calculated else 'External result, not recalculated') if en else ('系统计算／公共数据再分析' if calculated else '外部结果，未重新计算')
            locator=fact['locator'];metric=locator.get('field_path') or locator.get('column') or ('Recorded value' if en else '记录值')
            text=f"{prefix}; {metric}: {fact['display_value']} {fact['unit']} ({fact['observation_level']})."
            if locator.get('row_key'):text+=' '+('Row: ' if en else '行定位：')+json.dumps(locator['row_key'],ensure_ascii=False,sort_keys=True,separators=(',',':'))+'.'
            if fact.get('comparison'):text+=' '+('Comparison: ' if en else '比较：')+fact['comparison']+'.'
            item=values.get(fact['id']);bindings=[]
            if item:bindings=[dict(source_id=source['id'],fact_id=source['kind']+':'+source['id']+':'+item['fact_path'],value=item['value'])]
            p=paragraph('research:'+source['id']+':'+fact['id'],text,source,'computed_result' if calculated else 'user_provided',bindings)
            p['research_fact']=deepcopy(fact);paragraphs.append(p)
            if merge_exact:exact_facts[key]=p
        for method in content.get('methods',[]):
            key=canonical(method) if merge_exact else None
            if merge_exact and key in exact_methods:
                previous=exact_methods[key]
                if source['id'] not in previous['source_ids']:previous['source_ids'].append(source['id'])
                continue
            fingerprint=method_fingerprint(method)
            shown=present_method(method,payload['output_language'],reference='research_method.parameters / '+method['id']+'; research_method.software',
                duplicate_of=method_seen.get(fingerprint)) if readable else None
            if shown is not None:
                text=shown['title']+': '+'\n'.join(shown['paragraphs'])
                method_seen.setdefault(fingerprint,len(methods)+1)
            else:
                text=method['title']+': '+method['description']
                if method.get('parameters'):text+=' '+json.dumps(method['parameters'],ensure_ascii=False,sort_keys=True,separators=(',',':'))
                if method.get('software',{}).get('engine_version'):text+=' '+method['software']['engine_version']
                if not method['executed']:text=('Not executed: ' if en else '未执行：')+text
            p=paragraph('research-method:'+source['id']+':'+method['id'],text,source);p['research_method']=deepcopy(method);methods.append(p)
            if merge_exact:exact_methods[key]=p
        if content.get('figure'):
            figure=content['figure'];priority={'png':0,'tiff':1,'svg':2,'pdf':3}
            members=sorted((m for m in content['members'] if m['format'] in priority and m['role']=='figure'),key=lambda m:priority[m['format']])
            member=members[0] if members else None
            if member:
                figures.append(dict(id='research-figure:'+source['id'],source_ids=[source['id']],number=len(figures)+1,title=figure.get('title') or '',caption=figure.get('caption') or '',
                    panels=[],sha256=member['sha256'],research_member_id=member['id'],figure_language=figure.get('figure_language'),output_language=figure.get('language')))
                if member['format']!='png':figures[-1]['research_member_format']=member['format']
    if any(f.get('research_fact',{}).get('observation_level') in ('spot','region') for f in paragraphs):
        warnings.append('Spot/region observations are exploratory; they are not donor replicates or confirmed pure cell types.' if en else 'spot／区域观察属于探索性结果，不等于 donor 生物学重复或已确认纯细胞类型。')
    selected_sections=payload['sections']
    if 'materials_and_methods' in selected_sections:result['methods']=methods
    group=dict(id='research-results',title='Results' if en else '研究结果',paragraphs=paragraphs,tables=[],figures=figures,analysis_run_ids=[])
    if 'results' in selected_sections:result['results_groups']=[group]
    elif not base and payload['thesis_context']:
        result['results_groups']=[dict(group,paragraphs=[],tables=[],figures=[])]
    result.update(sources=deepcopy(sources),candidate_origin='system_fact_draft',writing_scope='results_methods',notice=notice,
        research_bridge=dict(schema_version=1,delivery_id=payload['document_context']['delivery_id'],document_kind=payload['document_context']['document_kind'],
            selected_source_ids=payload['selected_source_ids'],sections=selected_sections,base_version_id=payload.get('base_version_id'),base_snapshot_sha256=digest(base) if base else None),real_model_calls=False,real_network_calls=False,
        research_gaps=list(dict.fromkeys(gaps)),research_warnings=list(dict.fromkeys(warnings)),research_conflicts=conflicts,
        research_claims=claims,manual_notes=payload['manual_notes'])
    if merge_exact:result['research_bridge']['fact_projection_version']=FACT_PROJECTION_VERSION
    result['issues']=[i for i in result['issues'] if i.get('id')!='scope']+[dict(id='scope',kind='limitation',field='scope',message=notice,values=[])]
    if payload['thesis_context']:
        if not base:
            from app.domain.manuscripts.school import seed_school_snapshot
            result=seed_school_snapshot(result,payload['thesis_context'])
        else:
            for section in result['sections']:
                if section['purpose']=='results' and 'results' in selected_sections:section['paragraphs']=deepcopy(paragraphs)
                if section['purpose']=='materials_and_methods' and 'materials_and_methods' in selected_sections:section['paragraphs']=deepcopy(methods)
    elif base and 'sections' in result:
        for section in result['sections']:
            if section['id']=='results' and 'results' in selected_sections:section['paragraphs']=deepcopy(paragraphs)
            if section['id']=='materials_and_methods' and 'materials_and_methods' in selected_sections:section['paragraphs']=deepcopy(methods)
    return result


def render_fact_draft(payload,output):
    candidate=compose(payload);raw=canonical(candidate)
    if len(raw)>4*1024*1024:raise ValueError('Candidate exceeds bound')
    output=Path(output);output.mkdir(parents=True,exist_ok=True);path=output/'candidate.json';path.write_bytes(raw)
    return dict(manifest=dict(schema_version=1,kind='research_fact_draft',candidate_sha256=digest(candidate)),
        outputs=[dict(key='candidate',role='candidate',format='json',path=str(path.resolve()),sha256=digest(candidate),size_bytes=len(raw),properties={})])
