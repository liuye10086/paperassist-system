import {useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent} from 'react'
import type {SciSection} from '../manuscripts/articleStructure'

type Drag = {
  pointerId: number
  from: number
  to: number
  startY: number
  clientY: number
  listTop: number
  rows: DOMRect[]
  card: HTMLElement | null
  scrollFrame: number | null
  moved: boolean
}

export function useSciSectionDrag(sections: SciSection[], locked: boolean, onReorder: (sections: SciSection[]) => void) {
  const listRef = useRef<HTMLOListElement>(null)
  const dragRef = useRef<Drag | null>(null)
  const beforeDrop = useRef<Map<string | undefined, number> | null>(null)
  const [motion, setMotion] = useState<{from: number; to: number; offset: number; rowHeight: number} | null>(null)
  const last = sections.length - 2
  const movable = (index: number) => !locked && index >= 1 && index <= last

  useLayoutEffect(() => {
    const previous = beforeDrop.current
    beforeDrop.current = null
    if (!previous || !listRef.current || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    for (const row of Array.from(listRef.current.children) as HTMLElement[]) {
      const top = previous.get(row.dataset.sectionId)
      if (top === undefined) continue
      const offset = top - row.getBoundingClientRect().top
      if (Math.abs(offset) > 1) {
        row.animate?.([{transform: `translateY(${offset}px)`}, {transform: 'none'}], {
          duration: 160, easing: 'cubic-bezier(.2,.7,.3,1)',
        })
      }
    }
  }, [sections])

  useEffect(() => () => {
    const frame = dragRef.current?.scrollFrame
    if (frame != null) cancelAnimationFrame(frame)
  }, [])

  function reorder(from: number, to: number) {
    const list = listRef.current
    if (!list || !movable(from) || !movable(to) || from === to) return
    const rows = Array.from(list.children) as HTMLElement[]
    beforeDrop.current = new Map(rows.map(row => [row.dataset.sectionId, row.getBoundingClientRect().top]))
    const next = [...sections]
    next.splice(to, 0, ...next.splice(from, 1))
    onReorder(next)
  }

  function updateMotion(drag: Drag) {
    const list = listRef.current
    if (!list) return
    const row = drag.rows[drag.from]
    const distance = drag.clientY - drag.startY + drag.listTop - list.getBoundingClientRect().top
    if (!drag.moved && Math.abs(distance) < 4) return
    drag.moved = true
    const offset = Math.max(drag.rows[1].top - row.top, Math.min(distance, drag.rows[last].bottom - row.bottom))
    const center = row.top + row.height / 2 + offset
    drag.to = 1 + drag.rows.slice(1, last + 1).filter((target, index) =>
      index + 1 !== drag.from && center > target.top + target.height / 2).length
    setMotion({from: drag.from, to: drag.to, offset, rowHeight: row.height})
  }

  function scrollAtEdge(drag: Drag) {
    drag.scrollFrame = null
    const card = drag.card
    if (!card || dragRef.current !== drag || !drag.moved) return
    const {top, bottom} = card.getBoundingClientRect()
    const edge = 44
    const speed = drag.clientY < top + edge ? -10 : drag.clientY > bottom - edge ? 10 : 0
    if (!speed) return
    const previous = card.scrollTop
    card.scrollTop += speed
    if (card.scrollTop === previous) return
    updateMotion(drag)
    drag.scrollFrame = requestAnimationFrame(() => scrollAtEdge(drag))
  }

  function finish(pointerId: number, save: boolean) {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== pointerId) return
    if (drag.scrollFrame !== null) cancelAnimationFrame(drag.scrollFrame)
    dragRef.current = null
    if (drag.moved && save) reorder(drag.from, drag.to)
    setMotion(null)
  }

  return {
    listRef,
    sorting: !!motion,
    row(index: number) {
      const active = motion?.from === index
      const offset = !motion ? 0 : active ? motion.offset
        : motion.to <= index && index < motion.from ? motion.rowHeight
        : motion.from < index && index <= motion.to ? -motion.rowHeight : 0
      return {
        'data-section-id': sections[index].id,
        'data-dragging': active ? true : undefined,
        style: offset ? {transform: `translateY(${offset}px)`} : undefined,
      }
    },
    handle(index: number) {
      return {
        disabled: !movable(index),
        onPointerDown(event: PointerEvent<HTMLButtonElement>) {
          const list = listRef.current
          if (event.button !== 0 || !movable(index) || !list || dragRef.current) return
          event.preventDefault()
          event.currentTarget.focus({preventScroll: true})
          event.currentTarget.setPointerCapture(event.pointerId)
          const rows = Array.from(list.children)
          for (const row of rows) row.getAnimations?.().forEach(animation => animation.cancel())
          dragRef.current = {
            pointerId: event.pointerId, from: index, to: index, startY: event.clientY, clientY: event.clientY,
            listTop: list.getBoundingClientRect().top, rows: rows.map(row => row.getBoundingClientRect()),
            card: list.closest<HTMLElement>('.customer-section'), scrollFrame: null, moved: false,
          }
        },
        onPointerMove(event: PointerEvent<HTMLButtonElement>) {
          const drag = dragRef.current
          if (!drag || drag.pointerId !== event.pointerId) return
          drag.clientY = event.clientY
          updateMotion(drag)
          if (drag.moved && drag.scrollFrame === null && drag.card && drag.card.scrollHeight > drag.card.clientHeight) {
            drag.scrollFrame = requestAnimationFrame(() => scrollAtEdge(drag))
          }
        },
        onPointerUp(event: PointerEvent<HTMLButtonElement>) { finish(event.pointerId, true) },
        onPointerCancel(event: PointerEvent<HTMLButtonElement>) { finish(event.pointerId, false) },
        onLostPointerCapture(event: PointerEvent<HTMLButtonElement>) { finish(event.pointerId, false) },
        onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
          const drag = dragRef.current
          if (drag) {
            if (event.key === 'Escape') finish(drag.pointerId, false)
            return
          }
          if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
          event.preventDefault()
          reorder(index, index + (event.key === 'ArrowUp' ? -1 : 1))
        },
      }
    },
  }
}
