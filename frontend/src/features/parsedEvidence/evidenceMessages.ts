export const evidenceMessages:Record<string,string>={
 '已保存的文档结构':'Saved document structure','未记录物理页范围':'Physical-page scope not recorded',
 '已保存的解析警告':'Saved parser warnings','文档范围警告':'Document-level warning','物理页范围警告':'Physical-page warning',
 '记录数量：{count}':'Recorded count: {count}','解析器警告':'Parser warning',
 '来源行 {row}':'Source row {row}',
 '下载词法来源原始版本':'Download the raw parent for lexical evidence','原始版本读取值':'Value read from the raw version',
 '解析内容与来源':'Parsed content and sources', '正在读取解析证据……':'Loading parsed evidence…',
 '解析证据读取失败，请重试。':'Could not read parsed evidence. Please try again.', '重新读取解析证据':'Reload parsed evidence',
 '存储数量不是研究样本量。':'Stored counts are not the research sample size.', '解析范围':'Evidence scope',
 '解析证据第 {page} 页 · 本页 {returned} 条 · 共 {total} 条':'Evidence page {page} · {returned} items on this page · {total} total items',
 '上一页证据':'Previous evidence page', '下一页证据':'Next evidence page', '核对原件':'Check original file',
 '下载证据对象':'Download evidence object','读取类型与原值':'Read type and original value','XML 词法原值':'XML lexical value',
 '未提供词法原值':'Lexical value not provided','单位状态':'Unit status','单位已确认':'Unit confirmed',
 '说明关联候选':'Caption association candidate','关联依据':'Association basis','说明来源':'Caption source','目标来源':'Target source',
 '同容器相邻内容，仅为候选':'Adjacent in the same container; candidate only','同页近邻位置，仅为候选':'Nearby geometry on the same page; candidate only',
 '图片对象':'Image object','表格尺寸：{rows} 行 · {columns} 列':'Table dimensions: {rows} rows · {columns} columns',
 '证据类型：text':'Text','证据类型：table':'Table','证据类型：cell':'Cell','证据类型：field':'Field','证据类型：row':'Row','证据类型：image':'Image',
 '存储计数：paragraphs':'Stored paragraphs','存储计数：tables':'Stored tables','存储计数：cells':'Stored cells',
 '存储计数：images':'Stored image objects','存储计数：pages':'Stored pages','存储计数：text_blocks':'Stored text blocks',
 '存储计数：pages_without_text':'Pages without text','存储计数：embedded_images':'Embedded image locations',
 '存储计数：rows':'Stored range rows','存储计数：fields':'Stored fields',
}
const displayEntries:Record<string,[string,string]>={
 paragraphs:['存储段落数','Stored paragraphs'],tables:['存储表格数','Stored tables'],cells:['存储单元格数','Stored cells'],
 images:['存储图片对象数','Stored image objects'],pages:['存储页数','Stored pages'],text_blocks:['存储文本块数','Stored text blocks'],
 pages_without_text:['无文字页数','Pages without text'],embedded_images:['内嵌图片位置数','Embedded image locations'],
 rows:['存储范围行数','Stored range rows'],fields:['存储字段数','Stored fields'],
 text:['文本','Text'],table:['表格','Table'],cell:['单元格','Cell'],field:['字段','Field'],row:['数据行','Row'],image:['图片','Image'],
 number:['数值','Number'],boolean:['布尔值','Boolean'],blank:['空值','Blank'],date:['日期','Date'],datetime:['日期时间','Date and time'],time:['时间','Time'],duration:['时长','Duration'],formula:['公式','Formula'],error:['错误值','Error value'],
}
export const evidenceLabels:Record<string,string>={}
for(const [code,[zh,en]] of Object.entries(displayEntries)){evidenceLabels[code]=zh;evidenceMessages[zh]=en}
const warningEntries:Record<string,[string,string]>={
 stored_counts_not_research_n:['存储数量不是研究样本量。','Stored counts are not the research sample size.'],
 image_science_not_extracted:['未从图片推断科学数值或方法。','No scientific values or methods were inferred from the image.'],
 image_pixels_not_saved:['只提供内嵌图片位置，像素请核对原件。','Only embedded image locations are available. Check pixels in the original file.'],
 vector_figures_not_extracted:['未将矢量图识别为图片对象。','Vector figures were not extracted as image objects.'],
 legacy_pdf_images_not_extracted:['旧版 PDF 解析器未提取图片位置。','This legacy PDF parser did not extract image locations.'],
 caption_unlinked:['识别到明确说明文字，未指定关联目标。','Explicit caption text; no target has been assigned.'],
 caption_association_candidate:['说明已候选关联，尚未人工确认。','The caption has a candidate association, awaiting human confirmation.'],
 caption_ambiguous:['附近有多个说明或目标，未指定关联。','Multiple nearby captions or targets; no association was assigned.'],
 caption_missing:['未找到无歧义的邻近说明。','No unambiguous nearby caption was found.'],
 ocr_unreviewed:['原始 OCR 候选，尚未核对。','Original OCR candidate; unreviewed.'],
 ocr_review_not_projected:['此视图仅显示原始 OCR；核对决定请查看 OCR 核对面板。','This view shows original OCR only. Review decisions are available in the OCR review view.'],
 reading_order_candidate:['几何阅读顺序仅为候选，请核对原件。','Geometric reading order is a candidate; check the original.'],
 table_candidate:['有边框表格结构仅为候选，请核对原件。','Ruled table structure is a candidate; check the original.'],
 unstored_cells_not_materialized:['未存储的单元格不展开；不存在不等同于已存储空值。','Unstored cells are omitted; absence does not mean a stored null value.'],
 formula_cache_unverified:['公式缓存未核验，未执行公式。','Formula caches are unverified; formulas were not executed.'],
 prepared_raw_values_from_parent:['类型值是整理后的值；XML 词法值与公式缓存来自不可变原始版本。','Typed values are prepared values. XML lexical values and formula cache evidence come from the immutable raw parent.'],
 structure_hidden_sheet:['包含隐藏工作表。','Includes hidden worksheets.'],structure_blank_headers:['首行包含空名称。','The first row contains blank names.'],
 structure_duplicate_headers:['首行包含重复名称。','The first row contains duplicate names.'],structure_merged_cells:['包含合并单元格，未填补覆盖格。','Merged cells are present; covered cells were not filled.'],
 structure_formula_unverified:['公式缓存有效性未确认，未执行公式。','Formula cache validity is unconfirmed; formulas were not executed.'],
 structure_empty_sheet:['空工作表。','Empty worksheet.'],structure_first_row_candidate:['首行仅作候选显示名。','First-row names are display candidates only.'],
 structure_whitespace_values:['保留了空白字符串。','Whitespace strings are preserved.'],structure_precision_preserved:['数值词法原值以文本保留。','Numeric lexical values are preserved as text.'],
}
export const evidenceWarnings:Record<string,string>={}
for(const [code,[zh,en]] of Object.entries(warningEntries)){evidenceWarnings[code]=zh;evidenceMessages[zh]=en}
const parserEntries:Record<string,[string,string]>={
 revisions:['修订内容','Revisions'],equations:['公式对象','Equations'],other_parts:['其他文档部分','Other document parts'],
 legacy_images:['旧式图片','Legacy images'],textboxes:['文本框','Text boxes'],external_images:['外链图片','External images'],
 missing_image:['图片引用缺失','Missing image reference'],unsupported_blocks:['未支持内容容器','Unsupported content blocks'],fields:['域','Fields'],
 reading_order_candidate:['阅读顺序候选','Reading order candidate'],undecoded_characters:['未解码字符','Undecoded characters'],
 no_extractable_text:['无可提取文字','No extractable text'],table_candidate:['表格候选','Table candidate'],
 image_pixels_not_saved:['图片像素未保存','Image pixels not saved'],low_confidence:['低置信度文字','Low-confidence text'],unreviewed:['待核对文字','Unreviewed text'],
}
export const parserWarningLabels:Record<string,string>={}
for(const [code,[zh,en]] of Object.entries(parserEntries)){parserWarningLabels[code]=zh;evidenceMessages[zh]=en}
