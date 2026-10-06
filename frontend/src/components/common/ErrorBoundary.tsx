import { Component, ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return (
        <div className="min-h-screen bg-dark-bg flex items-center justify-center text-white">
          <div className="text-center space-y-4">
            <p className="text-lg font-semibold">Something went wrong</p>
            <p className="text-sm text-gray-400">{this.state.error?.message}</p>
            <button
              className="px-4 py-2 bg-blue-600 rounded hover:bg-blue-700 text-sm"
              onClick={() => window.location.reload()}
            >
              Reload
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
