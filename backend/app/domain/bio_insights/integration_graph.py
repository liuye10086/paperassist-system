"""Pure saved graph projection, usable by parent without scientific imports."""
import hashlib,json,math,random
from pathlib import Path

def integration_plot_data(source,config):
    if source['metadata'].get('kind')!='integration':raise ValueError('integration_figure_requires_saved_integration')
    member=source['members']['integration_data'];path=Path(member['path']);raw=path.read_bytes()
    if len(raw)!=member['size_bytes'] or hashlib.sha256(raw).hexdigest()!=member['sha256']:raise ValueError('integration_graph_sha_changed')
    data=json.loads(raw);flow=config.figure_type=='integration_flow'
    edges=data['edges'];nodes=data['nodes'];selected=sorted(nodes,key=lambda n:n['node_id'])[:min(200,config.top_n)]
    ids={n['node_id'] for n in selected};visible=[e for e in edges if e['source_node_id'] in ids and e['target_node_id'] in ids and (not flow or e['edge_type'] in ('processing_lineage','contains','integration_input','computed_relation'))][:1000]
    positions={};order=[n['node_id'] for n in selected];random.Random(1729).shuffle(order)
    if flow:
        levels={'canonical_lineage':0,'source':1,'processing_operation':2,'processing_output':3}
        for level in (0,1,2,3):
            group=[n for n in selected if levels.get(n['node_type'],2)==level]
            for i,n in enumerate(group):positions[n['node_id']]=[float(level),float(i-(len(group)-1)/2)]
    else:
        for i,node in enumerate(order):positions[node]=[math.cos(2*math.pi*i/max(1,len(order))),math.sin(2*math.pi*i/max(1,len(order)))]
    return dict(nodes=nodes,edges=edges,display_nodes=[{**n,'x':positions[n['node_id']][0],'y':positions[n['node_id']][1]} for n in selected],display_edge_ids=[e['edge_id'] for e in visible],display_filter={'max_nodes':min(200,config.top_n),'max_edges':1000,'edge_types':['processing_lineage','contains','integration_input','computed_relation'] if flow else 'all','node_order':'stable_node_id'},layout_seed=1729,analysis_recomputed=False,correlation_is_causation=False,flow_is_actual_lineage=True)
