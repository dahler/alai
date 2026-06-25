/**
 * Agent Service - Frontend interface for the agentic AI system
 */

import { api } from './api'

export interface Tool {
  name: string
  description: string
  category: string
  parameters: {
    name: string
    type: string
    description: string
    required: boolean
  }[]
  requires_confirmation: boolean
}

export interface ToolsResponse {
  tools: Tool[]
  count: number
}

export interface AgentEvent {
  type: 'thought' | 'action' | 'observation' | 'final_answer' | 'error' | 'complete'
  content?: string
  tool?: string
  input?: Record<string, unknown>
  result?: string
  status?: string
  message?: string
  sources?: string[]
  trace?: AgentTrace
}

export interface AgentStep {
  step_number: number
  state: string
  thought?: string
  action?: string
  action_input?: Record<string, unknown>
  observation?: string
  error?: string
  timestamp: number
}

export interface AgentTrace {
  task: string
  steps: AgentStep[]
  final_answer?: string
  sources: string[]
  total_time: number
  total_tokens: number
  success: boolean
}

export interface AgentExecuteResponse {
  task: string
  events: AgentEvent[]
  final_answer?: string
  trace?: AgentTrace
  execution_time: number
}

export interface AgentStatus {
  status: string
  capabilities: {
    total_tools: number
    categories: Record<string, number>
    max_steps: number
    features: string[]
  }
  model: string
}

export const agentService = {
  /**
   * List all available tools
   */
  async getTools(): Promise<ToolsResponse> {
    const response = await api.get<ToolsResponse>('/agent/tools')
    return response.data
  },

  /**
   * Execute agent (non-streaming)
   */
  async execute(
    task: string,
    context?: { role: string; content: string }[],
    maxSteps?: number
  ): Promise<AgentExecuteResponse> {
    const response = await api.post<AgentExecuteResponse>('/agent/execute', {
      task,
      context,
      max_steps: maxSteps || 10,
    })
    return response.data
  },

  /**
   * Execute agent with streaming
   */
  async *stream(
    task: string,
    context?: { role: string; content: string }[],
    maxSteps?: number
  ): AsyncGenerator<AgentEvent, void, unknown> {
    const response = await fetch('/api/agent/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify({
        task,
        context,
        max_steps: maxSteps || 10,
      }),
    })

    if (!response.ok) {
      throw new Error(`Agent stream failed: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') return

            try {
              const event = JSON.parse(data) as AgentEvent
              yield event
            } catch {
              // Skip invalid JSON
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  },

  /**
   * Execute a specific tool directly
   */
  async executeTool(
    toolName: string,
    parameters: Record<string, unknown>
  ): Promise<Record<string, unknown>> {
    const response = await api.post(`/agent/tools/${toolName}`, {
      tool_name: toolName,
      parameters,
    })
    return response.data
  },

  /**
   * Get agent system status
   */
  async getStatus(): Promise<AgentStatus> {
    const response = await api.get<AgentStatus>('/agent/status')
    return response.data
  },
}

export default agentService
