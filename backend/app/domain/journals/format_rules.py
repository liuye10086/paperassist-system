"""Read-only finite journal observations on the public manuscript structure."""
import re
from collections import Counter
from app.adapters.manuscript_docx import SECTION_LABELS
from app.domain.manuscript_review.facts import displayed_paragraphs

CATEGORIES=('length','sections','abstract','illustrations','references')

def count_text(text,language):
    return dict(hanzi=len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff]',text)),latin_words=len(re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)*",text)),whitespace_words=len(text.split()))

def category(key):
    if key.startswith('abstract'):return 'abstract'
    if key in ('word_limit',):return 'length'
    if key in ('required_sections','section_order','section_display_names') or key.startswith(('heading_','body_')):return 'sections'
    if key.startswith('reference'):return 'references'
    return 'illustrations'

def in_range(actual,expected):
    return actual<=expected if type(expected) is int else expected.get('min',0)<=actual<=expected.get('max',1000000)

def section_headings(snapshot):
    """Observe the public renderer's labels/order without exporting a document."""
    labels={key:en if snapshot['output_language']=='en' else zh for key,en,zh in SECTION_LABELS}
    if snapshot.get('journal_display_context'):
        from .display import display_sections
        return [s['display_name'] for s in display_sections(snapshot) if s['id']!='title']
    if 'sections' in snapshot:
        return [labels.get(s['id'],s.get('title') or s.get('heading') or s['id']) for s in snapshot['sections'] if s['id']!='title']
    # Legacy fact drafts render Results, then Methods, with optional References;
    # their storage/displayed_paragraphs order is not their document order.
    selected={'results','materials_and_methods'}
    if snapshot.get('references'):selected.add('references')
    return [labels[key] for key,_,_ in SECTION_LABELS if key in selected]

def check_format(snapshot,requirements,conflicts,*,public_issues=(),warnings=()):
    paragraphs=displayed_paragraphs(snapshot)
    sections=snapshot.get('sections')
    body='\n'.join(p['text'] for role,p in paragraphs if role not in ('abstract','references','title'))
    abstracts=[p for role,p in paragraphs if role=='abstract']
    abstract='\n'.join(p['text'] for p in abstracts)
    language=snapshot['output_language']
    figures=[f for g in snapshot.get('results_groups',[]) for f in g.get('figures',[])]
    tables=[t for g in snapshot.get('results_groups',[]) for t in g.get('tables',[])]
    items=[]
    def add(key,status,actual,expected,location,evidence,reason,automation='manual',identity=None):
        action={'pass':'保存当前检查依据。','mismatch':'按来源条款人工核对并在后续批次修改。','pending_verification':'补充明确原文、适用性或计数口径后新建检查。','manual':'人工核查；第二批不执行内容修改。','unsupported':'当前不支持自动核定，需人工处理。'}[status]
        item=dict(id=identity or key+':'+str(len(items)+1),category=category(key),key=key,status=status,actual=actual,expected=expected,location=location,evidence=evidence,suggested_action=action,future_automation=automation,reason=reason)
        items.append(item)
    for rule in requirements:
        key=rule['key'];expected=rule['value'];evidence=[rule];location='manuscript';automation='manual';actual=None
        blocked=[w for w in warnings if w.get('source_id') in (None,rule.get('source_id')) and w.get('blocks_rules',True)]
        if blocked:
            add(key,'pending_verification',None,expected,location,evidence,'；'.join(w['message'] for w in blocked));continue
        if rule['status']!='known':
            add(key,'unsupported' if rule['status']=='unsupported' else 'pending_verification',None,expected,location,evidence,'原文要求未知或不在当前支持范围。');continue
        if key in ('word_limit','abstract_word_limit'):
            is_abstract=key=='abstract_word_limit';text=abstract if is_abstract else body;actual=count_text(text,language);location='abstract' if is_abstract else 'body'
            method=rule.get('count_method');needed=('en_whitespace_' if language=='en' else 'zh_hanzi_latin_')+('abstract' if is_abstract else 'body')
            if is_abstract and not abstracts:status='mismatch';reason='已发布稿件缺少独立摘要结构，未从其他段落猜测摘要。'
            elif method!=needed:status='pending_verification';reason='缺少匹配语言及正文/摘要范围的明确计数口径；可见计数不等于期刊合规。'
            else:
                count=actual['whitespace_words'] if language=='en' else actual['hanzi']
                status='pass' if in_range(count,expected) else 'mismatch';reason='en按空白分词；zh按汉字计数并单列拉丁词。只含公共结构中可见正文，不计题注与参考文献，不替代Word字数。'
            automation='manual_semantic_compression'
        elif key=='section_display_names' or key.startswith(('heading_','body_')):
            from .display import context
            display=context(snapshot)
            actual=[dict(section_id=k,display_name=v) for k,v in display['names'].items()] if key=='section_display_names' else display['styles'].get(key)
            matches=({i['section_id']:i['display_name'] for i in actual}=={i['section_id']:i['display_name'] for i in expected}) if key=='section_display_names' else actual==expected
            status='pass' if matches else 'mismatch';location='journal_display_context';reason='读取固定期刊显示配置；未指定格式不认证为已适配。';automation='journal_display_v1'
        elif key in ('required_sections','section_order'):
            actual=section_headings(snapshot)
            if key=='section_order' and len(expected)==7 and snapshot.get('journal_display_context'):
                from .display import context
                display=context(snapshot);actual=[display['names'][k] for k in display['order']]
            normalized=[s.strip().casefold() for s in actual];wanted=[s.strip().casefold() for s in expected];location='sections'
            if key=='required_sections':status='pass' if all(s in normalized for s in wanted) else 'mismatch'
            else:
                ordered=[s for s in normalized if s in wanted];status='pass' if ordered==wanted else 'mismatch'
            reason='只作明确标题匹配；不猜测语义近似，不补写缺章。';automation='future_heading_or_order_after_confirmation'
        elif key=='abstract_required':
            actual=bool(abstracts and abstract.strip());status='pass' if actual==expected or (actual and not expected) else 'mismatch';location='abstract';reason='只读独立摘要结构；不从其他章节推断。';automation='manual_add_or_review_abstract'
        elif key=='abstract_headings':
            actual=[m.group(1).strip() for p in abstracts for m in re.finditer(r'(?:^|\n)\s*([^\n:：]{1,100})[:：]',p['text'])];status='pass' if all(h.casefold() in [a.casefold() for a in actual] for h in expected) else 'mismatch';location='abstract';reason='仅检查明确结构化摘要标题。';automation='manual_semantic_restructure'
        elif key in ('figure_limit','table_limit','reference_limit'):
            actual=len(figures if key=='figure_limit' else tables if key=='table_limit' else snapshot.get('references',[]));status='pass' if in_range(actual,expected) else 'mismatch';location='results_groups' if key!='reference_limit' else 'references';reason='按公共已保存结构统计，未扫描像素或增补资料。'
        elif key.startswith(('figure_','table_')):
            records=figures if key.startswith('figure_') else tables;kind='figure' if key.startswith('figure_') else 'table';suffix=key.split('_',1)[1];location='results_groups';missing=[]
            for record in records:
                if suffix=='captions':
                    value=record.get('caption') if kind=='figure' else record.get('title',record.get('caption'))
                    if expected and (not value or (kind=='figure' and record.get('caption_status') in ('missing','candidate'))):missing.append(record['id'])
                elif suffix=='numbering':
                    if expected and (type(record.get('number')) is not int or record.get('number',0)<1):missing.append(record['id'])
                elif suffix=='references':
                    cited={r.get('target_id') for _,p in paragraphs for r in p.get('cross_references',[]) if r.get('kind')==kind}
                    if expected and record['id'] not in cited:missing.append(record['id'])
            if suffix=='numbering':
                nums=[r.get('number') for r in records]
                if expected and len(set(nums))!=len(nums):missing+=['duplicate_numbers']
            actual=dict(count=len(records),missing=missing);status='mismatch' if missing else 'pass';reason='检查保存的身份、编号、题注或公共交叉引用关联；无图表时该存在性约束为空集。';automation='future_supported_layout_after_confirmation'
        elif key=='reference_style':
            actual=dict(style='NLM numeric structural checks',reference_count=len(snapshot.get('references',[])))
            if expected.upper()!='NLM':status='unsupported';reason='只支持NLM数字顺序与公共关联检查，未实现其他样式/CSL引擎。'
            else:
                violations=[i for i in public_issues if i['category']=='reference' and i['severity']=='error'];status='mismatch' if violations else 'pass';actual['public_violations']=violations;reason='复用公共引用连续编号、首次出现顺序、正文绑定及来源关联；复杂标点、期刊缩写和文献真实性仍需人工。'
            location='references';automation='future_supported_reference_layout_after_confirmation'
        else:status='manual';reason='稿件未保存可核定的实际DPI/清晰度元数据；不得从图像或文件名猜测。';location='results_groups'
        add(key,status,actual,expected,location,evidence,reason,automation)
    for conflict in conflicts:
        add(conflict['key'],'pending_verification',None,[r['value'] for r in conflict['requirements']],'guide',conflict['requirements'],conflict['reason'])
    # Unit tags cannot be reclassified as satisfied through a finite choice.
    for warning in warnings:
        if warning.get('key')=='unit_requirements':
            add('reference_style','manual',warning.get('actual'),None,'unit_requirements',warning.get('evidence',[]),warning['message'],identity='unit_requirements')
    for c in CATEGORIES:
        if not any(i['category']==c for i in items):
            default={'length':'word_limit','sections':'required_sections','abstract':'abstract_required','illustrations':'figure_limit','references':'reference_style'}[c]
            add(default,'pending_verification',None,None,'guide',[],'指南没有该类明确可用规则；不能宣称通过。')
    for issue in public_issues:
        if issue['severity']!='error':continue
        c='references' if issue['category']=='reference' else 'illustrations' if issue['category'] in ('caption','illustration') else 'sections' if issue['category']=='structure' else 'length'
        items.append(dict(id='public:'+issue['id'],category=c,key='public_consistency',status='mismatch',actual=issue.get('actual'),expected=issue.get('expected'),location=issue['location'],evidence=issue.get('source_evidence',[]),suggested_action='返回公共稿件检查修正精确数值、来源或引用关联；指南选择不能豁免。',future_automation='manual_public_consistency_fix',reason=issue['message']))
    summary=dict(counts=dict(Counter(i['status'] for i in items)),all_passed=bool(items) and all(i['status']=='pass' for i in items),meaning='任务成功仅表示只读检查完成，不表示全部投稿要求合规。')
    result=dict(items=items,adjustments=[i for i in items if i['status']!='pass'],summary=summary,public_issues=list(public_issues),count_method_version='visible_text_counts_v1',check_version=1,real_model_calls=False,real_network_calls=False)
    if snapshot.get('journal_display_context'):result['display_version']=snapshot['journal_display_context']['version']
    return result
