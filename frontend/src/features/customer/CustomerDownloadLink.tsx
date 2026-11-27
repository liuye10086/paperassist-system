import type {ComponentProps} from 'react'
import {createPortal} from 'react-dom'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import './customerDownloadLink.css'

type Props = Omit<ComponentProps<typeof ProjectDownloadLink>, 'className' | 'showProgress' | 'errorDurationMs' | 'renderError'>

export default function CustomerDownloadLink(props: Props) {
  return <ProjectDownloadLink {...props} className="button-accent customer-download-link" showProgress={false}
    errorDurationMs={3000} renderError={message => createPortal(
      <div className="customer-download-error error-panel" role="alert">{message.trimEnd().replace(/[。.]$/, '')}</div>,
      document.body,
    )}/>
}
