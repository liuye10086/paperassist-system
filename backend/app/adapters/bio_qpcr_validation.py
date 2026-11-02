"""Parent-side reconciliation of every qPCR audit/quantity/test member."""
from .bio_quantitative_validation import _ContinuousReconciliationWriter

def validate_qpcr(result,items,payload):
    from .bio_insights_engine.qpcr import run_qpcr
    writer=_ContinuousReconciliationWriter(items)
    writer.numeric_fields=writer.numeric_fields|{'statistical_effect_value','ci_log2_low','ci_log2_high','fold_change','ci_fold_low','ci_fold_high'}
    expected=run_qpcr(payload,writer)
    for member in writer.artifacts:
        actual=items.get(member['key'])
        if actual is None:raise ValueError('qpcr_member_missing:'+member['key'])
        if member['key'] in writer.numeric_tables:
            if actual['format']!='tsv':raise ValueError('qpcr_table_format')
        elif any(actual[k]!=member[k] for k in ('format','size_bytes','sha256')):raise ValueError('qpcr_full_member_mismatch:'+member['key'])
    if expected['summary']!=result['summary'] or any(result['methods'].get(k)!=v for k,v in expected['methods'].items()):raise ValueError('qpcr_summary_or_methods_mismatch')
