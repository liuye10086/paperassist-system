"""Stable literal tag matching, conditional facts and explicit unknown buckets."""
import re

METRIC_REQUIREMENT=re.compile(r'(?<![a-z])(?:scie?|jif|jcr|quartiles?)(?![a-z])|分区|影响因子',re.IGNORECASE)

LIMITATIONS=['离线规则建议；不代表真实推荐质量或用户验收。','SCI/SCIE、JIF/JCR、分区关闭；PubMed不能证明SCI。','不预测录用概率，不承诺审稿或发表时间。']

def normalized(value):return str(value).strip().casefold()

def recommend(snapshot,*,rules=None):
    if rules is not None:
        if (rules['recommendation_version']!='journal_recommendation_v1' or rules['source_mode']!='local_only'
            or rules['metrics_enabled'] is not False or rules['require_verification'] is not True):
            raise ValueError('Unsupported installed journal policy')
    request=snapshot['research'];buckets=dict(candidates=[],excluded=[],pending_verification=[])
    for profile in snapshot['profiles']:
        reasons=[];unknown=[];fail=[];matches=0;preferences=0
        def field(key):
            e=profile['fields'].get(key)
            return e if profile['source_status']=='available' and e and e['status']=='verified' else None
        def reason(key,message,state):
            e=profile['fields'].get(key) or dict(value=None,status='unknown',location='',quote='')
            reasons.append(dict(field=key,message=message,state=state,evidence=dict(e,profile_id=profile['id'],source_type=profile['source_type'],source_url=profile['source_url'],verified_on=e.get('verified_on') or profile['verified_on'],source_conditions=profile['conditions'])))
        def hard(key,expected):
            nonlocal preferences
            if expected in (None,'',[]):return
            is_hard=key in request['hard_filters']
            if key=='unit_requirements' and any(METRIC_REQUIREMENT.search(term) for term in expected):
                unknown.append(key);reason(key,'单位涉及的索引/指标当前关闭，不能通过PubMed或同名标签确认。','unknown');return
            e=field(key)
            if not e:
                if is_hard:unknown.append(key)
                reason(key,'硬条件缺少可用来源，待核实。' if is_hard else '软偏好缺少可用来源，不据此排除。','unknown' if is_hard else 'preference');return
            actual=e['value']
            if key=='oa':ok=actual==expected
            elif key=='fee':
                applicability=e.get('applicability') or {}
                has_conditions=bool(e.get('conditions') or profile['conditions'])
                explicit=bool(applicability.get('article_types')) or applicability.get('oa') is not None
                applicable=applicability.get('unconditional') is True or (explicit and (not applicability.get('article_types') or normalized(request['article_type']) in set(map(normalized,applicability['article_types']))) and (applicability.get('oa') is None or applicability['oa']==request['oa']))
                if has_conditions and not applicable:
                    if is_hard:unknown.append(key)
                    reason(key,'费用适用条件尚未确定，不能确认本次预算满足。','unknown' if is_hard else 'preference');return
                if actual['currency']!=expected['currency']:
                    if is_hard:unknown.append(key)
                    reason(key,'币种不同，未作汇率换算，预算待核实。','unknown' if is_hard else 'preference');return
                ok=actual['amount']<=expected['amount']
            else:ok=set(map(normalized,expected if isinstance(expected,list) else [expected])).issubset(set(map(normalized,actual)))
            if not is_hard:
                preferences+=int(ok);reason(key,'明确满足软偏好。' if ok else '软偏好不符，不据此排除。','preference');return
            reason(key,'明确满足硬条件。' if ok else '已知硬条件不符。','match' if ok else 'excluded')
            if not ok:fail.append(key)
        for key,expected in [('article_types',request['article_type']),('languages',request['language']),('oa',request['oa']),('fee',request['budget']),('disciplines',request['discipline']),('unit_requirements',request['unit_requirements'])]:hard(key,expected)
        terms=set(map(normalized,request['topics']+[request['domain']]))-{''}
        for key in ('topics','scope'):
            e=field(key)
            if e:
                matched=sorted(terms & set(map(normalized,e['value'])))
                if matched:matches+=len(matched);reason(key,'明确标签匹配：'+', '.join(matched),'match')
        if not matches:
            unknown.append('topic_scope');reason('topics','未找到主题/范围的明确标签匹配，需人工核实；未创造相关性依据。','unknown')
        target='excluded' if fail else 'pending_verification' if unknown else 'candidates'
        buckets[target].append(dict(profile=profile,reasons=reasons,matched_tag_count=matches,preference_match_count=preferences))
    for items in buckets.values():items.sort(key=lambda x:(-x['matched_tag_count'],-x['preference_match_count'],normalized(x['profile']['name']),x['profile']['id']))
    eligible=buckets['candidates'];buckets['candidate_total']=len(eligible);buckets['candidates']=eligible[:request['limit']]
    return buckets|dict(limitations=LIMITATIONS,real_model_calls=False,real_network_calls=False)
