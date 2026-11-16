"""Copy only research outputs required by a failed publication checkpoint."""

import json
from pathlib import Path
import sys


def prepared_research_assets(db, assets, staging, snapshot=None):
    tasks = db.execute("""SELECT t.* FROM tasks t
        WHERE t.status='failed' AND (
            t.task_type IN ('research_figure','research_report','research_fact_draft','delivery_package')
            OR (t.task_type IN ('word_report','collection_word_report')
                AND t.input_snapshot->'reader_export'->>'policy'='statistics_reader_export_v1'))
        AND (SELECT c.next_node FROM task_checkpoints c WHERE c.task_id=t.id
             ORDER BY c.seq DESC LIMIT 1)='publish' ORDER BY t.id""").fetchall()
    if not tasks:
        return []

    from app.adapters.research_objects import ResearchObjects
    from app.adapters.task_execution_store import TaskExecutionStore
    from app.domain.bioinformatics.contracts import canonical
    from app.domain.research_results.execution import ResearchExecution, checkpoint_for, result_identifier

    objects = ResearchObjects(assets)
    archived = ResearchObjects(snapshot) if snapshot is not None else None
    execution = ResearchExecution(TaskExecutionStore(directory=assets), staging)
    entries = []
    for task in tasks:
        checkpoint = checkpoint_for(db, task)['state_json']
        prepared = checkpoint['prepared']
        fields = ('object_key', 'size_bytes', 'sha256')
        members = {member['object_key']: {key: member[key] for key in fields} for member in prepared['members']}
        leaves = {leaf['record']['object_key']: leaf for leaf in checkpoint['prepared_leaves']}
        if (prepared['input_sha256'] != task['input_digest'] or not members
                or len(leaves) != len(checkpoint['prepared_leaves'])
                or members != {key: leaf['record'] for key, leaf in leaves.items()}):
            raise ValueError('Prepared research checkpoint differs from its output members')
        identifier = result_identifier(task)
        manifest_ref = objects.describe(identifier, canonical(prepared['manifest']), json=True)
        if manifest_ref != prepared['manifest_ref']:
            raise ValueError('Prepared research manifest differs from its checkpoint')
        if objects.path(manifest_ref['object_key']).exists():
            objects.verified_path(manifest_ref)
        for key, leaf in leaves.items():
            record = leaf['record']
            if key != f'{objects.prefix}/{identifier}/{record["sha256"]}.bin':
                raise ValueError('Prepared research member belongs to a different result')
            if objects.path(key).exists():
                objects.verified_path(record)
            elif archived is None:
                raise ValueError('Backup is missing a prepared research output')
            else:
                archived.write_path(record, execution.staging_path(task, leaf['path']))
                entries.append(dict(path=key, bytes=record['size_bytes'], sha256=record['sha256']))
    return entries


if __name__ == '__main__':
    from app.workers.config import load_secrets
    from app.db.database import database_connection

    load_secrets()
    snapshot = Path('/backup-assets') if sys.argv[1:] == ['capture'] else None
    with database_connection() as db:
        entries = prepared_research_assets(db, Path('/data'), Path('/research-staging'), snapshot)
    print(json.dumps(entries))
