import { useRef, useState } from 'react'
import { ReportTemplate, TemplateSection, TemplateCreate, defaultSection, templatesService } from '../../services/templates'

interface Props {
  initial?: ReportTemplate | null
  onSave: (payload: TemplateCreate) => Promise<void>
  onCancel: () => void
}

const FORMAT_OPTIONS = [
  { value: 'pdf', label: 'PDF' },
  { value: 'docx', label: 'Word (DOCX)' },
  { value: 'xlsx', label: 'Excel (XLSX)' },
  { value: 'pptx', label: 'PowerPoint (PPTX)' },
]

export function TemplateEditor({ initial, onSave, onCancel }: Props) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [format, setFormat] = useState<string>(initial?.format ?? 'pdf')
  const [keywords, setKeywords] = useState(initial?.keywords ?? '')
  const [sections, setSections] = useState<TemplateSection[]>(
    initial?.sections?.length ? initial.sections : [defaultSection()]
  )
  const [tempFileId, setTempFileId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [error, setError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const updateSection = (idx: number, patch: Partial<TemplateSection>) => {
    setSections((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)))
  }

  const updateTableHeaders = (idx: number, raw: string) => {
    const headers = raw.split(',').map((h) => h.trim()).filter(Boolean)
    updateSection(idx, { table_headers: headers })
  }

  const addSection = () => setSections((prev) => [...prev, defaultSection()])

  const removeSection = (idx: number) =>
    setSections((prev) => prev.filter((_, i) => i !== idx))

  const moveSection = (idx: number, dir: -1 | 1) => {
    const next = [...sections]
    const swap = idx + dir
    if (swap < 0 || swap >= next.length) return
    ;[next[idx], next[swap]] = [next[swap], next[idx]]
    setSections(next)
  }

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setExtracting(true)
    setError('')
    try {
      const response = await templatesService.extractHeadings(file)
      if (response.headings.length === 0) {
        setError('No headings found in the file.')
        return
      }
      setTempFileId(response.temp_file_id)
      setSections(response.headings.map((h) => ({
        heading: h.heading,
        level: h.level,
        placeholder: '',
        has_table: false,
        table_headers: [],
      })))
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to extract headings from file.')
    } finally {
      setExtracting(false)
      // Reset so the same file can be re-imported
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleSave = async () => {
    if (!name.trim()) { setError('Template name is required.'); return }
    if (!sections.length) { setError('Add at least one section.'); return }
    if (sections.some((s) => !s.heading.trim())) { setError('All sections must have a heading.'); return }
    setError('')
    setSaving(true)
    try {
      await onSave({ name, description, format, sections, keywords, temp_file_id: tempFileId ?? undefined })
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to save template.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-start justify-center overflow-y-auto py-8 px-4">
      <div className="bg-dark-sidebar rounded-xl shadow-2xl w-full max-w-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-dark-chat">
          <h2 className="text-lg font-semibold text-dark-text">
            {initial ? 'Edit Template' : 'New Template'}
          </h2>
          <button onClick={onCancel} className="text-dark-muted hover:text-dark-text">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {/* Basic fields */}
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-dark-muted mb-1">Template Name *</label>
              <input
                className="w-full bg-dark-bg border border-dark-chat rounded-lg px-3 py-2 text-sm text-dark-text focus:outline-none focus:border-dark-hover"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Currency Analysis Report"
              />
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-medium text-dark-muted mb-1">Description</label>
              <input
                className="w-full bg-dark-bg border border-dark-chat rounded-lg px-3 py-2 text-sm text-dark-text focus:outline-none focus:border-dark-hover"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Short description of when to use this template"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-dark-muted mb-1">Format *</label>
              <select
                className="w-full bg-dark-bg border border-dark-chat rounded-lg px-3 py-2 text-sm text-dark-text focus:outline-none focus:border-dark-hover"
                value={format}
                onChange={(e) => setFormat(e.target.value)}
              >
                {FORMAT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-dark-muted mb-1">
                Keywords
                <span className="ml-1 text-dark-muted font-normal">(comma-separated, for auto-matching)</span>
              </label>
              <input
                className="w-full bg-dark-bg border border-dark-chat rounded-lg px-3 py-2 text-sm text-dark-text focus:outline-none focus:border-dark-hover"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                placeholder="rupiah, sgd, currency, exchange rate"
              />
            </div>
          </div>

          {/* Sections */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <label className="text-xs font-medium text-dark-muted">Sections *</label>
              <div className="flex items-center gap-3">
                {/* Import from file */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".docx,.xlsx,.pptx,.pdf"
                  className="hidden"
                  onChange={handleImportFile}
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={extracting}
                  className="flex items-center gap-1.5 text-xs text-dark-muted hover:text-dark-text border border-dark-chat rounded-md px-2.5 py-1.5 hover:border-dark-hover transition disabled:opacity-50"
                >
                  {extracting ? (
                    <>
                      <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                      Extracting…
                    </>
                  ) : (
                    <>
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                      </svg>
                      Import from file
                    </>
                  )}
                </button>
                <button
                  onClick={addSection}
                  className="text-xs text-dark-hover hover:underline flex items-center gap-1"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                  Add section
                </button>
              </div>
            </div>

            {/* Style file badge */}
            {(tempFileId || initial?.has_template_file) && (
              <div className="flex items-center gap-1.5 text-xs text-green-400 mb-3">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Style file attached — generation will preserve fonts, colors, and layout
              </div>
            )}

            {/* Import hint */}
            {sections.length === 1 && !sections[0].heading && (
              <p className="text-xs text-dark-muted mb-3">
                Upload a Word, Excel, PowerPoint, or PDF file to automatically extract its headings, or add sections manually below. For DOCX/XLSX/PPTX, the file will be used as the style template during generation.
              </p>
            )}

            <div className="space-y-3">
              {sections.map((sec, idx) => (
                <div key={idx} className="bg-dark-bg border border-dark-chat rounded-lg p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    {/* Move up/down */}
                    <div className="flex flex-col gap-0.5">
                      <button
                        onClick={() => moveSection(idx, -1)}
                        disabled={idx === 0}
                        className="text-dark-muted hover:text-dark-text disabled:opacity-30 p-0.5"
                      >
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                        </svg>
                      </button>
                      <button
                        onClick={() => moveSection(idx, 1)}
                        disabled={idx === sections.length - 1}
                        className="text-dark-muted hover:text-dark-text disabled:opacity-30 p-0.5"
                      >
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </button>
                    </div>

                    {/* Heading */}
                    <input
                      className="flex-1 bg-dark-sidebar border border-dark-chat rounded px-2 py-1.5 text-sm text-dark-text focus:outline-none focus:border-dark-hover"
                      placeholder="Section heading *"
                      value={sec.heading}
                      onChange={(e) => updateSection(idx, { heading: e.target.value })}
                    />

                    {/* Level */}
                    <select
                      className="bg-dark-sidebar border border-dark-chat rounded px-2 py-1.5 text-sm text-dark-text focus:outline-none focus:border-dark-hover w-20"
                      value={sec.level}
                      onChange={(e) => updateSection(idx, { level: Number(e.target.value) })}
                    >
                      <option value={1}>H1</option>
                      <option value={2}>H2</option>
                      <option value={3}>H3</option>
                    </select>

                    {/* Remove */}
                    <button
                      onClick={() => removeSection(idx)}
                      disabled={sections.length === 1}
                      className="text-dark-muted hover:text-red-400 disabled:opacity-30 p-1"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>

                  {/* Placeholder */}
                  <input
                    className="w-full bg-dark-sidebar border border-dark-chat rounded px-2 py-1.5 text-xs text-dark-muted focus:outline-none focus:border-dark-hover"
                    placeholder="Describe what AI should write here (placeholder)"
                    value={sec.placeholder}
                    onChange={(e) => updateSection(idx, { placeholder: e.target.value })}
                  />

                  {/* Has table toggle + headers */}
                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={sec.has_table}
                        onChange={(e) => updateSection(idx, { has_table: e.target.checked })}
                        className="rounded"
                      />
                      <span className="text-xs text-dark-muted">Include table</span>
                    </label>
                    {sec.has_table && (
                      <input
                        className="flex-1 bg-dark-sidebar border border-dark-chat rounded px-2 py-1 text-xs text-dark-muted focus:outline-none focus:border-dark-hover"
                        placeholder="Column headers, comma-separated (e.g. Currency, Rate, Change)"
                        value={sec.table_headers.join(', ')}
                        onChange={(e) => updateTableHeaders(idx, e.target.value)}
                      />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-dark-chat">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-dark-muted hover:text-dark-text"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2 text-sm bg-dark-hover text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition"
          >
            {saving ? 'Saving…' : initial ? 'Save changes' : 'Create template'}
          </button>
        </div>
      </div>
    </div>
  )
}
