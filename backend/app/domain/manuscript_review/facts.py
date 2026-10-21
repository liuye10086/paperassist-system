"""Stable leaf identities and relationships from frozen material, never pixels."""
from copy import deepcopy
from math import isfinite
from app.domain.literature.service import digest

FACT_ROOTS = ('statistics','overall','groups','comparisons','coefficients')

def numeric_leaves(value,path=''):
    if isinstance(value,dict):
        for key,item in sorted(value.items()):
            yield from numeric_leaves(item,path+'/'+str(key).replace('~','~0').replace('/','~1'))
    elif isinstance(value,list):
        for index,item in enumerate(value): yield from numeric_leaves(item,path+'/'+str(index))
    elif type(value) in (int,float) and isfinite(value):
        yield path,str(value)

def extract_facts(snapshot):
    facts=[]
    for source in snapshot.get('sources',[]):
        if source.get('kind')!='analysis_run' or source.get('role')!='computed_results': continue
        content=source.get('content',{})
        for path,value in numeric_leaves({k:content[k] for k in FACT_ROOTS if k in content}):
            facts.append(dict(id='analysis_run:'+source['id']+':'+path,source_id=source['id'],path=path,value=value,source_sha256=source.get('sha256') or digest(content)))
    return facts

def displayed_paragraphs(snapshot):
    if 'sections' in snapshot:
        return [(s['id'],p) for s in snapshot['sections'] if s['id']!='references' for p in s['paragraphs']]
    return [('materials_and_methods',p) for p in snapshot.get('methods',[])]+[('results',p) for g in snapshot.get('results_groups',[]) for p in g.get('paragraphs',[])]

def relationships(snapshot,associations=()):
    paragraphs=[dict(id=p['id'],section_id=section,source_ids=deepcopy(p.get('source_ids',[])),figure_ids=[r['target_id'] for r in p.get('cross_references',[]) if r.get('kind')=='figure']) for section,p in displayed_paragraphs(snapshot)]
    figures=[dict(id=f['id'],source_ids=deepcopy(f.get('source_ids',[]))) for g in snapshot.get('results_groups',[]) for f in g.get('figures',[])]
    methods=[p for p in paragraphs if p['section_id']=='materials_and_methods']
    question=next((p['text'] for _,p in displayed_paragraphs(snapshot) if p['id']=='methods:research_question'),'')
    return dict(paragraphs=paragraphs,figures=figures,methods=methods,research_question=question,associations=deepcopy(list(associations)))
