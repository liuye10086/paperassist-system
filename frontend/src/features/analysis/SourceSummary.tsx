import { useI18n } from '../../shared/i18n'
import type { DatasetAnalysisSource } from './datasetSource'
export default function SourceSummary({ source, filename }: { source?: DatasetAnalysisSource; filename?: string }) {
 const { t } = useI18n()
 return <p className="muted analysis-source">{source?[
   filename&&t('来源：{filename}',{filename}),
   t('工作表：{sheet}',{sheet:source.sheet_name}),
   t(source.kind==='prepared_dataset_version'?'整理数据':'原始数据')
 ].filter(Boolean).join(' · '):t('来源：历史 Excel 配置。')}</p>
}
