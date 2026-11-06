import json
from pathlib import Path
import warnings
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.ft2font import FT2Font
from app.adapters.bio_engine import worker,plots
from app.adapters.bio_engine.manifest import Writer


def test_default_chinese_cell_plot_uses_supported_negative_tick_without_changing_coordinates(tmp_path,monkeypatch):
    font=FT2Font('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')
    assert 0x2212 not in font.get_charmap() and 0x2d in font.get_charmap()
    points=np.asarray([[-3.,-2.],[2.,-1.],[0.,3.],[1.,1.]])
    before=points.copy();barcodes=['a','b','c','d'];clusters=np.asarray(['0','0','1','1'])
    def render_saved(payload):
        assert plt.rcParams['axes.unicode_minus'] is False
        writer=Writer(tmp_path)
        plots.embedding_figure(writer,points,clusters,barcodes,'pca',dict(output_language='zh-CN',dpi=100))
        return writer.artifacts
    monkeypatch.setattr(worker,'run',render_saved)
    with plt.rc_context({'axes.unicode_minus':True}),warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        outputs=worker.run_analysis(dict(raw=dict(manifest=dict(assay='single_cell')),config=dict(output_language='zh-CN')))
        assert plt.rcParams['axes.unicode_minus'] is True
    assert not any('Glyph 8722' in str(item.message) for item in caught)
    members={m['key']:m for m in outputs}
    assert Path(members['pca_png']['path']).read_bytes().startswith(b'\x89PNG')
    saved=json.loads(Path(members['pca_data']['path']).read_bytes())
    np.testing.assert_array_equal(saved['coordinates'],before)
    np.testing.assert_array_equal(points,before)
    assert saved['barcodes']==barcodes


def test_default_plot_setting_is_scoped_to_chinese_single_cell(monkeypatch):
    monkeypatch.setattr(worker,'run',lambda payload:plt.rcParams['axes.unicode_minus'])
    with plt.rc_context({'axes.unicode_minus':True}):
        for assay,language in [('single_cell','en'),('visium','zh-CN')]:
            assert worker.run_analysis(dict(raw=dict(manifest=dict(assay=assay)),config=dict(output_language=language))) is True
