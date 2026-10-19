"""Explicit replay of retained NCBI receipts; no network fallback."""
from app.adapters.ncbi import parse_search, parse_fetch
from .policy import QUERIES, LivePolicyError


class RecordedNcbiClient:
    execution_kind = 'retained_ncbi_replay'

    def __init__(self, ledger):
        self._ledger = ledger

    def search(self, query, limit, sort):
        if limit != 20 or sort != 'relevance' or query not in QUERIES.values():
            raise LivePolicyError('live_replay_missing')
        with self._ledger.locked() as state:
            matches = [s for s in state['searches'] if QUERIES[s['query']] == query]
            if not matches:
                raise LivePolicyError('live_replay_missing')
            return parse_search((self._ledger._artifacts / matches[-1]['artifact']).read_bytes(), 20)

    def fetch(self, pmids):
        with self._ledger.locked() as state:
            matches = [f for f in state['fetches'] if f['ids'] == pmids]
            if not matches:
                raise LivePolicyError('live_replay_missing')
            return parse_fetch((self._ledger._artifacts / matches[-1]['artifact']).read_bytes(), pmids)
