"""Registration gaps describe missing knowledge without inventing facts."""
import csv
import io
from pydantic import ValidationError
from app.core.exceptions import StorageError
from .contracts import Sample


def gap(path, message, *, blocking=False, code='research_information_pending'):
    return {'code':code,'path':path,'message':message,'blocking':blocking}


def requirement_gaps(content):
    result=[]
    if not content['services']:
        result.append(gap('services','请选择至少一种交付。',blocking=True))
    for key in ('alias','email','phone'):
        if content['contact'][key]['state']=='pending':
            result.append(gap('contact.'+key,'联系信息待补。'))
    if content['analysis_request']['core_question']['state']=='pending':
        result.append(gap('analysis_request.core_question','核心问题待确认。',blocking=True))
    if content['schedule']['priority']['state']=='pending':
        result.append(gap('schedule.priority','优先内容待确认。',blocking=True))
    materials={item['purpose']:item for item in content['material_checklist']}
    for purpose in ('protocol','sample_sheet','raw_data','existing_results','figures','other'):
        item=materials.get(purpose)
        if item is None or item['availability']=='pending':
            result.append(gap('material_checklist.'+purpose,'材料状态或来源待补充。',blocking=True))
    return result


def design_gaps(content):
    result=[]
    if not content['experiments']:
        result.append(gap('experiments','尚未登记实验。',blocking=True))
    if not content['samples']:
        result.append(gap('samples','尚未登记样本。',blocking=True))
    for index,sample in enumerate(content['samples']):
        if sample['donor']['state']=='pending':
            result.append(gap(f'samples.{index}.donor','供体未知；切片或空间区域不能自动视作独立生物重复。',blocking=True))
    for key in ('statistical_unit','biological_replicate','technical_replicate'):
        if content['observation'][key]['state']=='pending':
            result.append(gap('observation.'+key,'重复和统计单位待确认。',blocking=True))
    if content['observation']['structure']=='pending':
        result.append(gap('observation.structure','样本配对或独立结构待确认。',blocking=True))
    return result


def design_table_preview(request):
    allowed=set(Sample.model_fields)-{'experiment_id','file_id','bio_dataset_version_id'}
    if not {'id','group_id'} <= request.mapping.keys() or set(request.mapping)-allowed:
        raise StorageError('research_design_invalid','映射须包含id/group_id，且只能使用样本表字段。',422)
    if len(request.text.encode('utf-8'))>2097152:
        raise StorageError('research_design_invalid','样本表文本最多2MiB。',422)
    reader=csv.DictReader(io.StringIO(request.text.lstrip('\ufeff')),delimiter=',' if request.format=='csv' else '\t',strict=True)
    try:
        headers=reader.fieldnames or []
    except csv.Error as exc:
        raise StorageError('research_design_invalid','CSV/TSV表头格式无效。',422) from exc
    if len(headers)!=len(set(headers)) or any(column not in headers for column in request.mapping.values()):
        raise StorageError('research_design_invalid','表头重复或映射列不存在。',422)
    samples=[]; conflicts=[]; seen=set(); groups=set(request.group_ids)
    def strict_rows():
        try:
            yield from reader
        except csv.Error as exc:
            raise StorageError('research_design_invalid','CSV/TSV引号或分隔符格式无效。',422) from exc
    for row_number,row in enumerate(strict_rows(),start=2):
        if row_number>10001:
            raise StorageError('research_design_invalid','样本表最多10000行。',422)
        if None in row or any(value is None for value in row.values()):
            raise StorageError('research_design_invalid','样本表每行列数须与表头一致。',422)
        values={'experiment_id':request.experiment_id}
        for key,column in request.mapping.items():
            value=(row.get(column) or '').strip()
            values[key]=value if key in ('id','group_id') else ({'state':'known','value':value} if value else {'state':'pending','value':None})
        try:
            sample=Sample.model_validate(values).model_dump(mode='json')
            if sample['id'] in seen:
                raise ValueError('样本ID重复。')
            if sample['group_id'] not in groups:
                raise ValueError('样本使用了未知组。')
            samples.append(sample); seen.add(sample['id'])
        except (ValidationError,ValueError):
            conflicts.append({'row':row_number,'code':'research_design_invalid','message':'样本字段无效、ID重复或组未登记。'})
    gaps=[gap(f'samples.{index}.donor','供体待确认。',blocking=True) for index,sample in enumerate(samples) if sample['donor']['state']=='pending']
    return {'samples':samples,'conflicts':conflicts,'gaps':gaps}
