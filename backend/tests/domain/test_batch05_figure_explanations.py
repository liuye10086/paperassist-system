import copy
import pytest
from app.domain.figure_workbench.explanations import build_payload,render,validate_saved,reuse
from app.core.exceptions import StorageError

def bundle():
    return {'result':{'id':'r','check':{'valid_count':8}},'figure':{'id':'f','sha256':'a'*64,'facts_sha256':'b'*64,'language':'en','title':'Outcome','caption':'Descriptive records','figure_kind':'bar','source':{'kind':'prepared_dataset_version'},'analysis_run_id':'r'},'configuration':{'config':{'figure_kind':'bar','language':'en','projection':{},'style':{'title':'','caption':'','aliases':{},'display_order':[],'palette':'blue'}}},'projection':{'result':{'audit':{'valid_n':4,'population_n':5,'excluded_n':1},'method':{'kind':'bar'},'series':[{'group':None,'points':[{'category':'A','n':4,'value':1.0,'denominator':4,'sd':None,'reason':None}]}]}}}

def test_six_sections_retain_draft_and_reject_fact_or_binding_tampering():
    b=bundle();p=build_payload(b)
    assert p['facts']['data.valid']['raw']==4 and p['facts']['data.original_n']['raw']==8
    draft={key:'; '.join('{{'+ref+'}}' for ref in refs) for key,refs in p['required_references'].items()}
    saved=render(b,draft,{'model':'test','response_id':'response','model_call_id':'call'})
    assert len(saved['sections'])==6
    validate_saved(b,saved)
    bad=copy.deepcopy(saved);bad['sections'][0]['text']='Invented result'
    with pytest.raises(StorageError):validate_saved(b,bad)
    bad=copy.deepcopy(saved);bad['figure_sha256']='c'*64
    with pytest.raises(StorageError):validate_saved(b,bad)
    newer=copy.deepcopy(b);newer['figure']['id']='g';newer['figure']['sha256']='d'*64
    newer['configuration']['config']['style']['palette']='gray'
    derived=reuse(b,newer,saved)
    assert derived['figure_id']=='g' and derived['id']!=saved['id'] and derived['derived_from']==saved['id']
    assert derived['provenance']['reuse_only'] is True
