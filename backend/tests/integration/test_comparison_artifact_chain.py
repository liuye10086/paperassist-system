"""Approved plans to real artifact persistence with independently computing synthetic providers."""
from tests.helpers.statistics import statistics_post
from copy import deepcopy
from fractions import Fraction
from io import BytesIO
import json
import statistics
from zipfile import ZipFile

import pytest
from psycopg.types.json import Jsonb
from app.db.database import database_connection
from tests.api.test_analysis import client
from tests.api.test_boxplot import cloud
from tests.domain.test_correlation_plan_contracts import research
from tests.integration.test_correlation_plan import prepared_correlations
from tests.integration.test_comparison_plan import selection,make_plan,approve,independent_rows
from tests.integration.test_dataset_artifact_chain import confirmed_task
from tests.integration.test_boxplot_execution import SyntheticPlotProvider,run as run_plot
from tests.integration.test_correlation_artifact_chain import ModernExplanationProvider,finish_plot
from tests.integration.test_explanation_execution import run as run_explanation


def result_for(client,method='welch_t',language='en'):
    paired=method in ('paired_t','wilcoxon')
    rows=([['ID','Before','After','Private note'],['PRIVATE-ID-1',8,2,'secret'],['PRIVATE-ID-2',9,3,'secret'],
        ['PRIVATE-ID-3',7,4,'secret'],['PRIVATE-ID-4',10,6,'secret'],['PRIVATE-ID-5',11,8,'secret'],['PRIVATE-ID-6',None,8,'secret']] if paired else independent_rows())
    base,file,prepared=prepared_correlations(client,rows=rows)
    choice=selection(prepared['source']['sheet_name'],method)
    if choice['design']=='multiple': choice['posthoc']='all_pairs_holm'
    declaration=research(); declaration.update(output_language=language,question='LOCAL-QUESTION-SENTINEL')
    if paired: declaration.update(observation_structure='paired',relationship_description='Same participant before and after')
    task,_=make_plan(client,base,prepared,choice,declaration)
    approve(client,task)
    response=statistics_post(client, base+'/analysis-runs',json={'expected_revision':1})
    assert response.status_code==200,response.text
    return base,file,response.json()


def comparison_task(client,base,file,result,kind,figure=None,explanation=None):
    task,owner=confirmed_task(client,base,file,result,kind,figure,explanation)
    if kind!='word_report':
        from app.domain.plot_policy import derive_execution_policy as plot_policy
        from app.domain.explanation_policy import derive_execution_policy as explanation_policy
        key='boxplot_policy' if kind=='boxplot' else 'explanation_policy'
        with database_connection(write=True) as db:
            snapshot=db.execute('SELECT input_snapshot FROM tasks WHERE id=%s',(task['id'],)).fetchone()['input_snapshot']
            policy=(plot_policy if kind=='boxplot' else explanation_policy)(snapshot[key],{'schema_version':3})
            db.execute('UPDATE tasks SET input_snapshot=jsonb_set(input_snapshot,%s,%s) WHERE id=%s',([key],Jsonb(policy),task['id']))
    return task,owner


def summary(values):
    ordered=sorted(values)
    def q(fraction):
        position=(len(ordered)-1)*fraction
        floor=position.numerator//position.denominator
        return Fraction(ordered[floor])+(Fraction(ordered[min(floor+1,len(ordered)-1)])-Fraction(ordered[floor]))*(position-floor)
    q1,median,q3=q(Fraction(1,4)),q(Fraction(1,2)),q(Fraction(3,4))
    return {'n':len(values),'mean':statistics.mean(values),'std':statistics.stdev(values),'min':min(values),'max':max(values),
        'q1':float(q1),'median':float(median),'q3':float(q3),'iqr':float(q3-q1)}


class ComparisonPlotProvider(SyntheticPlotProvider):
    """No authoritative result or expected statistics are available to this provider."""
    def __init__(self,*,corrupt=None):
        super().__init__(None,pending=False); self.corrupt=corrupt

    def receipt(self):
        value=super().receipt();value['response']['output'][1]['content'][0]['annotations'][0]['filename']='/mnt/data/figure.png';return value

    def download(self,file_id,container_id,limit,*,policy):
        self.downloads.append(file_id)
        if file_id=='cfile_png': return self.png
        payload=self.payload;paired=payload['figure_kind']=='paired_connected'
        values=list(map(list,zip(*payload['paired_values']))) if paired else [group['values'] for group in payload['groups']]
        groups=[{'label':group['label'],'statistics':summary(observations)} for group,observations in zip(payload['groups'],values)]
        manifest={key:deepcopy(payload[key]) for key in ('schema_version','figure_kind','language','variables','plot_config')}
        manifest.update(payload['labels'],groups=groups,statistics={'sample_sizes':[len(observations) for observations in values]})
        if paired: manifest['paired_summary']={'n_pairs':len(values[0]),'difference':summary([x-y for x,y in zip(*values)])}
        else:
            manifest['series']=[]
            for group,observations in zip(groups,values):
                ordered=sorted(observations);n=len(ordered)
                def q(k):
                    i,r=divmod((n-1)*k,4)
                    return (Fraction(ordered[i])*(4-r)+Fraction(ordered[min(i+1,n-1)])*r)/4
                a,b,c=q(1),q(2),q(3); low,high=a-(c-a)*Fraction(3,2),c+(c-a)*Fraction(3,2)
                inside=[v for v in ordered if low<=v<=high];outside=[v for v in ordered if v<low or v>high]
                manifest['series'].append({'label':group['label'],'n':n,'q1':float(a),'median':float(b),'q3':float(c),
                    'whislo':inside[0],'whishi':inside[-1],'fliers':sorted(set(outside)),'outlier_count':len(outside)})
        if self.corrupt=='count': manifest['statistics']['sample_sizes'][0]+=1
        if self.corrupt=='paired_difference': manifest['paired_summary']['difference']['mean']+=1
        return json.dumps(manifest,ensure_ascii=False).encode()


def complete_chain(client,method,language):
    base,file,result=result_for(client,method,language)
    task,_=comparison_task(client,base,file,result,'boxplot');provider=ComparisonPlotProvider()
    done=finish_plot(task,provider)
    assert done is not None and done['status']=='succeeded',done
    assert provider.posts==['container','upload','response'] and 'statistics' not in provider.payload
    assert 'PRIVATE-ID' not in json.dumps(provider.payload) and 'LOCAL-QUESTION-SENTINEL' not in json.dumps(provider.payload)
    with database_connection() as db: figure=json.loads(db.execute('SELECT figure_json FROM figures WHERE id=%s',(done['result_figure_id'],)).fetchone()['figure_json'])
    assert figure['schema_version']==3 and figure['engine']['id']=='openai_comparison_plot_v3'
    assert figure['statistics']['sample_sizes']==result['statistics']['sample_sizes']
    task,_=comparison_task(client,base,file,result,'explanation',figure);provider_explain=ModernExplanationProvider()
    done=run_explanation(task,provider_explain)
    assert done is not None and done['status']=='succeeded',done
    outbound=provider_explain.posts[0][1]
    assert outbound['schema_version']==3 and 'PRIVATE-ID' not in json.dumps(outbound) and 'LOCAL-QUESTION-SENTINEL' not in json.dumps(outbound)
    with database_connection() as db: explanation=json.loads(db.execute('SELECT explanation_json FROM explanations WHERE id=%s',(done['result_explanation_id'],)).fetchone()['explanation_json'])
    assert explanation['schema_version']==3 and explanation['engine']['id']=='analysis_explanation_v3'
    task,_=comparison_task(client,base,file,result,'word_report',figure,explanation)
    from app.domain.tasks.execution import run_word_task
    done=run_word_task(task['id'],task['revision'])
    assert done is not None and done['status']=='succeeded',done
    workspace=client.get('/api/v1/tasks/'+task['id']+'/workspace');assert workspace.status_code==200,workspace.text
    url=workspace.json()['artifacts']['report']['download_url'];download=client.get(url)
    assert download.status_code==200,download.text if download.status_code!=200 else ''
    from docx import Document
    document=Document(BytesIO(download.content));text='\n'.join(p.text for p in document.paragraphs)
    assert ('Group comparison report' if language=='en' else '组间比较分析报告') in text and 'LOCAL-QUESTION-SENTINEL' in text
    assert 'PRIVATE-ID' not in text and 'relationship_form' not in text
    if result['selection']['design']=='paired': assert ('5 complete pairs' if language=='en' else '5 个完整对') in text
    if result['selection']['posthoc']=='all_pairs_holm': assert 'Holm' in text and ('simultaneous' if language=='en' else '同时') in text
    with ZipFile(BytesIO(download.content)) as archive: assert [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]==[provider.png]
    return base,file,result,figure,explanation,url,download.content


@pytest.mark.parametrize('method,language',[('welch_t','en'),('mann_whitney_u','zh-CN'),('paired_t','zh-CN'),('wilcoxon','en'),('welch_anova','en'),('kruskal_wallis','zh-CN')])
def test_six_comparisons_real_consumers_download_and_keep_immutable_history(client,monkeypatch,method,language):
    from tests.browser.task_browser_support import block_real_providers
    blocked=block_real_providers(monkeypatch)
    base,file,result,figure,explanation,url,content=complete_chain(client,method,language)
    from tests.api.test_analysis import selection as descriptive_selection
    response=client.put(base+'/analysis-setup',json=descriptive_selection(dataset_id=result['source']['dataset_id'],expected_revision=1,
        sheet_name=result['selection']['sheet_name'],numeric_column='B' if result['selection']['design']=='paired' else 'A',group_column=None,unit=''))
    assert response.status_code==200,response.text
    assert client.get(url).content==content
    png_url=base+'/analysis-runs/'+result['id']+'/figures/'+figure['id']+'/download'
    assert client.get(png_url).status_code==200
    assert blocked==[]
    from app.maintenance.database_audit import audit_database
    with database_connection() as db: assert audit_database(db)['ok'] and db.execute('SELECT count(*) AS n FROM model_calls').fetchone()['n']==2


@pytest.mark.parametrize('corrupt',['count','paired_difference'])
def test_cloud_drawing_mismatch_persists_bounded_evidence_without_publish(client,corrupt):
    base,file,result=result_for(client,'paired_t')
    task,_=comparison_task(client,base,file,result,'boxplot')
    done=finish_plot(task,ComparisonPlotProvider(corrupt=corrupt))
    assert done is not None and done['status']=='failed' and done['error_code']=='plot_result_mismatch',done
    view=client.get('/api/v1/tasks/'+task['id']+'/workspace');assert view.status_code==200,view.text
    failure=view.json()['verification_failure'];assert failure['differences']
    assert 'PRIVATE-ID' not in json.dumps(failure) and 'paired_values' not in failure['manifest']
    with database_connection() as db: assert db.execute('SELECT count(*) AS n FROM figures').fetchone()['n']==0


@pytest.mark.parametrize('target',['figure','report'])
def test_paired_plot_difference_summary_cannot_be_tampered_for_consumers(client,target):
    base,file,result,figure,explanation,report_url,_=complete_chain(client,'paired_t','en')
    url=base+'/analysis-runs/'+result['id']+'/figures/'+figure['id']+'/download' if target=='figure' else report_url
    for change in ['difference','method','renderer']:
        changed=deepcopy(figure)
        if change=='difference': changed['paired_summary']['difference']['mean']=999.
        elif change=='method': changed['method']['id']='welch_t'
        else: changed['engine']['id']='openai_analysis_plot_v2'
        with database_connection(write=True) as db: db.execute('UPDATE figures SET figure_json=%s WHERE id=%s',(json.dumps(changed),figure['id']))
        response=client.get(url);assert response.status_code==409,(target,change,response.status_code)


def test_legacy_chinese_recovery_retains_differences_transactionally(client,cloud):
    from tests.api.test_boxplot import prepared,seed_legacy
    from app.domain.boxplot import recover_legacy_boxplot
    from app.adapters.storage import get_project_store
    base,file,result,url=prepared(client);job=seed_legacy(client,url);cloud.corrupt=True
    parts=url.split('/');store=get_project_store()
    state=recover_legacy_boxplot(parts[4],parts[6],parts[8],store)
    assert state['job']['status']=='failed' and state['job']['differences']
    persisted=store.figure_job(result['id'],'openai_boxplot_v1')
    assert persisted['differences']==state['job']['differences'] and persisted['output_json']['status']=='mismatched'
    assert any(item['path']=='overall.mean' for item in persisted['differences'])
    with database_connection() as db: assert db.execute('SELECT count(*) AS n FROM figures').fetchone()['n']==0
