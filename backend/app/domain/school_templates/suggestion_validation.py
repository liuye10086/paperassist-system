"""Source existence, finite renderer values and conflicts; never semantic approval."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
from app.domain.literature.service import digest
from .suggestion_contracts import SuggestionDraft

VERSION='school-rule-capabilities-v1'
ROLES=('body','heading1','heading2','heading3','figure_caption','table_caption')

def material(analysis,note_ids,*,front_matter=None):
    notes={n['id']:n for n in analysis['notes']}
    if len(note_ids)!=len(set(note_ids)) or not note_ids or not set(note_ids)<=notes.keys():raise ValueError('Select exact frozen notes')
    from .suggestion_eligibility import note_eligibility,IdentitySourceSelected
    if not set(note_ids)<=set(note_eligibility(analysis,front_matter)['eligible_note_ids']):raise IdentitySourceSelected('Selected note contains a known identity source; provide separate formatting requirements')
    # Source locations stay local. The selected prose must not smuggle a local
    # location or recognizable credential into the outbound note text either.
    private=re.compile(r'(?i)(?:[a-z]:[\\/]|\\\\|(?<![A-Za-z0-9])(?:/[A-Za-z0-9_.-]+){2,}|\bbearer\s+\S+|\bapi[_ -]?key\s*[:=]|\bsk-[A-Za-z0-9_-]{6,})')
    if any(private.search(notes[n]['text']) for n in note_ids):raise ValueError('Selected note contains a private location or credential')
    rules={r['id']:r for r in analysis['rules']};caps=[]
    for role in ROLES:
        for field,kind in (('font_size_pt','font_size'),('font_east_asia','font'),('font_latin','font'),('line_spacing','spacing'),('line_rule','line_rule')):
            identity=role+'.'+field
            caps.append(dict(id=identity,kind=kind,current_value=deepcopy(rules.get(identity,{}).get('value'))))
    for section in analysis['sections']:
        for side in ('top','bottom','left','right'):
            identity=section['id']+'.margin_'+side+'_cm'
            caps.append(dict(id=identity,kind='margin',current_value=deepcopy(rules.get(identity,{}).get('value'))))
    return dict(capability_catalog_version=VERSION,capabilities=caps,
        notes=[dict(alias='n'+str(i+1),text=notes[n]['text']) for i,n in enumerate(note_ids)])

def normalize(value,kind):
    if not isinstance(value,str):raise ValueError('Explicit supported rule value required')
    if kind=='font':
        if value not in ('宋体','黑体','Times New Roman','Arial'):raise ValueError('Font outside installed school catalog')
        return value
    if kind=='line_rule':
        if value not in ('auto','exact','atLeast'):raise ValueError('Invalid OpenXML spacing rule')
        return value
    try:number=Decimal(value)
    except InvalidOperation:raise ValueError('Invalid numeric rule') from None
    if not number.is_finite():raise ValueError('Nonfinite rule value')
    limits={'font_size':(6,72),'spacing':(100,1440),'margin':(0,10)}
    lo,hi=limits[kind]
    if not lo<=number<=hi or kind=='font_size' and number*2!=int(number*2) or kind=='spacing' and number!=int(number):raise ValueError('Rule value outside renderer limits')
    return str(int(number)) if kind=='spacing' else float(number) if number!=int(number) else int(number)

def validate_output(output,frozen):
    body=SuggestionDraft.model_validate(output).model_dump(mode='json')
    notes={n['alias']:n for n in frozen['notes']};caps={c['id']:c for c in frozen['capabilities']}
    seen=set();covered=set();result=[];duplicates=set()
    for candidate in body['candidates']:
        c=deepcopy(candidate);note=notes.get(c['note_alias'])
        if c['id'] in seen or not note or c['end']>len(note['text']) or c['start']>=c['end'] or note['text'][c['start']:c['end']]!=c['quote'] or not c['reason'].strip():raise ValueError('Candidate is not bound to exact frozen source text')
        # Distinct exact source spans or advice statuses remain separate candidates.
        seen.add(c['id']);covered.add(c['note_alias']);key=(c['note_alias'],c['start'],c['end'],c['status'],c['target_id'],c['value'])
        if key in duplicates:raise ValueError('Duplicate candidate')
        duplicates.add(key)
        value=None;current=None
        if c['status']=='proposed':
            capability=caps.get(c['target_id'])
            if not capability:raise ValueError('Proposed target outside frozen renderer catalog')
            value=normalize(c['value'],capability['kind']);current=capability['current_value']
            if current is not None and str(current)!=str(value):c['status']='conflict'
        elif c['target_id'] is not None or c['value'] is not None:raise ValueError('Unknown rules cannot carry executable targets')
        c.update(normalized_value=value,current_value=current,source_verified=True,human_confirmed=False)
        result.append(c)
    if covered!=notes.keys():raise ValueError('Every selected note requires explicit advice or unknown status')
    # Multiple distinct proposed values for a single renderer target are conflicts.
    for c in result:
        if c['target_id'] and len({str(x['normalized_value']) for x in result if x['target_id']==c['target_id']})>1:c['status']='conflict'
    return dict(capability_catalog_version=VERSION,candidates=result)
