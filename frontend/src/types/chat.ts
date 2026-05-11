export type MessageRole = 'user' | 'assistant' | 'system'

export interface Attachment {
  id: number
  filename: string
  original_filename: string
  content_type: string
  file_size: number
  url: string
  is_image: boolean
}

export interface Message {
  id: number
  conversation_id: number
  role: MessageRole
  content: string
  created_at: string
  attachments: Attachment[]
}

export interface Conversation {
  id: number
  title: string
  user_id: number | null
  anonymous_session_id: string | null
  created_at: string
  updated_at: string
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[]
}

export interface SendMessageRequest {
  content: string
  attachment_ids: number[]
}

export interface UploadResponse {
  id: number
  filename: string
  original_filename: string
  content_type: string
  file_size: number
  url: string
  is_image: boolean
}
