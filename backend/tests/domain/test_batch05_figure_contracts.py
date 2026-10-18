import pytest
from pydantic import ValidationError
from sqlalchemy import MetaData
from app.domain.figure_workbench.contracts import FigureConfig
from app.db.figure_workbench_schema import define_figure_workbench_tables


def test_configuration_separates_styles_and_semantics():
    config=FigureConfig.model_validate({'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'B'}})
    assert config.style.width==2400
    for body in [{'figure_kind':'bar','language':'en','projection':{'category_column':'A','bar_stat':'proportion','error_bars':'sd'}}, {'figure_kind':'boxplot','language':'en','style':{'width':True}}, {'figure_kind':'boxplot','language':'en','style':{'palette':'arbitrary'}}]:
        with pytest.raises(ValidationError): FigureConfig.model_validate(body)


def test_schema_defines_only_owned_tables():
    metadata=MetaData(); tables=define_figure_workbench_tables(metadata)
    assert [t.name for t in tables]==['figure_configurations','figure_config_versions','figure_projection_decisions','figure_projection_results']
    assert set(metadata.tables)==set(t.name for t in tables)
    assert 'figure_config_version_id' not in metadata.tables

def test_incomplete_draft_can_be_saved_without_pretending_ready():
    config=FigureConfig.model_validate({'figure_kind':'line','language':'en'})
    assert config.projection is None


@pytest.mark.parametrize('rules',[
    {'x_type':'datetime','expected_x':['not-a-date']},
    {'x_type':'datetime','expected_x':['2026-01-01T00:00:00Z']},
    {'x_type':'numeric','expected_x':['1']},
    {'x_type':'ordered','x_order':['a','a']},
    {'x_type':'ordered','x_order':['a'],'expected_x':['b']},
    {'x_type':'ordered','x_order':['a'*161]},
    {'included_categories':['a'*161]},
    {'expected_x':[10**400]},
])
def test_projection_rule_values_are_validated_before_persistence(rules):
    with pytest.raises(ValidationError):FigureConfig.model_validate({'figure_kind':'line','language':'en','projection':rules})
