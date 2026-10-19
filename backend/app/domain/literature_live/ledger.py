"""Append-only durable reservations, receipts and closure under a process lock."""
from contextlib import contextmanager
from hashlib import sha256
import math
import os
from pathlib import Path
import re
import threading
import time

from app.adapters.ncbi import parse_search, parse_fetch
from app.adapters.doi import valid_doi
from .policy import LivePolicyError, POLICY, QUERIES, strict_json

_THREAD_LOCKS = {}
_LOCKS_LOCK = threading.Lock()


def _sync_directory(path):
    # Windows FlushFileBuffers is provided by file fsync; directory handles are not supported by os.open.
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class LiveLedger:
    policy = POLICY

    def __init__(self, path, *, batch_id):
        if not isinstance(batch_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', batch_id):
            raise LivePolicyError('live_batch_invalid')
        self.path = Path(path).resolve()
        self.batch_id = batch_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._artifacts = self.path.with_name(self.path.name + '.responses')
        self._lock_stream = None
        with self.locked(initialize=True):
            pass

    @contextmanager
    def locked(self, *, initialize=False):
        """Serialize the whole dispatch/receipt, including independent processes."""
        with _LOCKS_LOCK:
            mutex = _THREAD_LOCKS.setdefault(str(self.path).casefold(), threading.Lock())
        with mutex:
            with self.path.with_name(self.path.name + '.lock').open('a+b') as lock:
                lock.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    while True:
                        try:
                            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            time.sleep(0.02)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    # Locking a region beyond EOF is supported on both platforms. Initialize
                    # only after acquiring it, so simultaneous first opens cannot append two markers.
                    lock.seek(0, 2)
                    if lock.tell() == 0:
                        lock.write(b'\0')
                        lock.flush()
                        os.fsync(lock.fileno())
                    lock.seek(0)
                    checkpoint = lock.read()
                    if initialize and not self.path.exists():
                        if checkpoint != b'\0' or self._artifacts.exists():
                            raise LivePolicyError('live_ledger_invalid')
                        with self.path.open('xb') as stream:
                            self._write(stream, {'event': 'opened', 'batch_id': self.batch_id, 'policy': self.policy})
                        _sync_directory(self.path.parent)
                        self._checkpoint(lock)
                        _sync_directory(self.path.parent)
                    state = self._load(lock)
                    self._lock_stream = lock
                    yield state
                finally:
                    self._lock_stream = None
                    lock.seek(0)
                    if os.name == 'nt':
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _write(stream, event):
        import json
        stream.write((json.dumps(event, ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())

    def append(self, event):
        # Internal API: caller must hold locked(). Never rewrite existing bytes.
        try:
            if self._lock_stream is None:
                raise ValueError()
            self._verify_checkpoint(self._lock_stream, self.path.read_bytes())
            with self.path.open('ab') as stream:
                self._write(stream, event)
            # Commit the durable length/hash before returning to dispatch. A crash
            # between journal and checkpoint writes leaves a mismatch, never a reset.
            self._checkpoint(self._lock_stream)
        except Exception:
            raise LivePolicyError('live_ledger_invalid') from None

    def _checkpoint(self, lock):
        raw = self.path.read_bytes()
        self._write(lock, {'length': len(raw), 'sha256': sha256(raw).hexdigest()})

    @staticmethod
    def _verify_checkpoint(lock, raw):
        lock.seek(0)
        checkpoint = lock.read(65537)
        if (len(checkpoint) > 65536 or not checkpoint.startswith(b'\0')
                or not checkpoint.endswith(b'\n')):
            raise ValueError()
        previous = 0
        for line in checkpoint[1:].splitlines():
            record = strict_json(line)
            if (not isinstance(record, dict) or set(record) != {'length', 'sha256'}
                    or type(record['length']) is not int
                    or not previous < record['length'] <= len(raw)
                    or raw[record['length'] - 1:record['length']] != b'\n'
                    or record['sha256'] != sha256(raw[:record['length']]).hexdigest()):
                raise ValueError()
            previous = record['length']
        if previous != len(raw) or previous == 0:
            raise ValueError()

    def _load(self, lock):
        try:
            raw = self.path.read_bytes()
            self._verify_checkpoint(lock, raw)
            if not raw or not raw.endswith(b'\n') or len(raw) > 4 * 1024 * 1024:
                raise ValueError()
            events = [strict_json(line) for line in raw.splitlines()]
            first = events[0]
            if (not isinstance(first, dict) or set(first) != {'event', 'batch_id', 'policy'}
                    or first['event'] != 'opened' or first['policy'] != self.policy):
                raise ValueError()
            if first['batch_id'] != self.batch_id:
                raise LivePolicyError('live_batch_mismatch')
            state = dict(ncbi_attempts=0, doi_attempts=0, distinct_dois=[], searches=[], fetches=[],
                         closed=False, reservations={}, finished=set(), last_ncbi=None, ncbi_pending=False)
            for event in events[1:]:
                if not isinstance(event, dict) or state['closed']:
                    raise ValueError()
                kind = event.get('event')
                if kind == 'reserved':
                    if set(event) != {'event', 'attempt', 'kind', 'action', 'at'}:
                        raise ValueError()
                    attempt = event['attempt']
                    if type(attempt) is not int or attempt != len(state['reservations']) + 1:
                        raise ValueError()
                    self._validate_action(state, event['kind'], event['action'])
                    self._time(event['at'])
                    source = event['kind']
                    count = source + '_attempts'
                    state[count] += 1
                    if state[count] > 10:
                        raise ValueError()
                    if source == 'doi':
                        doi = event['action']['doi']
                        if doi not in state['distinct_dois']:
                            state['distinct_dois'].append(doi)
                        if len(state['distinct_dois']) > 5:
                            raise ValueError()
                    else:
                        state['last_ncbi'] = event['at']
                        state['ncbi_pending'] = True
                    state['reservations'][attempt] = event
                elif kind in ('received', 'failed'):
                    expected = {'event', 'attempt', 'at', 'artifact', 'sha256'} if kind == 'received' else {'event', 'attempt', 'at', 'code'}
                    if set(event) != expected or type(event['attempt']) is not int:
                        raise ValueError()
                    reservation = state['reservations'][event['attempt']]
                    if event['attempt'] in state['finished']:
                        raise ValueError()
                    self._time(event['at'])
                    if kind == 'received':
                        if reservation['kind'] != 'ncbi':
                            raise ValueError()
                        self._receive(state, reservation, event)
                    elif event['code'] not in ('ncbi_unavailable', 'ncbi_request_rejected', 'ncbi_response_invalid', 'doi_finished', 'doi_unavailable'):
                        raise ValueError()
                    if reservation['kind'] == 'ncbi':
                        state['last_ncbi'] = event['at']
                        state['ncbi_pending'] = False
                    state['finished'].add(event['attempt'])
                elif kind == 'completed' and set(event) == {'event', 'at'}:
                    self._time(event['at'])
                    state['closed'] = True
                else:
                    raise ValueError()
            return state
        except LivePolicyError:
            raise
        except Exception:
            raise LivePolicyError('live_ledger_invalid') from None

    @staticmethod
    def _time(value):
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise ValueError()

    def _validate_action(self, state, kind, action):
        if not isinstance(action, dict):
            raise ValueError()
        if kind == 'ncbi':
            if set(action) == {'query'} and action['query'] in QUERIES:
                if not any(s['query'] == action['query'] for s in state['searches']):
                    return
            if set(action) == {'search', 'ids'}:
                matches = [s for s in state['searches'] if s['attempt'] == action['search'] and s['ids'] == action['ids'] and s['ids']]
                if matches:
                    return
        elif kind == 'doi' and set(action) == {'doi'} and action['doi'] in self._dois(state):
            return
        raise ValueError()

    def _receive(self, state, reservation, event):
        name = f"{reservation['attempt']:02d}.bin"
        if event['artifact'] != name or not isinstance(event['sha256'], str):
            raise ValueError()
        data = (self._artifacts / name).read_bytes()
        if sha256(data).hexdigest() != event['sha256']:
            raise ValueError()
        action = reservation['action']
        common = dict(attempt=reservation['attempt'], artifact=name)
        if 'query' in action:
            result = parse_search(data, 20)
            state['searches'].append(dict(**common, query=action['query'], ids=result.pmids))
        else:
            result = parse_fetch(data, action['ids'])
            state['fetches'].append(dict(**common, ids=action['ids'], records=result.records))

    @staticmethod
    def _dois(state):
        return list(dict.fromkeys(r['doi'] for f in state['fetches'] for r in f['records'] if valid_doi(r['doi'])))

    def reserve(self, state, kind, action):
        if state['closed']:
            raise LivePolicyError('live_closed')
        try:
            self._validate_action(state, kind, action)
        except Exception:
            raise LivePolicyError('live_request_denied') from None
        if state[kind + '_attempts'] >= 10:
            raise LivePolicyError('live_budget_exhausted')
        if kind == 'doi' and action['doi'] not in state['distinct_dois'] and len(state['distinct_dois']) >= 5:
            raise LivePolicyError('live_doi_limit')
        if kind == 'ncbi' and state['last_ncbi'] is not None:
            # A crash with no finish event requires a fresh full interval after lock acquisition.
            wait = 0.5 if state['ncbi_pending'] else max(0, state['last_ncbi'] + 0.5 - time.time())
            if wait:
                time.sleep(wait)
        attempt = len(state['reservations']) + 1
        self.append(dict(event='reserved', attempt=attempt, kind=kind, action=action, at=time.time()))
        return attempt

    def retain(self, attempt, data):
        self._artifacts.mkdir(exist_ok=True)
        name = f'{attempt:02d}.bin'
        with (self._artifacts / name).open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(self._artifacts)
        _sync_directory(self._artifacts.parent)
        self.append(dict(event='received', attempt=attempt, at=time.time(), artifact=name, sha256=sha256(data).hexdigest()))

    def finish(self, attempt, code):
        self.append(dict(event='failed', attempt=attempt, at=time.time(), code=code))

    def summary(self):
        with self.locked() as state:
            return dict(batch_id=self.batch_id, policy=POLICY, closed=state['closed'],
                        ncbi_attempts=state['ncbi_attempts'], doi_attempts=state['doi_attempts'],
                        distinct_dois=len(state['distinct_dois']), searches=len(state['searches']), fetches=len(state['fetches']))

    def allowed_dois(self):
        with self.locked() as state:
            return self._dois(state)

    def complete(self):
        with self.locked() as state:
            if not state['closed']:
                self.append(dict(event='completed', at=time.time()))

    def recorded_ncbi_client(self):
        """Offline parser-backed client; immutable retained bytes, zero transport."""
        from .replay import RecordedNcbiClient
        return RecordedNcbiClient(self)
