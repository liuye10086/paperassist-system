import ReadableDetails from '../../shared/components/ReadableDetails'
import {apiError, useI18n} from '../../shared/i18n'
import type {ReportNarrative} from './contracts'
import {OperationStatus, TaskStatus} from './ResearchShared'
import {ReportDisclosureFacts, ReportDisclosureSummary} from './ReportFacts'
import type {useReportNarrative} from './useReportNarrative'

export function NarrativePreparation({projectId, enabled, preparation, taskLink}: {
  projectId:string;enabled:boolean;preparation:ReturnType<typeof useReportNarrative>;taskLink?:(taskId:string)=>string
}) {
  const {t, locale} = useI18n()
  const {preview, status, ready, read, matching} = preparation
  const cost = preview && new Intl.NumberFormat(locale, {style: 'currency', currency: 'USD', maximumFractionDigits: 6}).format(preview.reserved_micro_usd / 1_000_000)
  return <section className="research-detail-block">
    {(!matching?.id || preparation.canRegenerate) && !preview && !preparation.operation.unknown && <button type="button" disabled={!enabled || preparation.blocking}
      onClick={() => void preparation.inspect()}>{t(preparation.canRegenerate?'重新生成详细解读（会再次调用模型）':'生成详细解读')}</button>}
    {preview && <section aria-label={t('确认外发材料与费用')}>
      <h4>{t('确认外发材料与费用')}</h4>
      <p>{t(preview.cached?'可复用与当前内容匹配的解读。':'将向外部模型发送所选研究发现的固定结果摘要及下列图片。')}</p>
      <p>{t('模型 {model} · 本次预算预留 {amount}', {model: preview.model, amount: cost ?? ''})}</p>
      <p>{t('结果摘要包含 {facts} 项内容，图片 {figures} 张。', {facts: preview.fact_count, figures: preview.figures.length})}</p>
      {!!preview.figures.length && <ol>{preview.figures.map((figure, index) => <li key={figure.number ?? index}>
        {figure.title}
        {(figure.source_caption || !!figure.caption_facts?.length) && <details>
          <summary>{t('查看将发送的图注与绑定事实')}</summary>
          {figure.source_caption && <section><h5>{t('图注说明')}</h5><ReadableDetails value={figure.source_caption} readerView/></section>}
          {!!figure.caption_facts?.length && <section><h5>{t('图注绑定事实')}</h5><ReportDisclosureFacts facts={figure.caption_facts}/></section>}
        </details>}
      </li>)}</ol>}
      {preview.facts != null && <details><summary>{t('查看将发送的结果摘要')}</summary><ReportDisclosureSummary material={preview.facts}/></details>}
      {!preview.real_calls_enabled && !preview.cached && <p role="status">{t('当前未启用真实模型调用。')}</p>}
      <label><input type="checkbox" checked={preparation.consent} onChange={event => preparation.setConsent(event.target.checked)}/>{t(preview.cached?'确认使用上述材料的已保存解读':'我同意发送上述材料以生成详细解读')}</label>
      <button type="button" className="button-primary" disabled={!preparation.consent || !enabled || preparation.blocking || !preview.real_calls_enabled && !preview.cached}
        onClick={() => void preparation.submit()}>{t('确认材料并生成解读')}</button>
      <button type="button" onClick={preparation.cancelPreview}>{t('取消')}</button>
    </section>}
    {preparation.busy && <p role="status">{t('正在核对解读材料与任务。')}</p>}
    {preparation.error && <p role="alert">{t(preparation.error)}</p>}
    {matching?.id && <>
      {read.loading && !status && <p role="status">{t('正在读取详细解读。')}</p>}
      {read.error && <p role="alert">{t(read.error)}</p>}
      {!read.error && read.data && !status && <p role="alert">{t('详细解读与当前报告内容不一致。')}</p>}
      {status && <TaskStatus projectId={projectId} task={status.task} href={taskLink?.(status.task.id)}/>}
      {status?.task.error_code && <p role="alert">{t(apiError({detail:{code:status.task.error_code}}, '请查看任务详情处理。'))}</p>}
      {(!ready || read.error) && <button type="button" disabled={read.loading || preparation.blocking} onClick={read.refresh}>{t('刷新解读状态')}</button>}
      {status?.allowed_actions?.some(action => action === 'retry' || action === 'resume') && <button type="button" disabled={read.loading || preparation.blocking}
        onClick={() => void preparation.retry()}>{t(status.allowed_actions.includes('resume') ? '继续查看原解读任务' : '重试原解读任务')}</button>}
    </>}
    {ready?.result && <ReportNarrativeView result={ready.result}/>}
    <OperationStatus operation={preparation.operation}/>
  </section>
}

const sectionTitles = {
  abstract: '摘要', design_and_data: '研究设计与数据', quality_control: '质量与可用性', methods_summary: '实际方法',
  key_findings: '主要结果', limitations: '局限性', reader_cautions: '阅读提示',
} as const

export function ReportNarrativeView({result, draft = true}: {result: ReportNarrative; draft?: boolean}) {
  const {t} = useI18n()
  return <section aria-label={t('详细报告解读')}>
    <h4>{t('详细报告解读')}</h4>
    {result.origin === 'saved_explanation_reuse' ? <p className="muted">{t('正文沿用已保存的统计结果和解释。图像细节需结合原图人工核对。')}</p> : <>
      {draft && <p className="muted">{t('解读由模型生成。请核对研究事实、图件顺序和局限后再生成报告。')}</p>}
      <p className="muted">{t('解读依据选定的摘要事实和图件。解读中的“未提供”仅指本次解读所见材料。已保存的完整结果以所选结果表为准。')}</p>
    </>}
    {Object.entries(sectionTitles).map(([key, title]) => <section key={key}>
      <h5>{t(title)}</h5><p className="research-narrative-paragraph">{result.narrative[key as keyof ReportNarrative['narrative']]}</p>
    </section>)}
    {!!result.figures.length && <h5>{t('逐图解读')}</h5>}
    {result.figures.map(figure => <section key={figure.number}>
      <h6>{t('图 {number}', {number: figure.number})} {figure.title}</h6>
      <dl>{([
        ['读图方式', figure.reading], ['实际观察', figure.observations], ['解释', figure.interpretation],
        ['局限性', figure.limitations],
      ] as const).map(([label, value]) => <div key={label}><dt>{t(label)}</dt><dd className="research-narrative-paragraph">{value}</dd></div>)}</dl>
    </section>)}
  </section>
}
