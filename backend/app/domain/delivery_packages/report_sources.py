"""Compare independently verified reader reports by their fixed analysis."""

from app.adapters.research_results_store import ResearchResultsStore
from app.domain.bioinformatics.contracts import digest


def _without(value, *fields):
    return {key: item for key, item in value.items() if key not in fields}


def _analysis_projection(content):
    proof = _without(content, 'title', 'language')
    proof['figures'] = [
        {**figure, 'config': _without(figure['config'], 'title')}
        for figure in content['figures']
    ]
    if content['selection']['kind'] == 'bulk' and len(content['supporting_sources']) == 1:
        # In v1 these limitations are the built-in, localized report text.
        # The fixed preparation receipt guarantees their origin. Compare
        # the archived proof, independently of the current localized text.
        selection = content['selection']
        fixed = content['supporting_sources'][0]
        facts = fixed['facts']
        scientific = content['scientific']
        localized = ('language', 'facts_digest', 'limitations')
        if (fixed['kind'] == 'bulk' and fixed['delivery'] == selection['delivery']
                and facts['language'] == selection['delivery']['language'] == ('en' if content['language'] == 'en' else 'zh')
                and facts['facts_digest'] == selection['delivery']['facts_digest'] == digest(_without(facts, 'facts_digest'))
                and scientific['limitations'] == facts['limitations']
                and all(scientific['summary'][field] == facts[field] for field in localized)):
            delivery = _without(selection['delivery'], 'language', 'facts_digest')
            proof['selection'] = {**selection, 'delivery': delivery}
            proof['supporting_sources'] = [{**fixed, 'delivery': delivery, 'facts': _without(facts, *localized)}]
            proof['scientific'] = {**_without(scientific, 'limitations'),
                                   'summary': _without(scientific['summary'], *localized)}
    return proof


def reader_report_analysis_digest(db, project, owner, finding_id):
    # Only a finding produced by reader report preparation qualifies. A hand
    # edited finding may select different facts or add different claims.
    context = db.execute('''SELECT c.content_json,c.content_sha256 FROM research_source_bindings b
        JOIN bio_report_context_versions c ON c.id=b.source_id AND c.content_sha256=b.source_sha256
            AND c.project_id=b.project_id AND c.user_id=b.user_id
        WHERE b.project_id=%s AND b.user_id=%s AND b.finding_version_id=%s AND b.source_kind='bio_report_context'
        AND EXISTS (SELECT 1 FROM bio_report_context_requests r WHERE r.context_id=c.id
            AND r.project_id=b.project_id AND r.user_id=b.user_id AND r.finding_version_id=b.finding_version_id)
        AND NOT EXISTS (SELECT 1 FROM research_source_bindings other WHERE other.finding_version_id=b.finding_version_id
            AND other.project_id=b.project_id AND other.user_id=b.user_id AND other.id<>b.id)''',
        (project, owner, finding_id)).fetchone()
    if context is None:
        return None
    content = ResearchResultsStore.verify_content(context)
    if content.get('schema_version') != 1:
        return None
    return digest(_analysis_projection(content))
