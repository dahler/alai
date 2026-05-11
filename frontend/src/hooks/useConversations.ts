import { useEffect } from 'react'
import { useConversationStore } from '../store/conversationStore'

export function useConversations() {
  const {
    conversations,
    currentConversationId,
    isLoading,
    error,
    fetchConversations,
    createConversation,
    deleteConversation,
    renameConversation,
    setCurrentConversation,
    updateConversationInList,
  } = useConversationStore()

  useEffect(() => {
    fetchConversations()
  }, [fetchConversations])

  return {
    conversations,
    currentConversationId,
    isLoading,
    error,
    fetchConversations,
    createConversation,
    deleteConversation,
    renameConversation,
    setCurrentConversation,
    updateConversationInList,
  }
}
