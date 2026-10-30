import json
import hashlib
from pathlib import Path
import numpy as np
import pytest
from scipy import sparse
from matplotlib.colors import BoundaryNorm,to_rgba
from app.adapters.bio_engine.manifest import Writer
from app.adapters.bio_engine import plots


def capture(monkeypatch):
    saved=[]
    def save(writer,key,fig,data,config=None):
        saved.append((key,fig,data,config))
    monkeypatch.setattr(plots,'save',save)
    return saved


def test_standalone_cluster_uses_discrete_norm_and_preserves_tissue_status(tmp_path,monkeypatch):
    saved=capture(monkeypatch)
    positions=[{'barcode':'a','in_tissue':1,'pxl_col_in_fullres':0,'pxl_row_in_fullres':0},
               {'barcode':'b','in_tissue':0,'pxl_col_in_fullres':10,'pxl_row_in_fullres':0}]
    plots.spatial(Writer(tmp_path),'spatial_cluster',positions,['a','b'],np.array([True,True]),np.array([0.,1.]),{'kind':'spatial_cluster','layer':'log1p'})
    _,fig,data,_=saved[0]
    color=next(c for c in fig.axes[0].collections if c.get_array() is not None)
    assert isinstance(color.norm,BoundaryNorm)
    assert data['in_tissue']==[1,0]
    assert any('outside tissue' in text.get_text() for text in fig.axes[0].get_legend().get_texts())
    fig.canvas.draw()
    assert not fig.axes[0].get_legend().get_window_extent(fig.canvas.get_renderer()).overlaps(fig.axes[0].get_window_extent())


@pytest.mark.parametrize('n',[21,50])
def test_discrete_palette_has_unique_stable_shared_rgb_for_every_cluster(tmp_path,monkeypatch,n):
    saved=capture(monkeypatch)
    positions=[{'barcode':str(i),'in_tissue':1,'pxl_col_in_fullres':i*2,'pxl_row_in_fullres':0} for i in range(n)]
    plots.spatial(Writer(tmp_path),'spatial_clusters',positions,[str(i) for i in range(n)],np.ones(n,dtype=bool),np.arange(n,dtype=float),{})
    _,fig,data,_=saved[0]
    color=next(c for c in fig.axes[0].collections if c.get_array() is not None)
    assert len(color.norm.boundaries)==n+1
    rgb=[tuple(color.cmap(color.norm(i))[:3]) for i in range(n)]
    assert len(set(rgb))==n
    for kind in ['pca','umap']:
        plots.embedding_figure(Writer(tmp_path),np.column_stack([np.arange(n),np.arange(n)]),np.asarray([str(i) for i in range(n)]),[str(i) for i in range(n)],kind,{'palette':'tab20'})
        _,score_fig,score_data,score_config=saved[-1]
        assert [tuple(collection.get_facecolors()[0,:3]) for collection in score_fig.axes[0].collections]==rgb
        assert score_config['effective_palette']=='paperassist_golden_angle_hsl_v1'
        assert set(score_data['category_colors'])==set(str(i) for i in range(n))
    selected=[0,n//2,n-1]
    plots.embedding_figure(Writer(tmp_path),np.zeros((3,2)),np.asarray([str(i) for i in selected]),['a','b','c'],'pca',{'palette':'tab20'})
    assert [tuple(c.get_facecolors()[0,:3]) for c in saved[-1][1].axes[0].collections]==[rgb[i] for i in selected]
    for _,figure,_,_ in saved:plots.plt.close(figure)


def test_marker_request_gene_kind_and_styles_are_actually_used(tmp_path,monkeypatch):
    saved=capture(monkeypatch)
    counts=sparse.csr_matrix([[1,0],[2,1],[0,4],[1,3]])
    logged=counts.astype('float32');logged.data=np.log1p(logged.data)
    plots.marker_figures(Writer(tmp_path),counts,logged,np.array(['0','0','1','1']),['g1','g2'],[{'feature_id':'g1'}],
                         {'kind':'marker_heatmap','gene_ids':['g2'],'cmap':'magma','vmin':0.,'vmax':3.,'title':'Fixed title'})
    assert [s[0] for s in saved]==['marker_heatmap']
    _,fig,data,_=saved[0]
    assert data['feature_ids']==['g2']
    assert fig.axes[0].images[0].get_cmap().name=='magma'
    assert fig.axes[0].images[0].get_clim()==(0.,3.)
    assert fig.axes[0].get_title()=='Fixed title'


def test_qc_mitochondrial_figure_has_explicit_unknown_and_fraction(tmp_path,monkeypatch):
    saved=capture(monkeypatch)
    qc={'raw_counts':np.array([1,2]),'raw_detected':np.array([1,1]),'filtered_total':np.array([1,2]),'filtered_detected':np.array([1,1]),
        'obs_mask':np.ones(2,dtype=bool),'mt_fraction':None,'mt_reason':'mitochondrial_rule_unconfirmed','extreme_fences':{}}
    plots.qc_figures(Writer(tmp_path),qc,{})
    data=next(s[2] for s in saved if s[0]=='qc_mitochondrial')
    assert data['status']=='not_computable' and data['reason']=='mitochondrial_rule_unconfirmed'
    saved.clear();qc.update(mt_fraction=np.array([.2,.7]),mt_reason=None)
    plots.qc_figures(Writer(tmp_path),qc,{})
    data=next(s[2] for s in saved if s[0]=='qc_mitochondrial')
    np.testing.assert_equal(data['fraction'],[.2,.7])


def test_annotation_polygons_points_and_legend_share_label_colors(tmp_path,monkeypatch):
    import anndata as ad
    import pandas as pd
    from app.adapters.bio_engine.figure import render
    from test_bio_engine_transport import payload_fixture
    payload,raw=payload_fixture(tmp_path);saved=capture(monkeypatch)
    obj=ad.AnnData(raw.astype('float32'),obs=pd.DataFrame({'raw_index':np.arange(24),'cluster':['0']*24},index=['b'+str(i) for i in range(24)]))
    path=tmp_path/'object.h5ad';obj.write_h5ad(path)
    def descriptor(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size_bytes':path.stat().st_size}
    geometry=tmp_path/'geometry.json';geometry.write_text(json.dumps({'regions':[
        {'id':'r1','label_id':'A','points':[[0,0],[10,0],[0,10]]},
        {'id':'r2','label_id':'A','points':[[10,10],[20,10],[10,20]]},
        {'id':'r3','label_id':'B','points':[[20,20],[30,20],[20,30]]}]+[
        {'id':'r'+str(i+2),'label_id':'L'+str(i),'points':[[i,0],[i+1,0],[i,1]]} for i in range(2,50)]}))
    assignments=tmp_path/'assignments.json';assignments.write_text(json.dumps({'rows':[{'barcode':'b0','label_id':'A'},{'barcode':'b1','label_id':'B'}]}))
    payload.update(mode='figure',processed={'manifest':{},'members':{'processed':descriptor(path)}},config={'kind':'annotation','palette':'tab20'},
        annotation={'labels':[{'id':'B','name':'B label','status':'proposed'},{'id':'A','name':'A label','status':'proposed'}]+[
            {'id':'L'+str(i),'name':'Label '+str(i),'status':'proposed'} for i in range(2,50)],
                    'members':{'geometry':descriptor(geometry),'assignments':descriptor(assignments)}})
    render(payload)
    _,fig,data,_=saved[0];ax=fig.axes[0]
    a_poly=ax.patches[0].get_facecolor()[:3]
    assert a_poly==ax.patches[1].get_facecolor()[:3]
    assert a_poly==to_rgba(ax.lines[0].get_color())[:3]
    assert ax.patches[2].get_facecolor()[:3]==to_rgba(ax.lines[1].get_color())[:3]
    assert len(set(tuple(color[:3]) for color in data['label_colors'].values()))==50
    assert saved[0][3]['effective_palette']=='paperassist_golden_angle_hsl_v1'
