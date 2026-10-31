import pytest
from sqlalchemy import CheckConstraint
from app.db.schema import metadata


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


TABLES = ('research_finding_sets','research_finding_versions','research_figure_versions',
          'research_figure_members','research_report_versions','research_report_members',
          'research_source_bindings','manuscript_research_sources','research_manuscript_candidates')


def test_all_nine_tables_have_owner_project_scope_and_bounded_json():
    assert set(TABLES) <= set(metadata.tables), 'CR-B03 schema missing'
    for name in TABLES:
        t = metadata.tables[name]
        assert {'id','project_id','user_id','created_at','schema_version'} <= set(t.c.keys())
        assert any({'project_id','user_id'} == set(f.column_keys) for f in t.foreign_key_constraints)


def test_typed_bindings_and_manuscript_sources_use_project_scoped_foreign_keys():
    assert set(TABLES) <= set(metadata.tables), 'CR-B03 schema missing'
    for name in ('research_source_bindings','manuscript_research_sources'):
        table=metadata.tables[name]
        for col in ('processed_version_id','analysis_artifact_id','bio_figure_version_id','file_id',
                    'external_evidence_version_id','source_finding_version_id','research_figure_version_id','source_report_version_id'):
            assert any({col,'project_id'} <= set(f.column_keys) for f in table.foreign_key_constraints)
        checks=' '.join(str(x.sqltext) for x in table.constraints if isinstance(x,CheckConstraint))
        assert 'num_nonnulls' in checks and 'source_id=' in checks


def test_research_tasks_have_exact_typed_results_and_report_pdf_is_typed():
    for col in ('result_research_figure_version_id','result_research_report_version_id','result_research_candidate_id'):
        assert col in metadata.tables['tasks'].c, 'CR-B03 task result missing'
        assert any({col,'project_id'} <= set(f.column_keys) for f in metadata.tables['tasks'].foreign_key_constraints)
    assert 'research_report_member_id' in metadata.tables['pdf_exports'].c
    assert {'delivery_id','document_kind'} <= set(metadata.tables['manuscripts'].c.keys())
