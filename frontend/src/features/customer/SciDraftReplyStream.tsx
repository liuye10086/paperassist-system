import {useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react'
import type {DraftReplyPart, Section} from './useSciDraftRead'

const segmenter = typeof Intl.Segmenter === 'function' ? new Intl.Segmenter(undefined, {granularity: 'grapheme'}) : null
const maxRevealMs = 900
const msPerCharacter = 36

function characterStarts(text: string) {
  if (segmenter) return Array.from(segmenter.segment(text), ({index}) => index)
  const starts: number[] = []
  let index = 0
  for (const character of text) {
    starts.push(index)
    index += character.length
  }
  return starts
}

export default function SciDraftReplyStream({parts, sections, onReveal}: {
  parts: DraftReplyPart[]
  sections: Pick<Section, 'id' | 'heading'>[]
  onReveal?: () => void
}) {
  const {chunks, total} = useMemo(() => {
    let total = 0
    const chunks = parts.map(part => {
      const starts = characterStarts(part.text)
      const chunk = {...part, offset: total, starts}
      total += starts.length
      return chunk
    })
    return {chunks, total}
  }, [parts])
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  const revealed = useRef(0)
  const [count, setCount] = useState(0)
  const visible = reducedMotion ? total : Math.min(count, total)

  useEffect(() => {
    const start = Math.min(revealed.current, total)
    const pending = total - start
    if (reducedMotion || pending === 0) return
    const duration = Math.min(maxRevealMs, pending * msPerCharacter)
    let firstFrame: number | undefined
    let frame: number
    function advance(now: number) {
      firstFrame ??= now
      const next = start + Math.min(pending, Math.max(1, Math.floor(pending * (now - firstFrame) / duration)))
      if (next !== revealed.current) {
        revealed.current = next
        setCount(next)
      }
      if (next < total) frame = requestAnimationFrame(advance)
    }
    frame = requestAnimationFrame(advance)
    return () => cancelAnimationFrame(frame)
  }, [total, reducedMotion])

  useLayoutEffect(() => {
    if (visible) onReveal?.()
  }, [visible, onReveal])

  if (!visible) return null
  return <div className="sci-revision-preview-reply" aria-live="off">
    {chunks.map(part => {
      const length = visible - part.offset
      if (length <= 0 || !part.text) return null
      return <div key={part.section_id ?? 'advice'}>
        {chunks.length > 1 && <strong>{sections.find(section => section.id === part.section_id)?.heading}</strong>}
        <p>{part.text.slice(0, part.starts[length])}</p>
      </div>
    })}
  </div>
}
