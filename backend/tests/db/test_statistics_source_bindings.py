"""B05 typed run targets: metadata checks need no PostgreSQL; DB cases share one schema."""
import importlib.util
from pathlib import Path
import pytest
from sqlalchemy import CheckConstraint
from app.db.schema import metadata
@pytest.fixture(autouse=True)
def postgres_schema():yield None

def test_statistics_source_has_typed_fk_and_exclusive_target_in_both_bindings():
    from app.db.research_results_schema import SOURCE_TARGETS
    assert SOURCE_TARGETS['analysis_run']==('analysis_run_id','analysis_runs')
    for name in ('research_source_bindings','manuscript_research_sources'):
        table=metadata.tables[name]
        assert any(list(f.column_keys)==['analysis_run_id'] and f.referred_table.name=='analysis_runs' for f in table.foreign_key_constraints)
        assert any("source_kind='analysis_run'" in str(c.sqltext) and 'num_nonnulls' in str(c.sqltext) for c in table.constraints if isinstance(c,CheckConstraint))

def test_0063_contains_project_completion_protection_and_no_old_run_rewrite():
    path=Path(__file__).parents[2]/'alembic/versions/0063_qpcr_statistics_bridge.py'
    assert path.exists()
    text=path.read_text(encoding='utf8')
    assert 'b05_statistics_source_scope' in text and 'files' in text and 'completed_at' in text
    assert 'bio_comparison_qpcr_v1' in text
    assert 'UPDATE analysis_runs' not in text and 'DELETE FROM' not in text
