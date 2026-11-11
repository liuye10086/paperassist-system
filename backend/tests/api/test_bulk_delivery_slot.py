"""Real PostgreSQL interprocess serialization; disposable schema from conftest."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from tests.api.test_projects import client, create_project


def test_heavy_slot_serializes_processes_and_releases_after_exception(client, tmp_path):
    from app.db.database import database_connection
    project = create_project(client)['id']
    with database_connection() as db:
        owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project,)).fetchone()['owner_id']
    script = tmp_path / 'slot.py'
    script.write_text('''import json, sys, time
from pathlib import Path
from app.adapters.storage import ProjectStore
from app.core.config import get_data_dir
from app.domain.bio_insights.bulk_delivery_cache import heavy_slot
assets = ProjectStore(get_data_dir(), owner_id=sys.argv[1])
Path(sys.argv[3]+'.ready').write_text('ready')
try:
    with heavy_slot(assets, sys.argv[2]):
        with heavy_slot(assets, sys.argv[2]):
            Path(sys.argv[3]+'.entered').write_text(str(time.time()))
            time.sleep(float(sys.argv[4]))
            if sys.argv[5] == 'fail': raise RuntimeError('release slot')
finally:
    Path(sys.argv[3]+'.done').write_text(str(time.time()))
''', encoding='utf-8')
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2])}
    def start(label, delay, fail='ok'):
        return subprocess.Popen([sys.executable, str(script), owner, project, str(tmp_path / label), str(delay), fail],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    def wait_file(name):
        until = time.monotonic() + 20
        while not (tmp_path / name).exists() and time.monotonic() < until:
            time.sleep(.02)
        assert (tmp_path / name).exists()
    first = start('first', 3, 'fail')
    second = None
    try:
        wait_file('first.entered')
        second = start('second', 0)
        wait_file('second.ready')
        # The contender has connected in a separate process, but cannot enter yet.
        if not (tmp_path / 'first.done').exists():
            assert not (tmp_path / 'second.entered').exists()
        _, error = first.communicate(timeout=20)
        assert first.returncode != 0 and b'release slot' in error
        _, error = second.communicate(timeout=20)
        assert second.returncode == 0, error.decode(errors='replace')
        assert float((tmp_path / 'second.entered').read_text()) >= float((tmp_path / 'first.entered').read_text()) + 2.9
    finally:
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
