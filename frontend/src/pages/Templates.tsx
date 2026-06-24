import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { authService } from '../services/auth'
import { ReportTemplate, TemplateCreate, templatesService } from '../services/templates'
import { TemplateEditor } from '../components/templates/TemplateEditor'

type Tab = 'mine' | 'company'

const FORMAT_BADGE: Record<string, string> = {
  pdf: 'bg-red-900/40 text-red-300',
  docx: 'bg-blue-900/40 text-blue-300',
  xlsx: 'bg-green-900/40 text-green-300',
  pptx: 'bg-orange-900/40 text-orange-300',
}

export function Templates() {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const [tab, setTab] = useState<Tab>('mine')
  const [templates, setTemplates] = useState<ReportTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<ReportTemplate | null | 'new'>('new' as any)
  const [showEditor, setShowEditor] = useState(false)
  const [toggling, setToggling] = useState<number | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      setTemplates(await templatesService.list())
    } catch {
      setError('Failed to load templates.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!authService.isAuthenticated()) {
      navigate('/')
      return
    }
    load()
  }, [])

  const mine = templates.filter((t) => t.is_mine)
  const company = templates.filter((t) => t.is_company_wide)
  const displayed = tab === 'mine' ? mine : company

  const openNew = () => { setEditing(null); setShowEditor(true) }
  const openEdit = (t: ReportTemplate) => { setEditing(t); setShowEditor(true) }
  const closeEditor = () => setShowEditor(false)

  const handleSave = async (payload: TemplateCreate) => {
    if (editing && typeof editing === 'object' && (editing as ReportTemplate).id) {
      await templatesService.update((editing as ReportTemplate).id, payload)
    } else {
      await templatesService.create(payload)
    }
    closeEditor()
    await load()
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this template?')) return
    await templatesService.delete(id)
    setTemplates((prev) => prev.filter((t) => t.id !== id))
  }

  const handleToggleCompanyWide = async (id: number) => {
    setToggling(id)
    try {
      const updated = await templatesService.toggleCompanyWide(id)
      setTemplates((prev) => prev.map((t) => (t.id === id ? updated : t)))
    } finally {
      setToggling(null)
    }
  }

  return (
    <div className="min-h-screen bg-dark-bg text-dark-text">
      {/* Top bar */}
      <div className="flex items-center gap-4 px-6 py-4 border-b border-dark-sidebar bg-dark-sidebar">
        <button
          onClick={() => navigate('/')}
          className="text-dark-muted hover:text-dark-text"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <h1 className="text-lg font-semibold">Report Templates</h1>
      </div>

      <div className="max-w-4xl mx-auto px-6 py-8">
        {/* Tabs + New button */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex gap-1 bg-dark-sidebar rounded-lg p-1">
            <button
              onClick={() => setTab('mine')}
              className={`px-4 py-1.5 rounded-md text-sm transition ${
                tab === 'mine'
                  ? 'bg-dark-chat text-dark-text'
                  : 'text-dark-muted hover:text-dark-text'
              }`}
            >
              My Templates
              {mine.length > 0 && (
                <span className="ml-2 text-xs bg-dark-hover/40 text-dark-hover px-1.5 py-0.5 rounded-full">
                  {mine.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setTab('company')}
              className={`px-4 py-1.5 rounded-md text-sm transition ${
                tab === 'company'
                  ? 'bg-dark-chat text-dark-text'
                  : 'text-dark-muted hover:text-dark-text'
              }`}
            >
              Company Templates
              {company.length > 0 && (
                <span className="ml-2 text-xs bg-dark-hover/40 text-dark-hover px-1.5 py-0.5 rounded-full">
                  {company.length}
                </span>
              )}
            </button>
          </div>

          <button
            onClick={openNew}
            className="flex items-center gap-2 px-4 py-2 bg-dark-hover text-white text-sm rounded-lg hover:opacity-90 transition"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            New Template
          </button>
        </div>

        {/* Error */}
        {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

        {/* Loading */}
        {loading ? (
          <div className="text-center py-16 text-dark-muted">Loading…</div>
        ) : displayed.length === 0 ? (
          <div className="text-center py-16 text-dark-muted">
            {tab === 'mine' ? (
              <>
                <p className="text-lg mb-2">No personal templates yet</p>
                <p className="text-sm mb-6">Create a template to make AI generate reports in your preferred structure.</p>
                <button
                  onClick={openNew}
                  className="px-5 py-2 bg-dark-hover text-white text-sm rounded-lg hover:opacity-90"
                >
                  Create your first template
                </button>
              </>
            ) : (
              <>
                <p className="text-lg mb-2">No company-wide templates</p>
                {user?.is_admin && (
                  <p className="text-sm">
                    Create a template and toggle "Publish company-wide" to make it available to everyone.
                  </p>
                )}
              </>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {displayed.map((tpl) => (
              <div
                key={tpl.id}
                className="bg-dark-sidebar border border-dark-chat rounded-xl p-5 flex items-start justify-between gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <h3 className="font-medium text-dark-text">{tpl.name}</h3>
                    <span className={`text-xs px-2 py-0.5 rounded-full uppercase tracking-wide ${FORMAT_BADGE[tpl.format] ?? 'bg-dark-chat text-dark-muted'}`}>
                      {tpl.format}
                    </span>
                    {tpl.is_company_wide && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-900/40 text-indigo-300">
                        Company-wide
                      </span>
                    )}
                    {tpl.has_template_file && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-green-900/40 text-green-400">
                        Style preserved
                      </span>
                    )}
                  </div>
                  {tpl.description && (
                    <p className="text-sm text-dark-muted mb-2">{tpl.description}</p>
                  )}
                  <div className="flex items-center gap-4 text-xs text-dark-muted">
                    <span>{tpl.sections.length} section{tpl.sections.length !== 1 ? 's' : ''}</span>
                    {tpl.keywords && (
                      <span>
                        Keywords: <span className="text-dark-text">{tpl.keywords}</span>
                      </span>
                    )}
                  </div>
                  {/* Section preview */}
                  <div className="mt-3 flex flex-wrap gap-1">
                    {tpl.sections.map((s, i) => (
                      <span
                        key={i}
                        className="text-xs bg-dark-bg text-dark-muted px-2 py-0.5 rounded border border-dark-chat"
                      >
                        {s.heading}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Actions — only visible to the template owner */}
                {tpl.is_mine && (
                  <div className="flex items-center gap-2 shrink-0">
                    {/* Publish / unpublish company-wide */}
                    <button
                      onClick={() => handleToggleCompanyWide(tpl.id)}
                      disabled={toggling === tpl.id}
                      title={tpl.is_company_wide ? 'Unpublish from company' : 'Publish company-wide'}
                      className={`p-2 rounded-lg text-sm transition ${
                        tpl.is_company_wide
                          ? 'text-indigo-400 hover:bg-dark-bg'
                          : 'text-dark-muted hover:text-indigo-400 hover:bg-dark-bg'
                      }`}
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064" />
                      </svg>
                    </button>

                    {/* Edit */}
                    <button
                      onClick={() => openEdit(tpl)}
                      className="p-2 rounded-lg text-dark-muted hover:text-dark-text hover:bg-dark-bg transition"
                      title="Edit"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                    </button>

                    {/* Delete */}
                    <button
                      onClick={() => handleDelete(tpl.id)}
                      className="p-2 rounded-lg text-dark-muted hover:text-red-400 hover:bg-dark-bg transition"
                      title="Delete"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Editor modal */}
      {showEditor && (
        <TemplateEditor
          initial={editing && typeof editing === 'object' ? editing as ReportTemplate : null}
          onSave={handleSave}
          onCancel={closeEditor}
        />
      )}
    </div>
  )
}
