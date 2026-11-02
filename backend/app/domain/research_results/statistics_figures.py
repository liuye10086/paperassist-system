"""Local publication plots from saved statistics or frozen included rows; never refit."""
import io

def render_statistics_figure(source,*,language=None):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    result=source.content['result'];stats=result.get('statistics',{});selection=result['selection'];method=selection.get('method','descriptive_statistics')
    en=(language if language in ('zh-CN','en') else source.content.get('output_language'))!='zh-CN'
    labels={'time':('Prespecified time','预设时点'),'unknown':('unit unknown','单位未知'),'mean':('Mean','均值'),'fpr':('False positive rate','假阳性率'),'tpr':('True positive rate','真阳性率'),'survival':('Survival probability','生存概率'),'coef':('Coefficient (95% CI)','系数（95%置信区间）'),'or':('Odds ratio (95% CI)','比值比（95%置信区间）'),'n':('saved n','保存的实际 n'),'pairs':('complete pairs n','完整对 n'),'rows':('included source rows','纳入来源行')}
    label=lambda key:labels[key][0 if en else 1]
    fig=Figure(figsize=(8,5),dpi=150);FigureCanvasAgg(fig);ax=fig.subplots();roles=selection.get('data_roles',{});records=source.content.get('role_records',[])
    # Explicit time order; retain every included participant, never draw excluded rows.
    if roles.get('structure') in ('paired_long','repeated_long') and records:
        from app.domain.statistics_roles import StatisticsDataRoles,validate_role_records
        validate_role_records(records,StatisticsDataRoles.model_validate(roles))
        audit=source.content.get('frozen_role_audit',result.get('row_audit',{}));included=set(sum(audit.get('group_rows',[]),[])) if audit.get('group_rows') else set(audit.get('included_rows',[]))
        if not included and selection.get('task_type')!='descriptive_boxplot':raise ValueError('Trajectory requires frozen inclusion audit')
        order=roles.get('time_order',[]);groups={}
        for row in records:
            if row['row'] not in included:continue
            if row.get(roles['endpoint']) is None:continue
            groups.setdefault((type(row[roles['individual_id']]).__name__,str(row[roles['individual_id']])),[]).append(row)
        if not order:order=list(dict.fromkeys(str(r[roles['time']]) for r in records))
        for rows in groups.values():
            points=sorted((order.index(str(r[roles['time']])),r[roles['endpoint']]) for r in rows)
            ax.plot([p[0] for p in points],[p[1] for p in points],marker='o',alpha=.45,lw=1)
        ax.set_xticks(range(len(order)),order);ax.set_xlabel(label('time'));ax.set_ylabel(selection.get('unit') or label('unknown'))
    elif selection.get('design')=='paired' and source.content.get('frozen_plot'):
        groups=source.content['frozen_plot']['groups']
        for a,b in zip(*groups):ax.plot([0,1],[a,b],marker='o',alpha=.5,lw=1)
        ax.set_xticks([0,1],[g['label'] for g in result['groups']]);ax.set_ylabel(selection.get('unit') or label('unknown'))
    elif method=='roc_auc':
        pts=stats['points'];ax.plot([p['fpr'] for p in pts],[p['tpr'] for p in pts]);ax.plot([0,1],[0,1],ls='--',color='gray');ax.set(xlabel=label('fpr'),ylabel=label('tpr'),xlim=(0,1),ylim=(0,1))
    elif method=='kaplan_meier':
        for group in stats['groups']:
            pts=group['points'];ax.step([0]+[p['time'] for p in pts],[1]+[p['survival'] for p in pts],where='post',label=f"{group['label']} (n={group['n']})")
        ax.set(xlabel=selection.get('time_unit') or label('time'),ylabel=label('survival'),ylim=(0,1.05));ax.legend()
    elif method in ('ols','logistic'):
        points=stats['coefficients'];odds=method=='logistic'
        for index,p in enumerate(points):
            value=p['or_value'] if odds else p['beta'];low=p['or_ci_low'] if odds else p['ci_low'];high=p['or_ci_high'] if odds else p['ci_high']
            ax.errorbar(value,index,xerr=[[value-low],[high-value]],fmt='o',color='#2077b4',capsize=4)
        ax.set_yticks(range(len(points)),[p['term'] for p in points]);ax.axvline(1 if odds else 0,color='gray',ls='--');ax.set_xlabel(label('or') if odds else label('coef'))
        if odds:ax.set_xscale('log')
    elif result.get('groups') or result.get('overall'):
        groups=result.get('groups') or [dict(label='Overall',statistics=result['overall'])]
        values=[g['statistics']['mean'] for g in groups];ax.bar(range(len(groups)),values,color='#347c9d');ax.set_xticks(range(len(groups)),[f"{g['label']} (n={g['statistics']['n']})" for g in groups]);ax.set_ylabel(label('mean')+' / '+(selection.get('unit') or label('unknown')))
    elif method in ('pearson','spearman'):
        if stats.get('matrix') is not None:
            image=ax.imshow(stats['matrix'],vmin=-1,vmax=1,cmap='coolwarm');fig.colorbar(image,ax=ax,label='Saved correlation');ax.set_xticks(range(len(selection['columns'])),selection['columns']);ax.set_yticks(range(len(selection['columns'])),selection['columns'])
        elif source.content.get('frozen_plot'):
            rows=source.content['frozen_plot']['rows'];ax.scatter([r[0] for r in rows],[r[1] for r in rows],s=15,alpha=.7);ax.set_xlabel(selection['columns'][0]);ax.set_ylabel(selection['columns'][1])
        else:
            ax.bar([method],[stats['coefficient']],color='#347c9d');ax.set_ylim(-1,1);ax.set_ylabel('Saved correlation coefficient')
    else:raise ValueError('No plottable saved statistics')
    n=stats.get('n',result.get('check',{}).get('valid_count','unknown'))
    if selection.get('design')=='paired':
        pairs=stats['sample_sizes'][0];rows=len(result.get('row_audit',{}).get('included_rows',[]))
        ax.set_title(f"{method} | {label('pairs')}={pairs}; {label('rows')}={rows}")
    else:ax.set_title(f"{method} | {label('n')}={n}")
    ax.grid(axis='y',alpha=.15)
    if not en:
        from pathlib import Path
        from matplotlib.font_manager import FontProperties
        from matplotlib.text import Text
        candidates=('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc','C:/Windows/Fonts/msyh.ttc','C:/Windows/Fonts/simhei.ttf')
        font=next((p for p in candidates if Path(p).is_file()),None)
        if font is None:raise ValueError('Chinese statistics figure requires an installed CJK font')
        prop=FontProperties(fname=font)
        for text in fig.findobj(Text):text.set_fontproperties(prop)
    fig.tight_layout()
    out=io.BytesIO();fig.savefig(out,format='png',metadata={'Software':'PaperAssist saved-statistics projection v1'});return out.getvalue()
