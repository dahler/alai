import { useEffect, useRef, useState, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { documentsService, DocGraphNode, DocGraphData } from '../services/documents'

interface SimNode extends DocGraphNode {
  x: number
  y: number
  vx: number
  vy: number
  pinned?: boolean
  connectionCount: number
}

interface SimEdge {
  sourceId: number
  targetId: number
  weight: number
}

// ─── Force simulation ────────────────────────────────────────────────────────

const MAX_VEL = 80

function runStep(nodes: SimNode[], edges: SimEdge[], cx: number, cy: number, alpha: number) {
  // Repulsion between all pairs
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[j].x - nodes[i].x || 0.1
      const dy = nodes[j].y - nodes[i].y || 0.1
      const dist2 = Math.max(dx * dx + dy * dy, 1)
      const dist = Math.sqrt(dist2)
      const f = (alpha * 18000) / dist2
      const fx = (dx / dist) * f
      const fy = (dy / dist) * f
      nodes[i].vx -= fx; nodes[i].vy -= fy
      nodes[j].vx += fx; nodes[j].vy += fy
    }
  }

  // Spring attraction along edges
  const map = new Map(nodes.map((n) => [n.id, n]))
  for (const e of edges) {
    const s = map.get(e.sourceId)
    const t = map.get(e.targetId)
    if (!s || !t) continue
    const dx = t.x - s.x
    const dy = t.y - s.y
    const dist = Math.sqrt(dx * dx + dy * dy) || 1
    const f = (dist - 280) * alpha * 0.15
    const fx = (dx / dist) * f
    const fy = (dy / dist) * f
    s.vx += fx; s.vy += fy
    t.vx -= fx; t.vy -= fy
  }

  // Gravity toward center + velocity damping
  for (const n of nodes) {
    if (n.pinned) { n.vx = 0; n.vy = 0; continue }
    n.vx += (cx - n.x) * alpha * 0.025
    n.vy += (cy - n.y) * alpha * 0.025
    n.vx = Math.max(-MAX_VEL, Math.min(MAX_VEL, n.vx)) * 0.78
    n.vy = Math.max(-MAX_VEL, Math.min(MAX_VEL, n.vy)) * 0.78
    n.x += n.vx
    n.y += n.vy
    if (!isFinite(n.x)) n.x = cx
    if (!isFinite(n.y)) n.y = cy
  }
}

// ─── Visual constants ────────────────────────────────────────────────────────

const C_DEFAULT  = '#6366f1'   // indigo
const C_SELECTED = '#f59e0b'   // amber
const C_OUT      = '#a78bfa'   // violet  — referenced by selected
const C_IN       = '#34d399'   // emerald — references selected

const EDGE_DEFAULT    = 'rgba(99,102,241,0.22)'
const EDGE_OUT        = 'rgba(167,139,250,0.75)'
const EDGE_IN         = 'rgba(52,211,153,0.75)'
const ARROW_DEFAULT   = '#4f46e5'
const ARROW_OUT       = '#a78bfa'
const ARROW_IN        = '#34d399'

function nodeRadius(n: SimNode) {
  return Math.max(14, Math.min(30, 14 + Math.log2(n.connectionCount + 1) * 5))
}

// ─── Component ───────────────────────────────────────────────────────────────

export function DocumentGraph() {
  const navigate = useNavigate()

  const [graphData, setGraphData] = useState<DocGraphData>({ nodes: [], edges: [] })
  const [isLoading, setIsLoading] = useState(true)
  const [isRedetecting, setIsRedetecting] = useState(false)
  const [redetectResult, setRedetectResult] = useState<string | null>(null)

  const simNodesRef = useRef<SimNode[]>([])
  const simEdgesRef = useRef<SimEdge[]>([])
  const alphaRef    = useRef(0)
  const rafRef      = useRef<number>()
  const [tick, setTick] = useState(0)

  const containerRef = useRef<HTMLDivElement>(null)
  const [svgSize, setSvgSize] = useState({ w: 800, h: 600 })

  const [transform, setTransform]       = useState({ x: 0, y: 0, k: 1 })
  const [selectedId, setSelectedId]     = useState<number | null>(null)
  const [hoveredId, setHoveredId]       = useState<number | null>(null)
  const [tooltipNode, setTooltipNode]   = useState<{ id: number; x: number; y: number } | null>(null)

  const nodeDragRef = useRef<{ id: number; ox: number; oy: number; mx: number; my: number } | null>(null)
  const panDragRef  = useRef<{ mx: number; my: number; tx: number; ty: number } | null>(null)

  // ── Data loading ─────────────────────────────────────────────────────────

  const loadData = useCallback(() => {
    setIsLoading(true)
    documentsService.getConnections()
      .then((data) => { setGraphData(data); setIsLoading(false) })
      .catch(() => setIsLoading(false))
  }, [])

  const handleRedetect = async () => {
    setIsRedetecting(true)
    setRedetectResult(null)
    try {
      const result = await documentsService.redetectConnections()
      setRedetectResult(`${result.processed} docs scanned · ${result.total_connections} connections`)
      loadData()
    } catch {
      setRedetectResult('Scan failed')
    } finally {
      setIsRedetecting(false)
    }
  }

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      setSvgSize({ w: width, h: height })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // ── Simulation setup ──────────────────────────────────────────────────────

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

    // Circular initial layout for better starting positions
    const n = graphData.nodes.length
    const radius = Math.max(180, n * 30)
    simNodesRef.current = graphData.nodes.map((node, i) => {
      const angle = (2 * Math.PI * i) / n
      return {
        ...node,
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
        vx: 0, vy: 0,
        connectionCount: connCount.get(node.id) ?? 0,
      }
    })
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

  // ── Derived selection ─────────────────────────────────────────────────────

  const outgoingEdges = useMemo(
    () => selectedId === null ? [] : graphData.edges.filter((e) => e.source === selectedId),
    [selectedId, graphData],
  )
  const incomingEdges = useMemo(
    () => selectedId === null ? [] : graphData.edges.filter((e) => e.target === selectedId),
    [selectedId, graphData],
  )
  const outIds = useMemo(() => new Set(outgoingEdges.map((e) => e.target)), [outgoingEdges])
  const inIds  = useMemo(() => new Set(incomingEdges.map((e) => e.source)), [incomingEdges])
  const selectedNode = useMemo(() => graphData.nodes.find((n) => n.id === selectedId) ?? null, [selectedId, graphData])

  function nodeColor(id: number) {
    if (id === selectedId)   return C_SELECTED
    if (outIds.has(id))      return C_OUT
    if (inIds.has(id))       return C_IN
    return C_DEFAULT
  }

  // ── Fit to view ───────────────────────────────────────────────────────────

  const fitToView = useCallback(() => {
    const nodes = simNodesRef.current
    if (nodes.length === 0) return
    const pad = 80
    const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y)
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    const gw = maxX - minX || 1, gh = maxY - minY || 1
    const { w, h } = svgSize
    const k = Math.min((w - pad * 2) / gw, (h - pad * 2) / gh, 2)
    setTransform({
      k,
      x: (w - (minX + maxX) * k) / 2,
      y: (h - (minY + maxY) * k) / 2,
    })
  }, [svgSize])

  // ── Mouse handlers ────────────────────────────────────────────────────────

  const handleNodeMouseDown = (e: React.MouseEvent, id: number) => {
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
      if (node) {
        node.x = d.ox + (e.clientX - d.mx) / transform.k
        node.y = d.oy + (e.clientY - d.my) / transform.k
        setTick((t) => t + 1)
      }
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

  const handleBgMouseDown = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget || (e.target as SVGElement).tagName === 'rect') {
      setSelectedId(null)
      panDragRef.current = { mx: e.clientX, my: e.clientY, tx: transform.x, ty: transform.y }
    }
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const factor = e.deltaY > 0 ? 0.88 : 1.14
    // Zoom toward cursor position
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    setTransform((p) => {
      const newK = Math.max(0.15, Math.min(6, p.k * factor))
      return {
        k: newK,
        x: mx - (mx - p.x) * (newK / p.k),
        y: my - (my - p.y) * (newK / p.k),
      }
    })
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const visibleNodes = useMemo(() => simNodesRef.current, [tick])

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
        <div className="flex-1 min-w-0">
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

        {/* Left panel */}
        <div className="w-48 flex-shrink-0 border-r border-dark-chat bg-dark-sidebar flex flex-col p-3 gap-5">
          <div>
            <p className="text-[10px] font-semibold text-dark-muted uppercase tracking-wider mb-2.5">Legend</p>
            <div className="space-y-2">
              {[
                { color: C_DEFAULT,  label: 'Document' },
                { color: C_SELECTED, label: 'Selected' },
                { color: C_OUT,      label: 'Referenced' },
                { color: C_IN,       label: 'References' },
              ].map(({ color, label }) => (
                <div key={label} className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
                  <span className="text-xs text-dark-muted">{label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="border-t border-dark-chat pt-3 text-xs text-dark-muted space-y-1.5">
            <p>Scroll to zoom · Drag background to pan · Drag nodes to reposition · Click to select</p>
          </div>

          <div className="mt-auto space-y-1.5">
            <div className="flex gap-1.5">
              <button onClick={() => setTransform((p) => ({ ...p, k: Math.min(6, p.k * 1.25) }))}
                className="flex-1 py-1.5 text-xs bg-dark-chat hover:bg-dark-hover rounded text-dark-muted hover:text-dark-text">
                + Zoom
              </button>
              <button onClick={() => setTransform((p) => ({ ...p, k: Math.max(0.15, p.k * 0.8) }))}
                className="flex-1 py-1.5 text-xs bg-dark-chat hover:bg-dark-hover rounded text-dark-muted hover:text-dark-text">
                − Zoom
              </button>
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
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}>

          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <svg className="w-6 h-6 animate-spin text-dark-muted" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
            </div>
          )}
          {!isLoading && graphData.nodes.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-8">
              <p className="text-dark-muted font-medium">No connections found</p>
              <p className="text-sm text-dark-muted mt-2 max-w-sm">
                Upload documents that reference other document filenames. Connections are detected automatically.
              </p>
            </div>
          )}

          <svg width="100%" height="100%"
            onWheel={handleWheel}
            style={{ cursor: panDragRef.current ? 'grabbing' : 'grab' }}>
            <defs>
              <marker id="arr-def" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <path d="M0,0 L0,7 L10,3.5 z" fill={ARROW_DEFAULT} />
              </marker>
              <marker id="arr-out" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <path d="M0,0 L0,7 L10,3.5 z" fill={ARROW_OUT} />
              </marker>
              <marker id="arr-in" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <path d="M0,0 L0,7 L10,3.5 z" fill={ARROW_IN} />
              </marker>
              <filter id="glow">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
            </defs>

            <rect width="100%" height="100%" fill="transparent" onMouseDown={handleBgMouseDown} />

            <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>

              {/* Edges */}
              {simEdgesRef.current.map((e, i) => {
                const src = visibleNodes.find((n) => n.id === e.sourceId)
                const tgt = visibleNodes.find((n) => n.id === e.targetId)
                if (!src || !tgt) return null

                const isOut = selectedId === e.sourceId || hoveredId === e.sourceId
                const isIn  = selectedId === e.targetId || hoveredId === e.targetId
                const hiOut = isOut && !isIn
                const hiIn  = isIn && !isOut
                const hi    = isOut || isIn

                const strokeColor  = hiOut ? EDGE_OUT : hiIn ? EDGE_IN : EDGE_DEFAULT
                const arrowMarker  = hiOut ? 'url(#arr-out)' : hiIn ? 'url(#arr-in)' : 'url(#arr-def)'
                const strokeW      = hi ? Math.max(2, e.weight * 0.6) : 1.2
                const strokeOp     = hi ? 1 : 0.5

                // Curved path
                const dx = tgt.x - src.x, dy = tgt.y - src.y
                const len = Math.sqrt(dx * dx + dy * dy) || 1
                const tr = nodeRadius(tgt as SimNode)
                // shorten end point to not overlap node
                const ex = tgt.x - (dx / len) * (tr + 10)
                const ey = tgt.y - (dy / len) * (tr + 10)
                const mx = (src.x + ex) / 2
                const my = (src.y + ey) / 2
                const perp = Math.min(len * 0.18, 35)
                const cpx  = mx - (dy / len) * perp
                const cpy  = my + (dx / len) * perp
                const midX = (src.x + 2 * cpx + ex) / 4
                const midY = (src.y + 2 * cpy + ey) / 4

                return (
                  <g key={i}>
                    <path
                      d={`M${src.x},${src.y} Q${cpx},${cpy} ${ex},${ey}`}
                      fill="none"
                      stroke={strokeColor}
                      strokeWidth={strokeW}
                      strokeOpacity={strokeOp}
                      markerEnd={arrowMarker}
                      filter={hi ? 'url(#glow)' : undefined}
                    />
                    {hi && e.weight > 1 && (
                      <>
                        <rect x={midX - 11} y={midY - 8} width={22} height={14} rx={4}
                          fill="#1c1d28" opacity={0.85} />
                        <text x={midX} y={midY + 1} textAnchor="middle" dominantBaseline="middle"
                          fontSize="9" fill={hiOut ? ARROW_OUT : ARROW_IN}
                          className="pointer-events-none select-none font-mono">
                          ×{e.weight}
                        </text>
                      </>
                    )}
                  </g>
                )
              })}

              {/* Nodes */}
              {visibleNodes.map((node) => {
                const r = nodeRadius(node)
                const color = nodeColor(node.id)
                const isSel = selectedId === node.id
                const isHov = hoveredId === node.id
                const label = node.label.length > 26 ? node.label.slice(0, 26) + '…' : node.label
                const labelW = label.length * 6.2 + 12

                return (
                  <g key={node.id}
                    transform={`translate(${node.x},${node.y})`}
                    style={{ cursor: 'pointer' }}
                    onClick={(e) => { e.stopPropagation(); setSelectedId(selectedId === node.id ? null : node.id) }}
                    onMouseDown={(e) => handleNodeMouseDown(e, node.id)}
                    onMouseEnter={(e) => {
                      setHoveredId(node.id)
                      const rect = containerRef.current!.getBoundingClientRect()
                      setTooltipNode({ id: node.id, x: e.clientX - rect.left, y: e.clientY - rect.top })
                    }}
                    onMouseLeave={() => { setHoveredId(null); setTooltipNode(null) }}
                  >
                    {/* Glow ring on select/hover */}
                    {(isSel || isHov) && (
                      <circle r={r + 8} fill={color} fillOpacity={0.18} />
                    )}
                    {/* Node circle */}
                    <circle r={r}
                      fill={color}
                      fillOpacity={isSel ? 1 : 0.85}
                      stroke={isSel ? '#fff' : color}
                      strokeWidth={isSel ? 2.5 : 1}
                      strokeOpacity={isSel ? 1 : 0.4}
                      filter={isSel ? 'url(#glow)' : undefined}
                    />
                    {/* Connection count badge */}
                    {node.connectionCount > 0 && (
                      <text y={r * 0.4} textAnchor="middle" dominantBaseline="middle"
                        fontSize={r > 18 ? '10' : '8'} fill="rgba(255,255,255,0.9)"
                        fontWeight="700" className="pointer-events-none select-none">
                        {node.connectionCount}
                      </text>
                    )}
                    {/* Label with background pill */}
                    <rect
                      x={-labelW / 2} y={r + 6}
                      width={labelW} height={16} rx={4}
                      fill="#0a0b10" fillOpacity={0.82}
                    />
                    <text
                      y={r + 15} textAnchor="middle" dominantBaseline="middle"
                      fontSize="11"
                      fill={isSel ? '#fff' : isHov ? '#e8eaf2' : '#8082a0'}
                      fontWeight={isSel ? '600' : '400'}
                      className="pointer-events-none select-none"
                    >
                      {label}
                    </text>
                  </g>
                )
              })}
            </g>
          </svg>

          {/* Hover tooltip for full filename */}
          {tooltipNode && (() => {
            const full = graphData.nodes.find((n) => n.id === tooltipNode.id)?.label ?? ''
            if (full.length <= 26) return null
            return (
              <div
                className="absolute z-20 pointer-events-none px-2.5 py-1.5 rounded-lg text-xs bg-dark-sidebar border border-dark-chat text-dark-text shadow-xl max-w-xs break-all"
                style={{ left: tooltipNode.x + 12, top: tooltipNode.y - 30 }}
              >
                {full}
              </div>
            )
          })()}
        </div>

        {/* Right panel — details */}
        <div className="w-64 flex-shrink-0 border-l border-dark-chat bg-dark-sidebar flex flex-col overflow-y-auto">
          {!selectedNode ? (
            <div className="flex items-center justify-center h-full text-center p-6">
              <p className="text-sm text-dark-muted">Click a node to see its connections</p>
            </div>
          ) : (
            <div className="p-4 space-y-4">
              <div>
                <h2 className="text-sm font-semibold text-dark-text leading-tight break-words">
                  {selectedNode.label}
                </h2>
                <p className="text-xs text-dark-muted mt-1">
                  {outgoingEdges.length} references out · {incomingEdges.length} referenced by
                </p>
              </div>

              {outgoingEdges.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-dark-muted uppercase tracking-wider mb-2">
                    References
                  </p>
                  <div className="space-y-1">
                    {outgoingEdges.map((e, i) => {
                      const tgt = graphData.nodes.find((n) => n.id === e.target)
                      return (
                        <div key={i} className="flex items-start gap-2 text-xs">
                          <span className="text-violet-400 font-mono flex-shrink-0 mt-0.5">→</span>
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

              {incomingEdges.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-dark-muted uppercase tracking-wider mb-2">
                    Referenced By
                  </p>
                  <div className="space-y-1">
                    {incomingEdges.map((e, i) => {
                      const src = graphData.nodes.find((n) => n.id === e.source)
                      return (
                        <div key={i} className="flex items-start gap-2 text-xs">
                          <button className="text-left flex-1 text-dark-text hover:text-white break-words"
                            onClick={() => setSelectedId(e.source)}>
                            {src?.label ?? `Doc #${e.source}`}
                          </button>
                          <span className="text-emerald-400 font-mono flex-shrink-0 mt-0.5">→</span>
                          {e.weight > 1 && <span className="text-dark-muted flex-shrink-0">×{e.weight}</span>}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {outgoingEdges.length === 0 && incomingEdges.length === 0 && (
                <p className="text-xs text-dark-muted">No connections for this document.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
