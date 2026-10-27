"""Linux numerical fixture, synthetic provider; active model configuration consumed."""
import json
from tests.api.test_admin_configurations import accounts,admin,baseline,saved,validated,switch
from tests.api.test_analysis import client
from app.db.database import database_connection


def test_queued_workbench_keeps_old_policy_and_instruction_after_switch(admin,client,monkeypatch,tmp_path):
    from tests.domain.test_plot_policy import execution_policy
    from tests.integration.test_batch05_figure_execution import queued_figure,IndependentLineProvider
    from app.domain.figure_workbench.execution import run_figure_workbench_task
    policy=execution_policy();policy['policy']['model']='gpt-5.6-sol';policy['policy']['price']['model']='gpt-5.6-sol'
    policy['input_token_allowance']=100000
    policy['task_limit_micro_usd']=200000
    path=tmp_path/'synthetic-plot.json';path.write_text(json.dumps(policy),encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_PLOT_POLICY_FILE',str(path))
    one=baseline(admin);one=saved(admin,one,'prompts','plot_instruction','Use a compact caption.')
    validated(admin,one);assert switch(admin,one,0,'first').status_code==200
    store,project,result,vid,task=queued_figure(client,monkeypatch)
    two=saved(admin,one,'prompts','plot_instruction','Use a detailed caption.')
    validated(admin,two);assert switch(admin,two,1,'second').status_code==200
    provider=IndependentLineProvider(result,pending=False);seen=[];original=provider.create_plot;receipt=provider.receipt
    def fixed_receipt():
        value=receipt();value['model']='gpt-5.6-sol';value['response']['model']='gpt-5.6-sol';return value
    def capture(**kw):seen.append(kw);return original(**kw)
    provider.receipt=fixed_receipt;provider.create_plot=capture
    for _ in range(5):
        task=run_figure_workbench_task(task['id'],task['revision'],provider_factory=lambda:provider)
        assert task is not None
        assert task['status']!='waiting_confirmation',task
        if task['status'] in ('succeeded','failed'):break
    assert task['status']=='succeeded',task
    assert 'Use a compact caption.' in seen[0]['instructions']
    assert 'Use a detailed caption.' not in seen[0]['instructions']
    assert seen[0]['policy'].model=='gpt-5.6-sol'
    with database_connection() as db:
        call=db.execute('SELECT price_snapshot FROM model_calls WHERE task_id=%s',(task['id'],)).fetchone()
        assert call['price_snapshot']['version']==policy['policy']['price']['version']
