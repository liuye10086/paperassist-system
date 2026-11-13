import {apiError} from '../../shared/i18n'

const figureNames:Record<string,string>={
 umap:'UMAP 聚类图',annotation:'UMAP 细胞注释图',pca:'PCA 分布图',pca_variance:'PCA 解释方差图',
 qc:'质量控制图',qc_distribution:'质量指标分布图',qc_violin:'质量指标小提琴图',
 qc_scatter:'检测基因数与总计数散点图',qc_mitochondrial:'线粒体比例图',
 qc_by_sample_id:'分样本质量概况',qc_by_section:'分切片质量概况',qc_by_batch:'分批次质量概况',
 integration_covariates:'协变量校正前后对比图',integration_harmony:'批次整合前后对比图',
 marker_dotplot:'标记基因气泡图',marker_heatmap:'标记基因热图',
 spatial_cluster:'空间聚类图',spatial_gene:'空间基因表达图',
 volcano:'差异表达火山图',ma:'表达量与差异散点图',heatmap:'表达热图',gsea:'基因集富集图',
 enrichment:'功能富集图',correlation_heatmap:'样本相关性热图',sample_correlation_heatmap:'样本相关性热图',sample_distance:'样本距离热图',
 boxplot:'箱线图',bar:'柱状图',scatter:'散点图',
 bulk_volcano:'差异表达火山图',bulk_ma:'表达量与差异散点图',bulk_heatmap:'差异基因热图',bulk_expression:'候选基因表达图',
 bulk_variable_heatmap:'高变基因热图',bulk_summary:'差异表达汇总图',
 topic_slingshot:'单细胞轨迹图',topic_genie3:'基因调控网络图',topic_cellchat:'细胞通讯图',
 sample_clustering:'样本聚类图',qc_missing:'样本缺失比例图',expression_distribution:'样本表达分布图',
 pca_scores:'PCA 分布图',qc_expression:'样本表达五数摘要图',sample_distance_heatmap:'样本距离热图',
}

export const resultTableLabels:Record<string,string>={
 mapping_strata:'观测分层汇总',observations:'观测明细',features:'特征明细',embedding:'降维坐标',hvg:'高变基因',
 cluster_summary:'聚类汇总',markers:'全部标记基因',markers_top:'各聚类主要标记基因',
 library_qc:'分文库质控统计',library_algorithms:'分文库质量模型结果',
 integration_diagnostics:'整合前后诊断',integration_design:'批次与研究组设计',integration_coordinates:'处理前后坐标',
 pca:'PCA 坐标',umap:'UMAP 坐标',pca_variance:'PCA 解释方差',cell_labels:'细胞注释',
 sample_qc:'样本质控',feature_qc:'特征质控',sample_distance:'样本距离矩阵',correlation:'样本相关性矩阵',
 cell_sample_donor:'细胞、样本与供体汇总',decontx:'环境 RNA 校正结果',
 sample_correlation:'样本相关性矩阵',candidate_results:'全部候选基因',bulk_candidate_top:'主要候选基因',
 enrichment_results:'功能富集结果',gsea_curves:'基因集富集曲线数据',comparison_results:'差异比较结果',
 expression_distribution:'样本表达分布',figure_data:'绘图数据',normalization_factors:'标准化系数',
 tool_log:'运行日志',library_qc_table:'分文库质控统计',qc_cells:'逐细胞质控结果',
 pca_loadings:'PCA 特征载荷',pca_variance_ratio:'PCA 方差解释比例',pca_feature_raw_indices:'PCA 特征原始位置',
}

type Translate=(label:string, params?:Record<string,string|number>)=>string
export const colorGroupNames:Record<string,string>={cluster:'按聚类',sample_id:'按样本',section:'按切片',batch:'按批次'}
export const paletteNames:Record<string,string>={viridis:'蓝绿渐变',magma:'紫橙渐变',tab20:'分类配色'}
export const layerNames:Record<string,string>={
 counts:'原始计数',normalized:'标准化表达',log1p:'对数转换表达',decontx_counts:'环境 RNA 校正计数',
 raw:'原始数据',filtered:'过滤后数据',analysis:'分析用数据',display:'显示用数据',
 raw_counts:'原始计数',filtered_counts:'过滤后计数',normalized_counts:'标准化计数',vst:'VST',
}

export function figureName(key:string,t:Translate,kind?:string){
 const match=key.replace(/_png$/,'').match(/^(.+?)(?:_page_(\d+))?$/)
 const stem=match?.[1]??key
 const gene=stem.match(/^spatial_gene_([A-Za-z0-9.\-]+)$/)?.[1]
 const name=t(figureNames[stem]??(gene?figureNames.spatial_gene:figureNames[kind??''])??'分析图件')
 return [name,gene,match?.[2]&&t('第 {number} 张',{number:Number(match[2])})].filter(Boolean).join(' - ')
}

export function figureConfigName(config:{kind:string;panel?:string;color_by?:string;title?:string},t:Translate){
 if(config.title&&/^marker_(?:dotplot|heatmap)_page_\d+$/.test(config.title))return figureName(config.title,t)
 const key=config.kind==='pca'&&config.panel==='variance'?'pca_variance':config.kind
 const panel=config.panel??''
 const qcKey=panel in colorGroupNames?`qc_by_${panel}`:`qc_${panel}`
 const name=figureName(config.kind==='qc'&&qcKey in figureNames?qcKey:key,t)
 const grouped=['pca','umap'].includes(key)&&config.color_by&&config.color_by!=='cluster'&&colorGroupNames[config.color_by]
 return grouped?`${name} · ${t(grouped)}`:name
}

export function resultFileName(member:{key:string;format:string;role?:string},t:Translate,kind?:string){
 const {key,format}=member
 const label=format==='png'?figureName(key,t,kind)
  :t(resultTableLabels[key]??({h5ad:'处理后的表达矩阵',json:'分析记录',tsv:'分析结果表',csv:'分析结果表',xlsx:'分析结果表',docx:'分析报告',zip:'分析成果包'}[format]??'分析成果'))
 return `${label}.${format.toLowerCase()}`
}

export const isTechnicalResultFile=(key:string,format?:string)=>
 /(?:^|_)(?:tool_versions|manifest|provenance|checksums|hashes)(?:_|$)/i.test(key)||format==='json'
 ||format==='npy'&&(/^(?:connectivities|counts|distances|log1p|normalized)_(?:data|indices|indptr)$/.test(key)||/^(?:feature|hvg|observation)_mask$/.test(key))

const blockerLabels:Record<string,string>={
 environment_unavailable:'生信计算环境尚未就绪；任务不能开始正式计算。',
 independent_biological_units_not_confirmed:'尚未确认独立的生物学重复。',
 single_cell_observations_limit:'细胞数超过当前计算上限。',
 single_cell_features_limit:'基因数超过当前计算上限。',
 single_cell_nnz_limit:'非零表达值数超过当前计算上限。',
 single_cell_dense_hvg_limit:'高变基因计算所需资源超过上限，请减少高变基因数或使用较小的矩阵。',
 single_cell_matrix_dimensions_unknown:'矩阵规模尚未确认，无法估算所需资源。',
}
export const bioConditionLabel=(code:string)=>blockerLabels[code]??apiError({code},'请核对分析条件和输入资料。')
