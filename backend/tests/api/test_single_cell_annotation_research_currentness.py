"""Only a figure's explicit label dependency invalidates research source freezes."""
from types import SimpleNamespace
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def reader(monkeypatch,annotation_id='labels-v1',current='labels-v1'):
    from app.domain.research_results import sources
    figure=dict(id='figure',task_id='t',annotation_version_id=annotation_id,manifest_sha256='a'*64)
    view=dict(config=dict(kind='annotation' if annotation_id else 'umap'),processed_source=dict(raw_source=dict(source_file_ids=['f'])),members=[])
    class Figures:
        def __init__(self,*args):pass
        def require(self,*args):return figure
        def get(self,*args):return view
    monkeypatch.setattr(sources,'BioFigureStore',Figures)
    value=object.__new__(sources.ResearchSourceReader);value.assets=None
    value._completed=lambda *args:dict(status='succeeded')
    value.bio=SimpleNamespace(require=lambda db,table,project,identifier:
        dict(set_id='set',id='labels-v1') if table=='bio_annotation_versions' else dict(current_version_id=current))
    return value


def test_stale_label_figure_cannot_become_a_current_research_source(monkeypatch):
    from app.core.exceptions import StorageError
    with pytest.raises(StorageError) as exc:
        reader(monkeypatch,current='labels-v2')._bio_figure(None,'p',SimpleNamespace(source_id='figure'))
    assert exc.value.code=='research_source_conflict'


@pytest.mark.parametrize('annotation,current',[('labels-v1','labels-v1'),(None,'labels-v2')])
def test_current_labels_and_label_independent_figures_remain_usable(monkeypatch,annotation,current):
    value=reader(monkeypatch,annotation,current)._bio_figure(None,'p',SimpleNamespace(source_id='figure'))
    assert value['source_file_ids']==['f']


def test_historical_reader_can_read_exact_old_labels_without_marking_them_current(monkeypatch):
    value=reader(monkeypatch,current='labels-v2');value.allow_stale_labels=True
    historical=value._bio_figure(None,'p',SimpleNamespace(source_id='figure'))
    assert historical['sha256']=='a'*64
