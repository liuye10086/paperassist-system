from types import SimpleNamespace
from app.domain.figure_workbench.sources import population_rows


def test_population_keeps_confirmed_range_and_groups_but_not_original_complete_cases():
    cells=[SimpleNamespace(row=r,column=1,kind='text',value=v) for r,v in [(2,'A'),(3,'B'),(4,'C'),(5,'A'),(6,'A')]]
    sheet=SimpleNamespace(data_range='A2:C6',cells=cells)
    result={'selection':{'group_column':'A','groups':[{'kind':'text','value':'A'},{'kind':'text','value':'B'}]},'analysis_context':{'plan':{'check':{'data_range':'A2:C5'}}},'row_audit':{'included_rows':[2,3],'excluded_rows':[{'row':5,'reason':'selected_missing'}]}}
    rows,audit=population_rows(sheet,result)
    assert rows=={2,3,5}
    assert audit==[{'row':4,'reason':'population_group_not_selected'},{'row':6,'reason':'outside_confirmed_range'}]
