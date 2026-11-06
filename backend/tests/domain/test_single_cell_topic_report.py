import io
import pytest
from docx import Document
from app.adapters.single_cell_insight_report import build_single_cell_insight_report

@pytest.fixture(autouse=True)
def postgres_schema():yield None

@pytest.mark.parametrize('method,title,table,values',[
    ('slingshot','单细胞轨迹分析报告','trajectory_results',dict(barcode='00123',lineage_id='Lineage1',pseudotime=None,weight=0)),
    ('genie3','单细胞调控网络报告','regulation_results',dict(regulator='00123',target='GENE2',weight=.00000012345678,stability_weight=0)),
    ('cellchat','单细胞通讯分析报告','communication_results',dict(unit_id='u1',sender='T',receiver='B',interaction_id='DEMO_MIF_CD74_CD44',probability=0,cell_permutation_p_value=None))])
def test_topic_report_keeps_saved_values_and_method_boundary(method,title,table,values):
    config=dict(kind='integration',schema_version=2,method=method,output_language='zh-CN')
    blob=build_single_cell_insight_report('r','a'*64,config,dict(methods={'name':method},summary={'topic_method':method}),{table:{'rows':[values],'total':1}},[])
    doc=Document(io.BytesIO(blob));content='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert title in content and 'NA' in content if method!='genie3' else title in content and '00123' in content
    assert '0' in content
    assert '供者级差异表达报告' not in content


def test_communication_report_keeps_edge_specific_donor_numbers_and_missing_reason():
    config=dict(kind='integration',schema_version=2,method='cellchat',output_language='zh-CN')
    rows=[dict(sender='T',receiver='B',interaction_id='LR1',n_denominator=3,n_numerator=3,complete_pairs=3,status='tested',reason=None,donor_p_value=.04,donor_q_value=.08),
          dict(sender='B',receiver='T',interaction_id='LR2',n_denominator=0,n_numerator=0,complete_pairs=0,status='not_computable',reason='insufficient_computable_donors')]
    blob=build_single_cell_insight_report('r','a'*64,config,dict(methods={},summary={'actual_units':[dict(contrast_id='communication',n_denominator=4,n_numerator=4,complete_pairs=4)]}),{'communication_comparisons':{'rows':rows,'total':2}},[])
    doc=Document(io.BytesIO(blob));content='\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert '设计入选数量' in content
    assert '逐边实际供者数' in content and 'insufficient_computable_donors' in content
    assert 'n_denominator' in content and '3' in content


@pytest.mark.parametrize('all_zero',[True,False])
def test_zero_color_scale_note_uses_complete_table_check_not_excerpt(all_zero):
    config=dict(kind='integration',schema_version=2,method='cellchat',output_language='en')
    table=dict(rows=[dict(probability='0',status='computed')],total=432,all_modeled_probabilities_zero=all_zero)
    blob=build_single_cell_insight_report('r','a'*64,config,dict(methods={},summary={}),{'communication_results':table},[])
    content='\n'.join(p.text for p in Document(io.BytesIO(blob)).paragraphs)
    assert ('Negative ticks from automatic color scaling' in content)==all_zero


@pytest.mark.parametrize('method,all_zero',[
    ('slingshot',False),('genie3',False),('cellchat',False),('cellchat',True),('legacy_comparison',False)])
def test_saved_plot_is_embedded_for_every_report_branch(method,all_zero):
    import zipfile
    from PIL import Image
    picture=io.BytesIO();Image.new('RGB',(8,8),'blue').save(picture,format='PNG')
    config=(dict(kind='comparison',mode='donor_paired',output_language='en') if method=='legacy_comparison'
        else dict(kind='integration',schema_version=2,method=method,output_language='en'))
    tables={'communication_results':dict(rows=[],total=0,all_modeled_probabilities_zero=all_zero)}
    blob=build_single_cell_insight_report('r','a'*64,config,dict(methods={},summary={}),tables,
        [dict(key='saved_plot',sha256='b'*64,content=picture.getvalue())])
    document=Document(io.BytesIO(blob))
    assert len(document.inline_shapes)==1
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        media=[name for name in archive.namelist() if name.startswith('word/media/')]
        assert len(media)==1 and archive.read(media[0])==picture.getvalue()
