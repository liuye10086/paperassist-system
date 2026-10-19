"""Fixed approval for one public-topic batch; identity never enters receipts."""
import json
from pathlib import Path

from app.adapters.ncbi import NcbiSettings, _identity
from app.domain.literature.contracts import SearchRequest, effective_query


class LivePolicyError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


TOPIC = 'aspirin[Title/Abstract] AND primary prevention[Title/Abstract]'


def _query(publication_type):
    return effective_query(SearchRequest(query=TOPIC, year_from=2010, year_to=2025,
        publication_types=[publication_type], research_topic='public', limit=20, sort='relevance'))


INITIAL_QUERY = _query('Randomized Controlled Trial')
SUPPLEMENT_BODY_QUERY = _query('Meta-Analysis')
# The supplement API supplies only query; its execution wraps effective_query once.
SUPPLEMENT_QUERY = '(' + SUPPLEMENT_BODY_QUERY + ')'
QUERIES = {'initial': INITIAL_QUERY, 'supplement': SUPPLEMENT_QUERY}
POLICY = 'stage05-batch05-public-aspirin-v1:ncbi10:doi10:distinct5:interval0.5'


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))


def load_private_identity(path, *, enabled=False):
    """Read exact existing JSON fields; approved runner may enable only this object."""
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(16385)
        if len(raw) > 16384 or type(enabled) is not bool:
            raise ValueError()
        values = strict_json(raw)
        if (not isinstance(values, dict) or set(values) != {'enabled', 'tool', 'email', 'api_key'}
                or type(values['enabled']) is not bool
                or any(not isinstance(values[k], str) for k in ('tool', 'email', 'api_key'))
                or values['tool'] != 'PaperAssist'):
            raise ValueError()
        settings = NcbiSettings(enabled, values['tool'], values['email'], values['api_key'])
        # Validate supplied identity even if the requested instance is disabled.
        _identity(NcbiSettings(True, settings.tool, settings.email, settings.api_key))
        return settings
    except Exception:
        raise LivePolicyError('live_identity_invalid') from None
