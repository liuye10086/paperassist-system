"""Pure deterministic suggestion and lossless original segmentation."""
import re
from app.core.exceptions import StorageError

def invalid(message,status=422):return StorageError('task_input_invalid',message,status)

def split_text(text,explicit=None,locations=None):
    if not isinstance(text,str) or not text.strip():raise invalid('意见原文不能为空。')
    if len(text)>500000:raise invalid('意见原文过长。')
    if explicit is not None:
        spans=[s.model_dump() if hasattr(s,'model_dump') else dict(s) for s in explicit]
    else:
        lines=list(re.finditer(r'(?m)^\s*(?:\d+[.)、．]|[（(]\d+[）)])\s*',text))
        if lines:
            starts=[m.start() for m in lines]
            if text[:starts[0]].strip():starts.insert(0,0)
            spans=[dict(start=s,end=starts[i+1] if i+1<len(starts) else len(text),original_number=(re.match(r'\s*((?:\d+[.)、．]|[（(]\d+[）)]))',text[s:]).group(1) if re.match(r'\s*((?:\d+[.)、．]|[（(]\d+[）)]))',text[s:]) else '')) for i,s in enumerate(starts)]
        else:spans=[dict(start=m.start(),end=m.end(),original_number='') for m in re.finditer(r'[^\n]+(?:\n(?!\s*\n)[^\n]+)*',text) if m.group().strip()]
    covered=set();result=[]
    for span in spans:
        start,end=span['start'],span['end']
        if not 0<=start<end<=len(text) or any(i in covered for i in range(start,end)):raise invalid('意见分段位置重叠或超出原文。')
        covered.update(range(start,end))
        location=next((b['location'] for b in locations or [] if b['start']<=start<b['end']),dict(kind='text',start=start,end=end))
        result.append(dict(start=start,end=end,original_number=span.get('original_number',''),text=text[start:end],location=location))
    if any(not c.isspace() and i not in covered for i,c in enumerate(text)) or not result:raise invalid('分段必须完整覆盖非空白原文且不得重复。')
    return result

def propose(source,index,segment):
    text=segment['text'];lower=text.lower();category='uncategorized'
    for name,words in [('experiment',['experiment','实验','试验']),('statistics',['statistic','统计','p value','sample size']),('figure',['figure','table','图','表']),('method',['method','方法']),('literature',['reference','citation','文献','引用']),('format',['format','格式']),('structure',['structure','结构','section order','before results']),('expression',['wording','grammar','措辞','语法','压缩','局限性'])]:
        if any(w in lower for w in words):category=name;break
    flags=[]
    if any(w in lower for w in ['conclusion','结论','导致','causal','causation','cause','相关']):flags.append('conclusion_change')
    if category=='uncategorized':flags.append('ambiguous')
    needs=[dict(kind='experiment',description='需要用户提供实验材料；本批不执行实验。')] if category=='experiment' else []
    plans={'expression':'在固定目标段落核对措辞与冗余，保留事实、数值和局限性；修改后复核语义。','structure':'核对固定章节顺序及所选学校/期刊约束，列出调整前后顺序；冲突意见交用户选择。','literature':'定位需支持的具体陈述，核对已有引用和证据；缺失文献列为待核验，不插入虚构引用。','statistics':'对照固定稿件和既有统计核对样本量、口径、单位；需要重分析时关联已确认计划的本地统计任务，取得并采用实际结果后再提交具体改文。','figure':'定位固定图表及图注，核对已有单位、编号和来源；未知内容需补充原图或依据。','method':'定位固定方法段落，按已有材料补充方法说明并核对与结果的一致性。','format':'对照选定固定学校确认/期刊指南列出格式差异，仅提出已支持范围的检查计划。','experiment':'明确独立验证实验的目的、所需数据和证明标准；等待用户提供材料，本批不执行实验。','uncategorized':'请用户澄清意见含义和固定目标位置，再补充处理计划。'}
    if category=='literature':needs=[dict(kind='literature',description='核验已有或补充文献对陈述的支持；新检索与模型核验仍须授权，未核验资料不能作为已完成引用。')]
    return dict(id=source['id']+':'+str(index),source_id=source['id'],number=index,original_number=segment['original_number'],original_text=text,source_location=segment['location'],revision=1,category=category,locations=[],translation=None,plan=plans[category],evidence_ids=[],needs=needs,flags=flags,conflicting_item_ids=[],proposed_action='modify',not_adopt_reason='',status='pending',uncompleted_reason='返修计划尚未执行具体改文；关联任务或材料到达不能单独代表意见已完成。',decision=None)

def update_status(items):
    for item in items:
        decision=item.get('decision');action=decision and decision['action']
        if action=='not_adopt':item['status']='not_adopted';item['uncompleted_reason']=decision['reason']
        elif item['needs']:item['status']='waiting_material';item['uncompleted_reason']='待补充或核验材料、分析、实验、文献；取得实际结果并通过公共检查后才能完成修改。'
        elif (item['flags'] or item['proposed_action']=='not_adopt') and action not in ('accept','clarify'):item['status']='waiting_confirmation';item['uncompleted_reason']='待用户明确处理歧义、冲突或结论变化。'
        else:item['status']='pending';item['uncompleted_reason']='返修计划已保存，尚未实际修改稿件。'
    return items


def detect_conflicts(items):
    """Finite opposite requests are candidates, never semantic adjudication."""
    for n,left in enumerate(items):
        a=left['original_text'].lower()
        for right in items[n+1:]:
            b=right['original_text'].lower()
            limitation=any(w in a for w in ('limitation','局限性')) and any(w in b for w in ('limitation','局限性'))
            order=any(w in a for w in ('section order','before results','章节顺序')) and any(w in b for w in ('section order','before results','章节顺序'))
            opposite=(any(w in a for w in ('delete','remove','删除')) and any(w in b for w in ('retain','keep','保留'))) or (any(w in b for w in ('delete','remove','删除')) and any(w in a for w in ('retain','keep','保留')))
            opposite_order=(any(w in a for w in ('before results','调整','更改')) and any(w in b for w in ('retain','keep','保留'))) or (any(w in b for w in ('before results','调整','更改')) and any(w in a for w in ('retain','keep','保留')))
            if limitation and opposite or order and opposite_order:
                for item,other in ((left,right),(right,left)):
                    if 'conflict' not in item['flags']:item['flags'].append('conflict')
                    item['conflicting_item_ids'].append(other['id'])
    return items
