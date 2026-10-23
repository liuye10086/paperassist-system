import type {TaskView} from '../tasks/taskTypes'
import {useI18n} from '../../shared/i18n'
import {revisionHash} from './revisionTypes'
export default function ReviewTaskOutcome({task}:{task:TaskView}){const {t}=useI18n(),input=task.input_version;if(input.kind!=='review_revision'&&input.kind!=='review_document_export')return null;return <aside className="manuscript-panel"><a href={revisionHash(task.project_id,input.round_id,input.revision_id,input.kind==='review_document_export'?input.document_id:undefined)}>{t(input.kind==='review_document_export'?'查看此份固定成果':'查看此批固定修改成果')}</a><p>{t(input.kind==='review_revision'?'请在固定修改批次核对公共新稿任务、实际变化与待补事项。':'此任务只导出指定成果版本；后续编辑和确认不会覆盖本文件。')}</p><p>{t('任务成功和下载不会改变投稿或评审进展。')}</p></aside>}
