import hashlib
import json
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dev'))
import cr_b05_evidence as evidence


def test_retained_material_rejects_changed_bytes_and_index(tmp_path):
    target=tmp_path/'counts.tsv';target.write_bytes(b'1\t0\n')
    index=tmp_path/'files.json';index.write_text(json.dumps([dict(path='counts.tsv',bytes=4,sha256=hashlib.sha256(target.read_bytes()).hexdigest())]))
    expected=hashlib.sha256(index.read_bytes()).hexdigest()
    assert evidence.locked_files(tmp_path,'files.json',expected)=={'counts.tsv'}
    target.write_bytes(b'2\t0\n')
    with pytest.raises(AssertionError,match='bytes/SHA'):evidence.locked_files(tmp_path,'files.json',expected)
    index.write_text('[]')
    with pytest.raises(AssertionError,match='index SHA'):evidence.locked_files(tmp_path,'files.json',expected)


def test_table_identity_rejects_whole_missing_or_duplicate_table():
    expected={'a':{'sha256':'aaa'},'b':{'sha256':'bbb'}}
    rows=[dict(source={'source_id':k},sha256=v['sha256']) for k,v in expected.items()]
    evidence.exact_table_set(rows,expected)
    for wrong in ([],rows[:1],rows+[rows[0]],[dict(rows[0],sha256='x'),rows[1]]):
        with pytest.raises(AssertionError):evidence.exact_table_set(wrong,expected)


def test_result_axes_and_actual_n_reject_substitution_direction_and_false_n():
    expected={'f1':(3,3),'f2':(2,3)}
    rows=[dict(feature_id=k,contrast_id='primary',numerator='C2',denominator='C1',observation_level='sample',inference_scope='sample_exploratory',n_numerator=str(a),n_denominator=str(b),n_pairs='NA',group_sizes=json.dumps({'C2':a,'C1':b})) for k,(a,b) in expected.items()]
    evidence.result_axes(rows,expected,['C2','C1'],'sample_exploratory',False)
    for field,value in [('feature_id','replaced'),('numerator','C1'),('n_numerator','9')]:
        bad=[dict(r) for r in rows];bad[0][field]=value
        with pytest.raises(AssertionError):evidence.result_axes(bad,expected,['C2','C1'],'sample_exploratory',False)


def test_quantitative_gate_rejects_other_code_environment_or_incomplete_evidence():
    import cr_b05_probe
    checks=dict(quantitative_counts=True,quantitative_continuous=True,quantitative_sample_figure=True)
    report=dict(code_digest='code',runtime_identity=dict(code_digest='code',environment_digest='env'),checks=checks,sample_figure_types=['distribution','heatmap'])
    parent=dict(parent_validation=True,validated_names=['continuous-comparison','bulk_counts-comparison','sample-distribution','sample-heatmap'],sample_figure_types=['distribution','heatmap'],checks=checks)
    assert cr_b05_probe.quantitative_checks(report,'code','env',parent)==checks
    for bad in (dict(report,code_digest='old'),dict(report,runtime_identity={'environment_digest':'old'}),dict(report,checks={})):
        with pytest.raises(ValueError):cr_b05_probe.quantitative_checks(bad,'code','env',parent)
    for bad in ({},dict(parent,parent_validation=False),dict(parent,validated_names=parent['validated_names'][:-1]),dict(parent,sample_figure_types=['distribution']),dict(parent,checks={})):
        with pytest.raises(ValueError):cr_b05_probe.quantitative_checks(report,'code','env',bad)
    with pytest.raises(ValueError):cr_b05_probe.quantitative_checks(dict(report,sample_figure_types=['distribution']),'code','env',parent)


def test_bh_keeps_tested_na_in_family_and_low_count_exclusions_outside():
    rows=[dict(feature_id=f,p_value=p,tested=str(t),q_within_contrast=q,q_global_family=q) for f,p,t,q in [('a','.01',True,'.03'),('b','.04',True,'.06'),('c','NA',True,'NA'),('d','NA',False,'NA')]]
    evidence.verify_bh(rows,{'a','b','c'})
    rows[0]['q_within_contrast']='.04'
    with pytest.raises(AssertionError):evidence.verify_bh(rows,{'a','b','c'})


def test_bh_accepts_formal_writer_blank_numeric_nulls():
    rows=[dict(feature_id=f,p_value=p,tested=str(t),q_within_contrast=q,q_global_family=q) for f,p,t,q in [('a','.01',True,'.02'),('b','',True,''),('c','',False,'')]]
    evidence.verify_bh(rows,{'a','b'})


def test_plot_reconciles_every_sample_and_rejects_changed_value(tmp_path):
    import numpy as np
    folder=tmp_path/'figure';folder.mkdir();comparison=tmp_path/'comparison';comparison.mkdir();processed=tmp_path/'processed';processed.mkdir()
    (comparison/'comparison_results.tsv').write_text('feature_id\tq_within_contrast\nf\t0.02\n')
    (processed/'raw_axes.json').write_text(json.dumps(dict(feature_ids=['f'],sample_ids=['a','b'])))
    np.save(processed/'analysis_values.npy',np.array([[3.],[0.]]));np.save(processed/'analysis_missing.npy',np.array([[False],[True]]))
    config=dict(figure_type='distribution',analysis_layer='analysis',feature_ids=['f'],sample_groups=[dict(label='G',sample_keys=[dict(processed_version_id='p',sample_id=s) for s in ['a','b']])])
    (folder/'figure_metadata.json').write_text(json.dumps(dict(config=config,analysis_recomputed=False)))
    data=dict(feature_ids=['f'],z_score=False,source_id='p',source_sha256='sha',groups=[dict(group='G',feature_id='f',total_n=2,measured_n=1,missing_n=1)],rows=[dict(processed_version_id='p',sample_id=s,feature_id='f',group='G',missing=absent,value=value) for s,absent,value in [('a',False,3.),('b',True,None)]])
    path=folder/'plot_data.json';path.write_text(json.dumps(data));source=dict(source_id='p',sha256='sha')
    assert evidence.verify_plot(folder,comparison,processed,config,source)['plot_cells']==2
    data['rows'][0]['value']=4.;path.write_text(json.dumps(data))
    with pytest.raises(AssertionError):evidence.verify_plot(folder,comparison,processed,config,source)


def _volcano_case(tmp_path,q,display):
    folder=tmp_path/'figure';folder.mkdir();comparison=tmp_path/'comparison';comparison.mkdir()
    (comparison/'comparison_results.tsv').write_text('feature_id\trow_key\tq_within_contrast\teffect_value\nf\trow\t'+('NA' if q is None else str(q))+'\t2.0\n')
    config={'figure_type':'volcano'}
    (folder/'figure_metadata.json').write_text(json.dumps(dict(config=config,analysis_recomputed=False)))
    row=dict(feature_id='f',row_key='row',q_value=q,effect_value=2.0,displayed=q is not None,display_neg_log10_q=display)
    path=folder/'plot_data.json'
    def check(**changes):
        path.write_text(json.dumps(dict(rows=[dict(row,**changes)])))
        return evidence.verify_plot(folder,comparison,tmp_path,config,{})
    return check


def test_volcano_accepts_cross_platform_libm_last_bit_only(tmp_path):
    # Retained sacurine example: Linux 0.12173011126333534;
    # Windows 0.12173011126333536 from exactly the same q.
    q=0.7555616193595251;expected=-math.log10(q)
    check=_volcano_case(tmp_path,q,math.nextafter(expected,math.inf))
    assert check()['rows']==1
    assert check(display_neg_log10_q=0.12173011126333534)['rows']==1
    bad=expected
    for _ in range(3):bad=math.nextafter(bad,math.inf)
    for changes in ({'display_neg_log10_q':bad},{'display_neg_log10_q':float('nan')},
                    {'display_neg_log10_q':-expected},{'q_value':math.nextafter(q,math.inf)},
                    {'effect_value':math.nextafter(2.0,math.inf)}):
        with pytest.raises(AssertionError):check(**changes)


@pytest.mark.parametrize('q,display,bad',[(None,None,0.0),(1.0,0.0,math.ulp(0.0)),
    (0.0,300.0,math.nextafter(300.0,math.inf)),(1e-310,300.0,math.nextafter(300.0,math.inf))])
def test_volcano_na_zero_and_display_floor_stay_exact(tmp_path,q,display,bad):
    check=_volcano_case(tmp_path,q,display)
    assert check()['q_floor_only_for_display'] is True
    with pytest.raises(AssertionError):check(display_neg_log10_q=bad)


@pytest.mark.parametrize('name',['../outside','/absolute','C:/foreign','nested\\foreign'])
def test_reproduction_archive_rejects_path_escape_before_writing(tmp_path,name):
    import zipfile
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from verify_cr_b05_reproduction import extract_checked
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as package:
        package.writestr('safe.txt','ok')
        entry=zipfile.ZipInfo('placeholder');entry.filename=name;entry.orig_filename=name
        package.writestr(entry,'bad')
    target=tmp_path/'unpacked'
    with pytest.raises(ValueError):extract_checked(archive,target)
    assert not target.exists()
