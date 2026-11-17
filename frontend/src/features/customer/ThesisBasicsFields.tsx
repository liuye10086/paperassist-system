import { useI18n } from '../../shared/i18n'
import PaperKeywordFields from './PaperKeywordFields'
import { educationLevels, thesisLanguages, type ThesisBasicsDraft } from './thesisProjectRequirements'

export default function ThesisBasicsFields({ draft, disabled, onChange, onError }: {
  draft: ThesisBasicsDraft; disabled: boolean; onChange: (draft: ThesisBasicsDraft) => void; onError: (message: string) => void
}) {
  const { t } = useI18n()
  return <fieldset className="thesis-basics-fields" disabled={disabled}>
    <div className="thesis-basics-selects">
      <label>{t('学位层次')}<select required value={draft.education_level}
        onChange={event => onChange({ ...draft, education_level: event.target.value as ThesisBasicsDraft['education_level'] })}>
        <option value="">{t('请选择学位层次')}</option>
        {educationLevels.map(level => <option key={level} value={level}>{t(level)}</option>)}
      </select></label>
      <label>{t('论文语种')}<select required value={draft.language}
        onChange={event => onChange({ ...draft, language: event.target.value as ThesisBasicsDraft['language'] })}>
        <option value="">{t('请选择论文语种')}</option>
        {Object.entries(thesisLanguages).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
      </select></label>
    </div>
    <label>{t('学校名称')}<input required maxLength={300} value={draft.school}
      onChange={event => onChange({ ...draft, school: event.target.value })} /></label>
    <label>{t('论文题目')}<input required maxLength={200} value={draft.title}
      onChange={event => onChange({ ...draft, title: event.target.value })} /></label>
    <PaperKeywordFields draft={draft} onChange={value => onChange({ ...draft, ...value })} onError={onError} />
  </fieldset>
}
