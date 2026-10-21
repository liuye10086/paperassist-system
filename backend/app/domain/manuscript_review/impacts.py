"""Conservative affected-location reports; no text mutation or binding substitution."""
def affected_locations(changes,relations):
    result=[]
    for change in changes:
        identity=change['id']
        locations=[p['id'] for p in relations['paragraphs'] if identity in p['source_ids']]
        locations += ['caption:'+f['id'] for f in relations['figures'] if identity in f['source_ids']]
        for association in relations['associations']:
            if identity in association['source_ids']:
                locations += association['paragraph_ids']+association['method_ids']+['caption:'+f for f in association['figure_ids']]
        scope='linked' if locations else 'conservative'
        if not locations:
            locations=[p['id'] for p in relations['paragraphs']]+['caption:'+f['id'] for f in relations['figures']]
        if not locations: locations=['manuscript']
        sections=['section:'+p['section_id'] for p in relations['paragraphs'] if p['id'] in locations]
        result.append(dict(source_id=identity,reasons=change['reasons'],locations=sorted(set(locations+sections)),scope=scope,pending_review=True))
    return result
