"""Bounded modern prose guards; statistics use locally typed fact spans."""
import re

NUMBER_WORDS=re.compile(r'\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|trillion|dozen|half|halves|quarter|quarters|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|thirtieth|fortieth|fiftieth|sixtieth|seventieth|eightieth|ninetieth|hundredth|thousandth|millionth)\b',re.I)
LARGE_NUMBER_WORDS=re.compile(r'\b(?:(?:hundred|thousand|[a-z]+illion|dozen|score)(?:s|th)?|zeroth)\b',re.I)
QUANTITY_PLURALS=re.compile(r'\b(?:ones|twos|threes|fours|fives|sixes|sevens|eights|nines|tens|elevens|twelves|thirteens|fourteens|fifteens|sixteens|seventeens|eighteens|nineteens|teens|twenties|thirties|forties|fifties|sixties|seventies|eighties|nineties)\b',re.I)
# Statistical metric names belong inside a typed placeholder, never an AI-authored assertion.
METRIC_PROSE=re.compile(r'\b(?:coefficients?|p[ -]?values?|sample[ -]?size|effective[ -]?n|common[ -]?n|confidence[ -]?intervals?|mean|median|quartiles?|standard[ -]?deviation|interquartile[ -]?range|outlier[ -]?count|whiskers?|r|rho|test[ -]?statistic|effect[ -]?size|degrees?[ -]of[ -]freedom|rank[ -]?biserial|adjusted[ -]?p)\b|'
    r'\bsample\b.{0,24}\b(?:contains?|includes?|consists?|comprises?)\b|'
    r'(?:相关)?系数|样本量|样本数|有效\s*n|共同\s*n|置信区间|均值|中位数|标准差|四分位|须端|离群.{0,4}(?:数|数量)|[pP]\s*值|检验统计量|效应量|自由度|秩双列',re.I)
SENSITIVE=re.compile(r'\b(?:significan\w*|caus\w*|prov(?:e|es|ed|en|ing))\b',re.I)
CLAUSE_SPLIT=re.compile(r'[.;!?\n,]|\b(?:and|or|nor|but|however|yet|while|although|whereas|despite|therefore|nevertheless)\b',re.I)
NEGATED_PREDICATE=re.compile(r'\b(?:cannot|can not|does not|do not|must not|should not|unable to|not enough to)\s+'
    r'(?:establish|imply|demonstrate|prove|support|show|justify|infer|claim|confirm|indicate|be|determine)\s+'
    r'(?:(?:a|any|the|clear|statistical|statistically)\s+){0,3}(?:caus\w*|significan\w*)$',re.I)
ZH_SENSITIVE=re.compile(r'显著|统计学意义|因果|疗效')
ZH_CLAUSE_SPLIT=re.compile(r'[，,。；;！？!?\n]|但是|然而|但|并且|而且|以及|同时|且|却|仍|或者|或')
ZH_NEGATED_PREDICATE=re.compile(r'(?:不能|无法|不足以|不应|不宜|尚不能)(?:据此)?'
    r'(?:说明|证明|认定|判断|推断|确定|声称|表明)'
    r'(?:(?:相关性?|关联|关系|结果|统计学?|的|任何|是否)){0,4}(?:显著|统计学意义|因果|疗效)$|'
    r'(?:未|没有|不)(?:进行|开展|计算|提供|报告)(?:统计学?)?(?:显著|统计学意义|因果|疗效)$|'
    r'(?:不等于|不代表|不意味着)(?:显著|统计学意义|因果|疗效)$')


def unsafe_modern_prose(prose):
    if re.search(r'\b(?:auc|odds[ -]?ratio|hazard[ -]?ratio|survival[ -]?probability|sensitivity|specificity|r[ -]?squared|log[ -]?likelihood)\b|优势比|风险比|生存概率|敏感度|特异度|拟合优度',prose,re.I): return True
    if NUMBER_WORDS.search(prose) or LARGE_NUMBER_WORDS.search(prose) or QUANTITY_PLURALS.search(prose) or METRIC_PROSE.search(prose): return True
    for match in ZH_SENSITIVE.finditer(prose):
        clause=ZH_CLAUSE_SPLIT.split(prose[:match.start()])[-1]
        if not ZH_NEGATED_PREDICATE.search(clause+match.group()): return True
    for match in SENSITIVE.finditer(prose):
        clause=CLAUSE_SPLIT.split(prose[:match.start()])[-1]
        # Bind the negation to this predicate; a preceding conjunct cannot confer it.
        if match.group().lower().startswith('prov') and re.search(r'\b(?:cannot|can not|does not|do not|must not|should not|unable to)\s+$',clause,re.I):
            continue
        if not NEGATED_PREDICATE.search(clause+match.group()): return True
    return False


def fact_span(key, fact):
    """The metric label and value are one program-owned statistical span."""
    typed=(type(fact['raw']) in (int,float) or key.startswith('matrix.')
           or key.startswith(('comparison.','pairwise.','modeling.'))
           or key in ('correlation.coefficient','correlation.n','correlation.p_value','correlation.confidence_interval'))
    return fact['label']+': '+fact['value'] if typed else fact['value']
