"""Column-scoped historical reads and SQL-level mixed task pagination."""
from app.domain.tasks.legacy import decode_legacy_id, missing_task


def require_legacy_task(db, user_id, task_id):
    kind, job_id = decode_legacy_id(task_id)
    table = 'figure_jobs' if kind == 'plot' else 'explanation_jobs'
    figure_join = '' if kind == 'plot' else 'JOIN figures g ON g.id=j.figure_id AND g.analysis_run_id=r.id'
    row = db.execute('''SELECT j.*,p.id AS project_id,r.file_id,r.setup_revision,r.result_json,
        f.filename,f.sha256 AS file_sha256,s.revision AS current_revision
        FROM ''' + table + ''' j JOIN analysis_runs r ON r.id=j.analysis_run_id
        JOIN files f ON f.id=r.file_id JOIN projects p ON p.id=f.project_id
        JOIN users u ON u.id=p.owner_id LEFT JOIN analysis_setups s ON s.file_id=f.id
        ''' + figure_join + ' WHERE j.id=%s AND p.owner_id=%s AND u.active', (job_id, user_id)).fetchone()
    if row is None:
        raise missing_task()
    return {**dict(row), 'kind': kind}


def _legacy_candidates(table, kind):
    figure_join = '' if kind == 'plot' else 'JOIN figures g ON g.id=j.figure_id AND g.analysis_run_id=r.id'
    task_type = 'boxplot' if kind == 'plot' else 'explanation'
    # PostgreSQL base64 wraps long strings; remove line breaks before URL encoding.
    identity = "'legacy-" + kind + ":' || rtrim(translate(replace(encode(convert_to(j.id,'UTF8'),'base64'), E'\\n', ''), '+/', '-_'), '=')"
    return '''SELECT ''' + identity + ''' AS id,'legacy' AS origin,p.id AS project_id,p.owner_id AS user_id,
        ''' + "'" + task_type + "' AS task_type," + '''CASE j.job_json::jsonb->>'status'
        WHEN 'submitting' THEN 'running' WHEN 'running' THEN 'running' WHEN 'completed' THEN 'succeeded'
        WHEN 'uncertain' THEN 'waiting_confirmation' ELSE 'failed' END AS status,
        j.created_at::timestamptz AS created_at
        FROM ''' + table + ''' j JOIN analysis_runs r ON r.id=j.analysis_run_id
        JOIN files f ON f.id=r.file_id JOIN projects p ON p.id=f.project_id
        JOIN users u ON u.id=p.owner_id ''' + figure_join + ' WHERE u.active'


CANDIDATES = '''WITH candidates AS (
    SELECT t.id,'unified' AS origin,t.project_id,t.user_id,t.task_type,t.status,t.created_at
    FROM tasks t JOIN projects p ON p.id=t.project_id AND p.owner_id=t.user_id
    JOIN users u ON u.id=t.user_id WHERE u.active UNION ALL
    ''' + _legacy_candidates('figure_jobs', 'plot') + ' UNION ALL ' + _legacy_candidates('explanation_jobs', 'explanation') + ') '


def mixed_task_page(db, user_id, project_id, *, page, page_size, status, task_type):
    conditions, values = ['project_id=%s', 'user_id=%s'], [project_id, user_id]
    for field, value in [('status', status), ('task_type', task_type)]:
        if value is not None:
            conditions.append(field + '=%s')
            values.append(value)
    where = ' WHERE ' + ' AND '.join(conditions)
    total = db.execute(CANDIDATES + 'SELECT count(*) AS n FROM candidates' + where, tuple(values)).fetchone()['n']
    rows = db.execute(CANDIDATES + 'SELECT id,origin FROM candidates' + where
                      + ' ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s',
                      (*values, page_size, (page - 1) * page_size)).fetchall()
    return total, rows
