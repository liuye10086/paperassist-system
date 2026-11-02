"""Freeze one real phenotype PNG once, then validate/reuse bytes without plotting."""
import base64,io,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from app.core.exceptions import StorageError

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def saved_source():
    from app.domain.research_results.contracts import FrozenResearchSource
    path=Path(__file__).parents[1]/'fixtures/phenotype_saved_statistics_source.json'
    return FrozenResearchSource.model_validate(json.loads(path.read_text(encoding='utf8')))

def panel_for():
    from app.domain.research_results.contracts import ResearchFigurePanel
    source=saved_source()
    return ResearchFigurePanel(source={'source_kind':'analysis_run','source_id':source.source_id})

def test_actual_host_freeze_then_worker_reuses_checked_png_without_matplotlib(monkeypatch):
    from app.domain.research_results.figure_members import read_figure_panel
    source=saved_source();reader=SimpleNamespace(_read_source_in_phase=lambda *args,**kwargs:source)
    _,frozen,raw=read_figure_panel(reader,None,'project',panel_for(),phase=None,figure_language='zh-CN')
    assert frozen['statistics_png']['source_sha256']==source.sha256
    with Image.open(io.BytesIO(raw)) as image:assert image.format=='PNG' and image.width>500
    def forbidden(*args,**kwargs):raise AssertionError('Frozen panel must not redraw')
    monkeypatch.setattr('app.domain.research_results.statistics_figures.render_statistics_figure',forbidden)
    monkeypatch.setitem(sys.modules,'matplotlib',None)
    _,checked,reused=read_figure_panel(reader,None,'project',panel_for(),phase=None,figure_language='zh-CN',frozen_panel=frozen)
    assert checked==frozen and reused==raw

@pytest.mark.parametrize('damage',['bytes','source_sha'])
def test_frozen_statistics_png_rejects_changed_bytes_or_source_sha(monkeypatch,damage):
    from app.domain.research_results.figure_members import read_figure_panel
    source=saved_source();reader=SimpleNamespace(_read_source_in_phase=lambda *args,**kwargs:source)
    out=io.BytesIO();Image.new('RGB',(10,10)).save(out,format='PNG')
    monkeypatch.setattr('app.domain.research_results.statistics_figures.render_statistics_figure',lambda *args,**kwargs:out.getvalue())
    _,frozen,_=read_figure_panel(reader,None,'project',panel_for(),phase=None,figure_language='en')
    bad=deepcopy(frozen)
    if damage=='bytes':bad['statistics_png']['png_base64']=base64.b64encode(b'changed').decode()
    else:bad['statistics_png']['source_sha256']='f'*64
    with pytest.raises(StorageError):read_figure_panel(reader,None,'project',panel_for(),phase=None,figure_language='en',frozen_panel=bad)
