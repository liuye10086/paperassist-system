"""Outbound eligibility from known frozen identity sources, never free-text PII guesses."""

class IdentitySourceSelected(ValueError):pass

def _same_location(a,b):
    if not isinstance(a,dict) or not isinstance(b,dict) or a.get('part')!=b.get('part'):return False
    left,right=a.get('path'),b.get('path')
    if not isinstance(left,str) or not isinstance(right,str) or not left or not right:return False
    # A paragraph and one of its runs are the same source. p[1] and p[10] are not.
    return left==right or left.startswith(right.rstrip('/')+'/') or right.startswith(left.rstrip('/')+'/')


def note_eligibility(analysis,front_matter=None):
    if not analysis:return dict(eligible_note_ids=[],blocked_notes=[])
    fields=analysis.get('identity_fields',[])
    labels={f for f in fields if isinstance(f,str)}
    protected=[f['source'] for f in fields if isinstance(f,dict) and isinstance(f.get('source'),dict)]
    sources=analysis.get('front_matter_sources',[])
    protected.extend(s['source'] for s in sources if s.get('suggested_label') in labels and isinstance(s.get('source'),dict))
    if front_matter:
        by_id={s['id']:s['source'] for s in sources}
        by_id.update({'note:'+n['id']:n['source'] for n in analysis.get('notes',[])})
        protected.extend(by_id[f['source_id']] for f in front_matter.get('fields',[])
            if f['kind'] in ('identity','signature','date') and f['source_id'] in by_id)
    eligible=[];blocked=[]
    for note in analysis.get('notes',[]):
        if any(_same_location(note.get('source'),source) for source in protected):
            blocked.append(dict(note_id=note['id'],reason_code='identity_source'))
        else:eligible.append(note['id'])
    return dict(eligible_note_ids=eligible,blocked_notes=blocked)
