"""Names for the files people read; stored member keys remain stable."""
import re

FIGURE_NAMES = {
    'umap': 'UMAP 聚类图', 'annotation': 'UMAP 细胞注释图',
    'pca': 'PCA 分布图', 'pca_variance': 'PCA 解释方差图',
    'qc': '质量控制图', 'qc_distribution': '质量指标分布图', 'qc_violin': '质量指标小提琴图',
    'qc_scatter': '检测基因数与总计数散点图', 'qc_mitochondrial': '线粒体比例图',
    'qc_by_sample_id': '分样本质量概况', 'qc_by_batch': '分批次质量概况', 'qc_by_section': '分切片质量概况',
    'integration_covariates': '协变量校正前后对比图', 'integration_harmony': '批次整合前后对比图',
    'marker_dotplot': '标记基因气泡图', 'marker_heatmap': '标记基因热图',
    'spatial_cluster': '空间聚类图', 'spatial_gene': '空间基因表达图',
    'volcano': '差异表达火山图', 'ma': '表达量与差异散点图',
    'heatmap': '表达热图', 'gsea': '基因集富集图', 'enrichment': '功能富集图',
    'correlation_heatmap': '样本相关性热图', 'sample_distance': '样本距离热图',
    'boxplot': '箱线图', 'bar': '柱状图', 'scatter': '散点图',
    'bulk_volcano': '差异表达火山图', 'bulk_ma': '表达量与差异散点图', 'bulk_heatmap': '差异基因热图',
    'bulk_expression': '候选基因表达图', 'bulk_variable_heatmap': '高变基因热图', 'bulk_summary': '差异表达汇总图',
    'topic_slingshot': '单细胞轨迹图', 'topic_genie3': '基因调控网络图', 'topic_cellchat': '细胞通讯图',
    'sample_clustering': '样本聚类图', 'qc_missing': '样本缺失比例图', 'expression_distribution': '样本表达分布图',
    'sample_correlation_heatmap': '样本相关性热图', 'sample_distance_heatmap': '样本距离热图',
    'pca_scores': 'PCA 分布图', 'qc_expression': '样本表达五数摘要图',
}


def analysis_figure_name(key, fallback_kind=None):
    stem = key.removesuffix('_png')
    page = re.search(r'_page_(\d+)$', stem)
    if page:
        stem = stem[:page.start()]
    name = FIGURE_NAMES.get(stem) or FIGURE_NAMES.get(fallback_kind) or '分析图件'
    if stem.startswith('spatial_gene_') and re.fullmatch(r'[A-Za-z0-9.\-]+', stem[len('spatial_gene_'):]):
        name = f"{FIGURE_NAMES['spatial_gene']} - {stem[len('spatial_gene_'):]}"
    return f'{name} - 第 {int(page[1])} 张' if page else name


def single_cell_report_name(annotated=False):
    return '单细胞分析报告（含细胞注释）.docx' if annotated else '单细胞分析报告.docx'
