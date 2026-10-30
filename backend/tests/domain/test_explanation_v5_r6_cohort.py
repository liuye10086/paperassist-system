import json
from copy import deepcopy
from pathlib import Path
import pytest
from app.core.exceptions import PlotError
from app.domain.figure_workbench.explanation_v5 import validate_draft_v5,sentence_draft_v5
DIR=Path(__file__).parents[1]/'fixtures/figure_b07'
@pytest.fixture(autouse=True)
def postgres_schema():yield None
def fixture(task):return json.loads((DIR/f'r6-actual-{task}.json').read_text(encoding='utf8'))
@pytest.mark.parametrize('path',sorted(DIR.glob('r6-actual-*.json')),ids=lambda p:p.stem)
def test_actual_raw(path):
    f=json.loads(path.read_text(encoding='utf8'));validate_draft_v5(f['draft'],f['payload'])
ROC='139aff4e-3c52-4bf2-a715-8376bc61b89a'
LINE='1ad7cfb6-c54b-44fb-89a6-596d7d8eb3ae'
VIOLIN='3170eaf0-dd0d-4db3-8849-929ce917ffb0'
KM='511f2d78-3b17-4485-9bc0-6e2e471d0900'
BAR='73763dce-0bc3-4395-aa77-cfc63761a263'
SCATTER='7a2bd90e-98fd-4281-b668-d285d7fdea2a'
HEAT='7c451efc-68b5-4b02-be0e-6179909a2f23'
KM_EN='812a0ffc-03fe-42a3-abde-11c7d94cfd5e'
SCAT_EN='de0becff-2f31-4809-9cc2-63550c037072'
VIO_CN='e1d281ae-ab76-4ed1-b535-a2761603f321'
def check(task,text):
    p=fixture(task)['payload'];d=sentence_draft_v5(p);d['results']+=' '+text;validate_draft_v5(d,p)
@pytest.mark.parametrize('task,text',[
    (ROC,'保存的置信区间信息为{{modeling.confidence_interval}}。'),
    (ROC,'本图使用的有效数据记录数为{{data.valid}}。'),
    (ROC,'本图使用的数据记录总数为{{data.total}}。'),
    (ROC,'本图排除的数据记录数为{{data.excluded}}。'),
    (LINE,'本图记录的投影排除记录数为{{data.excluded}}。'),
    (VIOLIN,'The saved lower quartile is {{projection.0.q1}}.'),
    (VIOLIN,'The saved projection record count is {{projection.0.n}}.'),
    (VIOLIN,'The projection valid-record count is {{data.valid}}.'),
    (VIOLIN,'The projection population-record count is {{data.total}}.'),
    (VIOLIN,'Record-count interpretation must account for {{limitation.1}}.'),
    (VIOLIN,'The projection uses a valid-record count of {{data.valid}}.'),
    (KM,'本图的数据记录总数为{{data.total}}。'),
    (KM,'该组保存的最长观察时间为{{modeling.groups.0.max_time}}。'),
    (KM,'保存结果同时提示{{modeling.warnings}}。'),
    (KM,'本图的科学解释须考虑{{limitation.0}}。'),
    (BAR,'The causal boundary is stated as follows: {{limitation.4}}.'),
    (BAR,'The observation-independence boundary is stated as follows: {{limitation.3}}.'),
    (BAR,'The distinction between record populations and independent participants is stated as follows: {{limitation.1}}.'),
    (SCATTER,'保存的共同有效记录数为{{correlation.n}}，该记录数不应直接视为已核实的独立参与者人数。'),
    (SCATTER,'这些数量描述数据记录，不代表已经核实的独立参与者人数。'),
    (SCATTER,'分析使用的完整记录数为{{data.valid}}。'),
    (SCATTER,'双侧检验的概率值为{{correlation.p_value}}。'),
    (HEAT,'The saved common effective record count is {{correlation.n}}.'),
    (HEAT,'The saved coefficient pairing {{variables.0.name}} with {{variables.1.name}} is {{matrix.0.1}}.'),
    (HEAT,'The analysis retains {{data.valid}} complete original records, without identifying them as independent participants.'),
    (HEAT,'The saved analysis method states: {{method.summary}}.'),
    (KM_EN,'Causal interpretation is bounded by {{limitation.5}}.'),
    (KM_EN,'The saved median is {{modeling.groups.0.median}}.'),
    (KM_EN,'The saved event count is {{modeling.groups.0.event_n}}.'),
    (KM_EN,'The saved censored-record count is {{modeling.groups.0.censored_n}}.'),
    (KM_EN,'The maximum observed time is {{modeling.groups.0.max_time}}.'),
    (SCAT_EN,'The results report a correlation coefficient of {{correlation.coefficient}}, a two-sided P value of {{correlation.p_value}}, and a confidence interval of {{correlation.confidence_interval}}.'),
    (SCAT_EN,'Interpretation must respect the association boundary: {{limitation.0}}.'),
    (SCAT_EN,'The saved association concerns {{variables.0.name}} and {{variables.1.name}}.'),
    (SCAT_EN,'The analysis includes {{data.valid}} complete original records, which are not thereby a verified count of independent participants.'),
    (SCAT_EN,'These counts describe source rows and original analysis records, not projection records or verified independent participants.'),
    (VIO_CN,'记录口径的解释须遵循{{limitation.1}}。'),
    (VIO_CN,'缺组处理遵循{{method.rule.missing_group}}。'),
    (VIO_CN,'原统计有效记录数另记为{{data.original_n}}。'),
])
def test_valid(task,text):check(task,text)
@pytest.mark.parametrize('task,text',[
    (ROC,'保存的置信区间信息为{{modeling.auc}}。'),
    (ROC,'本图使用的有效数据记录数为{{data.total}}。'),
    (ROC,'本图排除的数据记录数为{{data.valid}}。'),
    (LINE,'本图记录的投影排除记录数为{{data.original_n}}。'),
    (VIOLIN,'The saved lower quartile is {{projection.0.q3}}.'),
    (VIOLIN,'The saved projection record count is {{data.original_n}}.'),
    (VIOLIN,'The projection valid-record count is {{data.original_n}}.'),
    (VIOLIN,'Record-count interpretation must account for {{limitation.5}}.'),
    (VIOLIN,'Record-count interpretation must account for {{limitation.1}}, and the record count is twenty.'),
    (VIOLIN,'The weighted lower quartile is {{projection.0.q1}}.'),
    (KM,'本图的加权数据记录总数为{{data.total}}。'),
    (KM,'该组保存的最长观察时间为{{modeling.groups.0.median}}。'),
    (KM,'保存结果同时提示。'),
    (KM,'本图的科学解释须考虑。'),
    (BAR,'The causal boundary is stated as follows: {{limitation.3}}.'),
    (BAR,'The observation-independence boundary is stated as follows: {{limitation.4}}.'),
    (BAR,'The established causal boundary is stated as follows: {{limitation.4}}.'),
    (BAR,'The distinction between record populations and independent participants is stated as follows: {{limitation.4}}.'),
    (BAR,'The distinction between record populations and verified independent participants is stated as follows: {{limitation.1}}.'),
    (SCATTER,'这些数量描述数据记录，代表已经核实的独立参与者人数。'),
    (SCATTER,'双侧检验的概率值为{{correlation.coefficient}}。'),
    (HEAT,'The saved coefficient pairing {{variables.0.name}} with {{variables.1.name}} is {{matrix.1.0}}.'),
    (HEAT,'The saved coefficient pairing {{variables.0.name}} with {{variables.1.name}} is {{matrix.0.0}}.'),
    (HEAT,'The saved weighted coefficient pairing {{variables.0.name}} with {{variables.1.name}} is {{matrix.0.1}}.'),
    (HEAT,'The saved common effective record count is {{data.valid}}.'),
    (HEAT,'The analysis retains {{data.valid}} complete original records, identifying them as independent participants.'),
    (HEAT,'The analysis retains {{data.valid}} complete original records, without identifying them as independent participants, and independence is verified.'),
    (HEAT,'The saved analysis method states: and.'),
    (HEAT,'The saved states: {{method.summary}}.'),
    (VIOLIN,'The analysis retains {{data.valid}} complete original records, without identifying them as independent participants.'),
    (KM_EN,'Causal interpretation is bounded by {{limitation.4}}.'),
    (KM_EN,'Causal interpretation is established by {{limitation.5}}.'),
    (KM_EN,'The saved median is {{modeling.groups.0.max_time}}.'),
    (KM_EN,'The saved event count is {{modeling.groups.0.censored_n}}.'),
    (KM_EN,'The maximum observed time is {{modeling.groups.0.median}}.'),
    (SCAT_EN,'The results report a correlation coefficient of {{correlation.p_value}}.'),
    (SCAT_EN,'The results report a two-sided P value of {{correlation.coefficient}}.'),
    (SCAT_EN,'The results report a confidence interval of {{correlation.coefficient}}.'),
    (SCAT_EN,'The analysis includes {{data.valid}} complete original records, which are thereby a verified count of independent participants.'),
    (VIOLIN,'These counts describe source rows and original analysis records, not projection records or verified independent participants.'),
    (SCAT_EN,'These counts describe source rows and original analysis records, not projection records or verified independent participants, and independence is verified.'),
    (SCAT_EN,'Interpretation must respect.'),
    (SCAT_EN,'The saved association concerns.'),
    (VIO_CN,'记录口径的解释须遵循。'),
    (VIO_CN,'原统计有效记录数另记为{{data.valid}}。'),
    (VIO_CN,'原统计有效记录数另记为。'),
])
def test_bad(task,text):
    with pytest.raises(PlotError):check(task,text)

def test_group_pronoun_requires_unique_group_identity():
    p=deepcopy(fixture(KM)['payload'])
    p['facts']['modeling.groups.1.label']=deepcopy(p['facts']['modeling.groups.0.label'])
    d=sentence_draft_v5(p);d['results']+=' 该组保存的最长观察时间为{{modeling.groups.0.max_time}}。'
    with pytest.raises(PlotError):validate_draft_v5(d,p)

@pytest.mark.parametrize('replacement',['0.99','twenty','{{modeling.unknown}}','{{modeling.positive_n}}'])
def test_actual_roc_metric_replacement_stays_rejected(replacement):
    f=fixture('006f95bd-a60c-4ba5-930d-555f63593163');d=deepcopy(f['draft'])
    d['results']=d['results'].replace('{{modeling.auc}}',replacement)
    # Keep every required ref so rejection must concern the new claim/scope.
    d['results']+=' The saved results report {{modeling.auc}}.'
    with pytest.raises(PlotError):validate_draft_v5(d,f['payload'])

@pytest.mark.parametrize('changes',[{'raw':''},{'value':''},{'raw':'Causation cannot be inferred','value':'Causation cannot be inferred'}])
def test_record_population_meta_requires_actual_nonempty_limitation(changes):
    p=deepcopy(fixture(VIOLIN)['payload']);p['facts']['limitation.1'].update(changes)
    d=sentence_draft_v5(p);d['results']+=' Record-count interpretation must account for {{limitation.1}}.'
    with pytest.raises(PlotError):validate_draft_v5(d,p)
