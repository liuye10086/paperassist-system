"""Prepare the three authorized source statements from retained originals only."""
import hashlib
import json
from pathlib import Path

ALIAS_LOCATOR = 'Par2'
ALIAS_QUOTE = 'HER2, also known as ERBB2'
TCGA_CONDITION = '作者预处理 breast.TCGA 训练样本；原分子亚型保留，精确采样部位与治疗条件未提供'


def prepared_records(materials):
    materials = Path(materials)
    manifest = json.loads((materials / 'download-manifest.json').read_bytes())
    originals = {row['filename']: row for row in manifest['files']}
    article_name = 'PMC7603305.fullText.xml'
    hpa_name = 'HPA_v24_ERBB2_tissue.html'
    for name in (article_name, hpa_name):
        if hashlib.sha256((materials / name).read_bytes()).hexdigest() != originals[name]['sha256']:
            raise ValueError('Authorized original SHA differs: ' + name)

    def xml(identifier, quote):
        return dict(kind='xml_id', value=identifier, quote=quote)

    conditions = [
        xml('Par16', 'from March 2015 to September 2019'),
        xml('Par19', 'Peripheral blood samples were collected before receiving trastuzumab therapy or pyrotinib therapy.'),
        xml('Par20', 'genomic DNA from lymphocytes was sequenced as the normal control sample.'),
        xml('Par21', 'A panel of 1021 genes was assayed in the present study'),
        xml('Par22', 'human genome assembly HG19'),
    ]
    common = dict(object_id='ERBB2', namespace='author_gene_symbol', species_taxon_id=9606,
        tissue='外周血血浆 ctDNA；配对外周淋巴细胞基因组DNA对照', cell_type=None,
        condition='转移性乳腺癌回顾队列；女性、两所中国医院、临床医生提出ctDNA检测',
        dose=None, time='2015-03至2019-09入组；原文称采样在曲妥珠单抗或吡咯替尼治疗前',
        measurement_scale='1021基因panel测序检测的患者比例；不是表达量或工程突变效应',
        reference_version='HG19；具体蛋白参考accession未知', disease_id='metastatic breast cancer',
        disease_scope='direct', study_id='Yi2020_PMC7603305', cohort_id='Yi2020_retrospective_1184',
        dependency_group='Yi2020_PMC7603305', shared_dataset_ids=['Yi2020_retrospective_1184'],
        shared_donor_ids=None, obtained_date=originals[article_name]['time_utc'][:10],
        license='Yi等，npj Breast Cancer (2020)，DOI 10.1038/s41523-020-00201-9，CC BY 4.0；保留原作者署名及第三方材料说明。',
        effect_direction=None, result_status='reported', human_review_status='not_reviewed',
        independence_basis='与TCGA供体重叠未知；本轮未取得患者级数据、未执行独立分析run。两条文献记录属于同一研究及同一回顾队列。')
    disease = dict(common, evidence_type='disease_literature', variant_id=None,
        statement='原文回顾队列1184名转移性乳腺癌患者中105名检测到HER2突变（8.9%）。这是原文患者比例，未由本系统重算原始测序或验证疾病因果。',
        locators=[xml(ALIAS_LOCATOR, ALIAS_QUOTE),
            xml('Par5', 'In total, 1184 metastatic breast cancer patients were enrolled in the retrospective cohort.'),
            xml('Par5', 'HER2 mutations were detected in 8.9% (105/1184) of patients.'), *conditions])
    mutation = dict(common, evidence_type='mutation_literature', variant_id='p.V777L',
        statement='原文在105名HER2突变阳性患者中报告13名p.V777L（12.4%）。这是临床ctDNA检出记录，不是KO或工程突变实验；原作者的驱动分类也不是本系统致病性判定。',
        locators=[xml('Par6', 'HER2 p.V777L, p.L755S and p.D769Y were the top three mutations by frequency and were detected in 13 (12.4%), 10 (9.5%) and 10 (9.5%) patients, respectively.'), *conditions])

    hpa = json.loads((materials / 'derived/HPA-own-protein-evidence.json').read_bytes())
    html = (materials / hpa_name).read_text(encoding='utf-8')
    label = html.index('"label":"Breast"', hpa['html_character_offset'])
    start = html.rfind('{', hpa['html_character_offset'], label)
    source_row, length = json.JSONDecoder().raw_decode(html[start:])
    if source_row != hpa['source_row']:
        raise ValueError('HPA literal Breast record differs from retained parsed record')
    literal = html[start:start + length]
    atlas = dict(evidence_type='expression_atlas', object_id='ERBB2', namespace='author_gene_symbol',
        species_taxon_id=9606, tissue='正常乳腺组织', cell_type='Adipocytes / Glandular cells / Myoepithelial cells',
        condition='正常乳腺的knowledge-based IHC类别汇总；无肿瘤对照', dose=None, time=None,
        measurement_scale='IHC有序类别；原始图谱score=2.000不是连续蛋白丰度', reference_version='HPA24.1',
        variant_id=None, disease_id=None, disease_scope='unknown', study_id='HPA_v24.1', cohort_id=None,
        dependency_group='HPA_v24.1_own_IHC', shared_dataset_ids=['HPA_v24.1_own_IHC'], shared_donor_ids=None,
        obtained_date=originals[hpa_name]['time_utc'][:10],
        license='Human Protein Atlas v24.1 自有IHC数据，CC BY 4.0；本条不纳入GTEx/FANTOM5、RNA共识、外部注释或图像。',
        locators=[dict(kind='text', value=literal, quote=literal)],
        statement='HPA v24.1自有IHC乳腺汇总：脂肪细胞Not detected，腺体和肌上皮细胞Medium。正常组织类别不是癌症差异或阴性机制证据；Enhanced是原图谱注释，不代表本系统独立验证。',
        effect_direction=None, result_status='reported', human_review_status='not_reviewed',
        independence_basis='原页未给本条可核供体身份；与TCGA及论文重叠未知，未执行独立验证run。')
    return [
        dict(label='erbb2-disease', filename=article_name, title='ERBB2 疾病文献：原队列患者比例', typed_evidence=disease),
        dict(label='erbb2-v777l', filename=article_name, title='ERBB2 p.V777L：原文临床检出记录', typed_evidence=mutation),
        dict(label='erbb2-hpa', filename=hpa_name, title='ERBB2 正常乳腺：HPA自有IHC类别', typed_evidence=atlas),
    ]
