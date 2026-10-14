import { documentSourceLabel } from './documentLabels';
import { useState, type ReactNode } from 'react';
import { useI18n } from '../../shared/i18n';
import DocumentImage from './DocumentImage';
import type { Block, DocumentVersion, Style, Table } from './documentApi';
const propertyLabels: Record<string, string> = { 'b.val': '加粗', 'i.val': '斜体', 'u.val': '下划线', 'sz.val': '字号（半磅）', 'color.val': '文字颜色', 'jc.val': '对齐方式', 'spacing.before': '段前间距', 'spacing.after': '段后间距', 'spacing.line': '行距', 'rFonts.ascii': '西文字体', 'rFonts.eastAsia': '东亚字体', 'ind.left': '左缩进', 'ind.right': '右缩进', 'ind.firstLine': '首行缩进', 'pgSz.w': '页面宽度', 'pgSz.h': '页面高度', 'pgMar.top': '页面上边距', 'pgMar.bottom': '页面下边距', 'pgMar.left': '页面左边距', 'pgMar.right': '页面右边距', 'tblW.w': '表格宽度', 'shd.fill': '底纹颜色' };
const propertyKey = (key: string) => key.replace(/^(rPr|pPr|tblPr|sectPr)\./, '').replace(/\[\d+\]/g, '');
function Properties({ values }: {
    values: Record<string, string>;
}) { const { t } = useI18n(); return <dl className="document-properties">{Object.entries(values).filter(([key]) => Object.hasOwn(propertyLabels, propertyKey(key))).map(([key, value]) => <div key={key}><dt>{t(propertyLabels[propertyKey(key)])}</dt><dd>{['b.val', 'i.val'].includes(propertyKey(key)) ? t(['1', 'true', 'on'].includes(value) ? '启用' : '禁用') : value}</dd></div>)}</dl>; }
function DocumentTable({ block, version, base, onUnavailable }: {
    block: Table;
    version: DocumentVersion;
    base: string;
    onUnavailable: () => void;
}) {
    const { t } = useI18n();
    const [page, setPage] = useState(1);
    const start = (page - 1) * 20;
    const end = Math.min(start + 20, block.rows);
    // Include an anchor spanning a page boundary once, clipping only its visual row span.
    const rows = Array.from({ length: end - start }, (_, i) => start + i);
    function cellsForRow(row: number) {
        const result: ReactNode[] = [];
        let column = 0;
        function emptySlot(from: number, to: number) {
            if (to > from) result.push(<td key={`empty:${row}:${from}`} colSpan={to-from} data-document-empty="true" aria-label={t('未保存单元格的网格空位')} />);
        }
        const occupied = block.cells.filter(cell => cell.row <= row && cell.row + cell.row_span > row).sort((a,b)=>a.column-b.column);
        for (const cell of occupied) {
            emptySlot(column, cell.column);
            // Earlier anchors already occupy their grid columns through rowSpan.
            // At the page boundary render one clipped anchor, retaining its true source.
            if (cell.row === row || row === start) result.push(<td key={`${cell.row}:${cell.column}`} rowSpan={Math.min(cell.row + cell.row_span,end)-row} colSpan={cell.column_span}><small>{documentSourceLabel(cell.source.label,t)}</small>{cell.blocks.map(child=><DocumentBlock key={child.id} block={child} version={version} base={base} onUnavailable={onUnavailable}/>)}</td>);
            column = Math.max(column, cell.column + cell.column_span);
        }
        emptySlot(column, block.columns);
        return result;
    }
    return <section className="document-table"><p className="muted">{documentSourceLabel(block.source.label, t)} · {t('表格 {rows} 行 × {columns} 列', { rows: block.rows, columns: block.columns })}</p><div className="field-table-scroll" tabIndex={0}><table><caption>{t('当前显示第 {start}–{end} 行，共 {total} 行', { start: start + 1, end, total: block.rows })}</caption><tbody>{rows.map(row => <tr key={row}>{cellsForRow(row)}</tr>)}</tbody></table></div>{block.rows > 20 && <nav><button disabled={page === 1} onClick={() => setPage(p => p - 1)}>{t('上一页表格行')}</button><span>{page}</span><button disabled={end >= block.rows} onClick={() => setPage(p => p + 1)}>{t('下一页表格行')}</button></nav>}<Properties values={block.properties}/></section>;
}
export default function DocumentBlock({ block, version, base, onUnavailable }: {
    block: Block;
    version: DocumentVersion;
    base: string;
    onUnavailable: () => void;
}) {
    const { t } = useI18n();
    const style: Style | undefined = version.styles?.find(s => s.id === block.style_id);
    if (block.kind === 'table')
        return <DocumentTable block={block} version={version} base={base} onUnavailable={onUnavailable}/>;
    return <article className="document-paragraph"><small className="muted">{documentSourceLabel(block.source.label, t)}</small>{block.heading_level ? <p className="document-heading" role="heading" aria-level={Math.min(block.heading_level, 6)}>{block.text}</p> : <p className="document-text">{block.text}</p>}{style && <p className="muted">{t('段落样式：{name}', { name: style.name })}</p>}<Properties values={block.properties}/>{block.runs.filter(run => Object.keys(run.properties).length > 0).map((run, index) => <details key={index}><summary>{t('文字显式样式')} · {run.text}</summary><Properties values={run.properties}/></details>)}{block.image_ids.map(id => { const image = version.images?.find(v => v.id === id); return image && <DocumentImage key={id} image={image} url={`${base}/${encodeURIComponent(version.id)}/images/${encodeURIComponent(id)}`} onUnavailable={onUnavailable}/>; })}</article>;
}
export { Properties };
