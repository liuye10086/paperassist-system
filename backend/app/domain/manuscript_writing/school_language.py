"""Exact school rendering and per-item languages, with immutable manual options."""
from copy import deepcopy
from hashlib import sha256
from app.domain.literature.service import digest
from app.domain.manuscripts.school_export import compile_school_export
from app.domain.manuscripts.contracts import SchoolExportOptions
from app.adapters.school_docx import build_school_docx

def normalized_options(options):
    return SchoolExportOptions.model_validate(options).model_dump(mode='json')

def plan_digest(plan):
    # Language IDs and their proof are not rendered. All actual rendering rules,
    # options, chapter mappings and source identities remain in this digest.
    return digest({k:v for k,v in plan.items() if k!='snapshot_sha256'})

def validate_options_binding(candidate,options,plan=None):
    options=normalized_options(options);p=candidate['writing_provenance']
    if p.get('school_export_options_sha256')!=digest(options) or p.get('school_export_options')!=options:raise ValueError('School export options differ from the reviewed artifact')
    if plan is not None and p.get('school_render_plan_sha256')!=plan_digest(plan):raise ValueError('School render plan differs from reviewed material')

def inventory(candidate,images,image_items,analysis,options,*,cache=None,frozen=None):
    from .language import RENDERER_VERSION
    options=normalized_options(options)
    p=candidate['writing_provenance']
    if frozen is None or frozen.get('mapper_version')=='school-final-map-v2':p['school_pagination_version']=2
    elif frozen.get('mapper_version')!='school-final-map-v1' or p.get('school_pagination_version') is not None:raise ValueError('Frozen school pagination version differs')
    p['school_export_options']=deepcopy(options);p['school_export_options_sha256']=digest(options)
    plan=compile_school_export(candidate,analysis,options)
    p['school_render_plan_sha256']=plan_digest(plan)
    # The plan's snapshot SHA must include the sealed options and render proof.
    plan=compile_school_export(candidate,analysis,options)
    if cache is not None:
        from .school_render_cache import materialize
        raw,receipt,proof=materialize(cache['root'],cache['owner'],cache['project'],candidate,images,plan,db=cache.get('db'),frozen=frozen)
        mapped=receipt['source_map'];p['school_final_render']=proof
    else:
        from app.adapters.school_docx import complete_school_fields,final_school_source_map
        mapped=[];pending=build_school_docx(candidate,images,plan,source_map=mapped)
        raw,receipt=complete_school_fields(pending,plan)
        if receipt.get('status')!=('updated' if plan['toc']['enabled'] else 'not_requested'):raise ValueError('School final fields were not completed')
        mapped=final_school_source_map(pending,raw,mapped,candidate['output_language'])
    items=[dict(row,kind='export_text',content_sha256=digest(row['text']),narrative_ranges=[] if row.get('protected_identity') or row.get('scope') in ('label','reference_metadata') else [[0,len(row['text'])]]) for row in mapped]
    for image in image_items:
        row=deepcopy(image);identity=figure_identity(candidate,row)
        chapters=[s for s in candidate['sections'] if any(g['id'] in s['result_group_ids'] and any(f['id']==identity for f in g['figures']) for g in candidate['results_groups'])]
        if len(chapters)!=1:raise ValueError('School image requires one exact chapter language')
        row.update(figure_id=identity,chapter_id=chapters[0]['id'],target_language=chapters[0]['output_language']);items.append(row)
    p['school_docx_sha256']=sha256(raw).hexdigest();p['school_language_renderer']=(p['school_final_render']['docx_renderer_version'] if cache is not None else RENDERER_VERSION)+':'+(p['school_final_render']['mapper_version'] if cache is not None else 'school-final-map-v2')
    return items,plan

def figure_identity(candidate,item):
    known={f['id'] for group in candidate['results_groups'] for f in group['figures']}
    location=item['location'];explicit=item.get('figure_id')
    if explicit is not None:
        if explicit not in known or not (location=='image:'+explicit or location.startswith('image:'+explicit+':')):raise ValueError('Image item is not bound to its exact figure identity')
        return explicit
    matches=[identity for identity in known if location=='image:'+identity or location.startswith('image:'+identity+':')]
    if not matches:raise ValueError('Image item has no known complete figure identity')
    longest=max(len(identity) for identity in matches);matches=[identity for identity in matches if len(identity)==longest]
    if len(matches)!=1:raise ValueError('Image identity is ambiguous')
    return matches[0]

def validate_decisions(items,body):
    from .language import validate_decisions as common
    if digest(items)!=body['inventory_sha256']:raise ValueError('School language inventory changed')
    decisions=body['decisions']
    if len(decisions)!=len(items) or len({d['location'] for d in decisions})!=len(items):raise ValueError('Every school export item requires an explicit decision')
    lookup={i['location']:i for i in items}
    for decision in decisions:
        item=lookup.get(decision['location'])
        if item is None or decision['content_sha256']!=item['content_sha256'] or not decision['reason'].strip():raise ValueError('School language decision differs from the exact export item')
        if item.get('protected_identity'):
            if decision['decision']!='provided_literal' or decision['exceptions']:raise ValueError('Identity/signature/date values require explicit literal preservation')
        else:
            common([item],dict(inventory_sha256=digest([item]),decisions=[decision]),item['target_language'])
