"""Actual scientific writers must satisfy the independent parent validator."""
import hashlib
import numpy as np
import pytest


@pytest.mark.parametrize('operation',['spot','donor','import','resource','ora','gsea','candidate','figure'])
def test_actual_scientific_pipeline_satisfies_parent_contract(tmp_path,operation):
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    from bio_insights_fixtures import source,config,payload
    from test_bio_result_import import external
    from test_bio_ora import result_source,resource_source,config as ora_config
    from test_bio_gsea import setup
    from app.domain.bio_insights.contracts import ResourceImportRequest
    if operation in ('spot','donor'):
        if operation=='spot':
            s=source(tmp_path,[[1,9],[2,8],[3,7],[7,3],[8,2],[9,1]])
            value=payload(config(6),[s])
        else:
            from test_bio_pseudobulk import donor_fixture
            _,s,cfg=donor_fixture(tmp_path);value=payload(cfg,[s])
    elif operation=='import':value=external(tmp_path,b'id,lfc,p,q\ng1,2,0,0\ng2,-1,NA,NA\n')
    elif operation=='resource':
        path=tmp_path/'input.gmt';path.write_bytes(b't1\tterm one\tg1\tg2\n')
        member=dict(path=str(path),size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),format='gmt',role='gmt')
        cfg=ResourceImportRequest.model_validate(dict(kind='gene_sets',title='synthetic',species_taxon_id=9606,namespace='ensembl',release='v1',
            source={'institution':'synthetic','name':'synthetic','description':'test fixture'},usage={'basis':'test','scope':'project','redistribution_allowed':False},
            files=[{'file_id':'file1','sha256':member['sha256'],'role':'gmt','format':'gmt'}])).model_dump(mode='json')
        value=dict(schema_version=1,kind='bio_resource_import',config=cfg,sources=[dict(source_kind='original_file',source_id='file1',role='gmt',
            sha256=member['sha256'],metadata={},members={'original_file':member})])
    elif operation=='gsea':
        s,r,cfg=setup(tmp_path);value=dict(schema_version=1,kind='bio_enrichment',config=cfg,sources=[s,r])
    else:
        s=result_source(tmp_path)
        if operation=='ora':value=dict(schema_version=1,kind='bio_enrichment',config=ora_config(),sources=[s,resource_source(tmp_path)])
        elif operation=='candidate':value=dict(schema_version=1,kind='bio_candidate',sources=[s],config=dict(kind='candidate',
            result_source_ids=['result1'],primary_result_source_id='result1',source_contrasts={'result1':'c1'},
            steps=[dict(operation='threshold',source_ids=['result1'],q_column='q_within_contrast',q_threshold=.05)]))
        else:
            s['metadata']['kind']='comparison'
            value=dict(schema_version=1,kind='bio_insight_figure',sources=[s],config=dict(kind='figure',result_source_id='result1',
                figure_type='volcano',formats=['png'],width_inches=2.,height_inches=2.,dpi=72))
    output=tmp_path/'output';output.mkdir()
    value['identity']={'project_id':'synthetic-project','task_id':'synthetic-task','source_digest':'a'*64,
                       'engine_version':'bio_insights_v1.0.0','code_digest':'b'*64,'environment_digest':'c'*64,'lock_sha256':'d'*64}
    value['output_directory']=str(output)
    if value['kind']=='bio_comparison':
        from app.domain.bio_insights.contracts import ComparisonConfig
        # The service freezes complete normalized configurations; preserve its
        # default data-driven flag in the real pipeline rather than omitting it.
        value['config']=ComparisonConfig.model_validate(value['config']).model_dump(mode='json')
    result=run(value)
    assert validate_result(result,output,value)==result
