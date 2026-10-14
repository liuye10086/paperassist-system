import { useI18n } from '../../shared/i18n'
import type { DatasetAnalysisSource } from './datasetSource'
export default function SourceSummary({ source, filename }: { source?: DatasetAnalysisSource; filename?: string }) {
 const { t } = useI18n()
 return <p className="muted analysis-source">{source?.kind === 'prepared_dataset_version' ? t(filename ? '来源：{filename}；工作表：{sheet}；原始数据 v{raw} · 整理数据 v{prepared}。' : '工作表：{sheet}；原始数据 v{raw} · 整理数据 v{prepared}。', { filename: filename ?? '', sheet: source.sheet_name, raw: source.parent_dataset_version, prepared: source.dataset_version }) : source ? t(filename ? '来源：{filename}；工作表：{sheet}；原始数据版本 v{version}。' : '工作表：{sheet}；原始数据版本 v{version}。', { filename: filename ?? '', sheet: source.sheet_name, version: source.dataset_version }) : t('来源：历史 Excel 配置。')}</p>
}
