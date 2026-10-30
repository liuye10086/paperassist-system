"""New provenance persists with POST fences; fixtures never contact a provider."""
from copy import deepcopy

import pytest
from psycopg.types.json import Jsonb

from app.db.database import database_connection
from app.domain.model_usage.gateway import ModelGateway,input_digest
from tests.api.test_analysis import client  # noqa: F401
from tests.integration.test_model_usage import context,configure,request  # noqa: F401
from tests.integration.test_plot_gateway import context as plot_context,setup,Provider as PlotProvider,submit
from tests.adapters.test_model_gateway import Provider as TextProvider


class FixtureText(TextProvider):
    source_kind='synthetic_fixture'

    def create(self,**kwargs):
        self.posts.append(kwargs)
        row=self.service.get_call(self.call_id)
        assert row['provider_state']['submission_provenance']['kind']=='synthetic_fixture'
        return deepcopy(self.result)

    def retrieve(self,response_id,**kwargs):
        self.gets.append(response_id)
        return deepcopy(self.result)


def test_gateway_writes_source_in_submission_transaction_before_provider_and_exposes_same_projection(context):
    service=configure(context);req=request(context[3],input_digest=input_digest(instructions='safe',payload={}))
    saved=service.reserve_call(req);provider=FixtureText(service);provider.call_id=saved['id']
    value=ModelGateway(service,provider).submit(req,instructions='safe',payload={})
    assert value['call']['status']=='completed'
    assert service.task_usage(context[3])['items'][0]['provider_provenance']=='synthetic_fixture'
    from app.domain.admin_usage import provider_provenance
    assert provider_provenance(service.get_call(saved['id']))=='synthetic_fixture'
    from app.domain.literature_assistance.service import saved_calls
    with database_connection() as db:
        call=saved_calls(db,dict(id=context[3],project_id=context[2],user_id=context[1]))[0]
    assert call['provenance']=='synthetic_fixture'
    assert not {'provider_state','input_digest','id'} & call.keys()


def test_refresh_does_not_add_source_to_a_historical_unknown_call(context):
    service=configure(context);req=request(context[3]);call=service.reserve_call(req);service.begin_submission(call['id'])
    service.record_response(call['id'],event_key='pending',response_id='resp_text',request_id=None,model='test-model',status='in_progress',usage=None)
    before=service.get_call(call['id'])['provider_state']
    provider=FixtureText(service)
    value=ModelGateway(service,provider).refresh(call['id'])
    assert not provider.posts and provider.gets==['resp_text']
    assert 'submission_provenance' not in value['call']['provider_state']
    assert set(before)<=set(value['call']['provider_state'])
    assert service.task_usage(context[3])['items'][0]['provider_provenance'] is None


def test_plain_json_source_is_rejected_without_changing_submission_state(context):
    service=configure(context);call=service.reserve_call(request(context[3]))
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError):service.begin_submission(call['id'],provenance_context={'kind':'openai_live'})
    assert service.get_call(call['id'])['status']=='reserved'


@pytest.mark.parametrize('historical',[False,True])
def test_plot_first_fence_keeps_source_through_three_slices_and_never_labels_old_middle_step(plot_context,historical):
    service,req,lease=setup(plot_context)
    class FixturePlot(PlotProvider):source_kind='synthetic_fixture'
    provider=FixturePlot();gateway=ModelGateway(service,provider)
    first=submit(gateway,req,lease);call=first['call']
    assert call['provider_state']['submission_provenance']['kind']=='synthetic_fixture'
    original=deepcopy(call['provider_state']['submission_provenance'])
    if historical:
        state=dict(call['provider_state']);state.pop('submission_provenance')
        with database_connection(write=True) as db:db.execute('UPDATE model_calls SET provider_state=%s WHERE id=%s',(Jsonb(state),call['id']))
    for _ in range(2):result=submit(gateway,req,lease)
    result=gateway.refresh(result['call']['id'])
    state=result['call']['provider_state']
    if historical:assert 'submission_provenance' not in state
    else:assert state['submission_provenance']==original
    assert provider.calls==['container','upload','response','GET']
