import json
import httpx2
from app.adapters.models.openai_responses import OpenAIResponsesProvider
from app.domain.manuscript_writing.bundle import build_bundle
from tests.domain.test_manuscript_writing_live_bundle import material

def test_frozen_wire_is_sent_byte_exact_to_official_endpoint_with_no_retry():
    base,request=material();bundle=build_bundle(base,request);seen=[]
    def transport(request):
        seen.append(request)
        return httpx2.Response(200,json=dict(id='resp_mock',model='gpt-5.4-2026-03-05',status='completed',output=[],usage=None),headers={'x-request-id':'req_mock'})
    client=httpx2.Client(transport=httpx2.MockTransport(transport))
    provider=OpenAIResponsesProvider(api_key='synthetic-not-real',http_client=client)
    receipt=provider.create_frozen(wire_json=bundle['wire_json'])
    assert receipt['response_id']=='resp_mock'
    assert len(seen)==1 and str(seen[0].url)=='https://api.openai.com/v1/responses'
    assert seen[0].content==bundle['wire_json'].encode('utf-8')
    assert provider.client.max_retries==0
    provider.close()
