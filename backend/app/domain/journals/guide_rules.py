"""Exact finite line grammar; no semantic inference and no source certification."""
import re
from copy import deepcopy
from collections import defaultdict
from app.domain.literature.service import digest

NUMBER_LABELS={'Maximum body words':'word_limit','Maximum abstract words':'abstract_word_limit','Maximum figures':'figure_limit','Maximum tables':'table_limit','Maximum references':'reference_limit','Minimum DPI':'dpi','正文字数上限':'word_limit','摘要字数上限':'abstract_word_limit','图数上限':'figure_limit','表数上限':'table_limit'}
LIST_LABELS={'Required sections':'required_sections','Section order':'section_order','Abstract headings':'abstract_headings','必需章节':'required_sections','章节顺序':'section_order','摘要标题':'abstract_headings'}
BOOL_LABELS={'Abstract required':'abstract_required','Figure captions':'figure_captions','Table captions':'table_captions','Figure numbering':'figure_numbering','Table numbering':'table_numbering','Figure references':'figure_references','Table references':'table_references','必须摘要':'abstract_required'}
STYLE_LABELS={scope.title()+' '+label:scope+'_'+key for scope in ('heading','body') for label,key in [('font size','font_size_pt'),('line spacing','line_spacing'),('space before','space_before_pt'),('space after','space_after_pt')]}

def extract_requirements(text,*,location_prefix='line'):
    output=[]
    for line_no,line in enumerate(text.splitlines(),1):
        raw=line.strip()
        # Optional explicit [article type] qualifier is part of the saved quote.
        match=re.fullmatch(r'(?:\[([^\]]+)\]\s*)?([^:：]+)[:：]\s*(.+)',raw)
        if not match:continue
        article,label,value=match.groups();label=label.strip();value=value.strip();count=None;status='known'
        if label in STYLE_LABELS:
            key=STYLE_LABELS[label];unit=r'(?:multiple|倍)' if key.endswith('line_spacing') else 'pt'
            numeric=re.fullmatch(r'(\d+(?:\.\d+)?)\s*'+unit,value,re.I)
            if not numeric:continue
            value=float(numeric[1])
            from .display import validate_style
            try:validate_style(key,value)
            except ValueError:continue
        elif label=='Display sections':
            pairs=[p.strip().split('=',1) for p in value.split('|')]
            if any(len(p)!=2 for p in pairs):continue
            key='section_display_names';value=[dict(section_id=p[0].strip(),display_name=p[1].strip()) for p in pairs]
            from .format_contracts import Requirement
            try:Requirement(id='check',key=key,value=value,status='known',quote=raw,location='line:'+str(line_no))
            except ValueError:continue
        elif label in NUMBER_LABELS:
            numeric=re.fullmatch(r'(\d+)(?:\s*;\s*count:\s*(en_whitespace_body|zh_hanzi_latin_body|en_whitespace_abstract|zh_hanzi_latin_abstract))?',value)
            if not numeric:continue
            key=NUMBER_LABELS[label];value=int(numeric[1]);count=numeric[2]
            if key=='dpi':status='unsupported'
        elif label in LIST_LABELS:
            key=LIST_LABELS[label];value=[v.strip() for v in value.split('|')]
            if any(not v for v in value):continue
        elif label in BOOL_LABELS:
            key=BOOL_LABELS[label]
            if value not in ('yes','required','true','no','false','是','必须','否'):continue
            value=value in ('yes','required','true','是','必须')
        elif label in ('Reference style','引用样式'):
            key='reference_style';status='known' if value.upper()=='NLM' else 'unsupported'
        else:continue
        output.append(dict(id='extracted:'+str(line_no),key=key,value=value,status=status,quote=raw,location=f'{location_prefix}:{line_no}',article_type=article,count_method=count,origin='journal',note='有限固定行提取；仅反映登记原文，不认证来源真实性。'))
    return output

def select_requirements(requirements,article_type,resolutions):
    grouped=defaultdict(list);decisions=[]
    for rule in requirements:
        if rule.get('article_type') not in (None,article_type):continue
        grouped[(rule['key'],rule.get('source_id',''),rule.get('origin','journal'))].append(deepcopy(rule))
    by_key=defaultdict(list)
    for (key,_,_),rules in grouped.items():
        specific=[r for r in rules if r.get('article_type')==article_type]
        if specific:
            decisions.append(dict(key=key,selected_id=specific[0]['id'],preserved_ids=[r['id'] for r in rules],reason='明确适用文章类型的专属条款优先同来源一般条款。',evidence=rules))
            rules=specific
        by_key[key].extend(rules)
    choices={r['key']:r for r in resolutions};selected=[];conflicts=[]
    for key,rules in by_key.items():
        signatures={digest({k:r.get(k) for k in ('value','status','count_method')}) for r in rules}
        decision=choices.get(key)
        if decision:
            chosen=next((r for r in rules if r['id']==decision['requirement_id']),None)
            if decision['requirement_id'] is not None and chosen is None:raise ValueError('Conflict choice must select an applicable saved requirement.')
            decisions.append(dict(key=key,selected_id=decision['requirement_id'],preserved_ids=[r['id'] for r in rules],reason=decision['reason'],evidence=rules))
            if chosen:selected.append(chosen)
            else:conflicts.append(dict(key=key,requirements=rules,reason=decision['reason'],deferred=True))
        elif len(signatures)>1:conflicts.append(dict(key=key,requirements=rules,reason='不同来源或同范围条款存在冲突；请有限选择或暂缓并写理由。',deferred=False))
        else:selected.append(rules[0])
    if set(choices)-set(by_key):raise ValueError('No applicable saved requirements for the requested decision.')
    return selected,conflicts,decisions
