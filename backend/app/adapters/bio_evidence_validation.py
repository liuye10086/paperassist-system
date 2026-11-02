"""Parent validates complete deterministic matrix, identity and every exported row."""
import csv,json
from pathlib import Path
from app.adapters.bio_insights_engine.external_evidence import evidence_result

def validate_evidence(result,items,payload):
    expected=evidence_result(payload)
    if json.loads(Path(items['evidence_data']['path']).read_bytes())!=expected:raise ValueError('external_evidence_matrix_mismatch')
    for key,rows in [('candidate_results',expected['candidates']),('candidate_evidence',expected['matrix']),('evidence_nodes',expected['nodes']),('evidence_edges',expected['edges'])]:
        actual=list(csv.DictReader(Path(items[key]['path']).read_text(encoding='utf-8-sig').splitlines(),delimiter='\t'))
        if len(actual)!=len(rows):raise ValueError('external_evidence_table_row_count')
        fields=list(dict.fromkeys(k for r in rows for k in r))
        for row,want in zip(actual,rows):
            if set(row)!=set(fields):raise ValueError('external_evidence_table_fields')
            for k in fields:
                value=want.get(k);text=row[k]
                if isinstance(value,(dict,list)):
                    if json.loads(text)!=value:raise ValueError('external_evidence_nested_value')
                elif value is None:
                    if text!='':raise ValueError('external_evidence_unknown_changed')
                elif text!=str(value):raise ValueError('external_evidence_scalar_changed')
    if result['methods'].get('recipe')!=payload['config'] or result['methods'].get('upstream_analysis_recomputed') is not False:raise ValueError('external_evidence_methods')
    summary=result['summary']
    for k,v in dict(candidate_count=len(expected['candidates']),matrix_row_count=len(expected['matrix']),dependency_group_count=len(expected['dependency_groups']),independent_support_count=sum(r['independent_data_support'] for r in expected['matrix'])).items():
        if summary.get(k)!=v:raise ValueError('external_evidence_summary')
