import { useParams, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import { ChatWindow } from '../components/chat/ChatWindow'
import { useConversationStore } from '../store/conversationStore'
import { useChatStore } from '../store/chatStore'

export default function Chat() {
  const { conversationId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const setCurrentConversation = useConversationStore(
    (state) => state.setCurrentConversation
  )
  const { clearMessages, sendMessage } = useChatStore()

  useEffect(() => {
    if (!conversationId) {
      navigate('/')
      return
    }

    const id = parseInt(conversationId, 10)
    if (isNaN(id)) {
      navigate('/')
      return
    }

    setCurrentConversation(id)

    const starter = sessionStorage.getItem('starter_prompt')
    if (starter) {
      sessionStorage.removeItem('starter_prompt')
      // Small delay so ChatWindow has mounted and store is ready
      setTimeout(() => sendMessage(id, starter), 200)
    }

    return () => {
      clearMessages()
    }
  }, [conversationId, navigate, setCurrentConversation, clearMessages, sendMessage])

  if (!conversationId) {
    return null
  }

  return <ChatWindow conversationId={parseInt(conversationId, 10)} />
}
