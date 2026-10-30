"""Versioned numeric catalogs; provided prose never becomes computed evidence."""
from copy import deepcopy
from app.domain.manuscripts.illustrations import BODY_REFERENCE
from .numeric_review import numbers, value as numeric_value

INSTRUCTION = '''Use numeric contract 2. The source facts are the complete finite list of computed study values. Numeric context c-aliases describe provided methods or frozen illustration text, never computed study findings. Evidence e-aliases only offer quoted literature values pending new human claim review. For every numeric expression other than a valid figure/table identity, use a study_numeric_bindings row with an exact catalog source_alias, fact_path and value; this legacy field now carries typed catalog suggestions. Do not invent paths, change signs or precision, bind a figure/table number as a study fact, or use an evidence alias as a blanket numeric exemption. source_aliases lists only selected s-aliases; c-aliases belong only in binding rows. Keep provided-method statements separate from new study claims where possible. All suggestions remain pending scientific and language review.'''

# INSTRUCTION is frozen for contracts without an explicit instruction revision.
EXACT_INSTRUCTION = INSTRUCTION + '''
Before final serialization, check each final paragraph independently: after excluding valid figure/table identities, the set of numeric strings extracted from its text must exactly equal the set of normalized binding values. No missing or extraneous values are allowed. Repeated occurrences need coverage of that value; several exact catalog tuples may share a value, but every supplied value must actually occur in this paragraph. A qualitative comparison alone does not authorize binding unprinted numerical premises; source_aliases may still trace its selected study sources. Do not insert extra numbers merely to justify unused bindings.
Formula constants are numeric expressions too: n-1, n−1 and (n−1)p contain -1, not 1. If the supplied provided_context catalog contains the matching signed value for this method, copy that exact c-alias/fact_path/value tuple into study_numeric_bindings. It remains provided-method context, never a computed study result. If no suitable tuple exists, keep the unsupported detail explicit rather than inventing a path or result.
For example, given a provided_context tuple {"source_alias":"c1","fact_path":"/numbers/0","value":"-1"} for the stated divisor, text "The divisor is n−1; interpolation uses (n−1)p." has exactly the numeric set {"-1"} and uses that tuple; an empty list or a +1 binding fails. This is a conditional example, not an additional catalog entry. Text "Group B has a higher mean than Group A." has no numeric expressions and needs an empty binding list even if its selected study sources contain means 2.5 and 3.5. A valid Figure 1 identity alone also needs no numeric binding.
The server's check has these executable semantics (numbers normalizes supported signs and whitespace without rounding or equating 3 with 3.0; BODY_REFERENCE removes only valid figure/table identity text):
```python
actual = set(numbers(BODY_REFERENCE.sub('', paragraph['text'])))
supplied = {numeric_value(row['value']) for row in paragraph['study_numeric_bindings']}
assert actual == supplied
```
This equality does not replace exact tuple membership or claim review. Keep literature claims within the supplied quote and reading_scope: one study's abstract or plan does not establish what studies usually do. Attribute the specific quoted study; an e-alias never makes a new generalization, translation or claim verified. All such claims still require new human review.'''


def is_numeric_v2(bundle):
    contract=bundle.get('execution_contract', {})
    return contract.get('schema_version',1)==2 or contract.get('schema_version')==3 and contract.get('numeric_contract_version')==2


def context_facts(bundle):
    return {alias: {(f['fact_path'], f['value']) for f in row['values']}
            for alias, row in bundle.get('local_manifest', {}).get('numeric_context', {}).items()}


def text_facts(text, prefix):
    return [dict(fact_path=f'{prefix}/{i}', value=v)
            for i, v in enumerate(numbers(BODY_REFERENCE.sub('', text)))]


def add_catalogs(base, request, payload, local, safe_text):
    """Only selected, explicit text projections; never recursively mine prose."""
    from .context import normalize_sections
    rows = {}; seen = set()
    def add(text, location, origin):
        text = safe_text(text)
        key = (origin, text)
        if key in seen: return
        seen.add(key)
        values = text_facts(text, '/numbers')
        if values:
            rows['c' + str(len(rows) + 1)] = dict(kind='provided_context', location=location,
                origin=origin, text=text, values=values)
    for section in normalize_sections(base):
        if section['id'] != 'materials_and_methods': continue
        for i, paragraph in enumerate(section['paragraphs']):
            ids = paragraph.get('source_ids', [])
            if paragraph.get('origin') == 'user_provided' and not paragraph.get('citations') and set(ids) <= set(request['selected_source_ids']):
                add(paragraph['text'], f'materials_and_methods[{i}]', 'user_provided')
    # A complete old draft can keep its original explicit methods alongside
    # generated sections. These originals retain user origin and selection.
    for i, paragraph in enumerate(base.get('methods', [])):
        if paragraph.get('origin') == 'user_provided' and not paragraph.get('citations') and set(paragraph.get('source_ids', [])) <= set(request['selected_source_ids']):
            add(paragraph['text'], f'provided_methods[{i}]', 'user_provided')
    for i, item in enumerate(payload['illustrations']):
        if item['kind'] != 'figure': continue
        for field in ('title', 'caption'):
            if field in item: add(item[field], f'illustrations[{i}].{field}', 'frozen_illustration')
        for j, panel in enumerate(item.get('panels', [])):
            add(panel.get('description', ''), f'illustrations[{i}].panels[{j}]', 'frozen_illustration')
    local['numeric_context'] = deepcopy(rows)
    payload['numeric_contract_version'] = 2
    payload['numeric_context'] = [dict(alias=alias, **row) for alias, row in rows.items()]
    for evidence in payload['evidence']:
        evidence['numeric_facts'] = text_facts(evidence['quote'], '/quote/numbers')


def _catalogs(payload):
    study = {s['alias']: {(f['fact_path'], f['value']) for f in s['facts']} for s in payload['sources']}
    context = {s['alias']: {(f['fact_path'], f['value']) for f in s['values']} for s in payload['numeric_context']}
    literature = {e['alias']: {(f['fact_path'], f['value']) for f in e['numeric_facts']} for e in payload['evidence']}
    return study, context, literature


def output_schema(payload):
    from .live_contracts import LiveOutput
    schema = deepcopy(LiveOutput.model_json_schema())
    catalogs = _catalogs(payload)
    choices = []
    for catalog in catalogs:
        for alias, pairs in catalog.items():
            for path, raw in sorted(pairs):
                # Check the numeric representation without rounding it.
                numeric_value(raw)
                choices.append(dict(type='object', additionalProperties=False,
                    properties={key: dict(type='string', enum=[val]) for key, val in
                        (('source_alias', alias), ('fact_path', path), ('value', raw))},
                    required=['source_alias', 'fact_path', 'value']))
    paragraph = schema['$defs']['LiveParagraph']['properties']
    if choices: schema['$defs']['StudyNumericBinding'] = dict(anyOf=choices)
    else: paragraph['study_numeric_bindings']['maxItems'] = 0
    for field, aliases in (('source_aliases', list(catalogs[0])), ('evidence_aliases', list(catalogs[2]))):
        if aliases: paragraph[field]['items'] = dict(type='string', enum=aliases)
        else: paragraph[field]['maxItems'] = 0
    return schema


def validate_bindings(paragraph, payload):
    study, context, literature = _catalogs(payload)
    result = dict(study=[], context=[], literature=[])
    for binding in paragraph['study_numeric_bindings']:
        alias = binding['source_alias']; pair = (binding['fact_path'], binding['value'])
        if alias in study:
            if alias not in paragraph['source_aliases'] or pair not in study[alias]: raise ValueError('Unknown exact study fact')
            kind = 'study'
        elif alias in context:
            if pair not in context[alias]: raise ValueError('Unknown exact provided-context value')
            kind = 'context'
        elif alias in literature:
            if alias not in paragraph['evidence_aliases'] or pair not in literature[alias]: raise ValueError('Unknown exact literature value')
            kind = 'literature'
        else: raise ValueError('Unknown numeric catalog alias')
        result[kind].append(deepcopy(binding))
    actual = set(numbers(BODY_REFERENCE.sub('', paragraph['text'])))
    supplied = {numeric_value(b['value']) for b in paragraph['study_numeric_bindings']}
    if actual != supplied: raise ValueError('Unbound or extraneous numeric expression')
    return result
