import { api } from './api'

export interface GraphNode {
  id: number
  name: string
  type: string
  mention_count: number
}

export interface GraphEdge {
  source_id: number
  relation: string
  target_id: number
  confidence: number
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface OutgoingRel {
  id: number
  relation: string
  target_id: number
  target_name: string
  target_type: string
  confidence: number
  context?: string
  chunk_text?: string
}

export interface IncomingRel {
  id: number
  relation: string
  source_id: number
  source_name: string
  source_type: string
  confidence: number
  context?: string
  chunk_text?: string
}

export interface EntityDetail {
  id: number
  name: string
  type: string
  normalized_name: string
  mention_count: number
  outgoing_relationships: OutgoingRel[]
  incoming_relationships: IncomingRel[]
  documents: { document_id: number; filename: string; mention_count: number }[]
}

export const graphService = {
  async getOverview(limit = 100): Promise<GraphData> {
    const res = await api.get('/graph/overview', { params: { limit } })
    return res.data
  },

  async getDocumentGraph(docId: number): Promise<GraphData> {
    const res = await api.get(`/graph/documents/${docId}`)
    return {
      nodes: (res.data.entities ?? []).map((e: any) => ({
        id: e.id,
        name: e.name,
        type: e.type,
        mention_count: e.mention_count,
      })),
      edges: (res.data.relationships ?? []).map((r: any) => ({
        source_id: r.source_id,
        relation: r.relation,
        target_id: r.target_id,
        confidence: r.confidence ?? 1,
      })),
    }
  },

  async getEntityDetail(entityId: number): Promise<EntityDetail> {
    const res = await api.get(`/graph/entities/${entityId}`)
    return res.data
  },

  async searchEntities(query: string, entityType?: string): Promise<GraphNode[]> {
    const res = await api.get('/graph/entities/search', {
      params: { query, entity_type: entityType || undefined, limit: 40 },
    })
    return (res.data.results ?? []).map((e: any) => ({
      id: e.id,
      name: e.name,
      type: e.type,
      mention_count: e.mention_count,
    }))
  },
}
