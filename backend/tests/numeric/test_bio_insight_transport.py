"""Production pipe + fresh runtime attestation + kernel sandbox, no mocks."""
import pytest


@pytest.mark.parametrize('operation',['spot','donor','import','resource','ora','gsea','candidate','figure'])
def test_actual_fixed_child_under_kernel_sandbox(tmp_path,monkeypatch,operation):
    import json
    from pathlib import Path
    import subprocess
    from app.domain.bio_insights.settings import runtime_identity
    from app.adapters.bio_insights_engine import pipeline
    from test_bio_insight_parent_contract import test_actual_scientific_pipeline_satisfies_parent_contract
    runtime=runtime_identity()
    assert runtime['available'], 'Run with a fresh actual image runtime gate'
    def production(payload):
        payload['identity'].update({k:v for k,v in runtime.items() if k!='available'})
        try:
            process=subprocess.run(['/usr/local/bin/python','-I','-B',str(Path(__file__).with_name('bio_insight_parent_driver.py'))],
                input=json.dumps(payload),text=True,capture_output=True,timeout=240)
            if process.returncode:raise RuntimeError(process.stderr[-5000:])
            return json.loads(process.stdout)
        except Exception as exc:
            diagnostic=Path(payload['output_directory'])/'failure-diagnostics.json'
            if diagnostic.is_file():exc.add_note(diagnostic.read_text(encoding='utf-8'))
            raise
    monkeypatch.setattr(pipeline,'run',production)
    test_actual_scientific_pipeline_satisfies_parent_contract(tmp_path,operation)
