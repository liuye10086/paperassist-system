"""Plot projection preserves the full fixed cross product and all source locators."""
import json
from pathlib import Path

def evidence_plot_data(source,config):
    data=json.loads(Path(source['members']['evidence_data']['path']).read_bytes())
    workflow={'fixed_axis_selection','candidate_input','external_statement_input','fixed_original_locator','saved_result_reference'}
    displayed=[r['feature_id'] for r in data['candidates'][:config.top_n]]
    excluded={'candidate:'+r['feature_id'] for r in data['candidates'][config.top_n:]}
    edges=[e for e in data['edges'] if e['source'] not in excluded and e['target'] not in excluded and ((e['relation'] in workflow) if config.figure_type=='evidence_flow' else (e['relation'] not in workflow))]
    ids={e[k] for e in edges for k in ('source','target')}
    nodes=[n for n in data['nodes'] if n['id'] in ids]
    return dict(display_nodes=nodes,display_edges=edges,figure_type=config.figure_type,source_id=source['source_id'],source_sha256=source['sha256'],seed=1729,analysis_recomputed=False,causal_edges=False,display_candidates=[r['feature_id'] for r in data['candidates'][:config.top_n]],**data)
