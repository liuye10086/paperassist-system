import {useI18n} from '../../shared/i18n'
export default function BioDesignLinks({projectId}:{projectId:string}){const {t}=useI18n();return <a href={`#project=${encodeURIComponent(projectId)}&section=overview&view=design`}>{t('补充实验设计与材料')}</a>}
