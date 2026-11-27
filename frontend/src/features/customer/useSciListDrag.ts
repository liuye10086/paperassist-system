import {useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent} from 'react'

type RowBounds = Pick<DOMRect, 'top' | 'bottom' | 'height'>
type SortRange = {first: number; last: number}
type Drag = {
  pointerId: number
  from: number
  to: number
  startY: number
  clientY: number
  listTop: number
  rows: RowBounds[]
  range: SortRange
  rowGap: number
  card: HTMLElement | null
  scrollFrame: number | null
  moved: boolean
}

export function useSciListDrag<T>({items, id, locked, range, onReorder, snapToSlot = false}: {
  items: T[]; id: (item: T) => string; locked: boolean; snapToSlot?: boolean
  range: (index: number) => SortRange; onReorder: (items: T[]) => void
}) {
  const listRef = useRef<HTMLOListElement>(null)
  const dragRef = useRef<Drag | null>(null)
  const beforeDrop = useRef<Map<HTMLElement, number> | null>(null)
  const [motion, setMotion] = useState<{from: number; to: number; offset: number; rowSpace: number} | null>(null)

  function movableRange(index: number) {
    if (locked || index < 0 || index >= items.length) return null
    const bounds = range(index)
    return index >= bounds.first && index <= bounds.last ? bounds : null
  }

  useLayoutEffect(() => {
    const previous = beforeDrop.current
    beforeDrop.current = null
    if (!previous || !listRef.current || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    for (const row of Array.from(listRef.current.children) as HTMLElement[]) {
      const top = previous.get(row)
      if (top === undefined) continue
      const offset = top - row.getBoundingClientRect().top
      if (Math.abs(offset) > 1) {
        row.animate?.([{transform: `translateY(${offset}px)`}, {transform: 'none'}], {
          duration: 160, easing: 'cubic-bezier(.2,.7,.3,1)',
        })
      }
    }
  }, [items])

  useEffect(() => () => {
    const frame = dragRef.current?.scrollFrame
    if (frame != null) cancelAnimationFrame(frame)
  }, [])

  function reorder(from: number, to: number) {
    const list = listRef.current
    const bounds = movableRange(from)
    if (!list || !bounds || to < bounds.first || to > bounds.last || from === to) return
    if (!snapToSlot) {
      const rows = Array.from(list.children) as HTMLElement[]
      beforeDrop.current = new Map(rows.map(row => [row, row.getBoundingClientRect().top]))
    }
    const next = [...items]
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
    const {first, last} = drag.range
    const movingDown = distance > 0
    const adjacentRows = movingDown ? drag.rows.slice(drag.from + 1, last + 1) : drag.rows.slice(first, drag.from)
    const referencePoint = snapToSlot ? (movingDown ? row.bottom : row.top) : row.top + row.height / 2
    const position = referencePoint + distance
    const crossed = adjacentRows.filter(target => {
      const midpoint = target.top + target.height / 2
      return movingDown ? position >= midpoint : position <= midpoint
    }).length
    drag.to = drag.from + (movingDown ? crossed : -crossed)
    const target = drag.rows[drag.to]
    const offset = snapToSlot
      ? (movingDown ? target.bottom - row.bottom : target.top - row.top)
      : Math.max(drag.rows[first].top - row.top, Math.min(distance, drag.rows[last].bottom - row.bottom))
    setMotion({from: drag.from, to: drag.to, offset, rowSpace: row.height + drag.rowGap})
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
        : motion.to <= index && index < motion.from ? motion.rowSpace
        : motion.from < index && index <= motion.to ? -motion.rowSpace : 0
      return {
        'data-sort-id': id(items[index]),
        'data-dragging': active ? true : undefined,
        style: offset ? {transform: `translateY(${offset}px)`} : undefined,
      }
    },
    handle(index: number) {
      return {
        disabled: !movableRange(index),
        onPointerDown(event: PointerEvent<HTMLButtonElement>) {
          const list = listRef.current
          const bounds = movableRange(index)
          if (event.button !== 0 || !bounds || !list || dragRef.current) return
          event.preventDefault()
          event.currentTarget.focus({preventScroll: true})
          event.currentTarget.setPointerCapture(event.pointerId)
          const rows: RowBounds[] = []
          for (const row of Array.from(list.children) as HTMLElement[]) {
            if (!row.dataset.sortId) continue
            row.getAnimations?.().forEach(animation => animation.cancel())
            rows.push(row.getBoundingClientRect())
          }
          dragRef.current = {
            pointerId: event.pointerId, from: index, to: index, startY: event.clientY, clientY: event.clientY,
            listTop: list.getBoundingClientRect().top, rows, range: bounds,
            rowGap: Number.parseFloat(getComputedStyle(list).rowGap) || 0,
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
