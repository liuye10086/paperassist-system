"""Parent validation of complete integration tables, counts and NA boundaries."""
import csv,json,math
from pathlib import Path

def validate_integration(result,items,payload):
    def doc(key):return json.loads(Path(items[key]['path']).read_bytes())
    def table(key):
        if items[key]['format']!='tsv':raise ValueError('integration_table_format')
        with Path(items[key]['path']).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f,delimiter='\t'))
    def check(name,rows):
        actual=table(name)
        if len(actual)!=len(rows):raise ValueError('integration_table_count')
        def cell(v):return '' if v is None else json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v)
        for observed,row in zip(actual,rows):
            for k,value in observed.items():
                expected=row.get(k)
                equal=json.loads(value)==expected if isinstance(expected,(dict,list)) else value==cell(expected)
                if not equal:raise ValueError('integration_table_value:'+name+':'+k)
    config=payload['config']
    if payload['kind']=='bio_resource_import':
        resource=doc('resource')
        for k in ('kind','species_taxon_id','namespace','release','source','usage'):
            if resource[k]!=config[k]:raise ValueError('correspondence_config_changed')
        from app.domain.bio_insights.integration_contracts import normalize_correspondence
        rows=normalize_correspondence(config['kind'],[{k:v for k,v in r.items() if k not in ('row_number','row_key')} for r in resource['rows']])
        if len(rows)!=result['summary']['row_count']:raise ValueError('correspondence_count')
        check('correspondence_rows',resource['rows']);return
    data=doc('integration_data');summary=result['summary'];correlations=data['correlations']
    if result['methods']['recipe']!=config or not config['mapping_confirmed']:raise ValueError('integration_recipe_changed')
    if [r['pair_id'] for r in correlations]!=[p['pair_id'] for p in config['pairs']]:raise ValueError('integration_family_changed')
    if summary['pair_count']!=len(correlations) or summary['node_count']!=len(data['nodes']) or summary['edge_count']!=len(data['edges']):raise ValueError('integration_summary_changed')
    for row in correlations:
        used=[r for r in data['input_rows'] if r['pair_id']==row['pair_id'] and r['included']]
        if len(used)!=row['matched_observation_count'] or len(row['included'])!=len(used):raise ValueError('integration_matching_count')
        for field in ('left_observation_id','right_observation_id'):
            if len({r[field] for r in used})!=len(used):raise ValueError('integration_duplicate_unit')
        if row['coefficient'] is not None and (len(used)<3 or not -1.00000001<=row['coefficient']<=1.00000001):raise ValueError('integration_coefficient_invalid')
        if config['mode']=='descriptive' and (row['independent_n'] is not None or row['p_value'] is not None or row['q_value'] is not None or row['p_method'] is not None):raise ValueError('descriptive_inference_forbidden')
        if config['mode']=='inference' and row['independent_n']!=len(used):raise ValueError('integration_independent_n')
        if row['coefficient'] is None and not row['reason']:raise ValueError('uncalculable_reason_required')
    nodes={r['node_id'] for r in data['nodes']}
    if len(nodes)!=len(data['nodes']) or len({r['edge_id'] for r in data['edges']})!=len(data['edges']):raise ValueError('integration_graph_duplicates')
    for e in data['edges']:
        if e['source_node_id'] not in nodes or e['target_node_id'] not in nodes or e['edge_type']=='correlation' and e['directed']:raise ValueError('integration_graph_invalid')
    for name,key in [('integration_correlations','correlations'),('integration_concordance','concordances'),('integration_sample_audit','sample_audit'),('integration_object_audit','object_audit'),('integration_input_rows','input_rows'),('integration_nodes','nodes'),('integration_edges','edges')]:check(name,data[key])
