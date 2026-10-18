"""Readable figure metadata shared by local report rendering."""


def description_lines(presentation,en):
    for key,label in [('x','Horizontal axis' if en else '横轴'),('y','Vertical axis' if en else '纵轴')]:
        axis=presentation['axes'][key]
        yield label+': '+(axis['label'] or ('Not applicable' if en else '不适用'))
    legend=presentation['legend']
    if legend['entries']:
        yield ('Legend' if en else '图例')+': '+legend['title']+' — '+'; '.join(e['label']+' ('+e['color']+')' for e in legend['entries'])
    scale=presentation['color_scale']
    if scale:
        yield ('Color scale' if en else '色标')+': '+scale['label']+'; '+str(scale['min'])+' – '+str(scale['max'])+'; '+('center' if en else '中心')+' '+str(scale['center'])+'; '+('ticks' if en else '刻度')+' '+', '.join(map(str,scale['ticks']))+'; '+('palette' if en else '配色')+' '+' → '.join(scale['palette'])
    if presentation['abbreviations']:
        yield ('Abbreviations' if en else '缩写')+': '+'; '.join(x['term']+' — '+x['definition'] for x in presentation['abbreviations'])
    # v3's full caption, printed by the caller, already includes these notes.
    if presentation['schema_version'] == 1:
        for note in presentation['statistical_notes']:yield ('Statistical note: ' if en else '统计说明：')+note
