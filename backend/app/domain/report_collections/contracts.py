"""Immutable collection contracts; no current-setup or model dependency."""
from datetime import datetime
import json
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.adapters.report_store import digest
from app.core.exceptions import StorageError
from app.domain.explanation_content import SECTIONS

RENDERER = 'collection_word_v1'
SECTION_LABELS = {
    'overview': ('数据概况', 'Data overview'), 'quality': ('数据质量', 'Data quality'),
    'processing': ('处理方式', 'Data processing'), 'methods': ('分析方法', 'Analysis methods'),
    'statistics': ('统计结果', 'Statistical results'), 'figures': ('带标签图表', 'Labelled figures'),
    'explanations': ('逐图六节解释', 'Six-section explanations'),
    'findings': ('主要发现', 'Main findings'), 'summary': ('分析总结', 'Analysis summary'),
}

class ItemRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    figure_id: str | None = Field(default=None,min_length=1,max_length=64)
    figure_config_version_id: str | None = Field(default=None,min_length=1,max_length=64)
    explanation_id: str | None = Field(default=None,min_length=1,max_length=64)
    explanation_engine: str = Field(default='figure_explanation_v1',min_length=1,max_length=100)
    caption: str | None = Field(default=None,max_length=2000)

    @model_validator(mode='after')
    def exact_dependency(self):
        if bool(self.figure_id)==bool(self.figure_config_version_id): raise ValueError('Select exactly one figure or configuration version')
        if self.explanation_id and not self.figure_id: raise ValueError('An explanation must name its exact figure')
        return self

class CollectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1,max_length=200)
    language: Literal['zh-CN','en']
    automatic: bool = True
    items: list[ItemRequest] = Field(min_length=1,max_length=30)
    expected_revision: int | None = Field(default=None,ge=1,strict=True)


def invalid(code='collection_source_conflict'):
    messages={
        'collection_source_conflict':'集合必须使用同一整理数据版本、工作表及语言，且各项来源完整。',
        'collection_duplicate_figure':'同一集合版本不能重复包含同一张图。',
        'collection_legacy_numbering':'历史图片包含固定图号，请主动生成兼容的新图版本，或继续使用历史报告。',
        'collection_plan_required':'集合结果必须引用真实已确认的分析计划。',
        'collection_explanation_conflict':'解释未完整绑定此图与结果，请核对六节解释。',
    }
    return StorageError(code,messages.get(code,'报告集合资料不一致，请重新读取。'),409)


def request_key(value):
    if not isinstance(value,str) or not re.fullmatch(r'[!-~]{1,128}',value):
        raise StorageError('collection_input_invalid','请提供有效的请求标识。',422)
    return value


def json_value(value):
    def encode(item):
        if isinstance(item,datetime): return item.isoformat()
        raise TypeError('Unsupported frozen value')
    return json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False,default=encode))


def freeze_collection(bundles, *, language, title):
    """Freeze already authenticated bundles, retaining separate n/plan/figure bindings."""
    if not 1 <= len(bundles) <= 30 or language not in ('zh-CN','en'):
        raise invalid()
    items,seen,sources,missing=[],set(),{},[]
    for number,bundle in enumerate(bundles,1):
        item=json_value(bundle)
        result,figure,explanation=item['result'],item['figure'],item.get('explanation')
        user_caption=item.get('user_caption',item.get('caption'))
        base_caption=figure.get('caption','') if figure else item.get('planned_caption',item['configuration'].get('config',{}).get('style',{}).get('caption',''))
        item['user_caption']=user_caption
        item['caption']=base_caption+(('\nUser annotation: ' if language=='en' else '\n用户补充：')+user_caption if user_caption else '')
        source=result.get('source',{})
        if not result.get('analysis_plan',{}).get('plan_id') or not result['analysis_plan'].get('sha256'):
            raise invalid('collection_plan_required')
        identities={('configuration',item['configuration']['id'])}
        if figure: identities.add(('figure',figure['id']))
        if identities & seen: raise invalid('collection_duplicate_figure')
        seen.update(identities)
        if source.get('kind')!='prepared_dataset_version': raise invalid()
        sources[digest(source)]=source
        if len(sources)>1: raise invalid()
        if not figure:
            config=item['configuration'].get('config',{})
            if config.get('language',result.get('output_language',language))!=language: raise invalid()
            missing.append({'figure_config_version_id':item['configuration']['id'],'kind':'figure'})
            item.update(figure_number=number,
                hashes={key:digest(item[key]) if item.get(key) is not None else None for key in ('result','figure','explanation','configuration','projection')})
            items.append(item)
            continue
        if figure.get('numbering_mode')!='external' or figure.get('figure_number') is not None:
            raise invalid('collection_legacy_numbering')
        if (source.get('kind')!='prepared_dataset_version' or figure.get('source')!=source
            or figure.get('language')!=language or figure.get('analysis_run_id')!=result['id']
            or figure.get('setup_revision')!=result['setup_revision']
            or figure.get('source_sha256')!=result['source_sha256']
            or figure.get('file_id')!=result['file_id'] or figure.get('verification',{}).get('status')!='matched'):
            raise invalid()
        if explanation is not None:
            if (explanation.get('analysis_run_id')!=result['id'] or explanation.get('figure_id')!=figure['id']
                or explanation.get('figure_sha256')!=figure['sha256'] or explanation.get('language')!=language
                or explanation.get('verification',{}).get('status')!='references_checked'
                or [s.get('key') for s in explanation.get('sections',[])]!=list(SECTIONS)
                or any(not isinstance(s.get('text'),str) or not s['text'].strip() for s in explanation['sections'])):
                raise invalid('collection_explanation_conflict')
        else: missing.append({'figure_id':figure['id'],'kind':'explanation'})
        item.update(figure_number=number,
            hashes={key:digest(item[key]) if item.get(key) is not None else None for key in ('result','figure','explanation','configuration','projection')})
        items.append(item)
    saved={'schema_version':1,'title':title,'language':language,'sources':list(sources.values()),'items':items,
        'numbering':{x['figure']['id'] if x['figure'] else x['configuration']['id']:x['figure_number'] for x in items},'missing':missing,'ready':not missing}
    saved['sections']=preview_sections(saved)
    return saved


def preview_sections(snapshot):
    en=snapshot['language']=='en'
    pending='Not supplied; no quality claim is inferred.' if en else '未提供；不据此推断数据质量已完整核验。'
    results={x['result']['id']:x['result'] for x in snapshot['items']}
    profiles={digest(x['profile']):x['profile'] for x in snapshot['items'] if x.get('profile') is not None}
    processing={digest(x['processing']):x['processing'] for x in snapshot['items'] if x.get('processing') is not None}
    content={
        'overview':snapshot['sources'],
        'quality':list(profiles.values()) or [pending],
        'processing':list(processing.values()) or [pending],
        'methods':[{'analysis_run_id':r['id'],'plan':r.get('analysis_context',{}).get('plan',r['analysis_plan']),
                    'method':r.get('statistics',{}).get('method',r.get('engine',{})),'check':r.get('check',{})} for r in results.values()],
        'statistics':[{'analysis_run_id':r['id'],'statistics':r.get('statistics',r.get('groups',{})),'check':r.get('check',{})} for r in results.values()],
        'figures':[{**({'figure_id':x['figure']['id']} if x['figure'] else {}),'figure_config_version_id':x['configuration']['id'],'figure_number':x['figure_number'],'title':x['figure']['title'] if x['figure'] else x.get('planned_title',x['configuration'].get('config',{}).get('style',{}).get('title','')),'caption':x['caption'],**({'presentation':x['figure']['presentation']} if x.get('figure',{} ) and 'presentation' in x['figure'] else {}),'missing':not bool(x['figure'])} for x in snapshot['items']],
        'explanations':[{**({'figure_id':x['figure']['id']} if x['figure'] else {}),'figure_config_version_id':x['configuration']['id'],'figure_number':x['figure_number'],'sections':x['explanation']['sections'] if x.get('explanation') else [],'missing':not bool(x.get('explanation'))} for x in snapshot['items']],
        'findings':[{'analysis_run_id':x['result']['id'],'figure_number':x['figure_number'],'text':s['text']} for x in snapshot['items'] if x.get('explanation') for s in x['explanation']['sections'] if s['key']=='results'],
        'summary':[{'analysis_run_id':x['result']['id'],'figure_number':x['figure_number'],'text':s['text'],'limitations':x['explanation'].get('limitations',[])} for x in snapshot['items'] if x.get('explanation') for s in x['explanation']['sections'] if s['key']=='interpretation'],
    }
    return [{'key':key,'title':labels[int(en)],'content':content[key]} for key,labels in SECTION_LABELS.items()]
