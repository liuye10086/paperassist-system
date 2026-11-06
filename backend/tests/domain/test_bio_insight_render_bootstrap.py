"""Exported entrypoint must attest the same loaded runtime as the figure worker."""
import ast
from pathlib import Path
import pytest

@pytest.fixture(autouse=True)
def postgres_schema():yield None


def test_renderer_loads_locked_r_runtime_before_attestation_and_sandbox():
    path=Path(__file__).resolve().parents[2]/'app/reproduction_assets/bio_insights/render_worker.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)]
    lines={name:[node.lineno for node in calls if node.func.id==name] for name in ('initialize_propeller','actual_identity','enter')}
    assert len(lines['initialize_propeller'])==1, 'Exported render entrypoint omits the attested R native libraries'
    assert lines['initialize_propeller'][0]<lines['actual_identity'][0]<lines['enter'][0]
    assert not any(node.func.id in ('run','initialize_topics') for node in calls), 'Figure reproduction must not rerun the scientific pipeline'
