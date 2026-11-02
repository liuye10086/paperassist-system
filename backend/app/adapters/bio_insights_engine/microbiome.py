"""Microbiome relative composition, fixed diversity and exchangeability-limited tests."""
from collections import defaultdict
import math, warnings
import numpy as np
from scipy.spatial.distance import pdist, squareform
from app.domain.bio_insights.microbiome_contracts import MicrobiomeConfig
from app.domain.bio_insights.microbiome_design import prepare_microbiome, validate_microbiome_design, key
from app.domain.comparison.kernel import compute_comparison, ComparisonError

ALPHA_FIELDS=['row_key','sample_id','shannon','simpson','observed_features','measurement_scale','depth_limitation']
TEST_FIELDS=['row_key','feature_id','contrast_id','numerator','denominator','observation_level','inference_scope','effect_name','effect_value','effect_unit','statistic','p_value','q_within_contrast','q_global_family','correction_family_id','n_numerator','n_denominator','n_pairs','tested','test_status','reason','provenance']
BETA_FIELDS=['row_key','method','purpose','status','reason','statistic','p_value','permutations','seed','minimum_p_resolution','sample_count','group_count','center','ordination_method']

def diversity(relative):
    p=np.asarray(relative,dtype=float)
    logs=np.zeros_like(p);np.log(p,out=logs,where=p>0)
    return dict(shannon=-np.sum(p*logs,axis=1),simpson=1-np.sum(p*p,axis=1),observed_features=np.sum(p>0,axis=1))

def distances_ordination(relative):
    p=np.asarray(relative,dtype=float);distance=squareform(pdist(p,metric='braycurtis'))
    n=len(p);centering=np.eye(n)-np.ones((n,n))/n
    gram=-.5*centering@(distance**2)@centering
    eigenvalues,vectors=np.linalg.eigh(gram);order=np.argsort(eigenvalues)[::-1];eigenvalues=eigenvalues[order];vectors=vectors[:,order]
    tol=max(1.,float(np.max(abs(eigenvalues))))*1e-12
    positive=eigenvalues>tol;coordinates=vectors[:,positive]*np.sqrt(eigenvalues[positive]);total=float(eigenvalues[positive].sum())
    for j in range(coordinates.shape[1]):
        if coordinates[np.argmax(abs(coordinates[:,j])),j]<0:coordinates[:,j]*=-1
    return distance,eigenvalues,coordinates,positive,total,bool(np.any(eigenvalues < -tol))

def beta_tests(distance,groups,*,permutations=999,seed=0):
    from skbio import DistanceMatrix
    from skbio.stats.distance import permanova, permdisp
    dm=DistanceMatrix(distance,ids=[str(i) for i in range(len(distance))]);answers=[]
    for name,function,purpose in [('PERMANOVA',permanova,'between_group_structure'),('PERMDISP',permdisp,'dispersion_diagnostic')]:
        kwargs=dict(permutations=permutations,seed=seed)
        if name=='PERMDISP':kwargs.update(test='median',method='eigh',dimensions=0)
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter('always');result=function(dm,groups,**kwargs)
        stat=float(result['test statistic']);p=float(result['p-value']) if permutations else None
        finite=math.isfinite(stat) and (p is None or math.isfinite(p))
        answers.append(dict(row_key=key(['beta',name]),method=name,purpose=purpose,status='tested' if finite else 'not_computable',reason=None if finite else 'degenerate_distance_or_dispersion',statistic=stat if finite else None,p_value=p if finite else None,permutations=permutations,seed=seed,minimum_p_resolution=1/(permutations+1) if permutations else None,sample_count=len(groups),group_count=len(set(groups)),center='median' if name=='PERMDISP' else None,ordination_method='eigh' if name=='PERMDISP' else None))
    return answers

def alpha_comparisons(config,data,alpha):
    by_id={r['sample_id']:r for r in alpha};meta=data['metadata'];rows=[]
    scope='sample_inference' if config.contrasts or config.beta_inference else 'sample_exploratory'
    family_id=key(dict(metrics=config.alpha_metrics,contrasts=config.family_contrast_ids,method=config.alpha_method))
    for contrast in config.contrasts:
        groups=[[s for s in data['included'] if meta[s][config.group_column]==g] for g in (contrast.numerator,contrast.denominator)]
        if config.design=='paired':
            mapped=[{meta[s][config.pair_column]:s for s in group} for group in groups];pairs=sorted(mapped[0]);groups=[[m[p] for p in pairs] for m in mapped]
        for metric in config.alpha_metrics:
            values=[[float(by_id[s][metric]) for s in group] for group in groups]
            row=dict(row_key=key(['alpha',metric,contrast.contrast_id]),feature_id=metric,contrast_id=contrast.contrast_id,numerator=contrast.numerator,denominator=contrast.denominator,observation_level='sample',inference_scope=scope,effect_name='frozen_kernel_estimate',effect_value=None,effect_unit='alpha diversity',statistic=None,p_value=None,q_within_contrast=None,q_global_family=None,correction_family_id=family_id,n_numerator=len(groups[0]),n_denominator=len(groups[1]),n_pairs=len(groups[0]) if config.design=='paired' else None,tested=True,test_status='not_computable',reason=None,provenance='system_computed')
            try:computed=compute_comparison(values,method=config.alpha_method)
            except ComparisonError as exc:
                if exc.code not in ('comparison_sample_size','comparison_constant','comparison_near_constant'):raise
                row['reason']=exc.code
            else:row.update(statistic=computed['statistic']['value'],p_value=computed['p_value']['value'],effect_value=computed['estimate']['value'],effect_name=computed['estimate'].get('name','frozen_kernel_estimate'),test_status='tested')
            rows.append(row)
    # One predeclared global BH family across every frozen metric x contrast.
    m=len(rows);ordered=sorted(range(m),key=lambda i:rows[i]['p_value'] if rows[i]['p_value'] is not None else 1.);last=1.
    for rank,index in reversed(list(enumerate(ordered,1))):
        p=rows[index]['p_value'];last=min(last,(p if p is not None else 1.)*m/rank)
        if p is not None:rows[index]['q_global_family']=last
    for cid in config.family_contrast_ids:
        subset=[r for r in rows if r['contrast_id']==cid];last=1.
        for rank,row in reversed(list(enumerate(sorted(subset,key=lambda r:r['p_value'] if r['p_value'] is not None else 1.),1))):
            last=min(last,(row['p_value'] if row['p_value'] is not None else 1.)*len(subset)/rank)
            if row['p_value'] is not None:row['q_within_contrast']=last
    return rows,dict(family_id=family_id,metrics=config.alpha_metrics,contrasts=config.family_contrast_ids,planned_tests=m,method='BH',missing='NA internally 1 then restored NA')

def run_microbiome(payload,writer,*,_validated_beta=None):
    config=MicrobiomeConfig.model_validate(payload['config']);preview=validate_microbiome_design(config,payload['sources'])
    if not preview.executable:raise ValueError('microbiome_design_blocked:'+str(preview.blocking_reasons))
    data=prepare_microbiome(config,payload['sources']);p=np.asarray(data['relative']);samples=data['included'];metrics=diversity(p)
    alpha=[dict(row_key=key(['alpha_sample',s]),sample_id=s,**{m:float(metrics[m][i]) if m!='observed_features' else int(metrics[m][i]) for m in metrics},measurement_scale='relative abundance',depth_limitation='Observed features: nonzero features in supplied table; depth/filter dependent, no original depth or absolute load inferred.') for i,s in enumerate(samples)]
    distance,eigenvalues,coordinates,positive,total,negative=distances_ordination(p)
    aggregate={}
    for j,path in enumerate(data['paths']):aggregate.setdefault(path,np.zeros(len(samples)));aggregate[path]+=p[:,j]
    conserved=np.sum(list(aggregate.values()),axis=0)
    if not np.allclose(conserved,p.sum(1),rtol=0,atol=1e-12):raise ValueError('microbiome_taxonomy_conservation_failed')
    ordered=sorted(aggregate,key=lambda path:(-float(aggregate[path].mean()),path));top=ordered[:config.top_n];other=[path for path in ordered if path not in top]
    composition=[]
    for i,s in enumerate(samples):
        for path in top:composition.append(dict(row_key=key(['composition',s,path]),sample_id=s,taxon_path=path,taxon_label=__import__('json').loads(path)[-1][1],relative_abundance=float(aggregate[path][i]),display_only=True))
        if other:composition.append(dict(row_key=key(['composition',s,'other']),sample_id=s,taxon_path='__other__',taxon_label='其他',relative_abundance=math.fsum(float(aggregate[path][i]) for path in other),display_only=True))
    comparisons,family=alpha_comparisons(config,data,alpha)
    if config.beta_inference:
        groups=[data['metadata'][s][config.group_column] for s in samples];beta=_validated_beta if _validated_beta is not None else beta_tests(distance,groups,permutations=config.permutations,seed=config.seed)
    else:beta=[dict(row_key=key(['beta',name]),method=name,purpose=purpose,status='not_applicable',reason='descriptive_or_nonexchangeable_design',statistic=None,p_value=None,permutations=0,seed=config.seed,minimum_p_resolution=None,sample_count=len(samples),group_count=None,center='median' if name=='PERMDISP' else None,ordination_method='eigh' if name=='PERMDISP' else None) for name,purpose in [('PERMANOVA','between_group_structure'),('PERMDISP','dispersion_diagnostic')]]
    warnings_zh=list(preview.warnings)
    if negative:warnings_zh.append('Bray–Curtis 非欧氏距离产生负特征值；完整特征值保留，PCoA 图仅用正轴，不能完整重构原距离。')
    methods=dict(name=config.recipe,config=config.model_dump(mode='json'),assay='microbiome',observation_level='sample',host_identity=config.host_identity,feature_identity=config.feature_identity,
        measurement_pipeline=config.measurement_pipeline,classification_database=config.classification_database,classification_version=config.classification_version,
        input_scale=config.abundance_scale,closure='Explicit p=x/sum; source unchanged; original sums and factors in microbiome_input_audit.',
        alpha_definitions=dict(shannon='-sum(p*ln(p)); natural logarithm',simpson='1-sum(p^2)',observed_features='nonzero features in supplied table; depth/filter dependent'),
        distance='Bray-Curtis on closed relative abundance for counts/fraction/percent alike',ordination='Classical PCoA via full symmetric eigh; full signed eigenvalues; coordinates only positive axes; proportions among positive eigenvalues.',
        missing='Entire sample excluded from composition, alpha, distance, ordination when any abundance missing or all-zero; no imputation; audit retains metadata and source masks.',
        taxonomy='Full hierarchical paths; missing ranks become Unclassified with raw taxonomy retained; per-sample conservation checked; Top N + Other is display only.',
        alpha_comparison=config.alpha_method,correction=family,beta=dict(design=config.design,enabled=config.beta_inference,permutations=config.permutations,seed=config.seed,permdisp_center='median',permdisp_method='eigh',permdisp_dimensions=0,p_value='(1 + exceedances)/(1 + permutations); separate structure and dispersion purposes; no automatic causal/group claim'),
        chinese_methods='输入保留原始计数或明确 fraction/percent 尺度及分类数据库版本。显式闭合 p=x/样本总和，逐样本记录原总和和因子；全零或任一缺测样本整体排除并审计。按完整分类路径聚合，保留未分类项并核对守恒；Top N 与其他仅改变图示。Shannon 使用自然对数，Simpson=1−Σp²，Observed features 为给定表中非零特征数，受深度和过滤限制。Bray–Curtis 固定相对丰度口径，PCoA 用完整 eigh；保留负特征值并提示。alpha 仅按冻结的独立两组或完整配对方法比较，预设指标×对比采用 BH。beta 仅对确认独立、可交换的单因素样本执行 PERMANOVA，并同时报告 median/eigh PERMDISP；分别解释组间结构与离散度，置换 P 值保留实际次数与有限分辨率。相对丰度不代表绝对菌量或原始测序深度。',
        limitations='No rarefaction, phylogenetic diversity/UniFrac, differential abundance, absolute load, multifactor or longitudinal permutation; exploratory software outputs are not biological validation.',warnings=warnings_zh,source_semantics=dict(processed_source_id=config.processed_source_id,raw_dataset_version_id=data['source'].get('metadata',{}).get('raw_dataset_version_id'),source_file_ids=data['source'].get('metadata',{}).get('source_file_ids',[]),raw_assay='microbiome',original_scale=data['source']['raw']['manifest']['scale']))
    writer.table('microbiome_input_audit',data['audit']);writer.table('microbiome_taxonomy',data['taxonomy'])
    writer.table('microbiome_relative_abundance',[dict(row_key=key(['abundance',fid]),feature_id=fid,**{s:float(p[i,j]) for i,s in enumerate(samples)}) for j,fid in enumerate(data['features'])])
    writer.table('microbiome_aggregated_abundance',[dict(row_key=key(['aggregate',path]),taxon_path=path,**{s:float(aggregate[path][i]) for i,s in enumerate(samples)}) for path in ordered])
    writer.table('microbiome_conservation',[dict(row_key=key(['conserve',s]),sample_id=s,before=float(p[i].sum()),after=float(conserved[i]),difference=float(conserved[i]-p[i].sum()),conserved=True) for i,s in enumerate(samples)])
    writer.table('microbiome_composition',composition);writer.table('microbiome_alpha',alpha,ALPHA_FIELDS)
    writer.table('microbiome_distance',[dict(row_key=key(['distance',s,other]),sample_a=s,sample_b=other,distance=float(distance[i,j])) for i,s in enumerate(samples) for j,other in enumerate(samples)])
    writer.table('microbiome_pcoa',[dict(row_key=key(['pcoa',s]),sample_id=s,**{f'PCoA{j+1}':float(coordinates[i,j]) for j in range(coordinates.shape[1])}) for i,s in enumerate(samples)])
    writer.table('microbiome_eigenvalues',[dict(row_key=key(['eigen',j]),axis=j+1,eigenvalue=float(v),positive_coordinate_axis=bool(positive[j]),explained_positive_ratio=float(v/total) if positive[j] and total else 0.,negative_warning=negative) for j,v in enumerate(eigenvalues)])
    writer.table('comparison_results',comparisons,TEST_FIELDS);writer.table('microbiome_beta',beta,BETA_FIELDS)
    writer.json('comparison_design',preview.model_dump(mode='json'));writer.json('correction_families',family)
    scope='sample_inference' if config.contrasts or config.beta_inference else 'sample_exploratory'
    return dict(summary=dict(row_count=len(comparisons),sample_count=len(data['samples']),included_samples=len(samples),excluded_samples=len(data['samples'])-len(samples),feature_count=len(data['features']),taxon_count=len(aggregate),negative_eigenvalues=negative,result_member_key='microbiome_alpha',tested_universe_complete=True,observation_level='sample'),methods=methods,inference_scope=scope,provenance='system_computed')
