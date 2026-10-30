"""Transactional immutable versions with root CAS and stable request replay."""
import hashlib
import json
from uuid import uuid4
from app.core.exceptions import StorageError
from app.adapters.research_intake_store import VERSION_TABLES, now, require_owner, require_reference, version_view
from .delivery_access import capabilities, delivery_capabilities
from .validation import requirement_gaps, design_gaps, design_table_preview


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def request_key(value):
    if not isinstance(value,str) or not 1<=len(value)<=128 or not value.strip() or any(ord(x)<32 for x in value):
        raise StorageError('research_request_key_required','请提供1至128字符的Idempotency-Key。',422)
    return value


def gaps(kind,content):
    return requirement_gaps(content) if kind=='requirements' else design_gaps(content)


def read_intake(store,project_id):
    with store.connection() as db:
        project=require_owner(db,store,project_id)
        root=db.execute('SELECT * FROM research_intakes WHERE project_id=%s',(project_id,)).fetchone()
        if root is None:
            raise StorageError('research_intake_not_found','项目尚无需求登记。',404)
        requirement=version_view(db,db.execute('SELECT * FROM research_requirement_versions WHERE id=%s',(root['current_requirement_version_id'],)).fetchone(),'requirements')
        design=version_view(db,db.execute('SELECT * FROM research_design_versions WHERE id=%s',(root['current_design_version_id'],)).fetchone(),'research-designs')
        deliveries=[dict(row) for row in db.execute('SELECT * FROM research_deliveries WHERE project_id=%s ORDER BY kind',(project_id,))]
        issues=(gaps('requirements',requirement['content']) if requirement else [])+(gaps('research-designs',design['content']) if design else [])
        return {'project_id':project_id,'revision':root['revision'],'current_requirement':requirement,'current_design':design,
                'deliveries':delivery_capabilities(project,deliveries),'capabilities':capabilities(project),'gaps':issues}


def read_versions(store,project_id,kind,*,page=1,version_id=None,key=None):
    table=VERSION_TABLES[kind]
    with store.connection() as db:
        require_owner(db,store,project_id)
        if version_id or key:
            column='id' if version_id else 'request_key'
            row=db.execute(f'SELECT * FROM {table} WHERE project_id=%s AND {column}=%s',(project_id,version_id or key)).fetchone()
            if row is None:
                raise StorageError('research_version_not_found','版本不存在。',404)
            return version_view(db,row,kind)
        total=db.execute(f'SELECT count(*) AS n FROM {table} WHERE project_id=%s',(project_id,)).fetchone()['n']
        rows=db.execute(f'SELECT * FROM {table} WHERE project_id=%s ORDER BY version DESC LIMIT 5 OFFSET %s',(project_id,(page-1)*5))
        return {'items':[version_view(db,row,kind) for row in rows],'page':page,'page_size':5,'total':total}


def _validate_refs(db,project_id,kind,content,refs):
    references=[('research_deliveries',r.delivery_id) for r in refs if r.delivery_id]
    references += [('files',r.file_id) for r in refs if r.file_id]
    references += [('bio_dataset_versions',r.bio_dataset_version_id) for r in refs if r.bio_dataset_version_id]
    if kind=='research-designs':
        for sample in content['samples']:
            for key,table in [('file_id','files'),('bio_dataset_version_id','bio_dataset_versions')]:
                if sample[key]:
                    references.append((table,sample[key]))
                    # Every structured object reference also has a real scoped
                    # material FK attached to this immutable version.
                    if not any(getattr(r,key)==sample[key] and r.availability=='provided' for r in refs):
                        raise StorageError('research_material_invalid','样本来源须同时登记为provided材料引用。',422)
    else:
        for identifier in content['figure_request']['existing_file_ids']:
            references.append(('files',identifier))
            if not any(r.file_id==identifier and r.availability=='provided' for r in refs):
                raise StorageError('research_material_invalid','已有图片须同时登记为provided材料引用。',422)
        for item in content['material_checklist']:
            if item['availability']=='provided' and not any(r.purpose==item['purpose'] and r.availability=='provided' for r in refs):
                raise StorageError('research_material_invalid','已提供材料须绑定实际文件或数据集版本。',422)
    for table,identifier in references:
        require_reference(db,table,identifier,project_id)


def write_version(store,project_id,kind,request,key):
    key=request_key(key); table=VERSION_TABLES[kind]
    body=request.model_dump(mode='json'); request_digest=digest(body); content=body['content']
    issues=gaps(kind,content)
    if request.operation=='confirm':
        if kind=='requirements' and not content['services']:
            raise StorageError('research_requirement_invalid','确认需求须至少选择一种交付。',422)
        if kind=='research-designs' and not content['experiments']:
            raise StorageError('research_design_invalid','确认设计须至少登记一套实验。',422)
    if len(canonical(content).encode())>4*1024*1024:
        raise StorageError('research_content_too_large','需求或设计内容超过4MiB。',422)
    with store.connection(write=True) as db:
        project=require_owner(db,store,project_id)
        replay=db.execute(f'SELECT * FROM {table} WHERE project_id=%s AND request_key=%s',(project_id,key)).fetchone()
        if replay:
            if replay['request_digest']!=request_digest:
                raise StorageError('research_request_conflict','相同请求键已用于不同内容。',409)
            # Revision at this saved result is stable even if later saves exist.
            return {'project_id':project_id,'revision':request.expected_revision+1,'version':version_view(db,replay,kind),'gaps':issues}
        root=db.execute('SELECT * FROM research_intakes WHERE project_id=%s FOR UPDATE',(project_id,)).fetchone()
        if root is None:
            raise StorageError('research_intake_not_found','项目尚无需求登记。',404)
        if root['revision']!=request.expected_revision:
            raise StorageError('research_revision_conflict','需求已被另一窗口修改，请读取新版本并保留本地草稿。',409)
        _validate_refs(db,project_id,kind,content,request.material_refs)
        version=db.execute(f'SELECT coalesce(max(version),0)+1 AS n FROM {table} WHERE project_id=%s',(project_id,)).fetchone()['n']
        pointer='current_requirement_version_id' if kind=='requirements' else 'current_design_version_id'
        identifier=str(uuid4()); moment=now()
        db.execute(f'''INSERT INTO {table}(id,project_id,version,parent_id,operation,content_json,sha256,request_key,request_digest,created_by,created_at)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)''',
            (identifier,project_id,version,root[pointer],request.operation,canonical(content),digest(content),key,request_digest,store.owner_id,moment))
        ref_column='requirement_version_id' if kind=='requirements' else 'design_version_id'
        for ref in request.material_refs:
            db.execute(f'''INSERT INTO research_material_refs(id,project_id,{ref_column},delivery_id,file_id,bio_dataset_version_id,locator,availability,purpose,note)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (str(uuid4()),project_id,identifier,ref.delivery_id,ref.file_id,ref.bio_dataset_version_id,ref.locator,ref.availability,ref.purpose,ref.note))
        changed=db.execute(f'UPDATE research_intakes SET {pointer}=%s,revision=revision+1,updated_at=%s WHERE project_id=%s AND revision=%s',
                           (identifier,moment,project_id,request.expected_revision))
        if changed.rowcount!=1:
            raise StorageError('research_revision_conflict','需求版本已变化。',409)
        if kind=='requirements':
            selected=set(content['services'])
            # Legacy inferred delivery remains registered; changing intake never
            # modifies the old project_type or its existing manuscript contract.
            db.execute('UPDATE research_deliveries SET active=(kind=ANY(%s)),revision=revision+1,updated_at=%s WHERE project_id=%s', (list(selected),moment,project_id))
            for delivery_kind in selected:
                db.execute('''INSERT INTO research_deliveries(id,project_id,kind,name,origin,active,revision,created_by,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,'user_selected',true,1,%s,%s,%s) ON CONFLICT(project_id,kind) DO NOTHING''',
                    (str(uuid4()),project_id,delivery_kind,delivery_kind,store.owner_id,moment,moment))
        row=db.execute(f'SELECT * FROM {table} WHERE id=%s',(identifier,)).fetchone()
        return {'project_id':project_id,'revision':request.expected_revision+1,'version':version_view(db,row,kind),'gaps':issues}


def preview_table(store,project_id,request):
    with store.connection() as db:
        require_owner(db,store,project_id)
        source=None
        if request.file_id:
            row=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s',(request.file_id,project_id)).fetchone()
            if not row:
                raise StorageError('research_material_invalid','样本表不存在或不属于当前项目。',422)
            file=dict(row)
            source={'file_id':file['id'],'sha256':file['sha256']}
            if file['file_type']=='xlsx':
                if file['parse_status']!='parsed':
                    raise StorageError('research_design_invalid','请等待XLSX解析完成后映射样本表。',422)
                text,sheet_name=_xlsx_sample_text(store,file,request.sheet)
                source['sheet_name']=sheet_name
                request=request.model_copy(update={'text':text,'format':'csv'})
            elif file['file_type']=='bio_component' and file['filename'].lower().endswith(('.csv','.tsv')):
                if file['size_bytes']>2097152:
                    raise StorageError('research_design_invalid','样本表最多2MiB。',422)
                try:
                    text=store.original(file).decode('utf-8-sig')
                except UnicodeError as exc:
                    raise StorageError('research_design_invalid','CSV/TSV须为UTF-8文本。',422) from exc
                inferred='tsv' if file['filename'].lower().endswith('.tsv') else 'csv'
                request=request.model_copy(update={'text':text,'format':request.format or inferred})
            else:
                raise StorageError('research_design_invalid','请选择已解析XLSX或UTF-8 CSV/TSV样本表。',422)
        result=design_table_preview(request)
        if source:
            result['source']=source
            for sample in result['samples']:
                sample['file_id']=source['file_id']
        return result


def _xlsx_sample_text(store,file,sheet,*,max_rows=10000,max_text_bytes=2097152):
    """Reuse the bounded XLSX scanner; never execute spreadsheet formulas."""
    import csv
    import io
    from app.adapters.excel import WorkbookPreview, parse_workbook, json_value
    from app.core.config import get_excel_settings
    preview=WorkbookPreview.model_validate_json(file['preview_json'])
    if isinstance(sheet,int):
        if sheet>=len(preview.sheets):
            raise StorageError('research_design_invalid','工作表不存在。',422)
        sheet_name=preview.sheets[sheet].name
    else:
        sheet_name=sheet
        if not any(item.name==sheet_name for item in preview.sheets):
            raise StorageError('research_design_invalid','工作表不存在。',422)
    selected=next(item for item in preview.sheets if item.name==sheet_name)
    if selected.row_count>max_rows or selected.column_count>100:
        raise StorageError('research_design_invalid',f'样本表最多{max_rows}行、100列。',422)
    text=io.StringIO();writer=csv.writer(text);count=0
    def observe(name,index,cells):
        nonlocal count
        if name!=sheet_name:
            return
        if index>max_rows+1 or len(cells)>100:
            raise StorageError('research_design_invalid',f'样本表最多{max_rows}行、100列。',422)
        if any(cell.data_type=='f' for cell in cells):
            raise StorageError('research_design_invalid','样本表含未计算公式，请上传核对后的文本或值副本。',422)
        values=['' if cell.value is None else str(json_value(cell.value)) for cell in cells]
        writer.writerow((values+['']*selected.column_count)[:selected.column_count])
        count+=1
        if text.tell()>max_text_bytes:
            raise StorageError('research_design_invalid',f'样本表文本最多{max_text_bytes//1048576}MiB。',422)
    parse_workbook(store.original(file),file['filename'],get_excel_settings(),observe_row=observe)
    if not count:
        raise StorageError('research_design_invalid','样本表为空。',422)
    return text.getvalue(),sheet_name
