"""Read-only project ownership, checkpoint and saved-response consistency checks."""
from app.adapters.ncbi import parse_search, parse_fetch
from app.domain.literature.objects import LiteratureObjects
from app.domain.literature.service import require_snapshot, latest_checkpoint, digest


def audit_literature(db):
    checks = []
    tasks = {r['id']:dict(r) for r in db.execute("SELECT * FROM tasks WHERE task_type='literature_search'")}
    searches = {r['task_id']:r for r in db.execute('SELECT * FROM literature_searches')}
    projects = {r['id']:r['owner_id'] for r in db.execute('SELECT id,owner_id FROM projects')}
    invalid = 0
    for task in tasks.values():
        try:
            require_snapshot(task)
            checkpoint = latest_checkpoint(db,task)
            if projects.get(task['project_id']) != task['user_id']: raise ValueError()
            if (task['status']=='succeeded') != (checkpoint['next_node']=='done'): raise ValueError()
            if (task['status']=='waiting_confirmation') != (checkpoint['next_node']=='await_confirmation'): raise ValueError()
        except Exception:
            invalid += 1
    invalid += len(set(searches)-set(tasks))
    checks.append(dict(table='literature_searches',column='input_and_checkpoint',rows=len(searches),invalid=invalid))
    receipts = {r['id']:r for r in db.execute('SELECT * FROM literature_fetch_receipts')}
    parsed = {}
    objects = LiteratureObjects()
    invalid = 0
    for identity,row in receipts.items():
        try:
            task = tasks[row['task_id']]
            request = row['request_json']
            if (row['project_id']!=task['project_id'] or row['user_id']!=task['user_id']
                    or request.get('operation')!=row['operation'] or digest(request)!=row['request_digest']): raise ValueError()
            if row['operation']=='esearch':
                expected = dict(operation='esearch',query=task['input_snapshot']['effective_query'],
                    limit=task['input_snapshot']['input']['limit'],sort=task['input_snapshot']['input']['sort'])
                if request!=expected: raise ValueError()
            else:
                pmids = searches[row['task_id']]['pmids_json']
                if (set(request)!= {'operation','pmids'} or request['pmids'] not in
                        [pmids[n:n+20] for n in range(0,len(pmids),20)]): raise ValueError()
            if row['cached_from_id']:
                original = receipts[row['cached_from_id']]
                if (original['cached_from_id'] is not None or original['status']!='succeeded'
                    or any(row[k]!=original[k] for k in ('project_id','user_id','operation','request_digest',
                        'source_kind','object_key','sha256','size_bytes','attempted_at'))): raise ValueError()
            if row['status']=='succeeded':
                raw = objects.read(row)
                result = parse_search(raw,request['limit']) if row['operation']=='esearch' else parse_fetch(raw,request['pmids'])
                parsed[identity] = result
                if row['operation']=='esearch':
                    search = searches[row['task_id']]
                    if (result.pmids!=search['pmids_json'] or result.count!=search['matched_count']
                            or result.query_translation!=search['query_translation']): raise ValueError()
        except Exception:
            invalid += 1
    checks.append(dict(table='literature_fetch_receipts',column='request_and_raw_source',rows=len(receipts),invalid=invalid))
    candidates = {r['id']:r for r in db.execute('SELECT * FROM project_references')}
    records = {r['id']:r['pmid'] for r in db.execute('SELECT * FROM literature_records')}
    hits = db.execute('SELECT * FROM literature_search_hits').fetchall()
    invalid = 0
    for hit in hits:
        try:
            candidate = candidates[hit['project_reference_id']]
            source = receipts[hit['receipt_id']]
            actual = {r['pmid']:r for r in parsed[hit['receipt_id']].records}
            pmid = records[hit['reference_id']]
            if (actual.get(pmid)!=hit['record_json'] or source['task_id']!=hit['task_id']
                or any(hit[k]!=candidate[k] for k in ('project_id','user_id','reference_id'))): raise ValueError()
        except Exception:
            invalid += 1
    checks.append(dict(table='literature_search_hits',column='record_and_raw_source',rows=len(hits),invalid=invalid))
    invalid = 0
    for row in candidates.values():
        try:
            decisions = row['decisions_json']
            if projects.get(row['project_id'])!=row['user_id'] or row['revision']!=len(decisions)+1: raise ValueError()
            for number,decision in enumerate(decisions,2):
                if (decision['revision']!=number or decision['decided_by']!=row['user_id']
                        or decision['status'] not in ('candidate','shortlisted','excluded')): raise ValueError()
            if decisions and (decisions[-1]['status']!=row['selection_status'] or decisions[-1]['note']!=row['selection_note']): raise ValueError()
            if not decisions and (row['selection_status']!='candidate' or row['selection_note']): raise ValueError()
        except Exception:
            invalid += 1
    checks.append(dict(table='project_references',column='owner_and_decisions',rows=len(candidates),invalid=invalid))
    return checks
