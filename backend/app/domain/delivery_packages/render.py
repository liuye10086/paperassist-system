"""Read-only bounded ZIP assembly. Never invokes scientific/document generation."""
import hashlib,json
from pathlib import Path
from app.domain.research_results.report_package import make_package
from app.adapters.research_results_store import invalid


def public_snapshot(snapshot):
    from copy import deepcopy
    result=deepcopy(snapshot)
    for m in result['members']:m.pop('download_url',None)
    if result['mode']=='blind':
        for key in ('project_id','delivery_id','source_file_ids','requirement_version_id','parent_snapshot_id','change_note','opinion_round','opinion_round_binding','source_notices'):result.pop(key,None)
        result['quality_items']=['Blind derivations selected; full archive anonymity has not been independently verified.']
        result['changes']={'reason':'Separate frozen blind derivative scope; original materials excluded.'}
        result['members']=[{k:m[k] for k in ('id','name','format','sha256','size_bytes','language','review_mode')} for m in result['members']]
    return result


def build_package(snapshot,raws):
    if len(raws)!=len(snapshot['members']):raise invalid()
    public=public_snapshot(snapshot);files={}
    for member,raw in zip(snapshot['members'],raws):
        if member['name'] in files or len(raw)!=member['size_bytes'] or hashlib.sha256(raw).hexdigest()!=member['sha256']:raise invalid()
        files[member['name']]=raw
    encode=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2).encode()
    files['delivery.json']=encode(public);files['changes.json']=encode(public['changes'])
    files['materials-and-limitations.txt']=('Existing frozen artifacts only. No analysis, model call, plotting or conversion.\nCompleteness: '+snapshot['completeness']+'\nMissing: '+', '.join(snapshot['gaps'])+'\nQuality: '+', '.join(public['quality_items'])+'\nSource declarations: '+json.dumps(public.get('source_notices',[]),ensure_ascii=False,sort_keys=True)+'\nExisting licenses and access restrictions remain in force.\nCustomer acceptance is a separate append-only event; not part of this archive.\n'+('Blind: only explicitly blind manuscript derivatives included; archive anonymity requires independent review.\n' if snapshot['mode']=='blind' else '')).encode()
    try:return make_package(files,dict(kind='delivery_package',snapshot_id=snapshot['id'],snapshot_sha256=snapshot['sha256'],mode=snapshot['mode']))
    except ValueError as exc:raise invalid('research_export_limit_exceeded',422) from exc


def render_delivery_package(payload,output):
    raw,inner=build_package(payload['snapshot'],payload['raws']);path=Path(output)/'delivery.zip';path.write_bytes(raw)
    member=dict(key='delivery',role='zip',format='zip',path=str(path.resolve()),sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw),properties=dict(snapshot_sha256=payload['snapshot']['sha256']))
    return dict(outputs=[member],manifest=dict(schema_version=1,kind='delivery_package',snapshot_id=payload['snapshot']['id'],snapshot_sha256=payload['snapshot']['sha256'],inner_manifest=inner))
