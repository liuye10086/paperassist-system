"""Read exact existing outputs. No render, conversion, download or model calls."""
from hashlib import sha256
from pathlib import Path
import io,json
from app.adapters.research_results_store import invalid
from app.adapters.research_objects import ResearchObjects
from app.adapters.bio_analysis_store import scoped_object
from app.domain.source_byte_verification import VerificationPhase
from app.domain.research_results.sources import ResearchSourceReader
from app.domain.bioinformatics.contracts import digest


_NOTICE_KEYS=frozenset(('limitations','warnings','gaps','conflicts','quality','license','restrictions','distribution','redistribution','scope','caption','panel_order','panel_labels','text_verification','font_verification','semantic_verification','language_review','blind','checks','verification_status','strength','review_decision','observation_level'))

def inherited_notices(value,path='$'):
    """Copy explicit source declarations, never reinterpret them as biological proof."""
    notices=[]
    if isinstance(value,dict):
        for key,item in value.items():
            child=path+'.'+key
            if key in _NOTICE_KEYS and item not in (None,'',[],{}):notices.append(dict(path=child,value=item))
            else:notices.extend(inherited_notices(item,child))
    elif isinstance(value,list):
        for index,item in enumerate(value):notices.extend(inherited_notices(item,path+'['+str(index)+']'))
    return notices


def unresolved_notices(notices):
    def pending(value):
        if isinstance(value,str):return value.lower() in ('pending','unknown','unverified','not_reviewed','unresolved','needs_evidence','conflict','failed') or value.lower().startswith(('pending_','unverified_','unknown_'))
        if isinstance(value,dict):return any(pending(v) for v in value.values())
        if isinstance(value,list):return any(pending(v) for v in value)
        return False
    return any(n['path'].endswith('.gaps') or pending(n['value']) for n in notices)


def image_properties(raw,format):
    props=dict(format=format,dpi_declared=None,dpi_measured=None,physical_size_mm=None,text_verification='unknown',font_verification='unverified',semantic_verification='unverified')
    if format in ('png','tiff','jpg','jpeg'):
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            props['pixels']=list(image.size);dpi=image.info.get('dpi')
            if dpi and all(isinstance(x,(int,float)) and x>0 for x in dpi):
                props['dpi_measured']=list(dpi);props['physical_size_mm']=[round(image.size[i]/dpi[i]*25.4,4) for i in (0,1)]
    elif format=='svg':
        import xml.etree.ElementTree as ET
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise invalid()
        tree=ET.fromstring(raw);props['vector_dimensions']={k:tree.attrib.get(k) for k in ('width','height','viewBox')}
        props['contains_raster']=any(e.tag.rsplit('}',1)[-1]=='image' for e in tree.iter())
    elif format=='pdf':
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw)) as reader:
            props['page_sizes_mm']=[[round(float(p.width)*25.4/72,4),round(float(p.height)*25.4/72,4)] for p in reader.pages]
            props['contains_raster']=any(bool(p.images) for p in reader.pages)
    return props


def require_document_delivery(service,db,project,delivery_id,manuscript_id):
    """Resolve legacy SCI/thesis through the existing context, without rewriting it."""
    from app.domain.manuscripts.delivery_context import resolve_document_context
    context=resolve_document_context(db,project,service.store.user_id,manuscript_id=manuscript_id,active=False)
    resolved=context['delivery_id']
    if resolved is None:
        kind={'sci':'sci_draft','thesis':'thesis_draft'}[context['document_kind']]
        mapped=db.execute('SELECT id FROM research_deliveries WHERE project_id=%s AND kind=%s',(project,kind)).fetchone()
        resolved=mapped['id'] if mapped else None
    if resolved!=delivery_id:raise invalid()
    return context


def resolve_members(service,db,project,delivery,selections,mode,progress=None,*,frozen_members=None):
    members=[];raws=[];source_files=set();validated={};seen=set();total=0
    frozen_by_id={m['id']:m for m in frozen_members or []}
    report_ids=set();findings=set()
    with VerificationPhase(db,service.assets,project) as phase:
        reader=ResearchSourceReader(service.assets)
        for selection in selections:
            if progress:progress()
            value=selection.model_dump(mode='json',exclude_none=True);kind=selection.kind;proof={};review='identified';language=None;presentation=None;format=None
            frozen=frozen_by_id.get(digest(value)[:24])
            if frozen_members is not None and frozen is None:raise invalid()
            frozen_proof=frozen['source_metadata'] if frozen is not None else None
            if kind in ('research_report_member','research_figure_member'):
                family='report' if kind=='research_report_member' else 'figure';token=(family,selection.version_id)
                if token not in validated:
                    bound=reader._read_source_in_phase(project,dict(source_kind='research_'+family+'_version',source_id=selection.version_id),db=db,phase=phase,progress=progress)
                    validated[token]=bound;source_files.update(bound.source_file_ids)
                bound=validated[token];table='research_'+family+'_members'
                row=db.execute('SELECT * FROM '+table+' WHERE id=%s AND project_id=%s AND user_id=%s',(selection.member_id,project,service.store.user_id)).fetchone()
                if not row or row[family+'_version_id']!=selection.version_id:raise invalid('research_source_not_found',404)
                if frozen is None and row['format']=='pdf':raise invalid('research_source_unsupported',422)
                obj=scoped_object(db,project,service.store.user_id,row['storage_object_id'])
                if any(obj[k]!=row[k] for k in ('sha256','size_bytes')):raise invalid()
                raw=ResearchObjects(service.assets.directory).read(obj);format=row['format'];proof=dict(source_version_sha256=bound.sha256,properties=row['properties_json'],source_notices=inherited_notices(bound.content),source_identity=dict(kind='research_'+family+'_version',id=selection.version_id,sha256=bound.sha256))
                if family=='report':
                    proof['finding_version_id']=bound.content.get('finding',{}).get('id')
                    report_ids.add(selection.version_id);findings.add(proof['finding_version_id'])
                language=bound.content.get('language',bound.content.get('config',{}).get('language'));filename=row['key']+'.'+format
                if family=='figure':
                    fixed=db.execute('SELECT root_id FROM research_figure_versions WHERE id=%s AND project_id=%s AND user_id=%s',(selection.version_id,project,service.store.user_id)).fetchone()
                    proof['scientific_figure_identity']=fixed['root_id']
                    proof['panel_order']=[p.get('label',p.get('id')) for p in bound.content.get('config',{}).get('panels',[])]
                    proof['dpi_declared']=bound.content.get('config',{}).get('dpi')
                    scientific=[]
                    for ref in db.execute("SELECT source_kind,source_id,source_sha256 FROM research_source_bindings WHERE figure_version_id=%s AND project_id=%s AND user_id=%s AND source_kind IN ('research_report_version','research_finding_version') ORDER BY source_kind,source_id",(selection.version_id,project,service.store.user_id)):
                        scientific.append(dict(ref))
                        if ref['source_kind']=='research_finding_version':findings.add(ref['source_id'])
                        else:
                            fixed_report=db.execute('SELECT finding_version_id FROM research_report_versions WHERE id=%s AND project_id=%s AND user_id=%s',(ref['source_id'],project,service.store.user_id)).fetchone()
                            if not fixed_report:raise invalid()
                            report_ids.add(ref['source_id']);findings.add(fixed_report['finding_version_id'])
                    proof['scientific_bindings']=scientific
                    proof['scientific_binding_status']='fixed' if scientific else 'unverified'
                if format=='zip':
                    from app.domain.research_results.report_package import verify_package
                    inner=verify_package(raw)
                    import zipfile
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:proof['inner_manifest_sha256']=sha256(archive.read('manifest.json')).hexdigest()
                    proof['inner_members']=inner['members']
                directory='reports' if family=='report' else 'figures'
            elif kind=='manuscript_export':
                from app.domain.manuscripts.service import ManuscriptService
                require_document_delivery(service,db,project,delivery['id'],selection.manuscript_id)
                row=db.execute('SELECT e.*,v.snapshot_json,v.manuscript_id FROM manuscript_exports e JOIN manuscript_versions v ON v.id=e.version_id WHERE e.id=%s AND v.project_id=%s AND v.user_id=%s',(selection.export_id,project,service.store.user_id)).fetchone()
                if not row or row['version_id']!=selection.version_id or row['manuscript_id']!=selection.manuscript_id:raise invalid('research_source_not_found',404)
                meta,raw=ManuscriptService(service.assets).export(project,selection.manuscript_id,selection.export_id,True)
                task=service.store.require_task(db,row['task_id']);presentation=task['input_snapshot'].get('presentation',{}).get('binding');review=presentation.get('review_mode','identified') if presentation else 'identified';language=presentation.get('language_view') if presentation else row['snapshot_json']['output_language']
                from app.domain.file_lifecycle.references import file_ids
                source_files.update(file_ids(row['snapshot_json']));proof=dict(presentation=meta.get('presentation'),manuscript_version_id=row['version_id'],source_notices=inherited_notices(row['snapshot_json'])+inherited_notices(meta.get('presentation',{})));format='docx';filename=meta['filename'];directory='manuscripts'
            elif kind=='pdf_export':
                # Only exact frozen snapshots may read retired PDF exports.
                if frozen is None:raise invalid('research_source_unsupported',422)
                from app.domain.pdf_exports.service import PdfExportService
                svc=PdfExportService(service.assets);row=svc.row(db,project,selection.export_id);meta,raw=svc.download(project,selection.export_id,progress=progress)
                if row['source_kind']=='manuscript_export':
                    doc=db.execute('SELECT e.*,v.manuscript_id FROM manuscript_exports e JOIN manuscript_versions v ON v.id=e.version_id WHERE e.id=%s AND v.project_id=%s AND v.user_id=%s',(row['source_id'],project,service.store.user_id)).fetchone()
                    if not doc:raise invalid()
                    require_document_delivery(service,db,project,delivery['id'],doc['manuscript_id'])
                    binding=service.store.require_task(db,doc['task_id'])['input_snapshot'].get('presentation',{}).get('binding');presentation=binding;review=binding.get('review_mode','identified') if binding else 'identified';language=binding.get('language_view') if binding else None
                elif row['source_kind']!='research_report':raise invalid('research_source_unsupported',422)
                report=None
                if row['source_kind']=='research_report':
                    report=db.execute("SELECT v.* FROM research_report_members m JOIN research_report_versions v ON v.id=m.report_version_id WHERE m.id=%s AND m.project_id=%s AND m.user_id=%s AND m.role='docx' AND m.format='docx'",(row['source_id'],project,service.store.user_id)).fetchone()
                    source_version=row['input_json']['source']['version']
                    if (not report or source_version['id']!=report['id'] or digest(report['content_json'])!=report['content_sha256'] or report['content_json'].get('finding',{}).get('id')!=report['finding_version_id'] or service.store.require_task(db,report['task_id'])['status']!='succeeded'):raise invalid()
                    report_ids.add(report['id']);findings.add(report['finding_version_id'])
                from app.domain.file_lifecycle.references import file_ids
                source_files.update(file_ids(row['input_json']));proof=dict(pdf_source_kind=row['source_kind'],pdf_source_id=row['source_id'],pdf_source_sha256=row['source_sha256'],source_notices=inherited_notices(row['input_json'])+inherited_notices(meta.get('presentation',{})));format='pdf';filename=meta['filename'];directory='manuscripts' if row['source_kind']=='manuscript_export' else 'reports'
                if report is not None:
                    proof.update(report_version_id=report['id'],finding_version_id=report['finding_version_id'])
                    proof['source_notices']+=inherited_notices(report['content_json'])
            else:
                row=db.execute('SELECT * FROM files WHERE project_id=%s AND id=%s',(project,selection.file_id)).fetchone()
                if not row:raise invalid('research_source_not_found',404)
                row=dict(row);raw=service.assets.original(row);source_files.add(row['id']);format=Path(row['filename']).suffix.lstrip('.').lower() or 'bin';filename=row['filename'];directory='materials';proof=dict(distribution='user_selected_existing_upload',license='no_new_license_granted',source_notices=[])
                from app.domain.external_evidence.service import validate_evidence_row
                if frozen_proof is None:
                    evidence_rows=list(db.execute('SELECT * FROM external_evidence_versions WHERE file_id=%s AND project_id=%s AND user_id=%s ORDER BY version,id',(row['id'],project,service.store.user_id)))
                    references=[dict(id=e['id'],sha256=e['sha256']) for e in evidence_rows]
                    proof['evidence_versions']=references
                else:
                    references=frozen_proof['evidence_versions']
                    proof['evidence_versions']=references
                    evidence_rows=[]
                    for ref in references:
                        fixed_evidence=db.execute('SELECT * FROM external_evidence_versions WHERE id=%s AND file_id=%s AND project_id=%s AND user_id=%s',(ref['id'],row['id'],project,service.store.user_id)).fetchone()
                        if not fixed_evidence or fixed_evidence['sha256']!=ref['sha256']:raise invalid()
                        evidence_rows.append(fixed_evidence)
                for evidence in evidence_rows:
                    validate_evidence_row(db,evidence)
                    proof['source_notices'].append(dict(path='external_evidence:'+evidence['id'],value=dict(version=evidence['version'],sha256=evidence['sha256'],declarations=inherited_notices(evidence['snapshot_json']))))
            if mode=='blind' and (kind not in ('manuscript_export','pdf_export') or review!='blind'):raise invalid()
            if mode=='complete' and review=='blind':raise invalid()
            actual=sha256(raw).hexdigest();total+=len(raw)
            if total>256*1024*1024:raise invalid('research_export_limit_exceeded',422)
            token=(kind,selection.member_id or selection.export_id or selection.file_id)
            if token in seen:raise invalid()
            seen.add(token);identifier=digest(value)[:24]
            # Generated safe names prevent internal filenames/owner identities leaking into blind exports.
            name=directory+'/'+identifier+'.'+format
            properties=image_properties(raw,format) if format in ('png','tiff','jpg','jpeg','svg','pdf') else {}
            if properties:
                properties['dpi_declared']=proof.get('dpi_declared')
                properties['source_declarations']=proof.get('properties',{});properties['figure_mapping']=value.get('figure_mapping');properties['mapping_status']='confirmed_by_current_user' if selection.figure_mapping and selection.figure_mapping.confirmed else 'pending_verification'
            proof['source_quality_unresolved']=unresolved_notices(proof.get('source_notices',[]))
            members.append(dict(id=identifier,selection=value,name=name,format=format,sha256=actual,size_bytes=len(raw),language=language,review_mode=review,presentation=presentation,source_metadata=proof,image=properties))
            raws.append(raw)
    # A PDF cannot silently substitute a different language/review output for the DOCX in this snapshot.
    doc_ids={m['selection'].get('export_id') for m in members if m['selection']['kind']=='manuscript_export'}
    for member in members:
        proof=member['source_metadata']
        if doc_ids and proof.get('pdf_source_kind')=='manuscript_export' and proof['pdf_source_id'] not in doc_ids:raise invalid()
    findings.discard(None)
    if len(findings)>1:raise invalid()
    for member in members:
        if member['selection']['kind']=='manuscript_export':
            refs=db.execute("SELECT source_kind,source_id FROM manuscript_research_sources WHERE version_id=%s AND project_id=%s AND user_id=%s",(member['selection']['version_id'],project,service.store.user_id)).fetchall()
            fixed_reports={r['source_id'] for r in refs if r['source_kind']=='research_report_version'}
            fixed_findings={r['source_id'] for r in refs if r['source_kind']=='research_finding_version'}
            if fixed_reports and report_ids and not report_ids<=fixed_reports:raise invalid()
            if fixed_findings and findings and not findings<=fixed_findings:raise invalid()
    return members,raws,sorted(source_files)
