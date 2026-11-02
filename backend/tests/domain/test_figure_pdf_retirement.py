"""Format retirement checks use tiny existing data, never a scientific fit."""
import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_new_bio_figure_defaults_and_explicit_pdf_rejection():
    from app.domain.bio_insights.contracts import FigureConfig
    assert FigureConfig(result_source_id='r',figure_type='volcano').formats==['png','tiff','svg']
    with pytest.raises(ValidationError):
        FigureConfig(result_source_id='r',figure_type='volcano',formats=['png','pdf'])


def test_frozen_bio_plan_reads_pdf_without_changing_config_or_new_request_rules():
    from app.domain.bio_insights.contracts import FrozenInsightPlanRequest,InsightPlanRequest
    data=dict(name='historical',kind='figure',decision='confirmed',expected_revision=1,
        sources=[dict(source_kind='bio_insight_result_version',source_id='r',role='result',sha256='a'*64)],
        config=dict(kind='figure',result_source_id='r',figure_type='volcano',formats=['png','pdf']))
    saved=FrozenInsightPlanRequest.model_validate(data)
    assert saved.config.formats==data['config']['formats']
    assert saved.model_dump(mode='json')['config']['formats']==['png','pdf']
    with pytest.raises(ValidationError):InsightPlanRequest.model_validate(data)


def test_bitmap_render_rejects_pdf_before_writing(tmp_path):
    from app.adapters.research_figure_render import render_figure
    raw=io.BytesIO();Image.new('RGB',(8,4),'red').save(raw,'PNG');path=tmp_path/'source.png';path.write_bytes(raw.getvalue())
    output=tmp_path/'out';output.mkdir()
    payload=dict(config=dict(mode='reuse',width_mm=85,dpi=150,formats=['pdf']),
        panels=[dict(path=str(path),sha256=hashlib.sha256(raw.getvalue()).hexdigest(),source={})])
    with pytest.raises(ValueError,match='format'):render_figure(payload,output)
    assert not list(output.iterdir())


def test_spatial_plot_save_writes_png_and_preserves_data_without_pdf(tmp_path):
    from app.adapters.bio_engine.plots import save,plt
    from app.adapters.bio_engine.manifest import Writer
    fig,ax=plt.subplots();ax.plot([0,1],[1,0]);writer=Writer(tmp_path)
    save(writer,'tiny',fig,{'values':[1,0]},{'dpi':100,'width_inches':2,'height_inches':2})
    assert {m['format'] for m in writer.artifacts}=={'png','json'}
    assert json.loads((tmp_path/'tiny_data.json').read_text())=={'values':[1,0]}


def test_tabular_plot_writes_png_tiff_svg_without_pdf(tmp_path):
    from app.adapters.bio_engine.tabular_assays import _figure
    from app.adapters.bio_engine.manifest import Writer
    writer=Writer(tmp_path)
    _figure(writer,'tiny','Fixture',lambda ax:ax.plot([0,1],[1,0]),{'values':[1,0]},SimpleNamespace(output_language='en'))
    assert {m['format'] for m in writer.artifacts}=={'png','tiff','svg','json'}
    assert json.loads((tmp_path/'tiny_manifest.json').read_text())['formats']==['png','tiff','svg']


@pytest.mark.parametrize('module',['bio_analysis_process','bio_insights_process'])
def test_new_child_output_validators_reject_pdf(tmp_path,module):
    from importlib import import_module
    from app.core.exceptions import StorageError
    raw=b'%PDF-1.4\nold historical bytes';path=tmp_path/'figure_pdf.pdf';path.write_bytes(raw)
    item=dict(key='figure_pdf',format='pdf',path=str(path),role='figure',sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw))
    with pytest.raises(StorageError):import_module('app.adapters.'+module).validate_artifacts([item],tmp_path)


@pytest.mark.parametrize('explicit',[False,True])
def test_portable_render_rejects_saved_or_explicit_pdf_before_running_worker(tmp_path,explicit):
    from app.reproduction_assets.bio_insights.reproduce import operate
    root=tmp_path/'package';(root/'input').mkdir(parents=True)
    (root/'package.json').write_text(json.dumps({'render':{'supported':True}}))
    (root/'input/payload.json').write_text('{}')
    payload=dict(config=dict(result_source_id='r',formats=['pdf']),sources=[])
    (root/'input/render-payload.json').write_text(json.dumps(payload))
    config=tmp_path/'config.json';config.write_text(json.dumps(payload['config']))
    with pytest.raises(ValueError,match='PDF figure export is retired'):
        operate(root,'render',tmp_path/'out',config=config if explicit else None)
    assert not (tmp_path/'out').exists()


def test_historical_pdf_configuration_cannot_start_current_runtime():
    from app.domain.bio_insights.contracts import FrozenFigureConfig
    from app.domain.bio_insights.service import BioInsightsService
    from app.core.exceptions import StorageError
    config=FrozenFigureConfig(result_source_id='r',figure_type='volcano',formats=['pdf'])
    with pytest.raises(StorageError) as error:
        BioInsightsService._runtime_for(object.__new__(BioInsightsService),config)
    assert error.value.code=='bio_figure_pdf_export_retired'


def test_portable_recompute_with_pdf_baseline_stops_before_worker(tmp_path):
    from app.reproduction_assets.bio_insights.reproduce import operate
    root=tmp_path/'package';(root/'input').mkdir(parents=True)
    (root/'package.json').write_text(json.dumps({'baseline':[{'format':'pdf'}]}))
    (root/'input/payload.json').write_text('{}')
    with pytest.raises(ValueError,match='PDF figure export is retired'):
        operate(root,'recompute',tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_historical_pdf_vector_comparison_remains_read_only(tmp_path):
    from app.reproduction_assets.bio_insights.reproduce import pdf_content
    raw=b'%PDF-1.4\n1 0 obj /Type /Page /MediaBox [0 0 72 72]\nstream\n0 0 m 1 1 l S\nendstream\nendobj'
    path=tmp_path/'historical.pdf';path.write_bytes(raw)
    assert pdf_content(path)['page_count']==1
    assert path.read_bytes()==raw
