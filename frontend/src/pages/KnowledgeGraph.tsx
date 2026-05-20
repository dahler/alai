import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { graphService, GraphNode, GraphData, EntityDetail } from '../services/graph'
import { documentsService, Document } from '../services/documents'

// ─── Colour helpers ───────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  pasal: '#f59e0b',
  person: '#60a5fa',
  organization: '#a78bfa',
  company: '#818cf8',
  regulation: '#fb923c',
  product: '#34d399',
  technology: '#22d3ee',
  country: '#f87171',
  location: '#2dd4bf',
  date: '#9ca3af',
  concept: '#fbbf24',
  event: '#f472b6',
  document: '#a3e635',
  standard: '#86efac',
  process: '#fdba74',
}

const getColor = (type: string) => TYPE_COLORS[type] ?? '#e5e7eb'
const getRadius = (count: number) =>
  Math.max(7, Math.min(22, 7 + Math.log2(count + 1) * 3.5))

// ─── Simulation types ─────────────────────────────────────────────────────────

interface SimNode extends GraphNode {
  x: number
  y: number
  vx: number
  vy: number
  pinned?: boolean
}

interface SimEdge {
  sourceId: number
  targetId: number
  relation: string
  confidence: number
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
  // Repulsion between all node pairs
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[j].x - nodes[i].x || 0.1
      const dy = nodes[j].y - nodes[i].y || 0.1
      const dist2 = Math.max(dx * dx + dy * dy, 1)
      const dist = Math.sqrt(dist2)
      const f = (alpha * 4000) / dist2
      nodes[i].vx -= (dx / dist) * f
      nodes[i].vy -= (dy / dist) * f
      nodes[j].vx += (dx / dist) * f
      nodes[j].vy += (dy / dist) * f
    }
  }
  // Spring force along edges (target distance: 140 px)
  const map = new Map(nodes.map((n) => [n.id, n]))
  for (const e of edges) {
    const s = map.get(e.sourceId)
    const t = map.get(e.targetId)
    if (!s || !t) continue
    const dx = t.x - s.x
    const dy = t.y - s.y
    const dist = Math.sqrt(dx * dx + dy * dy) || 1
    const f = (dist - 180) * alpha * 0.25
    s.vx += (dx / dist) * f
    s.vy += (dy / dist) * f
    t.vx -= (dx / dist) * f
    t.vy -= (dy / dist) * f
  }
  // Centre gravity + damping + position update
  for (const n of nodes) {
    if (n.pinned) {
      n.vx = 0
      n.vy = 0
      continue
    }
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

// ─── Component ────────────────────────────────────────────────────────────────

export function KnowledgeGraph() {
  const navigate = useNavigate()

  // ── Data state ──────────────────────────────────────────────────────────────
  const [docs, setDocs] = useState<Document[]>([])
  const [selectedDocId, setSelectedDocId] = useState<number | 'all'>('all')
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] })
  const [isLoading, setIsLoading] = useState(true)
  const [totalStats, setTotalStats] = useState({ entities: 0, relationships: 0 })

  // ── Simulation refs ─────────────────────────────────────────────────────────
  const simNodesRef = useRef<SimNode[]>([])
  const simEdgesRef = useRef<SimEdge[]>([])
  const alphaRef = useRef(0)
  const rafRef = useRef<number>()
  const [tick, setTick] = useState(0)

  // ── SVG size ────────────────────────────────────────────────────────────────
  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [svgSize, setSvgSize] = useState({ w: 800, h: 600 })

  // ── Interaction state ────────────────────────────────────────────────────────
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 })
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null)
  const [entityDetail, setEntityDetail] = useState<EntityDetail | null>(null)
  const [isDetailLoading, setIsDetailLoading] = useState(false)
  const [hoveredNodeId, setHoveredNodeId] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [enabledTypes, setEnabledTypes] = useState<Set<string>>(new Set())
  const [isPasalView, setIsPasalView] = useState(false)
  const [isHubMode, setIsHubMode] = useState(false)

  // ── Drag / pan refs ─────────────────────────────────────────────────────────
  const nodeDragRef = useRef<{
    id: number
    ox: number
    oy: number
    mx: number
    my: number
  } | null>(null)
  const panDragRef = useRef<{
    mx: number
    my: number
    tx: number
    ty: number
  } | null>(null)

  // ── Load documents on mount ──────────────────────────────────────────────────
  useEffect(() => {
    documentsService.list().then((data) => {
      const withGraph = [
        ...(data.personal_documents ?? []),
        ...(data.company_documents ?? []),
      ].filter((d) => d.graph_status === 'done')
      setDocs(withGraph)
    })
  }, [])

  // ── Load graph data when selectedDocId changes ───────────────────────────────
  useEffect(() => {
    setIsLoading(true)
    const promise =
      selectedDocId === 'all'
        ? graphService.getOverview(120)
        : graphService.getDocumentGraph(selectedDocId as number)
    promise
      .then((data) => {
        setGraphData(data)
        setTotalStats({
          entities: data.nodes.length,
          relationships: data.edges.length,
        })
        setEnabledTypes(new Set(data.nodes.map((n) => n.type)))
        setIsLoading(false)
        setSelectedNodeId(null)
        setEntityDetail(null)
      })
      .catch(() => setIsLoading(false))
  }, [selectedDocId])

  // ── Resize observer ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      setSvgSize({ w: width, h: height })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // ── Initialise simulation when graph data or container size changes ───────────
  useEffect(() => {
    if (graphData.nodes.length === 0) return
    cancelAnimationFrame(rafRef.current!)
    const { w, h } = svgSize
    const cx = w / 2
    const cy = h / 2

    const spread = Math.max(300, Math.sqrt(graphData.nodes.length) * 35)
    simNodesRef.current = graphData.nodes.map((n) => ({
      ...n,
      x: cx + (Math.random() - 0.5) * spread,
      y: cy + (Math.random() - 0.5) * spread,
      vx: 0,
      vy: 0,
    }))
    simEdgesRef.current = graphData.edges.map((e) => ({
      sourceId: e.source_id,
      targetId: e.target_id,
      relation: e.relation,
      confidence: e.confidence,
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

  // ── Node click → fetch entity detail ────────────────────────────────────────
  const handleNodeClick = useCallback(async (nodeId: number) => {
    setSelectedNodeId(nodeId)
    setEntityDetail(null)
    setIsHubMode(false)
    setIsDetailLoading(true)
    try {
      const detail = await graphService.getEntityDetail(nodeId)
      setEntityDetail(detail)
      setIsHubMode(true)
    } finally {
      setIsDetailLoading(false)
    }
  }, [])

  // ── Mouse events ─────────────────────────────────────────────────────────────
  const handleNodeMouseDown = (e: React.MouseEvent, nodeId: number) => {
    e.stopPropagation()
    const node = simNodesRef.current.find((n) => n.id === nodeId)
    if (!node) return
    nodeDragRef.current = {
      id: nodeId,
      ox: node.x,
      oy: node.y,
      mx: e.clientX,
      my: e.clientY,
    }
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
      const node = simNodesRef.current.find(
        (n) => n.id === nodeDragRef.current!.id,
      )
      if (node) node.pinned = false
      nodeDragRef.current = null
    }
    panDragRef.current = null
  }

  const handleBgMouseDown = (e: React.MouseEvent) => {
    if (
      e.target === e.currentTarget ||
      (e.target as SVGElement).tagName === 'rect'
    ) {
      if (isHubMode) {
        setIsHubMode(false)
        setSelectedNodeId(null)
        setEntityDetail(null)
        return
      }
      panDragRef.current = {
        mx: e.clientX,
        my: e.clientY,
        tx: transform.x,
        ty: transform.y,
      }
    }
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const factor = e.deltaY > 0 ? 0.9 : 1.1
    setTransform((prev) => {
      const newK = Math.max(0.2, Math.min(5, prev.k * factor))
      return { ...prev, k: newK }
    })
  }

  // ── Derived display data ──────────────────────────────────────────────────────
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const visibleNodes = useMemo(() => {
    const q = searchQuery.toLowerCase()
    return simNodesRef.current.filter((n) => {
      if (isPasalView && n.type !== 'pasal') return false
      return enabledTypes.has(n.type) && (!q || n.name.toLowerCase().includes(q))
    })
  }, [tick, searchQuery, enabledTypes, isPasalView]) // tick ensures re-compute after each simulation step

  const visibleNodeIds = useMemo(
    () => new Set(visibleNodes.map((n) => n.id)),
    [visibleNodes],
  )

  const visibleEdges = useMemo(
    () =>
      simEdgesRef.current.filter(
        (e) => visibleNodeIds.has(e.sourceId) && visibleNodeIds.has(e.targetId),
      ),
    [visibleNodes, visibleNodeIds],
  )

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    graphData.nodes.forEach((n) => {
      counts[n.type] = (counts[n.type] ?? 0) + 1
    })
    return counts
  }, [graphData])

  // ── Hub-and-spoke layout (computed when a node is selected) ──────────────────
  const hubSpoke = useMemo(() => {
    if (!isHubMode || !entityDetail || selectedNodeId === null) return null
    const { w, h } = svgSize
    const cx = w / 2
    const cy = h / 2
    const radius = Math.min(w, h) * 0.36

    type Spoke = {
      nodeId: number; name: string; type: string
      relation: string; direction: 'out' | 'in'
      context?: string; chunk_text?: string
      confidence: number; x: number; y: number
    }

    const seen = new Set<number>()
    const spokes: Spoke[] = []
    for (const r of entityDetail.outgoing_relationships) {
      if (!seen.has(r.target_id)) {
        seen.add(r.target_id)
        spokes.push({ nodeId: r.target_id, name: r.target_name, type: r.target_type, relation: r.relation, direction: 'out', context: r.context, chunk_text: r.chunk_text, confidence: r.confidence, x: 0, y: 0 })
      }
    }
    for (const r of entityDetail.incoming_relationships) {
      if (!seen.has(r.source_id)) {
        seen.add(r.source_id)
        spokes.push({ nodeId: r.source_id, name: r.source_name, type: r.source_type, relation: r.relation, direction: 'in', context: r.context, chunk_text: r.chunk_text, confidence: r.confidence, x: 0, y: 0 })
      }
    }
    spokes.forEach((s, i) => {
      const angle = (2 * Math.PI * i) / spokes.length - Math.PI / 2
      s.x = cx + Math.cos(angle) * radius
      s.y = cy + Math.sin(angle) * radius
    })
    return { hub: { x: cx, y: cy, id: selectedNodeId, name: entityDetail.name, type: entityDetail.type }, spokes, cx, cy }
  }, [isHubMode, entityDetail, selectedNodeId, svgSize])

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-screen bg-dark-bg text-dark-text">
      {/* ── Header ── */}
      <div className="flex items-center gap-4 px-4 py-3 border-b border-dark-chat flex-shrink-0">
        <button
          onClick={() => navigate('/')}
          className="p-2 hover:bg-dark-chat rounded-lg text-dark-muted hover:text-dark-text"
          title="Back"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15 19l-7-7 7-7"
            />
          </svg>
        </button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">Knowledge Graph</h1>
          <p className="text-xs text-dark-muted">
            {totalStats.entities} entities · {totalStats.relationships} relationships
          </p>
        </div>

        {/* Pasal View toggle */}
        <button
          onClick={() => setIsPasalView((v) => !v)}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            isPasalView
              ? 'bg-amber-500 text-black'
              : 'bg-dark-chat text-dark-muted hover:text-dark-text'
          }`}
          title="Show only Pasal entities and their cross-document relationships"
        >
          {isPasalView ? '✕ Pasal View' : 'Pasal View'}
        </button>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* ── Left panel ── */}
        <div className="w-64 flex-shrink-0 border-r border-dark-chat flex flex-col overflow-y-auto bg-dark-sidebar p-3 gap-4">
          {/* Document filter */}
          <div>
            <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">
              Document
            </p>
            <select
              value={selectedDocId}
              onChange={(e) =>
                setSelectedDocId(
                  e.target.value === 'all' ? 'all' : Number(e.target.value),
                )
              }
              className="w-full bg-dark-chat text-dark-text text-sm rounded-lg px-2 py-1.5 border border-dark-chat"
            >
              <option value="all">All documents</option>
              {docs.length === 0 && (
                <option disabled value="">
                  No graph-ready documents
                </option>
              )}
              {docs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.filename}
                </option>
              ))}
            </select>
          </div>

          {/* Search */}
          <div>
            <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">
              Search
            </p>
            <input
              type="text"
              placeholder="Filter entities..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-dark-chat text-sm text-dark-text rounded-lg px-2 py-1.5 border border-dark-chat placeholder-dark-muted"
            />
          </div>

          {/* Entity types */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide">
                Entity Types
              </p>
              <div className="flex gap-1">
                <button
                  onClick={() => setEnabledTypes(new Set(Object.keys(typeCounts)))}
                  className="text-xs text-dark-muted hover:text-dark-text px-1.5 py-0.5 rounded hover:bg-dark-chat"
                >
                  All
                </button>
                <span className="text-dark-chat">|</span>
                <button
                  onClick={() => setEnabledTypes(new Set())}
                  className="text-xs text-dark-muted hover:text-dark-text px-1.5 py-0.5 rounded hover:bg-dark-chat"
                >
                  None
                </button>
              </div>
            </div>
            <div className="space-y-1">
              {Object.entries(typeCounts)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => (
                  <label
                    key={type}
                    className="flex items-center gap-2 cursor-pointer hover:bg-dark-chat rounded px-1 py-0.5"
                  >
                    <input
                      type="checkbox"
                      checked={enabledTypes.has(type)}
                      onChange={(e) => {
                        const next = new Set(enabledTypes)
                        e.target.checked ? next.add(type) : next.delete(type)
                        setEnabledTypes(next)
                      }}
                      className="w-3 h-3 rounded"
                    />
                    <span
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: getColor(type) }}
                    />
                    <span className="text-xs text-dark-text flex-1 truncate capitalize">
                      {type}
                    </span>
                    <span className="text-xs text-dark-muted">{count}</span>
                  </label>
                ))}
            </div>
          </div>

          {/* Zoom controls */}
          <div className="mt-auto">
            <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">
              View
            </p>
            <div className="flex gap-2">
              <button
                onClick={() =>
                  setTransform((p) => ({ ...p, k: Math.min(5, p.k * 1.2) }))
                }
                className="flex-1 py-1 text-xs bg-dark-chat hover:bg-dark-hover rounded text-dark-muted hover:text-dark-text"
              >
                + Zoom
              </button>
              <button
                onClick={() =>
                  setTransform((p) => ({ ...p, k: Math.max(0.2, p.k * 0.8) }))
                }
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

        {/* ── SVG Graph ── */}
        <div
          ref={containerRef}
          className="flex-1 relative overflow-hidden"
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
        >
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-dark-muted">Loading graph...</div>
            </div>
          )}
          {!isLoading && graphData.nodes.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-8">
              <p className="text-dark-muted">No graph data yet.</p>
              <p className="text-sm text-dark-muted mt-1">
                Upload documents with "Extract Knowledge Graph" enabled.
              </p>
            </div>
          )}
          {!isLoading && graphData.nodes.length > 0 && isPasalView && visibleNodes.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-8 pointer-events-none">
              <p className="text-amber-400 font-medium">No pasal entities found</p>
              <p className="text-sm text-dark-muted mt-2 max-w-xs">
                Existing documents were processed before pasal extraction was added.
                Re-upload or re-process your documents to extract pasal entities.
              </p>
            </div>
          )}
          <svg
            ref={svgRef}
            width="100%"
            height="100%"
            onWheel={handleWheel}
            style={{ cursor: panDragRef.current ? 'grabbing' : 'grab' }}
          >
            <defs>
              <marker
                id="arrow"
                markerWidth="8"
                markerHeight="8"
                refX="8"
                refY="3"
                orient="auto"
              >
                <path d="M0,0 L0,6 L8,3 z" fill="#4b5563" />
              </marker>
            </defs>
            <rect
              width="100%"
              height="100%"
              fill="transparent"
              onMouseDown={handleBgMouseDown}
            />
            <g
              transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}
            >
            {isHubMode && hubSpoke ? (
              /* ── Hub-and-spoke layout ── */
              <>
                {/* Lines: hub ↔ each spoke */}
                {hubSpoke.spokes.map((spoke, i) => {
                  const x1 = spoke.direction === 'out' ? hubSpoke.cx : spoke.x
                  const y1 = spoke.direction === 'out' ? hubSpoke.cy : spoke.y
                  const x2 = spoke.direction === 'out' ? spoke.x : hubSpoke.cx
                  const y2 = spoke.direction === 'out' ? spoke.y : hubSpoke.cy
                  const lmx = (x1 + x2) / 2
                  const lmy = (y1 + y2) / 2
                  return (
                    <g key={`l${i}`}>
                      <line x1={x1} y1={y1} x2={x2} y2={y2}
                        stroke="#6b7280" strokeWidth={1.5} strokeOpacity={0.7}
                        markerEnd="url(#arrow)"
                      />
                      <text x={lmx} y={lmy - 6} textAnchor="middle" fontSize="8"
                        fill="#9ca3af" stroke="#111827" strokeWidth="2.5"
                        paintOrder="stroke" className="pointer-events-none select-none"
                      >
                        {spoke.relation.replace(/_/g, ' ')}
                      </text>
                    </g>
                  )
                })}

                {/* Spoke nodes */}
                {hubSpoke.spokes.map((spoke, i) => {
                  const r = 11
                  const color = getColor(spoke.type)
                  const isHov = hoveredNodeId === spoke.nodeId
                  const evidence = spoke.context || spoke.chunk_text || ''
                  return (
                    <g key={`s${i}`} transform={`translate(${spoke.x},${spoke.y})`}
                      style={{ cursor: 'pointer' }}
                      onClick={() => handleNodeClick(spoke.nodeId)}
                      onMouseEnter={() => setHoveredNodeId(spoke.nodeId)}
                      onMouseLeave={() => setHoveredNodeId(null)}
                    >
                      {isHov && <circle r={r + 5} fill={color} fillOpacity={0.2} />}
                      <circle r={r} fill={color} fillOpacity={isHov ? 1 : 0.85} />
                      <text y={r + 13} textAnchor="middle" fontSize="10"
                        fill="#f9fafb" stroke="#111827" strokeWidth="3"
                        paintOrder="stroke" className="pointer-events-none select-none"
                      >
                        {spoke.name.length > 22 ? spoke.name.slice(0, 22) + '…' : spoke.name}
                      </text>
                      {evidence && (
                        <foreignObject x={-110} y={r + 28} width={220} height={88}>
                          <div
                            style={{
                              fontSize: '9px', color: '#9ca3af', textAlign: 'center',
                              lineHeight: '1.4', wordBreak: 'break-word',
                              background: 'rgba(17,24,39,0.88)',
                              borderRadius: '5px', padding: '4px 6px',
                              border: '1px solid rgba(75,85,99,0.4)',
                            }}
                          >
                            {evidence.length > 180 ? evidence.slice(0, 180) + '…' : evidence}
                          </div>
                        </foreignObject>
                      )}
                    </g>
                  )
                })}

                {/* Hub node — on top */}
                <g transform={`translate(${hubSpoke.cx},${hubSpoke.cy})`}>
                  <circle r={30} fill={getColor(hubSpoke.hub.type)} fillOpacity={0.95}
                    stroke="#fff" strokeWidth={2.5}
                  />
                  <text y={43} textAnchor="middle" fontSize="11" fontWeight="600"
                    fill="#f9fafb" stroke="#111827" strokeWidth="3"
                    paintOrder="stroke" className="pointer-events-none select-none"
                  >
                    {hubSpoke.hub.name.length > 24
                      ? hubSpoke.hub.name.slice(0, 24) + '…'
                      : hubSpoke.hub.name}
                  </text>
                </g>
              </>
            ) : (
              /* ── Force-directed layout ── */
              <>
              {/* Edges */}
              {visibleEdges.map((e, i) => {
                const src = simNodesRef.current.find((n) => n.id === e.sourceId)
                const tgt = simNodesRef.current.find((n) => n.id === e.targetId)
                if (!src || !tgt) return null
                const isHovered =
                  hoveredNodeId === e.sourceId ||
                  hoveredNodeId === e.targetId ||
                  selectedNodeId === e.sourceId ||
                  selectedNodeId === e.targetId
                // Quadratic bezier: control point offset perpendicular to edge
                const dx = tgt.x - src.x
                const dy = tgt.y - src.y
                const len = Math.sqrt(dx * dx + dy * dy) || 1
                const mx = (src.x + tgt.x) / 2
                const my = (src.y + tgt.y) / 2
                const px = -dy / len
                const py = dx / len
                const curve = Math.min(len * 0.25, 45)
                const cpx = mx + px * curve
                const cpy = my + py * curve
                // Midpoint on the bezier (t=0.5)
                const labelX = (src.x + 2 * cpx + tgt.x) / 4
                const labelY = (src.y + 2 * cpy + tgt.y) / 4
                return (
                  <g key={i}>
                    <path
                      d={`M${src.x},${src.y} Q${cpx},${cpy} ${tgt.x},${tgt.y}`}
                      fill="none"
                      stroke={isHovered ? '#6b7280' : '#374151'}
                      strokeWidth={isHovered ? 1.5 : 1}
                      strokeOpacity={isHovered ? 0.9 : 0.4}
                      markerEnd="url(#arrow)"
                    />
                    <text
                      x={labelX}
                      y={labelY}
                      textAnchor="middle"
                      dominantBaseline="middle"
                      fontSize="7"
                      fill={isHovered ? '#d1d5db' : '#6b7280'}
                      stroke="#111827"
                      strokeWidth="2.5"
                      paintOrder="stroke"
                      className="pointer-events-none select-none"
                    >
                      {e.relation.replace(/_/g, ' ')}
                    </text>
                  </g>
                )
              })}

              {/* Nodes */}
              {visibleNodes.map((node) => {
                const r = getRadius(node.mention_count)
                const color = getColor(node.type)
                const isSelected = selectedNodeId === node.id
                const isHovered = hoveredNodeId === node.id
                const isHighlighted =
                  !!searchQuery &&
                  node.name.toLowerCase().includes(searchQuery.toLowerCase())
                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x},${node.y})`}
                    style={{ cursor: 'pointer' }}
                    onClick={() => handleNodeClick(node.id)}
                    onMouseDown={(e) => handleNodeMouseDown(e, node.id)}
                    onMouseEnter={() => setHoveredNodeId(node.id)}
                    onMouseLeave={() => setHoveredNodeId(null)}
                  >
                    {(isSelected || isHovered) && (
                      <circle r={r + 5} fill={color} fillOpacity={0.2} />
                    )}
                    {isHighlighted && !isSelected && (
                      <circle
                        r={r + 7}
                        fill="none"
                        stroke="#fbbf24"
                        strokeWidth={2}
                        strokeOpacity={0.7}
                      />
                    )}
                    <circle
                      r={r}
                      fill={color}
                      fillOpacity={isSelected ? 1 : 0.85}
                      stroke={isSelected ? '#fff' : color}
                      strokeWidth={isSelected ? 2 : 0}
                    />
                    <text
                      y={r + 12}
                      textAnchor="middle"
                      fontSize={Math.max(9, Math.min(11, 9 + Math.log2(node.mention_count + 1)))}
                      fill={isSelected || isHovered ? '#f9fafb' : '#d1d5db'}
                      stroke="#111827"
                      strokeWidth="3"
                      paintOrder="stroke"
                      className="pointer-events-none select-none"
                    >
                      {node.name.length > 18
                        ? node.name.slice(0, 18) + '…'
                        : node.name}
                    </text>
                  </g>
                )
              })}
              </>
            )}
            </g>
          </svg>

          {/* Back button in hub mode */}
          {isHubMode && (
            <button
              onClick={() => { setIsHubMode(false); setSelectedNodeId(null); setEntityDetail(null) }}
              className="absolute top-3 left-3 px-3 py-1.5 bg-dark-chat hover:bg-dark-hover text-dark-muted hover:text-dark-text text-xs rounded-lg border border-dark-chat"
            >
              ← Back to graph
            </button>
          )}

          {/* Legend */}
          <div className="absolute bottom-3 left-3 bg-dark-sidebar border border-dark-chat rounded-lg px-3 py-2 text-xs text-dark-muted">
            <p className="font-medium text-dark-text mb-1">Tip</p>
            {isHubMode
              ? <p>Click a spoke node to navigate · Click background to return</p>
              : <p>Drag nodes · Scroll to zoom · Drag background to pan · Click for details</p>
            }
          </div>
        </div>

        {/* ── Right panel — entity details ── */}
        <div className="w-80 flex-shrink-0 border-l border-dark-chat bg-dark-sidebar flex flex-col overflow-y-auto">
          {!selectedNodeId ? (
            <div className="flex items-center justify-center h-full text-center p-6">
              <p className="text-sm text-dark-muted">
                Click a node to see entity details
              </p>
            </div>
          ) : isDetailLoading ? (
            <div className="flex items-center justify-center h-full">
              <p className="text-dark-muted text-sm">Loading...</p>
            </div>
          ) : entityDetail ? (
            <div className="p-4 space-y-4">
              {/* Entity header */}
              <div>
                <div className="flex items-start justify-between gap-2 mb-1">
                  <h2 className="text-base font-semibold text-dark-text leading-tight">
                    {entityDetail.name}
                  </h2>
                  <span
                    className="text-xs px-2 py-0.5 rounded-full flex-shrink-0 font-medium capitalize"
                    style={{
                      backgroundColor: getColor(entityDetail.type) + '33',
                      color: getColor(entityDetail.type),
                    }}
                  >
                    {entityDetail.type}
                  </span>
                </div>
                <p className="text-xs text-dark-muted">
                  {entityDetail.mention_count} mention
                  {entityDetail.mention_count !== 1 ? 's' : ''}
                </p>
              </div>

              {/* Outgoing relationships */}
              {entityDetail.outgoing_relationships.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">
                    Outgoing
                  </p>
                  <div className="space-y-3">
                    {entityDetail.outgoing_relationships
                      .slice(0, 10)
                      .map((r, i) => (
                        <div key={i} className="space-y-1">
                          <div className="flex items-center gap-2 text-xs">
                            <span className="text-blue-400 font-mono shrink-0">→</span>
                            <span className="text-dark-muted italic shrink-0">
                              {r.relation.replace(/_/g, ' ')}
                            </span>
                            <button
                              className="truncate text-left hover:opacity-80"
                              onClick={() => handleNodeClick(r.target_id)}
                              style={{ color: getColor(r.target_type) }}
                            >
                              {r.target_name}
                            </button>
                          </div>
                          {(r.context || r.chunk_text) && (
                            <p className="text-xs text-dark-muted leading-relaxed pl-4 border-l border-dark-chat italic">
                              {(r.context || r.chunk_text || '').slice(0, 200)}
                              {(r.context || r.chunk_text || '').length > 200 ? '…' : ''}
                            </p>
                          )}
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* Incoming relationships */}
              {entityDetail.incoming_relationships.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">
                    Incoming
                  </p>
                  <div className="space-y-3">
                    {entityDetail.incoming_relationships
                      .slice(0, 10)
                      .map((r, i) => (
                        <div key={i} className="space-y-1">
                          <div className="flex items-center gap-2 text-xs">
                            <button
                              className="truncate text-left hover:opacity-80"
                              onClick={() => handleNodeClick(r.source_id)}
                              style={{ color: getColor(r.source_type) }}
                            >
                              {r.source_name}
                            </button>
                            <span className="text-dark-muted italic shrink-0">
                              {r.relation.replace(/_/g, ' ')}
                            </span>
                            <span className="text-blue-400 font-mono shrink-0">→</span>
                          </div>
                          {(r.context || r.chunk_text) && (
                            <p className="text-xs text-dark-muted leading-relaxed pl-4 border-l border-dark-chat italic">
                              {(r.context || r.chunk_text || '').slice(0, 200)}
                              {(r.context || r.chunk_text || '').length > 200 ? '…' : ''}
                            </p>
                          )}
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* Documents */}
              {entityDetail.documents.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-dark-muted uppercase tracking-wide mb-2">
                    In Documents
                  </p>
                  <div className="space-y-1">
                    {entityDetail.documents.map((d, i) => (
                      <div
                        key={i}
                        className="text-xs flex justify-between items-center"
                      >
                        <span className="text-dark-text truncate">{d.filename}</span>
                        <span className="text-dark-muted ml-2 flex-shrink-0">
                          ×{d.mention_count}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
