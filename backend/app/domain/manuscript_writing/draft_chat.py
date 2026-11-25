"""Keep provider deltas out of completed candidates and the model usage ledger."""
from time import monotonic

from psycopg.types.json import Jsonb
from pydantic_core import from_json


OUTPUT_BYTES = 250_000


class DraftReplyProgress:
    def __init__(self, repository, lease, request, stored, response_id, *, section_ids=None):
        self.repository = repository
        self.lease = lease
        self.request = request
        self.section_ids = section_ids if section_ids is not None else {sid: sid for sid in request['target_sections']}
        self.state = stored if response_id and stored and stored.get('response_id') == response_id else None
        self.raw_bytes = len(self.state['raw'].encode()) if self.state else 0
        self.last_saved = None
        self.dirty = False

    @property
    def cursor(self):
        return self.state['sequence'] if self.state else None

    @property
    def first_preview_at(self):
        return self.state.get('first_preview_at') if self.state else None

    def record(self, call, event):
        response_id = call['provider_response_id']
        sequence = event['sequence_number']
        item = [event['item_id'], event['output_index'], event['content_index']]
        delta = event['delta']
        try:
            size = len(delta.encode())
        except UnicodeEncodeError:
            return
        if not size or '\x00' in delta or self.raw_bytes + size > OUTPUT_BYTES:
            return
        if self.state and (self.state['response_id'] != response_id or self.state['item'] != item or sequence <= self.cursor):
            return
        previous = self.state or {}
        self.state = dict(previous, response_id=response_id, sequence=sequence, item=item,
                          raw=previous.get('raw', '') + delta, preview=previous.get('preview', []))
        self.raw_bytes += size
        self.dirty = True
        if not self.state['preview']:
            preview = _project_reply(self.request, self.state['raw'], self.section_ids)
            if preview:
                self.flush(preview)
        elif self.last_saved is None or monotonic() - self.last_saved >= .6:
            self.flush()

    def flush(self, preview=None):
        if not self.dirty:
            return
        if preview is None:
            preview = _project_reply(self.request, self.state['raw'], self.section_ids)
        if preview:
            self.state['preview'] = preview
        with self.repository.connection(write=True) as db:
            task = self.repository.require_lease(db, self.lease)
            self.repository.require_owner(db, task)
            if preview and not self.first_preview_at:
                self.state['first_preview_at'] = self.repository.now(db).isoformat()
            db.execute('UPDATE manuscript_writing_requests SET draft_chat_json=%s WHERE task_id=%s AND candidate_json IS NULL',
                       (Jsonb(self.state), task['id']))
        self.last_saved = monotonic()
        self.dirty = False


def _project_reply(request, raw, section_ids):
    try:
        value = from_json(raw, allow_partial='trailing-strings')
    except ValueError:
        return []
    if not isinstance(value, dict):
        return []
    if request.get('draft_advice'):
        text = value.get('advice')
        return [dict(section_id=None, text=text[:4000])] if isinstance(text, str) and text.strip() else []
    sections = value.get('sections')
    if not isinstance(sections, list):
        return []
    reply = []
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get('id'), str) or section['id'] not in section_ids:
            continue
        paragraphs = section.get('paragraphs')
        if not isinstance(paragraphs, list):
            continue
        text = '\n\n'.join(p['text'] for p in paragraphs if isinstance(p, dict) and isinstance(p.get('text'), str))
        if text.strip():
            reply.append(dict(section_id=section_ids[section['id']], text=text[:12000]))
    return reply
