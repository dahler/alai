import { useEffect, useRef, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { documentsService, DocGraphNode, DocGraphEdge, DocGraphData } from '../services/documents'

// ─── Simulation types ─────────────────────────────────────────────────────────

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

// ─── Force simulation step ───────────────────────────────────────────────────

const MAX_VELOCITY = 60

function runStep(
  nodes: SimNode[],
  edges: SimEdge[],
  cx: number,
  cy: number,
  alpha: number,
) {
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[j].x - nodes[i].x || 0.1
      const dy = nodes[j].y - nodes[i].y || 0.1
      const dist2 = Math.max(dx * dx + dy * dy, 1)
      const dist = Math.sqrt(dist2)
      const f = (alpha * 5000) / dist2
      nodes[i].vx -= (dx / dist) * f
      nodes[i].vy -= (dy / dist) * f
      nodes[j].vx += (dx / dist) * f
      nodes[j].vy += (dy / dist) * f
    }
  }
  const map = new Map(nodes.map((n) => [n.id, n]))
  for (const e of edges) {
    const s = map.get(e.sourceId)
    const t = map.get(e.targetId)
    if (!s || !t) continue
    const dx = t.x - s.x
    const dy = t.y - s.y
    const dist = Math.sqrt(dx * dx + dy * dy) || 1
    const f = (dist - 200) * alpha * 0.2
    s.vx += (dx / dist) * f
    s.vy += (dy / dist) * f
    t.vx -= (dx / dist) * f
    t.vy -= (dy / dist) * f
  }
  for (const n of nodes) {
    if (n.pinned) { n.vx = 0; n.vy = 0; continue }
    n.vx += (cx - n.x) * alpha * 0.04
    n.vy += (cy - n.y) * alpha * 0.04
    n.vx = Math.max(-MAX_VELOCITY, Math.min(MAX_VELOCITY, n.vx)) * 0.82
    n.vy = Math.max(-MAX_VELOCITY, Math.min(MAX_VELOCITY, n.vy)) * 0.82
    n.x += n.vx
    n.y += n.vy
    if (!isFinite(n.x)) n.x = cx
    if (!isFinite(n.y)) n.y = cy
  }
}

// ─── Colors ───────────────────────────────────────────────────────────────────

const NODE_COLOR = '#60a5fa'
const SELECTED_COLOR = '#f59e0b'
const REFERENCED_COLOR = '#a78bfa'
const REFERENCING_COLOR = '#34d399'

// ─── Component ────────────────────────────────────────────────────────────────

export function DocumentGraph() {
  const navigate = useNavigate()

  const [graphData, setGraphData] = useState<DocGraphData>({ nodes: [], edges: [] })
  const [isLoading, setIsLoading] = useState(true)
  const [isRedetecting, setIsRedetecting] = useState(false)
  const [redetectResult, setRedetectResult] = useState<string | null>(null)

  const simNodesRef = useRef<SimNode[]>([])
  const simEdgesRef = useRef<SimEdge[]>([])
  const alphaRef = useRef(0)
  const rafRef = useRef<number>()
  const [tick, setTick] = useState(0)

  const containerRef = useRef<HTMLDivElement>(null)
  const [svgSize, setSvgSize] = useState({ w: 800, h: 600 })

  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 })
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<number | null>(null)

  const nodeDragRef = useRef<{
    id: number; ox: number; oy: number; mx: number; my: number
  } | null>(null)
  const panDragRef = useRef<{
    mx: number; my: number; tx: number; ty: number
  } | null>(null)

  const loadData = () => {
    setIsLoading(true)
    documentsService
      .getConnections()
      .then((data) => { setGraphData(data); setIsLoading(false) })
      .catch(() => setIsLoading(false))
  }

  const handleRedetect = async () => {
    setIsRedetecting(true)
    setRedetectResult(null)
    try {
      const result = await documentsService.redetectConnections()
      setRedetectResult(
        `Scanned ${result.processed} docs · ${result.total_connections} connections found`
      )
      loadData()
    } catch {
      setRedetectResult('Failed to re-detect connections')
    } finally {
      setIsRedetecting(false)
    }
  }

  useEffect(() => { loadData() }, [])

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      setSvgSize({ w: width, h: height })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (graphData.nodes.length === 0) return
    cancelAnimationFrame(rafRef.current!)
    const { w, h } = svgSize
    const cx = w / 2
    const cy = h / 2

    const connCount = new Map<number, number>()
    for (const e of graphData.edges) {
      connCount.set(e.source, (connCount.get(e.source) ?? 0) + 1)
      connCount.set(e.target, (connCount.get(e.target) ?? 0) + 1)
    }

    const spread = Math.max(300, Math.sqrt(graphData.nodes.length) * 60)
    simNodesRef.current = graphData.nodes.map((n) => ({
      ...n,
      x: cx + (Math.random() - 0.5) * spread,
      y: cy + (Math.random() - 0.5) * spread,
      vx: 0,
      vy: 0,
      connectionCount: connCount.get(n.id) ?? 0,
    }))
    simEdgesRef.current = graphData.edges.map((e) => ({
      sourceId: e.source,
      targetId: e.target,
      weight: e.weight,
    }))
    alphaRef.current = 1

    const animate = () => {
      if (alphaRef.current < 0.005) return
      runStep(simNodesRef.current, simEdgesRef.current, cx, cy, alphaRef.current)
      alphaRef.current *= 0.98
      setTick((t) => t + 1)
      rafRef.current = requestAnimationFrame(animate)
    }
    rafRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(rafRef.current!)
  }, [graphData, svgSize])

  // ── Derived selection state ──────────────────────────────────────────────────

  const selectedNodeEdges = useMemo(() => {
    if (selectedNodeId === null) return { outgoing: [] as DocGraphEdge[], incoming: [] as DocGraphEdge[] }
    return {
      outgoing: graphData.edges.filter((e) => e.source === selectedNodeId),
      incoming: graphData.edges.filter((e) => e.target === selectedNodeId),
    }
  }, [selectedNodeId, graphData])

  const referencedIds = useMemo(
    () => new Set(selectedNodeEdges.outgoing.map((e) => e.target)),
    [selectedNodeEdges],
  )
  const referencingIds = useMemo(
    () => new Set(selectedNodeEdges.incoming.map((e) => e.source)),
    [selectedNodeEdges],
  )

  const selectedNode = useMemo(
    () => graphData.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [selectedNodeId, graphData],
  )

  const getNodeColor = (nodeId: number) => {
    if (nodeId === selectedNodeId) return SELECTED_COLOR
    if (referencedIds.has(nodeId)) return REFERENCED_COLOR
    if (referencingIds.has(nodeId)) return REFERENCING_COLOR
    return NODE_COLOR
  }

  const getNodeRadius = (node: SimNode) =>
    Math.max(10, Math.min(26, 10 + Math.log2(node.connectionCount + 1) * 4))

  // ── Mouse events ─────────────────────────────────────────────────────────────

  const handleNodeMouseDown = (e: React.MouseEvent, nodeId: number) => {
    e.stopPropagation()
    const node = simNodesRef.current.find((n) => n.id === nodeId)
    if (!node) return
    nodeDragRef.current = { id: nodeId, ox: node.x, oy: node.y, mx: e.clientX, my: e.clientY }
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
      setTransform((prev) => ({
        ...prev,
        x: d.tx + (e.clientX - d.mx),
        y: d.ty + (e.clientY - d.my),
      }))
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
      setSelectedNodeId(null)
      panDragRef.current = { mx: e.clientX, my: e.clientY, tx: transform.x, ty: transform.y }
    }
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const factor = e.deltaY > 0 ? 0.9 : 1.1
    setTransform((prev) => ({ ...prev, k: Math.max(0.2, Math.min(5, prev.k * factor)) }))
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const visibleNodes = useMemo(() => simNodesRef.current, [tick])

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-screen bg-dark-bg text-dark-text">
      {/* Header */}
      <div className="flex items-center gap-4 px-4 py-3 border-b border-dark-chat flex-shrink-0">
        <button
          onClick={() => navigate('/')}
          className="p-2 hover:bg-dark-chat rounded-lg text-dark-muted hover:text-dark-text"
          title="Back"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">Document Connection Graph</h1>
          <p className="text-xs text-dark-muted">
            {graphData.nodes.length} documents · {graphData.edges.length} connections
          </p>
        </div>
        {redetectResult && (
          <span className="text-xs text-dark-muted">{redetectResult}</span>
        )}
        <button
          onClick={handleRedetect}
          disabled={isRedetecting}
          className="px-3 py-1.5 rounded-lg text-sm text-dark-muted hover:text-dark-text bg-dark-chat hover:bg-dark-hover disabled:opacity-50"
          title="Re-scan all documents for filename cross-references"
        >
          {isRedetecting ? 'Scanning…' : 'Re-detect All'}
        </button>
        <button
          onClick={loadData}
          className="px-3 py-1.5 rounded-lg text-sm text-dark-muted hover:text-dark-text bg-dark-chat hover:bg-dark-hover"
        >
          Refresh
        </button>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Left panel — legend / controls */}
        <div className="w-52 flex-shrink-0 border-r border-dark-chat flex flex-col bg-dark-sidebar p-3 gap-4">
          <div>
            <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">Legend</p>
            <div className="space-y-2">
              {[
                { color: NODE_COLOR, label: 'Document' },
                { color: SELECTED_COLOR, label: 'Selected' },
                { color: REFERENCED_COLOR, label: 'Referenced by selected' },
                { color: REFERENCING_COLOR, label: 'References selected' },
              ].map(({ color, label }) => (
                <div key={label} className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
                  <span className="text-xs text-dark-muted">{label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="text-xs text-dark-muted space-y-1 border-t border-dark-chat pt-3">
            <p className="font-semibold text-dark-text">How it works</p>
            <p>Arrows show explicit filename references detected in document text during ingestion.</p>
            <p>Node size = number of connections. Edge weight = mention count.</p>
          </div>

          <div className="mt-auto">
            <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">View</p>
            <div className="flex gap-2">
              <button
                onClick={() => setTransform((p) => ({ ...p, k: Math.min(5, p.k * 1.2) }))}
                className="flex-1 py-1 text-xs bg-dark-chat hover:bg-dark-hover rounded text-dark-muted hover:text-dark-text"
              >
                + Zoom
              </button>
              <button
                onClick={() => setTransform((p) => ({ ...p, k: Math.max(0.2, p.k * 0.8) }))}
                className="flex-1 py-1 text-xs bg-dark-chat hover:bg-dark-hover rounded text-dark-muted hover:text-dark-text"
              >
                − Zoom
              </button>
            </div>
            <button
              onClick={() => setTransform({ x: 0, y: 0, k: 1 })}
              className="w-full mt-1 py-1 text-xs bg-dark-chat hover:bg-dark-hover rounded text-dark-muted hover:text-dark-text"
            >
              Reset View
            </button>
          </div>
        </div>

        {/* SVG Graph */}
        <div
          ref={containerRef}
          className="flex-1 relative overflow-hidden"
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
        >
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-dark-muted">Loading connections...</div>
            </div>
          )}
          {!isLoading && graphData.nodes.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-8">
              <p className="text-dark-muted font-medium">No document connections found.</p>
              <p className="text-sm text-dark-muted mt-2 max-w-sm">
                Upload documents that explicitly reference other document filenames.
                Connections are detected automatically during ingestion.
              </p>
            </div>
          )}
          <svg
            width="100%"
            height="100%"
            onWheel={handleWheel}
            style={{ cursor: panDragRef.current ? 'grabbing' : 'grab' }}
          >
            <defs>
              <marker id="doc-arrow" markerWidth="8" markerHeight="8" refX="8" refY="3" orient="auto">
                <path d="M0,0 L0,6 L8,3 z" fill="#4b5563" />
              </marker>
              <marker id="doc-arrow-hi" markerWidth="8" markerHeight="8" refX="8" refY="3" orient="auto">
                <path d="M0,0 L0,6 L8,3 z" fill="#6b7280" />
              </marker>
            </defs>
            <rect width="100%" height="100%" fill="transparent" onMouseDown={handleBgMouseDown} />
            <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
              {/* Edges */}
              {simEdgesRef.current.map((e, i) => {
                const src = visibleNodes.find((n) => n.id === e.sourceId)
                const tgt = visibleNodes.find((n) => n.id === e.targetId)
                if (!src || !tgt) return null
                const isHighlighted =
                  selectedNodeId === e.sourceId || selectedNodeId === e.targetId ||
                  hoveredNodeId === e.sourceId || hoveredNodeId === e.targetId
                const dx = tgt.x - src.x
                const dy = tgt.y - src.y
                const len = Math.sqrt(dx * dx + dy * dy) || 1
                const mx = (src.x + tgt.x) / 2
                const my = (src.y + tgt.y) / 2
                const px = -dy / len
                const py = dx / len
                const curve = Math.min(len * 0.2, 40)
                const cpx = mx + px * curve
                const cpy = my + py * curve
                const labelX = (src.x + 2 * cpx + tgt.x) / 4
                const labelY = (src.y + 2 * cpy + tgt.y) / 4
                return (
                  <g key={i}>
                    <path
                      d={`M${src.x},${src.y} Q${cpx},${cpy} ${tgt.x},${tgt.y}`}
                      fill="none"
                      stroke={isHighlighted ? '#6b7280' : '#374151'}
                      strokeWidth={isHighlighted ? Math.max(1.5, e.weight * 0.5) : 1}
                      strokeOpacity={isHighlighted ? 0.9 : 0.4}
                      markerEnd={isHighlighted ? 'url(#doc-arrow-hi)' : 'url(#doc-arrow)'}
                    />
                    {isHighlighted && e.weight > 1 && (
                      <text
                        x={labelX} y={labelY}
                        textAnchor="middle" dominantBaseline="middle"
                        fontSize="9" fill="#9ca3af"
                        stroke="#111827" strokeWidth="2.5" paintOrder="stroke"
                        className="pointer-events-none select-none"
                      >
                        ×{e.weight}
                      </text>
                    )}
                  </g>
                )
              })}

              {/* Nodes */}
              {visibleNodes.map((node) => {
                const r = getNodeRadius(node)
                const color = getNodeColor(node.id)
                const isSelected = selectedNodeId === node.id
                const isHovered = hoveredNodeId === node.id
                const shortLabel =
                  node.label.length > 22 ? node.label.slice(0, 22) + '…' : node.label
                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x},${node.y})`}
                    style={{ cursor: 'pointer' }}
                    onClick={() => setSelectedNodeId(selectedNodeId === node.id ? null : node.id)}
                    onMouseDown={(e) => handleNodeMouseDown(e, node.id)}
                    onMouseEnter={() => setHoveredNodeId(node.id)}
                    onMouseLeave={() => setHoveredNodeId(null)}
                  >
                    {(isSelected || isHovered) && (
                      <circle r={r + 6} fill={color} fillOpacity={0.15} />
                    )}
                    <circle
                      r={r}
                      fill={color}
                      fillOpacity={isSelected ? 1 : 0.8}
                      stroke={isSelected ? '#fff' : 'none'}
                      strokeWidth={isSelected ? 2 : 0}
                    />
                    <text
                      y={r + 13}
                      textAnchor="middle"
                      fontSize="10"
                      fill={isSelected || isHovered ? '#f9fafb' : '#d1d5db'}
                      stroke="#111827"
                      strokeWidth="3"
                      paintOrder="stroke"
                      className="pointer-events-none select-none"
                    >
                      {shortLabel}
                    </text>
                  </g>
                )
              })}
            </g>
          </svg>

          <div className="absolute bottom-3 left-3 bg-dark-sidebar border border-dark-chat rounded-lg px-3 py-2 text-xs text-dark-muted">
            <p className="font-medium text-dark-text mb-1">Tip</p>
            <p>Drag nodes · Scroll to zoom · Drag background to pan · Click node for details</p>
          </div>
        </div>

        {/* Right panel — selected document details */}
        <div className="w-72 flex-shrink-0 border-l border-dark-chat bg-dark-sidebar flex flex-col overflow-y-auto">
          {!selectedNode ? (
            <div className="flex items-center justify-center h-full text-center p-6">
              <p className="text-sm text-dark-muted">Click a node to see document connections</p>
            </div>
          ) : (
            <div className="p-4 space-y-4">
              <div>
                <h2 className="text-sm font-semibold text-dark-text leading-tight break-words">
                  {selectedNode.label}
                </h2>
                <p className="text-xs text-dark-muted mt-1">
                  {selectedNodeEdges.outgoing.length} references out ·{' '}
                  {selectedNodeEdges.incoming.length} referenced by
                </p>
              </div>

              {selectedNodeEdges.outgoing.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">
                    References
                  </p>
                  <div className="space-y-1">
                    {selectedNodeEdges.outgoing.map((e, i) => {
                      const target = graphData.nodes.find((n) => n.id === e.target)
                      return (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <span className="text-purple-400 font-mono flex-shrink-0">→</span>
                          <button
                            className="text-left truncate flex-1 text-dark-text hover:text-white"
                            onClick={() => setSelectedNodeId(e.target)}
                          >
                            {target?.label ?? `Doc #${e.target}`}
                          </button>
                          {e.weight > 1 && (
                            <span className="text-dark-muted flex-shrink-0">×{e.weight}</span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {selectedNodeEdges.incoming.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">
                    Referenced By
                  </p>
                  <div className="space-y-1">
                    {selectedNodeEdges.incoming.map((e, i) => {
                      const source = graphData.nodes.find((n) => n.id === e.source)
                      return (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <button
                            className="text-left truncate flex-1 text-dark-text hover:text-white"
                            onClick={() => setSelectedNodeId(e.source)}
                          >
                            {source?.label ?? `Doc #${e.source}`}
                          </button>
                          <span className="text-green-400 font-mono flex-shrink-0">→</span>
                          {e.weight > 1 && (
                            <span className="text-dark-muted flex-shrink-0">×{e.weight}</span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {selectedNodeEdges.outgoing.length === 0 &&
                selectedNodeEdges.incoming.length === 0 && (
                  <p className="text-xs text-dark-muted">No connections found for this document.</p>
                )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
