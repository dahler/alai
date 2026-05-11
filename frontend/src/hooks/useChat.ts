import { useChatStore } from '../store/chatStore'

export function useChat() {
  const {
    messages,
    isLoading,
    isStreaming,
    streamingContent,
    error,
    fetchMessages,
    sendMessage,
    clearMessages,
    addMessage,
  } = useChatStore()

  return {
    messages,
    isLoading,
    isStreaming,
    streamingContent,
    error,
    fetchMessages,
    sendMessage,
    clearMessages,
    addMessage,
  }
}
