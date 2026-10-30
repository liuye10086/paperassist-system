"""New isolated synthetic context science/language/publication/export chain."""
from copy import deepcopy
from io import BytesIO
import json
from zipfile import ZipFile
from tests.api.test_manuscripts import client, setup, body
from tests.api.test_manuscript_writing_live import LiveFixture, authorize, request_v2
from tests.api.test_manuscript_writing_live_review import decision
from tests.api.test_manuscript_writing_language import approve
from tests.api.test_literature_evidence import post
from tests.integration.test_literature_assistance import budgets
from app.domain.tasks.execution import run_task
from app.domain.manuscript_writing.execution import run_manuscript_writing_task


def test_context_science_requires_explicit_decision_then_language_and_exact_publication_export(client):
    path,_,_=setup(client)
    text='The divisor is n−1.'
    response=post(client,path,body(methods=dict(statistical_methods=text)),'context-base')
    assert response.status_code==201,response.text
    manuscript=response.json();root=path+'/'+manuscript['id']
    assert run_task(manuscript['versions'][0]['task_id'],1)['status']=='succeeded'
    response=post(client,root+'/writing-previews',dict(schema_version=2,base_revision=1,mode='full_draft',
        output_language='en',selected_source_ids=[],selected_evidence_ids=[]),'context-preview')
    assert response.status_code==201,response.text
    bundle=response.json();catalog=bundle['local_manifest']['numeric_context']
    alias,item=next((alias,item) for alias,item in catalog.items() if text in item['text'])
    fact=next(value for value in item['values'] if value['value']=='-1')
    _,authorization=authorize(client,root,bundle)
    response=post(client,root+'/writing-requests',request_v2(bundle,authorization),'context-request')
    assert response.status_code==202,response.text
    task=response.json()['task'];budgets(client,task)
    class ContextFixture(LiveFixture):
        def receipt(self):
            result=super().receipt();output=json.loads(result['response']['output'][0]['content'][0]['text'])
            output['sections'][-1]['paragraphs'][0].update(text=text,study_numeric_bindings=[dict(source_alias=alias,**fact)])
            result['response']['output'][0]['content'][0]['text']=json.dumps(output)
            return result
    provider=ContextFixture()
    assert run_manuscript_writing_task(task['id'],task['revision'],provider=provider)['status']=='succeeded'
    assert provider.posts==[bundle['wire_json']]
    path=root+'/writing-requests/'+task['id'];response=client.get(path+'/review-context')
    assert response.status_code==200,response.text
    context=response.json();raw=deepcopy(context['candidate']);paragraph=raw['sections'][5]['paragraphs'][0]
    assert paragraph['numeric_bindings']==[] and paragraph['source_ids']==[]
    request=decision(context)
    # The raw alias and context binding suggestion cannot replace a manual decision.
    assert post(client,path+'/reviews',request,'context-missing-decision').status_code==422
    request['paragraphs'][5].update(classification='context_claim',numeric_bindings=[dict(occurrence=0,
        kind='context',source_alias=alias,**fact)])
    response=post(client,path+'/reviews',request,'context-science')
    assert response.status_code==201,response.text
    science=response.json()
    assert science['report']['numeric_validation_version']==2
    assert client.get(path).json()['candidate']==raw
    assert client.get(path+'/reviews/'+science['id']).json()==science
    assert post(client,path+'/reviews',request,'context-science').json()==science
    publish=dict(schema_version=2,expected_revision=1,review_id=science['id'],review_sha256=science['review_sha256'])
    assert post(client,path+'/publish',publish,'context-no-language').status_code==409
    response=client.get(path+'/reviews/'+science['id']+'/language-context')
    assert response.status_code==200,response.text
    language_request=approve(response.json())
    response=post(client,path+'/language-reviews',language_request,'context-language')
    assert response.status_code==201,response.text
    language=response.json()
    assert language['candidate']['writing_provenance']['language_numeric_validation_version']==2
    assert client.get(path+'/language-reviews/'+language['id']).json()==language
    assert post(client,path+'/language-reviews',language_request,'context-language').json()==language
    publish.update(language_review_id=language['id'],language_review_sha256=language['artifact_sha256'])
    response=post(client,path+'/publish',publish,'context-publish')
    assert response.status_code==201,response.text
    assert response.json()['versions'][0]['snapshot']==language['candidate']
    assert post(client,path+'/publish',publish,'context-publish').status_code==200
    assert run_task(response.json()['versions'][0]['task_id'],1)['status']=='succeeded'
    response=client.get(root+'/reviews/context')
    assert response.status_code==200,response.text
    assert not [issue for issue in response.json()['issues'] if issue['category']=='numeric' and issue['severity']=='error']
    response=post(client,root+'/versions/2/exports',{},'context-export')
    assert response.status_code==201,response.text
    export=response.json();assert run_task(export['task_id'],1)['status']=='succeeded'
    exported=client.get(root+'/exports/'+export['id']).json()
    response=client.get(exported['download_url'])
    assert response.status_code==200,response.text
    with ZipFile(BytesIO(response.content)) as archive:assert text in archive.read('word/document.xml').decode()
    assert client.get(root+'/versions/2').json()['snapshot']==language['candidate']
