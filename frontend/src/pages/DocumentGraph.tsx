import { useEffect, useRef, useState, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { documentsService, DocGraphNode, DocGraphData } from '../services/documents'

interface SimNode extends DocGraphNode {
  x: number; y: number; vx: number; vy: number
  pinned?: boolean
  connectionCount: number
  isHub: boolean
}

interface SimEdge { sourceId: number; targetId: number; weight: number }

// ─── Hub detection ─────────────────────────────────────────────────────────────
// A node is a "hub" if its total connection count (in + out) >= 2.
// If all nodes have >=2, lower the bar to the median.

function computeHubThreshold(connMap: Map<number, number>): number {
  const counts = [...connMap.values()].sort((a, b) => a - b)
  if (counts.length === 0) return 2
  const median = counts[Math.floor(counts.length / 2)]
  return Math.max(2, median)
}

// ─── Force simulation ──────────────────────────────────────────────────────────

const MAX_VEL = 70

function runStep(
  nodes: SimNode[],
  edges: SimEdge[],
  cx: number, cy: number,
  alpha: number,
) {
  // Repulsion
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[j].x - nodes[i].x || 0.1
      const dy = nodes[j].y - nodes[i].y || 0.1
      const dist2 = Math.max(dx * dx + dy * dy, 1)
      const dist  = Math.sqrt(dist2)
      const f     = (alpha * 20000) / dist2
      const fx = (dx / dist) * f, fy = (dy / dist) * f
      nodes[i].vx -= fx; nodes[i].vy -= fy
      nodes[j].vx += fx; nodes[j].vy += fy
    }
  }

  // Spring along edges — shorter ideal distance within the same zone
  const map = new Map(nodes.map((n) => [n.id, n]))
  for (const e of edges) {
    const s = map.get(e.sourceId), t = map.get(e.targetId)
    if (!s || !t) continue
    const dx = t.x - s.x, dy = t.y - s.y
    const dist = Math.sqrt(dx * dx + dy * dy) || 1
    const ideal = s.isHub !== t.isHub ? 320 : 200   // cross-zone edges are longer
    const f  = (dist - ideal) * alpha * 0.12
    const fx = (dx / dist) * f, fy = (dy / dist) * f
    s.vx += fx; s.vy += fy
    t.vx -= fx; t.vy -= fy
  }

  // Zone separation + vertical centering + damping
  for (const n of nodes) {
    if (n.pinned) { n.vx = 0; n.vy = 0; continue }
    // Push hubs to left third, non-hubs to right third
    const zoneX = n.isHub ? cx * 0.42 : cx * 1.58
    n.vx += (zoneX - n.x) * alpha * 0.14
    n.vy += (cy    - n.y) * alpha * 0.03
    n.vx = Math.max(-MAX_VEL, Math.min(MAX_VEL, n.vx)) * 0.78
    n.vy = Math.max(-MAX_VEL, Math.min(MAX_VEL, n.vy)) * 0.78
    n.x += n.vx; n.y += n.vy
    if (!isFinite(n.x)) n.x = zoneX
    if (!isFinite(n.y)) n.y = cy
  }
}

// ─── Visual constants ──────────────────────────────────────────────────────────

const C_HUB      = '#b45309'   // amber-700   — hub nodes
const C_LEAF     = '#78716c'   // stone-500   — non-hub nodes
const C_SELECTED = '#d97706'   // amber-600
const C_OUT      = '#f59e0b'   // amber-400   — nodes referenced by selected
const C_IN       = '#34d399'   // emerald-400 — nodes that reference selected

function nodeRadius(n: SimNode) {
  const base = n.isHub ? 18 : 13
  return Math.max(base, Math.min(34, base + Math.log2(n.connectionCount + 1) * 4.5))
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function DocumentGraph() {
  const navigate = useNavigate()

  const [graphData, setGraphData]       = useState<DocGraphData>({ nodes: [], edges: [] })
  const [isLoading, setIsLoading]       = useState(true)
  const [isRedetecting, setIsRedetecting] = useState(false)
  const [redetectResult, setRedetectResult] = useState<string | null>(null)

  const simNodesRef = useRef<SimNode[]>([])
  const simEdgesRef = useRef<SimEdge[]>([])
  const alphaRef    = useRef(0)
  const rafRef      = useRef<number>()
  const [tick, setTick] = useState(0)

  const containerRef = useRef<HTMLDivElement>(null)
  const [svgSize, setSvgSize] = useState({ w: 900, h: 650 })

  const [transform, setTransform]     = useState({ x: 0, y: 0, k: 1 })
  const [selectedId, setSelectedId]   = useState<number | null>(null)
  const [hoveredId, setHoveredId]     = useState<number | null>(null)
  const [tooltipPos, setTooltipPos]   = useState<{ x: number; y: number; label: string } | null>(null)

  const nodeDragRef = useRef<{ id: number; ox: number; oy: number; mx: number; my: number } | null>(null)
  const panDragRef  = useRef<{ mx: number; my: number; tx: number; ty: number } | null>(null)

  // ── Data ──────────────────────────────────────────────────────────────────

  const loadData = useCallback(() => {
    setIsLoading(true)
    documentsService.getConnections()
      .then((d) => { setGraphData(d); setIsLoading(false) })
      .catch(() => setIsLoading(false))
  }, [])

  const handleRedetect = async () => {
    setIsRedetecting(true); setRedetectResult(null)
    try {
      const r = await documentsService.redetectConnections()
      setRedetectResult(`${r.processed} docs · ${r.total_connections} connections`)
      loadData()
    } catch { setRedetectResult('Scan failed') }
    finally { setIsRedetecting(false) }
  }

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver((e) => {
      const { width, height } = e[0].contentRect
      setSvgSize({ w: width, h: height })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // ── Simulation ────────────────────────────────────────────────────────────

  useEffect(() => {
    if (graphData.nodes.length === 0) return
    cancelAnimationFrame(rafRef.current!)
    const { w, h } = svgSize
    const cx = w / 2, cy = h / 2

    const connCount = new Map<number, number>()
    for (const e of graphData.edges) {
      connCount.set(e.source, (connCount.get(e.source) ?? 0) + 1)
      connCount.set(e.target, (connCount.get(e.target) ?? 0) + 1)
    }
    const threshold = computeHubThreshold(connCount)
    const isHub = (id: number) => (connCount.get(id) ?? 0) >= threshold

    const hubs  = graphData.nodes.filter((n) => isHub(n.id))
    const leafs = graphData.nodes.filter((n) => !isHub(n.id))

    // Initial positions: hubs on left, leafs on right, arranged vertically
    const place = (nodes: DocGraphNode[], baseX: number) =>
      nodes.map((n, i) => {
        const total = nodes.length
        const spacing = Math.min(120, (h - 120) / Math.max(total, 1))
        const startY  = cy - (spacing * (total - 1)) / 2
        const jitter  = (Math.random() - 0.5) * 60
        return {
          ...n,
          x: baseX + jitter,
          y: startY + i * spacing,
          vx: 0, vy: 0,
          connectionCount: connCount.get(n.id) ?? 0,
          isHub: isHub(n.id),
        } satisfies SimNode
      })

    simNodesRef.current = [
      ...place(hubs,  cx * 0.38),
      ...place(leafs, cx * 1.62),
    ]
    simEdgesRef.current = graphData.edges.map((e) => ({
      sourceId: e.source, targetId: e.target, weight: e.weight,
    }))
    alphaRef.current = 1

    const animate = () => {
      if (alphaRef.current < 0.004) return
      runStep(simNodesRef.current, simEdgesRef.current, cx, cy, alphaRef.current)
      alphaRef.current *= 0.975
      setTick((t) => t + 1)
      rafRef.current = requestAnimationFrame(animate)
    }
    rafRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(rafRef.current!)
  }, [graphData, svgSize])

  // ── Selection ─────────────────────────────────────────────────────────────

  const outEdges = useMemo(
    () => selectedId === null ? [] : graphData.edges.filter((e) => e.source === selectedId),
    [selectedId, graphData],
  )
  const inEdges = useMemo(
    () => selectedId === null ? [] : graphData.edges.filter((e) => e.target === selectedId),
    [selectedId, graphData],
  )
  const outIds = useMemo(() => new Set(outEdges.map((e) => e.target)), [outEdges])
  const inIds  = useMemo(() => new Set(inEdges.map((e) => e.source)), [inEdges])
  const selNode = useMemo(() => graphData.nodes.find((n) => n.id === selectedId) ?? null, [selectedId, graphData])

  function getNodeColor(n: SimNode) {
    if (n.id === selectedId) return C_SELECTED
    if (outIds.has(n.id))   return C_OUT
    if (inIds.has(n.id))    return C_IN
    return n.isHub ? C_HUB : C_LEAF
  }

  // ── Fit to view ───────────────────────────────────────────────────────────

  const fitToView = useCallback(() => {
    const nodes = simNodesRef.current
    if (!nodes.length) return
    const pad = 100
    const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y)
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    const { w, h } = svgSize
    const k = Math.min((w - pad * 2) / (maxX - minX || 1), (h - pad * 2) / (maxY - minY || 1), 2)
    setTransform({ k, x: (w - (minX + maxX) * k) / 2, y: (h - (minY + maxY) * k) / 2 })
  }, [svgSize])

  // ── Mouse handlers ────────────────────────────────────────────────────────

  const handleNodeDown = (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    const node = simNodesRef.current.find((n) => n.id === id)
    if (!node) return
    nodeDragRef.current = { id, ox: node.x, oy: node.y, mx: e.clientX, my: e.clientY }
    node.pinned = true
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (nodeDragRef.current) {
      const d = nodeDragRef.current
      const node = simNodesRef.current.find((n) => n.id === d.id)
      if (node) { node.x = d.ox + (e.clientX - d.mx) / transform.k; node.y = d.oy + (e.clientY - d.my) / transform.k; setTick((t) => t + 1) }
    } else if (panDragRef.current) {
      const d = panDragRef.current
      setTransform((p) => ({ ...p, x: d.tx + (e.clientX - d.mx), y: d.ty + (e.clientY - d.my) }))
    }
  }

  const handleMouseUp = () => {
    if (nodeDragRef.current) {
      const node = simNodesRef.current.find((n) => n.id === nodeDragRef.current!.id)
      if (node) node.pinned = false
      nodeDragRef.current = null
    }
    panDragRef.current = null
  }

  const handleBgDown = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget || (e.target as SVGElement).tagName === 'rect') {
      setSelectedId(null)
      panDragRef.current = { mx: e.clientX, my: e.clientY, tx: transform.x, ty: transform.y }
    }
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const mx = e.clientX - rect.left, my = e.clientY - rect.top
    const factor = e.deltaY > 0 ? 0.88 : 1.14
    setTransform((p) => {
      const k = Math.max(0.1, Math.min(6, p.k * factor))
      return { k, x: mx - (mx - p.x) * (k / p.k), y: my - (my - p.y) * (k / p.k) }
    })
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const visNodes = useMemo(() => simNodesRef.current, [tick])

  const hubCount  = visNodes.filter((n) => n.isHub).length
  const leafCount = visNodes.filter((n) => !n.isHub).length

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-screen bg-dark-bg text-dark-text">

      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-dark-chat flex-shrink-0">
        <button onClick={() => navigate('/')}
          className="p-2 hover:bg-dark-chat rounded-lg text-dark-muted hover:text-dark-text">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="flex-1">
          <h1 className="text-base font-semibold">Document Connection Graph</h1>
          <p className="text-xs text-dark-muted">
            {graphData.nodes.length} documents · {graphData.edges.length} connections
          </p>
        </div>
        {redetectResult && <span className="text-xs text-dark-muted shrink-0">{redetectResult}</span>}
        <button onClick={fitToView}
          className="px-3 py-1.5 rounded-lg text-sm bg-dark-chat text-dark-muted hover:text-dark-text hover:bg-dark-hover">
          Fit View
        </button>
        <button onClick={handleRedetect} disabled={isRedetecting}
          className="px-3 py-1.5 rounded-lg text-sm bg-dark-chat text-dark-muted hover:text-dark-text hover:bg-dark-hover disabled:opacity-50">
          {isRedetecting ? 'Scanning…' : 'Re-detect'}
        </button>
        <button onClick={loadData}
          className="px-3 py-1.5 rounded-lg text-sm bg-dark-chat text-dark-muted hover:text-dark-text hover:bg-dark-hover">
          Refresh
        </button>
      </div>

      <div className="flex flex-1 min-h-0">

        {/* Left sidebar */}
        <div className="w-52 flex-shrink-0 border-r border-dark-chat bg-dark-sidebar flex flex-col p-3 gap-5">
          {/* Zone counts */}
          <div className="space-y-2">
            <p className="text-[10px] font-semibold text-dark-muted uppercase tracking-wider mb-2">Layout</p>
            <div className="flex items-center gap-2 p-2 rounded-lg bg-dark-chat/50">
              <span className="w-3 h-3 rounded-full bg-indigo-400 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-dark-text font-medium">Hub documents</p>
                <p className="text-[10px] text-dark-muted">Highly connected · left side</p>
              </div>
              <span className="text-xs font-bold text-indigo-400">{hubCount}</span>
            </div>
            <div className="flex items-center gap-2 p-2 rounded-lg bg-dark-chat/50">
              <span className="w-3 h-3 rounded-full bg-sky-400 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-dark-text font-medium">Source documents</p>
                <p className="text-[10px] text-dark-muted">Fewer connections · right side</p>
              </div>
              <span className="text-xs font-bold text-sky-400">{leafCount}</span>
            </div>
          </div>

          {/* Legend */}
          <div>
            <p className="text-[10px] font-semibold text-dark-muted uppercase tracking-wider mb-2">Selection</p>
            <div className="space-y-1.5">
              {[
                { color: C_SELECTED, label: 'Selected' },
                { color: C_OUT,      label: 'Referenced by it' },
                { color: C_IN,       label: 'References it' },
              ].map(({ color, label }) => (
                <div key={label} className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
                  <span className="text-xs text-dark-muted">{label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="border-t border-dark-chat pt-3 text-[11px] text-dark-muted leading-relaxed">
            Scroll to zoom · Drag canvas to pan · Drag nodes to reposition
          </div>

          <div className="mt-auto space-y-1.5">
            <div className="flex gap-1.5">
              <button onClick={() => setTransform((p) => ({ ...p, k: Math.min(6, p.k * 1.25) }))}
                className="flex-1 py-1.5 text-xs bg-dark-chat hover:bg-dark-hover rounded text-dark-muted hover:text-dark-text">+ Zoom</button>
              <button onClick={() => setTransform((p) => ({ ...p, k: Math.max(0.1, p.k * 0.8) }))}
                className="flex-1 py-1.5 text-xs bg-dark-chat hover:bg-dark-hover rounded text-dark-muted hover:text-dark-text">− Zoom</button>
            </div>
            <button onClick={fitToView}
              className="w-full py-1.5 text-xs bg-dark-chat hover:bg-dark-hover rounded text-dark-muted hover:text-dark-text">
              Fit to View
            </button>
            <button onClick={() => setTransform({ x: 0, y: 0, k: 1 })}
              className="w-full py-1.5 text-xs bg-dark-chat hover:bg-dark-hover rounded text-dark-muted hover:text-dark-text">
              Reset
            </button>
          </div>
        </div>

        {/* SVG canvas */}
        <div ref={containerRef} className="flex-1 relative overflow-hidden"
          onMouseMove={handleMouseMove} onMouseUp={handleMouseUp} onMouseLeave={handleMouseUp}>

          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <svg className="w-7 h-7 animate-spin text-dark-muted" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
            </div>
          )}

          {!isLoading && graphData.nodes.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-8">
              <p className="text-dark-muted font-medium">No connections found</p>
              <p className="text-sm text-dark-muted mt-2 max-w-sm">
                Upload documents that reference other document filenames.
              </p>
            </div>
          )}

          <svg width="100%" height="100%" onWheel={handleWheel}
            style={{ cursor: panDragRef.current ? 'grabbing' : 'grab' }}>
            <defs>
              <marker id="arr-def" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <path d="M0,0 L0,7 L10,3.5 z" fill="rgba(99,102,241,0.6)" />
              </marker>
              <marker id="arr-out" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <path d="M0,0 L0,7 L10,3.5 z" fill="#c084fc" />
              </marker>
              <marker id="arr-in" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <path d="M0,0 L0,7 L10,3.5 z" fill="#34d399" />
              </marker>
              <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <filter id="glow-sm" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="2" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              {/* Zone gradients */}
              <linearGradient id="grad-hub" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#818cf8" stopOpacity="0.07" />
                <stop offset="100%" stopColor="#818cf8" stopOpacity="0" />
              </linearGradient>
              <linearGradient id="grad-leaf" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#38bdf8" stopOpacity="0" />
                <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.07" />
              </linearGradient>
            </defs>

            {/* Zone backgrounds */}
            <rect x="0" y="0" width="50%" height="100%" fill="url(#grad-hub)" />
            <rect x="50%" y="0" width="50%" height="100%" fill="url(#grad-leaf)" />
            {/* Center divider */}
            <line x1="50%" y1="0" x2="50%" y2="100%"
              stroke="rgba(255,255,255,0.04)" strokeWidth="1" strokeDasharray="6 6" />
            {/* Zone labels */}
            <text x="4%" y="28" fontSize="11" fill="rgba(129,140,248,0.55)" fontWeight="600" letterSpacing="0.08em">
              HUB DOCUMENTS
            </text>
            <text x="96%" y="28" fontSize="11" fill="rgba(56,189,248,0.55)" fontWeight="600" letterSpacing="0.08em" textAnchor="end">
              SOURCE DOCUMENTS
            </text>

            <rect width="100%" height="100%" fill="transparent" onMouseDown={handleBgDown} />

            <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>

              {/* Edges */}
              {simEdgesRef.current.map((e, i) => {
                const src = visNodes.find((n) => n.id === e.sourceId)
                const tgt = visNodes.find((n) => n.id === e.targetId)
                if (!src || !tgt) return null

                const hiOut = (selectedId === e.sourceId || hoveredId === e.sourceId) && selectedId !== e.targetId
                const hiIn  = (selectedId === e.targetId || hoveredId === e.targetId) && selectedId !== e.sourceId
                const hi    = hiOut || hiIn
                const isCross = src.isHub !== tgt.isHub

                const stroke  = hiOut ? 'rgba(192,132,252,0.85)' : hiIn ? 'rgba(52,211,153,0.85)' : isCross ? 'rgba(148,163,184,0.28)' : 'rgba(99,102,241,0.22)'
                const strokeW = hi ? Math.max(2, e.weight * 0.7) : isCross ? 1.5 : 1
                const marker  = hiOut ? 'url(#arr-out)' : hiIn ? 'url(#arr-in)' : 'url(#arr-def)'

                const dx = tgt.x - src.x, dy = tgt.y - src.y
                const len = Math.sqrt(dx * dx + dy * dy) || 1
                const tr = nodeRadius(tgt)
                const ex = tgt.x - (dx / len) * (tr + 9)
                const ey = tgt.y - (dy / len) * (tr + 9)
                const mx = (src.x + ex) / 2, my = (src.y + ey) / 2
                const perp = isCross ? 0 : Math.min(len * 0.15, 30)
                const cpx  = mx - (dy / len) * perp, cpy = my + (dx / len) * perp
                const midX = (src.x + 2 * cpx + ex) / 4, midY = (src.y + 2 * cpy + ey) / 4

                return (
                  <g key={i}>
                    <path d={`M${src.x},${src.y} Q${cpx},${cpy} ${ex},${ey}`}
                      fill="none" stroke={stroke} strokeWidth={strokeW}
                      markerEnd={marker}
                      filter={hi ? 'url(#glow-sm)' : undefined}
                    />
                    {hi && e.weight > 1 && (
                      <>
                        <rect x={midX - 11} y={midY - 8} width={22} height={14} rx={4}
                          fill="#0a0b10" opacity={0.9} />
                        <text x={midX} y={midY + 1} textAnchor="middle" dominantBaseline="middle"
                          fontSize="9" fill={hiOut ? '#c084fc' : '#34d399'}
                          className="pointer-events-none select-none">
                          ×{e.weight}
                        </text>
                      </>
                    )}
                  </g>
                )
              })}

              {/* Nodes */}
              {visNodes.map((node) => {
                const r     = nodeRadius(node)
                const color = getNodeColor(node)
                const isSel = node.id === selectedId
                const isHov = node.id === hoveredId
                const label = node.label.length > 24 ? node.label.slice(0, 24) + '…' : node.label
                const labelW = label.length * 6.2 + 14

                return (
                  <g key={node.id}
                    transform={`translate(${node.x},${node.y})`}
                    style={{ cursor: 'pointer' }}
                    onClick={(e) => { e.stopPropagation(); setSelectedId(node.id === selectedId ? null : node.id) }}
                    onMouseDown={(e) => handleNodeDown(e, node.id)}
                    onMouseEnter={(e) => {
                      setHoveredId(node.id)
                      if (node.label.length > 24) {
                        const rect = containerRef.current!.getBoundingClientRect()
                        setTooltipPos({ x: e.clientX - rect.left, y: e.clientY - rect.top, label: node.label })
                      }
                    }}
                    onMouseLeave={() => { setHoveredId(null); setTooltipPos(null) }}
                  >
                    {/* Outer glow ring */}
                    {(isSel || isHov) && (
                      <circle r={r + 9} fill={color} fillOpacity={0.15}
                        filter={isSel ? 'url(#glow)' : undefined} />
                    )}
                    {/* Hub ring (extra visual weight for hub nodes) */}
                    {node.isHub && (
                      <circle r={r + 3} fill="none" stroke={color} strokeWidth="1" strokeOpacity="0.3" />
                    )}
                    {/* Node fill */}
                    <circle r={r} fill={color} fillOpacity={isSel ? 1 : 0.82}
                      stroke={isSel ? '#fff' : color} strokeWidth={isSel ? 2.5 : 1} strokeOpacity={isSel ? 1 : 0.5}
                      filter={isSel ? 'url(#glow)' : undefined}
                    />
                    {/* Connection count inside node */}
                    {node.connectionCount > 0 && (
                      <text y={r * 0.35} textAnchor="middle" dominantBaseline="middle"
                        fontSize={r > 20 ? '11' : '9'} fill="rgba(255,255,255,0.95)"
                        fontWeight="700" className="pointer-events-none select-none">
                        {node.connectionCount}
                      </text>
                    )}
                    {/* Label pill */}
                    <rect x={-labelW / 2} y={r + 5} width={labelW} height={17} rx={4}
                      fill="#0a0b10" fillOpacity={0.85} />
                    <text y={r + 14} textAnchor="middle" dominantBaseline="middle"
                      fontSize="11"
                      fill={isSel ? '#fff' : isHov ? '#e8eaf2' : '#8082a0'}
                      fontWeight={isSel ? '600' : '400'}
                      className="pointer-events-none select-none">
                      {label}
                    </text>
                  </g>
                )
              })}
            </g>
          </svg>

          {/* Tooltip */}
          {tooltipPos && (
            <div className="absolute z-20 pointer-events-none px-2.5 py-1.5 rounded-lg text-xs bg-dark-sidebar border border-dark-chat text-dark-text shadow-xl max-w-xs break-all"
              style={{ left: tooltipPos.x + 14, top: tooltipPos.y - 32 }}>
              {tooltipPos.label}
            </div>
          )}
        </div>

        {/* Right panel */}
        <div className="w-64 flex-shrink-0 border-l border-dark-chat bg-dark-sidebar flex flex-col overflow-y-auto">
          {!selNode ? (
            <div className="flex items-center justify-center h-full text-center p-6">
              <p className="text-sm text-dark-muted">Click a node to see its connections</p>
            </div>
          ) : (
            <div className="p-4 space-y-4">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide"
                    style={{
                      background: visNodes.find((n) => n.id === selNode.id)?.isHub ? 'rgba(129,140,248,0.15)' : 'rgba(56,189,248,0.12)',
                      color:      visNodes.find((n) => n.id === selNode.id)?.isHub ? '#818cf8' : '#38bdf8',
                    }}>
                    {visNodes.find((n) => n.id === selNode.id)?.isHub ? 'Hub' : 'Source'}
                  </span>
                </div>
                <h2 className="text-sm font-semibold text-dark-text leading-tight break-words">{selNode.label}</h2>
                <p className="text-xs text-dark-muted mt-1">
                  {outEdges.length} outgoing · {inEdges.length} incoming
                </p>
              </div>

              {outEdges.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-dark-muted uppercase tracking-wider mb-2">References →</p>
                  <div className="space-y-1">
                    {outEdges.map((e, i) => {
                      const tgt = graphData.nodes.find((n) => n.id === e.target)
                      return (
                        <div key={i} className="flex items-start gap-2 text-xs">
                          <span className="text-amber-600 font-mono flex-shrink-0 mt-0.5">→</span>
                          <button className="text-left flex-1 text-dark-text hover:text-white break-words"
                            onClick={() => setSelectedId(e.target)}>
                            {tgt?.label ?? `Doc #${e.target}`}
                          </button>
                          {e.weight > 1 && <span className="text-dark-muted flex-shrink-0">×{e.weight}</span>}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {inEdges.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-dark-muted uppercase tracking-wider mb-2">Referenced by ←</p>
                  <div className="space-y-1">
                    {inEdges.map((e, i) => {
                      const src = graphData.nodes.find((n) => n.id === e.source)
                      return (
                        <div key={i} className="flex items-start gap-2 text-xs">
                          <button className="text-left flex-1 text-dark-text hover:text-white break-words"
                            onClick={() => setSelectedId(e.source)}>
                            {src?.label ?? `Doc #${e.source}`}
                          </button>
                          <span className="text-emerald-400 font-mono flex-shrink-0 mt-0.5">←</span>
                          {e.weight > 1 && <span className="text-dark-muted flex-shrink-0">×{e.weight}</span>}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {outEdges.length === 0 && inEdges.length === 0 && (
                <p className="text-xs text-dark-muted">No connections for this document.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
