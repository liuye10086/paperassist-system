from copy import deepcopy
import pytest
from tests.domain.test_correlation_artifacts import result,confirmed


def saved_sources():
    from app.domain.artifact_contracts import figure_metadata,explanation_metadata
    from app.domain.correlation_material import build_material
    from app.domain.external_material import explanation_material
    from app.domain.explanation_content import render_explanation
    value=result()
    _,expected=build_material(value,[[1.,2.],[2.,1.],[3.,4.],[4.,3.]],external=confirmed(value))
    figure={**figure_metadata(value,expected,{'model':'synthetic'},external=confirmed(value)),
            'id':'figure','sha256':'c'*64}
    external=confirmed(value,'explanation','Approved study summary')
    # Frozen title is the saved figure title, not an unrelated test fixture title.
    from app.domain.external_processing import digest, normalize_confirmation
    external['labels']['figure_title']=figure['title']
    external['confirmation_digest']=digest(normalize_confirmation({'version':4,'confirmed':True,
        'source_digest':external['source_digest'],'labels':external['labels']}))
    payload,_=explanation_material(value,figure,external)
    draft={key:'Based on '+', '.join('{{'+ref+'}}' for ref in refs)+'.' for key,refs in payload['required_references'].items()}
    explanation={**explanation_metadata(value,figure,render_explanation(draft,payload),payload,
        {'model':'synthetic','external_processing':external}),'id':'explanation'}
    return value,figure,explanation


def test_exact_modern_sources_and_fact_catalogue_are_accepted():
    from app.domain.reports import validate_sources
    validate_sources(*saved_sources())


@pytest.mark.parametrize('changed',['plan','language','kind','figure_hash','fact','input_hash','downgrade','method','statistics'])
def test_modern_source_changes_or_downgrades_block_word(changed):
    from app.domain.reports import validate_sources
    from app.core.exceptions import StorageError
    value,figure,explanation=deepcopy(saved_sources())
    if changed=='plan': figure['plan_sha256']='f'*64
    elif changed=='language': explanation['language']='zh-CN'
    elif changed=='kind': figure['figure_kind']='boxplot'
    elif changed=='figure_hash': explanation['figure_sha256']='f'*64
    elif changed=='fact': explanation['sections'][3]['evidence'][0]['value']='fake'
    elif changed=='input_hash': explanation['provenance']['input_sha256']='f'*64
    elif changed=='downgrade': figure['engine']['id']='openai_boxplot_v1'
    elif changed=='method': figure['correlation_method']='spearman'
    else: figure['statistics']['coefficient']=0.9
    with pytest.raises(StorageError) as error: validate_sources(value,figure,explanation)
    assert error.value.code=='report_source_changed'
