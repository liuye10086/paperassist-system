from app.domain.figure_workbench.presentation import enrich_material


def test_substring_field_name_does_not_steal_the_other_axis_unit():
    payload={'schema_version':5,'figure_kind':'scatter','language':'en','variables':[{'name':'Weight','unit':'g'},{'name':'BirthWeight','unit':'kg'}], 'labels':{'title':'Weight measurements','x_label':'Weight (g)','y_label':'BirthWeight (kg)','caption':''}}
    expected={'schema_version':5,**payload['labels']}
    out,_=enrich_material(payload,expected,config={'style':{}},result={},projection=None,fields={})
    assert out['presentation']['axes']['x']=={'label':'Weight (g)','unit':'g'}
    assert out['presentation']['axes']['y']=={'label':'BirthWeight (kg)','unit':'kg'}


def test_legend_retains_typed_group_identity_and_only_the_confirmed_population():
    from app.domain.figure_workbench.kernel import compute_projection
    from app.domain.figure_workbench.material import projection_material
    from app.domain.figure_workbench.contracts import FigureConfig
    config=FigureConfig(figure_kind='bar',language='en',projection={'category_column':'A','group_column':'B','bar_stat':'count','included_categories':['yes']}).model_dump()
    rows=[{'row':i+1,'category':'yes','group':g} for i,g in enumerate([True,1.,'True'])]+[{'row':4,'category':'no','group':'Excluded arm'}]
    projection=compute_projection('bar',rows,config['projection'])
    payload,expected=projection_material(config,rows,projection)
    out,_=enrich_material(payload,expected,config=config,result={},projection=projection,fields={})
    entries=out['presentation']['legend']['entries']
    assert len(entries)==3
    assert len({e['label'] for e in entries})==3
    assert not any('Excluded arm' in e['label'] for e in entries)
    assert any('boolean' in e['label'] for e in entries) and any('text' in e['label'] for e in entries)
