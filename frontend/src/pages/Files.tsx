import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadsService, FileInfo } from '../services/uploads'

export function Files() {
  const navigate = useNavigate()
  const [files, setFiles] = useState<FileInfo[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [selectedFile, setSelectedFile] = useState<FileInfo | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<number | 'all' | null>(null)

  const fetchFiles = async () => {
    setIsLoading(true)
    try {
      const data = await uploadsService.list()
      setFiles(data)
    } catch (error) {
      console.error('Failed to fetch files:', error)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchFiles()
  }, [])

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return 'Unknown'
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const handleDelete = async (id: number) => {
    try {
      await uploadsService.delete(id)
      setFiles(files.filter(f => f.id !== id))
      setDeleteConfirm(null)
      if (selectedFile?.id === id) {
        setSelectedFile(null)
      }
    } catch (error) {
      console.error('Failed to delete file:', error)
    }
  }

  const handleDeleteAll = async () => {
    try {
      await uploadsService.deleteAll()
      setFiles([])
      setDeleteConfirm(null)
      setSelectedFile(null)
    } catch (error) {
      console.error('Failed to delete all files:', error)
    }
  }

  const getFileIcon = (contentType: string) => {
    if (contentType.startsWith('image/')) {
      return (
        <svg className="w-8 h-8 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      )
    }
    if (contentType === 'application/pdf') {
      return (
        <svg className="w-8 h-8 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
        </svg>
      )
    }
    return (
      <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    )
  }

  return (
    <div className="flex flex-col h-full bg-dark-bg">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-dark-chat">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/')}
            className="p-2 hover:bg-dark-chat rounded-lg text-dark-muted hover:text-dark-text"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
          </button>
          <h1 className="text-xl font-semibold text-dark-text">Uploaded Files</h1>
          <span className="text-sm text-dark-muted">({files.length} files)</span>
        </div>
        <div className="flex items-center gap-2">
          {files.length > 0 && (
            <>
              <a
                href="/api/uploads/download/all"
                download
                className="flex items-center gap-2 px-4 py-2 bg-dark-hover text-dark-text rounded-lg hover:bg-opacity-80 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download All
              </a>
              <button
                onClick={() => setDeleteConfirm('all')}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
                Delete All
              </button>
            </>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* File List */}
        <div className="w-1/2 border-r border-dark-chat overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-dark-muted">Loading files...</div>
            </div>
          ) : files.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center p-8">
              <svg className="w-16 h-16 text-dark-muted mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z" />
              </svg>
              <p className="text-dark-muted">No files uploaded yet</p>
              <p className="text-sm text-dark-muted mt-1">Files you attach to chats will appear here</p>
            </div>
          ) : (
            <div className="divide-y divide-dark-chat">
              {files.map((file) => (
                <div
                  key={file.id}
                  className={`flex items-center gap-4 p-4 cursor-pointer hover:bg-dark-sidebar transition-colors ${
                    selectedFile?.id === file.id ? 'bg-dark-sidebar' : ''
                  }`}
                  onClick={() => setSelectedFile(file)}
                >
                  <div className="flex-shrink-0">
                    {file.is_image ? (
                      <img
                        src={`/api/uploads/${file.filename}`}
                        alt={file.original_filename}
                        className="w-12 h-12 object-cover rounded"
                      />
                    ) : (
                      <div className="w-12 h-12 bg-dark-chat rounded flex items-center justify-center">
                        {getFileIcon(file.content_type)}
                      </div>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-dark-text truncate">
                      {file.original_filename}
                    </p>
                    <p className="text-xs text-dark-muted">
                      {formatFileSize(file.file_size)} • {formatDate(file.created_at)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <a
                      href={`/api/uploads/${file.filename}`}
                      download={file.original_filename}
                      onClick={(e) => e.stopPropagation()}
                      className="p-2 text-dark-muted hover:text-dark-text hover:bg-dark-chat rounded"
                      title="Download"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                    </a>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setDeleteConfirm(file.id)
                      }}
                      className="p-2 text-dark-muted hover:text-red-500 hover:bg-dark-chat rounded"
                      title="Delete"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Preview Panel */}
        <div className="w-1/2 overflow-y-auto bg-dark-sidebar">
          {selectedFile ? (
            <div className="p-6">
              <div className="mb-6">
                <h2 className="text-lg font-semibold text-dark-text mb-2">
                  {selectedFile.original_filename}
                </h2>
                <div className="text-sm text-dark-muted space-y-1">
                  <p>Size: {formatFileSize(selectedFile.file_size)}</p>
                  <p>Type: {selectedFile.content_type}</p>
                  <p>Uploaded: {formatDate(selectedFile.created_at)}</p>
                </div>
              </div>

              {selectedFile.is_image ? (
                <div className="rounded-lg overflow-hidden bg-dark-chat">
                  <img
                    src={`/api/uploads/${selectedFile.filename}`}
                    alt={selectedFile.original_filename}
                    className="max-w-full h-auto"
                  />
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 bg-dark-chat rounded-lg">
                  {getFileIcon(selectedFile.content_type)}
                  <p className="text-dark-muted mt-4">Preview not available</p>
                  <a
                    href={`/api/uploads/${selectedFile.filename}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-4 px-4 py-2 bg-dark-hover text-dark-text rounded-lg hover:bg-opacity-80"
                  >
                    Open File
                  </a>
                </div>
              )}

              <div className="flex gap-2 mt-6">
                <a
                  href={`/api/uploads/${selectedFile.filename}`}
                  download={selectedFile.original_filename}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-dark-hover text-dark-text rounded-lg hover:bg-opacity-80"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Download
                </a>
                <button
                  onClick={() => setDeleteConfirm(selectedFile.id)}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                  Delete
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center p-8">
              <svg className="w-16 h-16 text-dark-muted mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              <p className="text-dark-muted">Select a file to preview</p>
            </div>
          )}
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      {deleteConfirm !== null && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-dark-sidebar rounded-lg p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-semibold text-dark-text mb-2">
              {deleteConfirm === 'all' ? 'Delete All Files?' : 'Delete File?'}
            </h3>
            <p className="text-dark-muted mb-6">
              {deleteConfirm === 'all'
                ? 'This will permanently delete all uploaded files. This action cannot be undone.'
                : 'This will permanently delete this file. This action cannot be undone.'}
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="flex-1 px-4 py-2 bg-dark-chat text-dark-text rounded-lg hover:bg-dark-hover"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (deleteConfirm === 'all') {
                    handleDeleteAll()
                  } else {
                    handleDelete(deleteConfirm)
                  }
                }}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
