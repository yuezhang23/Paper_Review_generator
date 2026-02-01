'use client'

import { memo, useState, useRef, useEffect, useCallback } from 'react'
import { Upload, FileText, Loader2, MessageSquare, Paperclip, X, Send } from 'lucide-react'
import axios from 'axios'
import { api } from '@/lib/api'
import type { Message, UploadedFile, Model } from '@/lib/types'

function addFile(file: File): UploadedFile {
  return {
    id: `${Date.now()}-${Math.random()}`,
    file,
    name: file.name,
    size: file.size,
    type: file.type,
  }
}

function ChatTabInner() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [models, setModels] = useState<Model[]>([])
  const [selectedModel, setSelectedModel] = useState('grok-4-fast')
  const [useOpenReview, setUseOpenReview] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    axios.get(api.models).then((res) => setModels(res.data.models || [])).catch(() => {})
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const list = Array.from(e.target.files || [])
    setFiles((prev) => [...prev, ...list.map(addFile)])
    setError(null)
    e.target.value = ''
  }, [])

  const removeFile = useCallback((id?: string) => {
    if (id) setFiles((prev) => prev.filter((f) => f.id !== id))
    else setFiles([])
    setError(null)
  }, [])

  const sendMessage = useCallback(async () => {
    if ((!input.trim() && files.length === 0) || loading) return

    const userMsg: Message = {
      role: 'user',
      content: input || (files.length ? `Uploaded ${files.length} file(s)` : ''),
      timestamp: new Date(),
      id: `msg-${Date.now()}`,
      files: files.length ? [...files] : undefined,
    }
    const next = [...messages, userMsg]
    setMessages(next)
    setInput('')
    const toUpload = [...files]
    setFiles([])
    setLoading(true)
    setError(null)

    try {
      let fileIds: string[] = []
      if (toUpload.length > 0) {
        const fd = new FormData()
        toUpload.forEach((f) => fd.append('files', f.file))
        const res = await axios.post(api.upload, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
        fileIds = res.data.file_ids || []
      }
      const res = await axios.post(api.chat, {
        messages: next.map((m) => ({ role: m.role, content: m.content })),
        model: selectedModel,
        use_openreview: useOpenReview && selectedModel !== 'supermind-agent-v1',
        file_ids: fileIds.length ? fileIds : undefined,
        mode: 'chat',
      })

      if (res.data.requires_clarification) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: res.data.message,
            timestamp: new Date(),
            id: `msg-${Date.now()}`,
            requires_clarification: true,
          },
        ])
        return
      }
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: res.data.message,
          timestamp: new Date(),
          id: `msg-${Date.now()}`,
          pdf_links: res.data.pdf_links,
          is_summary: res.data.is_summary,
        },
      ])
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string }
      setError(e.response?.data?.detail || e.message || 'An error occurred')
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.', timestamp: new Date(), id: `msg-${Date.now()}` },
      ])
    } finally {
      setLoading(false)
    }
  }, [input, files, loading, messages, selectedModel, useOpenReview])

  const clearChat = useCallback(() => {
    setMessages([])
    setFiles([])
    setError(null)
    if (fileRef.current) fileRef.current.value = ''
  }, [])

  return (
    <div className="bg-gray-800/50 rounded-2xl border border-gray-700 p-8 shadow-2xl flex flex-col" style={{ height: 'calc(100vh - 200px)' }}>
      {/* Model & OpenReview controls */}
      <div className="flex items-center justify-between gap-3 mb-4 shrink-0">
        <button
          onClick={clearChat}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg text-sm transition-colors"
        >
          New Chat
        </button>
        <div className="flex items-center gap-3">
        <select
          value={selectedModel}
          onChange={(e) => setSelectedModel(e.target.value)}
          className="px-3 py-2 bg-gray-800 text-gray-200 rounded-lg border border-gray-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {models.length > 0
            ? models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))
            : (
              <>
                <option value="grok-4-fast">Grok-4 Fast</option>
                <option value="gpt-5">GPT-5</option>
                <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
              </>
            )}
        </select>
        <div className="flex items-center gap-2 px-3 py-2 bg-gray-800 rounded-lg border border-gray-600">
          <span className="text-xs text-gray-300">OpenReview</span>
          <button
            onClick={() => setUseOpenReview((v) => !v)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${useOpenReview ? 'bg-blue-500' : 'bg-gray-600'}`}
          >
            <span
              className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                useOpenReview ? 'translate-x-5' : 'translate-x-1'
              }`}
            />
          </button>
        </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto mb-4 space-y-4 min-h-0">
        {messages.length === 0 && (
          <div className="text-center mt-12">
            <MessageSquare className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-xl font-bold text-white mb-2">Start a Conversation</h3>
            <p className="text-gray-400">Ask questions about academic papers</p>
          </div>
        )}
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-3xl rounded-lg px-4 py-3 ${
                msg.role === 'user'
                  ? 'bg-gradient-to-br from-blue-500 to-purple-500 text-white'
                  : 'bg-gray-900 text-gray-100 border border-gray-700'
              }`}
            >
              {msg.role === 'user' && msg.files && msg.files.length > 0 && (
                <div className="mt-2 mb-2 pt-2 border-t border-white/20">
                  <div className="text-xs font-semibold text-white/80 mb-1 flex items-center gap-1">
                    <Upload className="w-3 h-3" />
                    Files ({msg.files.length})
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {msg.files.map((f) => (
                      <span key={f.id} className="px-2 py-1 bg-white/20 rounded text-xs">
                        {f.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {msg.role === 'assistant' && msg.pdf_links && msg.pdf_links.length > 0 && (
                <div className="mb-2 pb-2 border-b border-gray-700">
                  <div className="text-xs font-semibold text-gray-400 mb-1">Related Papers:</div>
                  <div className="flex flex-wrap gap-1">
                    {msg.pdf_links
                      .filter((l) => l.url?.startsWith('http'))
                      .map((l, i) => (
                        <a
                          key={i}
                          href={l.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="px-2 py-1 bg-blue-900/30 hover:bg-blue-900/50 text-blue-300 rounded text-xs"
                        >
                          {l.title || 'Paper'}
                        </a>
                      ))}
                  </div>
                </div>
              )}
              <div className="whitespace-pre-wrap text-sm">{msg.content}</div>
              <div className="text-xs mt-2 opacity-70">{msg.timestamp.toLocaleTimeString()}</div>
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-900 border border-gray-700 rounded-lg px-4 py-3">
              <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-700 pt-4 shrink-0">
        {files.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {files.map((f) => (
              <div
                key={f.id}
                className="px-2 py-1 bg-gray-700 rounded text-xs text-gray-300 flex items-center gap-2"
              >
                <FileText className="w-3 h-3" />
                {f.name}
                <button onClick={() => removeFile(f.id)} className="hover:text-red-400">
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        {error && <div className="mb-2 p-2 bg-red-900/30 border border-red-700 rounded text-xs text-red-400">{error}</div>}
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  sendMessage()
                }
              }}
              placeholder="Ask about papers, request summaries..."
              rows={3}
              className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none pr-10"
            />
            <input
              ref={fileRef}
              type="file"
              multiple
              onChange={handleFileSelect}
              className="hidden"
              accept=".pdf,.txt,.doc,.docx"
            />
            <button
              onClick={() => fileRef.current?.click()}
              className="absolute top-2 right-2 p-1.5 text-gray-400 hover:text-gray-300"
            >
              <Paperclip className="w-4 h-4" />
            </button>
          </div>
          <button
            onClick={sendMessage}
            disabled={(!input.trim() && files.length === 0) || loading}
            className="px-6 py-3 bg-gradient-to-r from-blue-500 to-purple-500 text-white rounded-lg hover:from-blue-600 hover:to-purple-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2 shrink-0"
          >
            <Send className="w-4 h-4" />
            Send
          </button>
        </div>
      </div>
    </div>
  )
}

export const ChatTab = memo(ChatTabInner)
export default ChatTab
