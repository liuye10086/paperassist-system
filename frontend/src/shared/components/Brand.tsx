import logo from '../assets/arviva-logo.jpg'

/** Original Arviva brand asset; keep its aspect ratio intact. */
export default function Brand() {
  return <img className="arviva-brand-logo" src={logo} alt="Arviva Therapeutics" />
}
