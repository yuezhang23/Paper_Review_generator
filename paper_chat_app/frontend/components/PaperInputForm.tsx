'use client'

import { useRef } from 'react'
import { Upload, FileText, Link, File, X } from 'lucide-react'
import type { PaperFormState, UploadedFile } from '@/lib/types'

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${Math.round((bytes / Math.pow(k, i)) * 100) / 100} ${sizes[i]}`
}

interface PaperInputFormProps {
  form: PaperFormState
  onChange: (form: PaperFormState) => void
  onError: (msg: string | null) => void
}

export function PaperInputForm({ form, onChange, onError }: PaperInputFormProps) {
  const fileRef = useRef<HTMLInputElement>(null)

  const setInputType = (inputType: PaperFormState['inputType']) => {
    onChange({ ...form, inputType })
    onError(null)
  }

  const setPaperUrl = (paperUrl: string) => {
    onChange({ ...form, paperUrl })
    onError(null)
  }

  const setPaperName = (paperName: string) => {
    onChange({ ...form, paperName })
    onError(null)
  }

  const addFile = (file: File): UploadedFile => ({
    id: `${Date.now()}-${Math.random()}`,
    file,
    name: file.name,
    size: file.size,
    type: file.type,
  })

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = (e.target.files || [])[0]
    if (file) onChange({ ...form, uploadedFile: addFile(file) })
    onError(null)
    e.target.value = ''
  }

  const removeFile = () => {
    onChange({ ...form, uploadedFile: null })
    onError(null)
  }

  const inputTypes: { type: PaperFormState['inputType']; icon: typeof File; label: string }[] = [
    { type: 'file', icon: File, label: 'Upload File' },
    { type: 'url', icon: Link, label: 'Paper URL' },
    { type: 'name', icon: FileText, label: 'Paper Name' },
  ]

  return (
    <div>
      <div className="flex gap-3 mb-4">
        {inputTypes.map(({ type, icon: Icon, label }) => (
          <button
            key={type}
            onClick={() => setInputType(type)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              form.inputType === type ? 'bg-blue-500 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            <Icon className="w-4 h-4 inline mr-2" />
            {label}
          </button>
        ))}
      </div>

      {form.inputType === 'file' && (
        <div className="border-2 border-dashed border-gray-600 rounded-lg p-8 text-center hover:border-blue-500 transition-colors">
          {form.uploadedFile ? (
            <div className="flex items-center justify-center gap-3 p-4 bg-gray-700 rounded-lg max-w-md mx-auto">
              <FileText className="w-8 h-8 text-blue-400 shrink-0" />
              <div className="flex-1 text-left min-w-0">
                <p className="text-white font-medium truncate">{form.uploadedFile.name}</p>
                <p className="text-gray-400 text-sm">{formatFileSize(form.uploadedFile.size)}</p>
              </div>
              <button onClick={removeFile} className="p-2 hover:bg-gray-600 rounded-lg transition-colors shrink-0">
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>
          ) : (
            <>
              <Upload className="w-12 h-12 text-gray-400 mx-auto mb-4" />
              <p className="text-gray-300 mb-2">Click to upload or drag and drop</p>
              <p className="text-gray-500 text-sm mb-4">PDF, DOC, DOCX, TXT</p>
              <button
                onClick={() => fileRef.current?.click()}
                className="px-6 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
              >
                Select File
              </button>
            </>
          )}
          <input
            ref={fileRef}
            type="file"
            onChange={handleFileSelect}
            className="hidden"
            accept=".pdf,.txt,.doc,.docx"
          />
        </div>
      )}

      {form.inputType === 'url' && (
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">Paper URL</label>
          <input
            type="url"
            value={form.paperUrl}
            onChange={(e) => setPaperUrl(e.target.value)}
            placeholder="https://openreview.net/forum?id=..."
            className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      )}

      {form.inputType === 'name' && (
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">Paper Name/Title</label>
          <input
            type="text"
            value={form.paperName}
            onChange={(e) => setPaperName(e.target.value)}
            placeholder="Enter the paper title or name"
            className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      )}
    </div>
  )
}
