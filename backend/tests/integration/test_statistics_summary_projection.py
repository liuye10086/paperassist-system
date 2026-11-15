"""Exercise summary SQL with read-only CTE fixtures: no schema, DDL or writes."""
import json
import os

import psycopg
from psycopg.rows import dict_row
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():
    # This narrow projection check intentionally never runs migration fixtures.
    yield None


def report_metadata(identifier,kind,*,reader):
    value=dict(id=identifier,filename=identifier+'.docx',size_bytes=10,sha256='a'*64,
               created_at='2026-11-15T12:00:00+00:00')
    if reader:
        version=identifier+'-version'
        value.update(reader_export=dict(policy='statistics_reader_export_v1',context_id=identifier+'-context',
            report_version_id=version,task_id=identifier+'-task',task_type=kind,origin='saved_explanation_reuse',
            adapter_version='statistics_saved_explanation_v1'),
            members=[dict(id=identifier+'-'+role,key=role,role=role,format=role,sha256='a'*64,size_bytes=10,
                download_url=f'/api/v1/projects/project/research-reports/{version}/members/{identifier}-{role}/download')
                for role in ('docx','xlsx','zip')],reader_report={'narrative':'Large private narrative is not a summary field'})
    return value


def fixtures():
    data=dict(runs=[dict(id='run',file_id='file',filename='input.csv',setup_revision=1,current_revision=2)],
        figures=[dict(id='figure',analysis_run_id='run',renderer_version='figure-v1',figure_json=json.dumps(dict(
            created_at='2026-11-15T11:00:00+00:00',size_bytes=2,sha256='b'*64)))],
        explanations=[dict(id=f'explanation-{i}',analysis_run_id='run',figure_id='figure') for i in range(3)],reports=[],collection_reports=[],
        report_collection_versions=[dict(id='collection-version',collection_id='collection',revision=1,
            content_json={'title':'Frozen collection title'},source_json={'file_id':'file'})],
        report_collections=[dict(id='collection',project_id='project',created_by='owner')],
        projects=[dict(id='project',owner_id='owner')],files=[dict(id='file',filename='input.csv',project_id='project')],
        report_collection_items=[dict(version_id='collection-version',analysis_run_id='run')])
    expected={}
    # Multiple exports share one analysis or collection version. The projection
    # must retain each report's own fixed members, never the newest export's.
    for kind,table in [('word_report','reports'),('collection_word_report','collection_reports')]:
        for index in range(3):
            identifier=kind+'-'+str(index);metadata=report_metadata(identifier,kind,reader=index>0)
            expected[identifier]=metadata
            row=dict(id=identifier,renderer_version='statistics_reader_report_v1' if index else 'historical-v1')
            if kind=='word_report':
                row.update(analysis_run_id='run',explanation_id=f'explanation-{index}',report_json=json.dumps(metadata))
            else:
                row.update(version_id='collection-version',export_revision=index+1,
                    created_at=f'2026-11-15T12:0{index}:00+00:00',report_json=metadata,sha256=metadata['sha256'])
            data[table].append(row)
    return data,expected


SHAPES={
    'runs':'id text,file_id text,filename text,setup_revision integer,current_revision integer',
    'figures':'id text,analysis_run_id text,renderer_version text,figure_json text',
    'explanations':'id text,analysis_run_id text,figure_id text',
    'reports':'id text,analysis_run_id text,renderer_version text,explanation_id text,report_json text',
    'collection_reports':'id text,version_id text,renderer_version text,created_at timestamptz,report_json jsonb,sha256 text,export_revision integer',
    'report_collection_versions':'id text,collection_id text,revision integer,content_json jsonb,source_json jsonb',
    'report_collections':'id text,project_id text,created_by text',
    'projects':'id text,owner_id text',
    'files':'id text,filename text,project_id text',
    'report_collection_items':'version_id text,analysis_run_id text',
}


@pytest.mark.parametrize('kind',('word_report','collection_word_report'))
def test_summary_projects_only_each_exact_report_files_and_keeps_historical_fallback(kind):
    from app.domain.project_summary import ARTIFACTS,ArtifactSummary
    data,expected=fixtures()
    ctes=['fixture AS (SELECT %s::jsonb AS body)']
    ctes.extend(f"{table} AS (SELECT r.* FROM fixture,jsonb_to_recordset(body->'{table}') AS r({shape}))"
                for table,shape in SHAPES.items())
    # Dedicated test database, a read-only transaction, and only VALUES-like
    # CTEs. No production or retained test-schema tables are read or changed.
    url=os.environ['PAPERASSIST_TEST_DATABASE_URL'].replace('postgresql+psycopg://','postgresql://',1)
    try:
        connection=psycopg.connect(url,row_factory=dict_row)
    except psycopg.Error:
        raise RuntimeError('Read-only projection fixture connection failed') from None
    with connection as db:
        db.execute('SET TRANSACTION READ ONLY')
        assert db.execute('SELECT current_database() AS name').fetchone()['name']=='paperassist_system_test'
        rows=db.execute('WITH '+','.join(ctes)+' '+ARTIFACTS,(json.dumps(data),'project')).fetchall()
    selected=[row for row in rows if row['id'].startswith(kind+'-')]
    assert len(selected)==3
    for row in selected:
        fixed=expected[row['id']]
        assert row['reader_export']==fixed.get('reader_export')
        assert row['members']==fixed.get('members')
        if kind=='word_report':
            url=f"/api/v1/projects/project/files/file/analysis-runs/run/report/{row['id']}/download"
            assert row['analysis_run_id']=='run' and row['collection_id'] is None
        else:
            url=f"/api/v1/projects/project/report-collections/collection/reports/{row['id']}/download"
            assert row['collection_version_id']=='collection-version' and row['analysis_run_id'] is None
        public=ArtifactSummary(**row,download_url=url).model_dump(mode='json')
        assert public['id']==fixed['id'] and public['download_url']==url
        assert public.get('reader_export')==fixed.get('reader_export') and public.get('members')==fixed.get('members')
        if 'reader_export' not in fixed:assert 'reader_export' not in public and 'members' not in public
        assert 'reader_report' not in public and 'narrative' not in json.dumps(public)
    figure=next(row for row in rows if row['id']=='figure')
    assert figure['reader_export'] is None and figure['members'] is None
