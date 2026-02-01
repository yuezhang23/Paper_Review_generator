'use client'

import { memo, useState, useCallback } from 'react'
import { FileText, Loader2, Image } from 'lucide-react'
import axios from 'axios'
import { PaperInputForm } from './PaperInputForm'
import { api } from '@/lib/api'
import type { PaperFormState, AnalysisResult, ImageResult } from '@/lib/types'
import { INITIAL_FORM_STATE } from '@/lib/types'

interface SummaryTabProps {
  form: PaperFormState
  setForm: (f: PaperFormState | ((prev: PaperFormState) => PaperFormState)) => void
}

function SummaryTabInner({ form, setForm }: SummaryTabProps) {
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [generatedImage, setGeneratedImage] = useState<ImageResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [imageLoading, setImageLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = useCallback(async () => {
    if (form.inputType === 'file' && !form.uploadedFile) return setError('Please upload a file')
    if (form.inputType === 'url' && !form.paperUrl.trim()) return setError('Please enter a paper URL')
    if (form.inputType === 'name' && !form.paperName.trim()) return setError('Please enter a paper name')

    setError(null)
    setLoading(true)
    try {
      let fileIds: string[] = []
      if (form.inputType === 'file' && form.uploadedFile) {
        const fd = new FormData()
        fd.append('files', form.uploadedFile.file)
        const res = await axios.post(api.upload, fd, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000 })
        fileIds = res.data.file_ids || []
      }
      const res = await axios.post(api.summary, {
        file_ids: fileIds.length > 0 ? fileIds : undefined,
        paper_url: form.inputType === 'url' ? form.paperUrl : undefined,
        paper_name: form.inputType === 'name' ? form.paperName : undefined,
        use_openreview: true,
      }, { timeout: 900000 })
      setResult({
        type: 'summary',
        content: res.data.summary || res.data.message,
        timestamp: new Date(),
        metadata: res.data,
      })
      setGeneratedImage(null)
    } catch (err: unknown) {
      const e = err as { code?: string; message?: string; response?: { data?: { detail?: string } } }
      setError(e.code === 'ECONNABORTED' || e.message?.includes('timeout')
        ? 'Request timed out. Try a smaller PDF.'
        : e.response?.data?.detail || e.message || 'Failed to generate summary')
    } finally {
      setLoading(false)
    }
  }, [form])

  const handleGenerateImage = useCallback(async () => {
    if (!result) return
    setError(null)
    setImageLoading(true)
    setGeneratedImage(null)
    try {
      const res = await axios.post(api.image, {
        file_ids: result.metadata?.file_ids,
        paper_url: result.metadata?.paper_url,
        paper_name: result.metadata?.paper_name,
        pdf_path: result.metadata?.pdf_path,
        file_id: result.metadata?.file_id,
        use_openreview: true,
      }, { timeout: 300000 })
      setGeneratedImage({
        image_url: res.data.image_url,
        revised_prompt: res.data.revised_prompt,
        methodology_steps: res.data.methodology_steps,
      })
    } catch (err: unknown) {
      const e = err as { code?: string; message?: string; response?: { data?: { detail?: string } } }
      setError(e.code === 'ECONNABORTED' || e.message?.includes('timeout')
        ? 'Image generation timed out.'
        : e.response?.data?.detail || e.message || 'Failed')
    } finally {
      setImageLoading(false)
    }
  }, [result])

  const clearAll = useCallback(() => {
    setResult(null)
    setGeneratedImage(null)
    setForm(INITIAL_FORM_STATE)
    setError(null)
  }, [setForm])

  return (
    <div className="bg-gray-800/50 rounded-2xl border border-gray-700 p-8 shadow-2xl">
      <h2 className="text-xl font-bold text-white mb-4">Paper Summary</h2>
      <PaperInputForm form={form} onChange={setForm} onError={setError} />
      <div className="mt-6">
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="w-full px-6 py-3 bg-gradient-to-r from-blue-500 to-purple-500 text-white font-semibold rounded-lg hover:from-blue-600 hover:to-purple-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {loading ? <><Loader2 className="w-5 h-5 animate-spin" /> Processing...</> : 'Generate Summary'}
        </button>
      </div>
      {error && (
        <div className="mt-4 p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-400">{error}</div>
      )}
      {result && (
        <div className="mt-8 pt-8 border-t border-gray-700">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <FileText className="w-5 h-5 text-blue-400" />
              Analysis Result
            </h3>
            <div className="flex gap-2">
              <button
                onClick={handleGenerateImage}
                disabled={imageLoading}
                className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white rounded-lg text-sm flex items-center gap-2"
              >
                {imageLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Image className="w-4 h-4" />}
                Generate Image
              </button>
              <button onClick={clearAll} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg text-sm">
                New Analysis
              </button>
            </div>
          </div>
          <div className="bg-gray-900 rounded-lg p-6 border border-gray-700">
            <div className="text-gray-200 whitespace-pre-wrap leading-relaxed">{result.content}</div>
            {generatedImage?.image_url && (
              <div className="mt-6 pt-6 border-t border-gray-700">
                <h4 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                  <Image className="w-5 h-5 text-purple-400" />
                  Generated Methodology Diagram
                </h4>
                <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
                  <img
                    src={generatedImage.image_url}
                    alt="Methodology diagram"
                    className="max-w-full h-auto rounded-lg w-full max-w-[1024px] aspect-square object-contain"
                  />
                  {generatedImage.revised_prompt && (
                    <p className="mt-4 text-sm text-gray-400 italic">{generatedImage.revised_prompt}</p>
                  )}
                </div>
              </div>
            )}
            <div className="mt-4 text-xs text-gray-500">{result.timestamp.toLocaleString()}</div>
          </div>
        </div>
      )}
    </div>
  )
}

export const SummaryTab = memo(SummaryTabInner)
export default SummaryTab
