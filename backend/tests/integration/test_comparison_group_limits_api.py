"""Real requests reject oversized category labels without changing source assets."""
from tests.helpers.legacy_plans import seed_legacy_plan
import copy
from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook
import pytest

from app.db.database import database_connection
from tests.api.test_analysis import client
from tests.api.test_dataset_analysis import version
from tests.domain.test_correlation_plan_contracts import research
from tests.integration.test_comparison_plan import independent_rows, selection
from tests.integration.test_correlation_plan import prepared_correlations
from tests.integration.test_dataset_preparation import run, review, decide, decision


@pytest.mark.parametrize('value',['1e100000','1e-100000'])
def test_plan_api_rejects_short_unbounded_numeric_group_before_creating_task(client,value):
    base,_,prepared=prepared_correlations(client,rows=independent_rows())
    source_before=client.get(prepared['download_url']).content
    chosen=selection(prepared['source']['sheet_name'])
    chosen['groups']=[dict(kind='number',value=value),dict(kind='number',value='2')]
    with database_connection() as db:
        tasks_before=db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n']
    response=seed_legacy_plan(client, base+'/analysis-plans',json=dict(schema_version=3,dataset_id=prepared['id'],
        expected_setup_revision=0,selection=chosen,research_request=research(),recommendation_ref=None),
        headers={'Idempotency-Key':'unbounded-numeric-group'})
    assert response.status_code==422,response.text
    assert response.json()['detail']['code']=='invalid_request'
    assert client.get(prepared['download_url']).content==source_before
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM tasks').fetchone()['n']==tasks_before
        assert db.execute('SELECT count(*) AS n FROM analysis_setups').fetchone()['n']==0


def prepared_extreme_group(client,kind,value):
    project=client.post('/api/v1/projects',json=dict(name='Bounded group labels',research_topic='Synthetic input',project_type='sci')).json()
    book=Workbook();book.active.title='Limits'
    for row in [['Outcome','Group'],[1,1 if kind=='number' else value],[2,'A'],[3,'A'],[4,'B'],[5,'B'],[6,'B']]:book.active.append(row)
    original=BytesIO();book.save(original);book.close()
    if kind=='number':
        # Original XML preserves numeric precision beyond the preview's binary64 display.
        replaced=BytesIO()
        with ZipFile(BytesIO(original.getvalue())) as source,ZipFile(replaced,'w') as target:
            for info in source.infolist():
                content=source.read(info.filename)
                if info.filename=='xl/worksheets/sheet1.xml':
                    needle=b'<c r="B2" t="n"><v>1</v></c>'
                    assert content.count(needle)==1
                    content=content.replace(needle,('<c r="B2" t="n"><v>'+value+'</v></c>').encode())
                target.writestr(info,content)
        original=replaced
    uploaded=client.post('/api/v1/projects/'+project['id']+'/files',files={'file':('limits.xlsx',original.getvalue())})
    assert uploaded.status_code==201,uploaded.text
    file=uploaded.json()['file'];assert file['parse_status']=='parsed'
    base='/api/v1/projects/'+project['id']+'/files/'+file['id']
    raw=version(client,base)
    defaults=client.get(base+'/dataset-versions/'+raw['id']+'/preparation-defaults');assert defaults.status_code==200,defaults.text
    recipe=copy.deepcopy(defaults.json()['recipe'])
    for field in recipe['fields']:field['unit']=dict(status='confirmed',value='')
    response=client.post(base+'/dataset-preparations',json=dict(dataset_id=raw['id'],recipe=recipe),headers={'Idempotency-Key':'extreme-group-prepare'})
    assert response.status_code==202,response.text
    task=response.json();assert run(task)['status']=='waiting_confirmation'
    approved=decide(client,task,decision(review(client,task))).json()
    assert run(approved)['status']=='succeeded'
    return base,review(client,task)['result']


@pytest.mark.parametrize('kind,value',[('number','1e100000'),('number','1e-100000'),('text','x'*501)])
def test_options_api_rejects_extreme_source_label_without_mutating_prepared_data(client,kind,value):
    base,prepared=prepared_extreme_group(client,kind,value)
    source_before=client.get(prepared['download_url']).content
    source=client.get(prepared['download_url']).json()
    assert next(c for c in source['sheet']['cells'] if c['coordinate']=='B2')['value']==value
    response=client.get(base+'/comparison-group-options',params=dict(dataset_id=prepared['id'],sheet='Limits',group_column='B'))
    assert response.status_code==422,response.text
    assert response.json()['detail']['code']=='group_type'
    assert '500' in response.json()['detail']['message'] or kind=='number'
    assert client.get(prepared['download_url']).content==source_before
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM analysis_setups').fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==0
