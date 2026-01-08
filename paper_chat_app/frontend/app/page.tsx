'use client'

import { useState, useRef, useEffect } from 'react'
import { Upload, FileText, Link, File, Loader2, CheckCircle2, AlertCircle, X, Send, MessageSquare, Globe, Paperclip } from 'lucide-react'
import axios from 'axios'

interface UploadedFile {
  id: string
  file: File
  name: string
  size: number
  type: string
}

interface AnalysisResult {
  type: 'summary' | 'plagiarism'
  content: string
  timestamp: Date
  metadata?: any
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  id?: string
  pdf_links?: Array<{ title: string; url: string; review_url?: string }>
  files?: UploadedFile[]
  requires_clarification?: boolean
  is_summary?: boolean
}

interface Model {
  id: string
  name: string
  description: string
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type TabType = 'summary' | 'plagiarism' | 'chat'

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabType>('summary')
  
  // Tab-specific form state - preserved when switching tabs
  const [summaryForm, setSummaryForm] = useState<{
    inputType: 'file' | 'url' | 'name'
    paperUrl: string
    paperName: string
    uploadedFile: UploadedFile | null
  }>({
    inputType: 'file',
    paperUrl: '',
    paperName: '',
    uploadedFile: null
  })
  
  const [plagiarismForm, setPlagiarismForm] = useState<{
    inputType: 'file' | 'url' | 'name'
    paperUrl: string
    paperName: string
    uploadedFile: UploadedFile | null
  }>({
    inputType: 'file',
    paperUrl: '',
    paperName: '',
    uploadedFile: null
  })
  
  // Tab-specific results - preserved when switching tabs
  const [summaryResult, setSummaryResult] = useState<AnalysisResult | null>(null)
  const [plagiarismResult, setPlagiarismResult] = useState<AnalysisResult | null>(null)
  const [chatMessages, setChatMessages] = useState<Message[]>([])
  
  // Current tab state (for form inputs)
  const currentForm = activeTab === 'summary' ? summaryForm : 
                      activeTab === 'plagiarism' ? plagiarismForm : null
  const currentResult = activeTab === 'summary' ? summaryResult :
                        activeTab === 'plagiarism' ? plagiarismResult : null
  
  // Processing state
  const [isProcessing, setIsProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  // Chat state
  const [chatInput, setChatInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [availableModels, setAvailableModels] = useState<Model[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('grok-4-fast')
  const [useOpenReview, setUseOpenReview] = useState<boolean>(false)
  const [chatFiles, setChatFiles] = useState<UploadedFile[]>([])
  
  const fileInputRef = useRef<HTMLInputElement>(null)
  const chatFileInputRef = useRef<HTMLInputElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadAvailableModels()
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [chatMessages])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const loadAvailableModels = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/models`)
      setAvailableModels(response.data.models || [])
    } catch (error) {
      console.error('Failed to load models:', error)
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    const newFiles: UploadedFile[] = files.map(file => ({
      id: `${Date.now()}-${Math.random()}`,
      file,
      name: file.name,
      size: file.size,
      type: file.type
    }))
    
    if (activeTab === 'chat') {
      setChatFiles(prev => [...prev, ...newFiles])
    } else if (activeTab === 'summary') {
      setSummaryForm(prev => ({ ...prev, uploadedFile: newFiles[0] }))
    } else if (activeTab === 'plagiarism') {
      setPlagiarismForm(prev => ({ ...prev, uploadedFile: newFiles[0] }))
    }
    setError(null)
    
    // Reset input
    const ref = activeTab === 'chat' ? chatFileInputRef : fileInputRef
    if (ref.current) {
      ref.current.value = ''
    }
  }

  const removeFile = (fileId?: string) => {
    if (activeTab === 'chat') {
      if (fileId) {
        setChatFiles(prev => prev.filter(f => f.id !== fileId))
      } else {
        setChatFiles([])
      }
    } else if (activeTab === 'summary') {
      setSummaryForm(prev => ({ ...prev, uploadedFile: null }))
    } else if (activeTab === 'plagiarism') {
      setPlagiarismForm(prev => ({ ...prev, uploadedFile: null }))
    }
    setError(null)
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  const handleSubmit = async () => {
    if (!currentForm) return
    
    setError(null)
    
    // Validate input based on type
    if (currentForm.inputType === 'file' && !currentForm.uploadedFile) {
      setError('Please upload a file')
      return
    }
    if (currentForm.inputType === 'url' && !currentForm.paperUrl.trim()) {
      setError('Please enter a paper URL')
      return
    }
    if (currentForm.inputType === 'name' && !currentForm.paperName.trim()) {
      setError('Please enter a paper name')
      return
    }

    setIsProcessing(true)

    try {
      if (activeTab === 'summary') {
        await handleSummary()
      } else if (activeTab === 'plagiarism') {
        await handlePlagiarism()
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'An error occurred')
    } finally {
      setIsProcessing(false)
    }
  }

  const handleSummary = async () => {
    if (!currentForm || activeTab !== 'summary') return
    
    let fileIds: string[] = []

    // Handle file upload
    if (currentForm.inputType === 'file' && currentForm.uploadedFile) {
      const formData = new FormData()
      formData.append('files', currentForm.uploadedFile.file)

      const uploadResponse = await axios.post(`${API_BASE_URL}/api/upload-files`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      fileIds = uploadResponse.data.file_ids || []
    }

    // Call dedicated summary API endpoint
    const response = await axios.post(`${API_BASE_URL}/api/summary`, {
      file_ids: fileIds.length > 0 ? fileIds : undefined,
      paper_url: currentForm.inputType === 'url' ? currentForm.paperUrl : undefined,
      paper_name: currentForm.inputType === 'name' ? currentForm.paperName : undefined,
      use_openreview: true,
      model: 'grok-4-fast'
    })

    setSummaryResult({
      type: 'summary',
      content: response.data.message || response.data.summary,
      timestamp: new Date(),
      metadata: response.data
    })
  }

  const handlePlagiarism = async () => {
    if (!currentForm || activeTab !== 'plagiarism') return
    
    let fileIds: string[] = []

    // Handle file upload
    if (currentForm.inputType === 'file' && currentForm.uploadedFile) {
      const formData = new FormData()
      formData.append('files', currentForm.uploadedFile.file)

      const uploadResponse = await axios.post(`${API_BASE_URL}/api/upload-files`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      fileIds = uploadResponse.data.file_ids || []
    }

    // Call plagiarism checker API
    const response = await axios.post(`${API_BASE_URL}/api/plagiarism-check`, {
      file_ids: fileIds.length > 0 ? fileIds : undefined,
      paper_url: currentForm.inputType === 'url' ? currentForm.paperUrl : undefined,
      paper_name: currentForm.inputType === 'name' ? currentForm.paperName : undefined
    })

    setPlagiarismResult({
      type: 'plagiarism',
      content: response.data.analysis,
      timestamp: new Date(),
      metadata: response.data
    })
  }

  const sendChatMessage = async () => {
    if ((!chatInput.trim() && chatFiles.length === 0) || isLoading) return

    const userMessage: Message = {
      role: 'user',
      content: chatInput || (chatFiles.length > 0 ? `Uploaded ${chatFiles.length} file(s)` : ''),
      timestamp: new Date(),
      id: `msg-${Date.now()}`,
      files: chatFiles.length > 0 ? [...chatFiles] : undefined
    }

    const messagesToSend = [...chatMessages, userMessage]
    setChatMessages(messagesToSend)
    setChatInput('')
    const filesToUpload = [...chatFiles]
    setChatFiles([])
    setIsLoading(true)
    setError(null)

    try {
      // Upload files if any
      let uploadedFileIds: string[] = []
      if (filesToUpload.length > 0) {
        const formData = new FormData()
        filesToUpload.forEach(file => {
          formData.append('files', file.file)
        })

        try {
          const uploadResponse = await axios.post(`${API_BASE_URL}/api/upload-files`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
          })
          uploadedFileIds = uploadResponse.data.file_ids || []
        } catch (uploadError) {
          console.error('File upload error:', uploadError)
        }
      }

      // Call chat API
      const response = await axios.post(`${API_BASE_URL}/api/chat`, {
        messages: messagesToSend.map(m => ({ role: m.role, content: m.content })),
        model: selectedModel,
        use_openreview: useOpenReview && selectedModel !== 'supermind-agent-v1',
        file_ids: uploadedFileIds.length > 0 ? uploadedFileIds : undefined,
        mode: 'chat'  // Specify chat mode to use general paper analysis prompt
      })

      // Check if clarification is required
      if (response.data.requires_clarification) {
        const clarificationMessage: Message = {
          role: 'assistant',
          content: response.data.message,
          timestamp: new Date(),
          id: `msg-${Date.now()}`,
          requires_clarification: true
        }
        setChatMessages(prev => [...prev, clarificationMessage])
        return
      }

      // Create assistant message
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.data.message,
        timestamp: new Date(),
        id: `msg-${Date.now()}`,
        pdf_links: response.data.pdf_links || undefined,
        is_summary: response.data.is_summary || false
      }
      setChatMessages(prev => [...prev, assistantMessage])
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'An error occurred')
      const errorMessage: Message = {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date(),
        id: `msg-${Date.now()}`
      }
      setChatMessages(prev => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const resetForm = () => {
    // Only clear form inputs, NOT results (results are preserved when switching tabs)
    if (activeTab === 'summary') {
      setSummaryForm({
        inputType: 'file',
        paperUrl: '',
        paperName: '',
        uploadedFile: null
      })
    } else if (activeTab === 'plagiarism') {
      setPlagiarismForm({
        inputType: 'file',
        paperUrl: '',
        paperName: '',
        uploadedFile: null
      })
    }
    setError(null)
    setChatFiles([])
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
    if (chatFileInputRef.current) {
      chatFileInputRef.current.value = ''
    }
  }
  
  const clearResults = () => {
    // Clear results for current tab only
    if (activeTab === 'summary') {
      setSummaryResult(null)
    } else if (activeTab === 'plagiarism') {
      setPlagiarismResult(null)
    } else if (activeTab === 'chat') {
      setChatMessages([])
    }
    resetForm()
  }
  
  const switchTab = (tab: TabType) => {
    // Switch tabs without clearing results - they are preserved per tab
    setActiveTab(tab)
    setError(null)
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900">
      {/* Header with Navigation */}
      <header className="bg-gray-900/80 backdrop-blur-sm border-b border-gray-700 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between mb-4">
            <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">
              Paper Analysis Tool
            </h1>
            {activeTab === 'chat' && (
              <div className="flex items-center gap-3">
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="px-3 py-2 bg-gray-800 text-gray-200 rounded-lg border border-gray-600 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {availableModels.length > 0 ? (
                    availableModels.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.name}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="grok-4-fast">Grok-4 Fast</option>
                      <option value="gpt-5">GPT-5</option>
                      <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
                    </>
                  )}
                </select>
                <div className="flex items-center gap-2 px-3 py-2 bg-gray-800 rounded-lg border border-gray-600">
                  <Globe className={`w-4 h-4 ${useOpenReview ? 'text-blue-400' : 'text-gray-400'}`} />
                  <span className="text-xs text-gray-300">OpenReview</span>
                  <button
                    onClick={() => setUseOpenReview(!useOpenReview)}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                      useOpenReview ? 'bg-blue-500' : 'bg-gray-600'
                    }`}
                  >
                    <span
                      className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                        useOpenReview ? 'translate-x-5' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>
              </div>
            )}
          </div>
          
          {/* Navigation Tabs */}
          <div className="flex gap-2">
            <button
              onClick={() => switchTab('summary')}
              className={`px-6 py-2 rounded-lg font-semibold transition-all duration-200 ${
                activeTab === 'summary'
                  ? 'bg-gradient-to-r from-blue-500 to-purple-500 text-white shadow-lg'
                  : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              }`}
            >
              Summary
            </button>
            <button
              onClick={() => switchTab('plagiarism')}
              className={`px-6 py-2 rounded-lg font-semibold transition-all duration-200 ${
                activeTab === 'plagiarism'
                  ? 'bg-gradient-to-r from-blue-500 to-purple-500 text-white shadow-lg'
                  : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              }`}
            >
              Plagiarism Checker
            </button>
            <button
              onClick={() => switchTab('chat')}
              className={`px-6 py-2 rounded-lg font-semibold transition-all duration-200 ${
                activeTab === 'chat'
                  ? 'bg-gradient-to-r from-blue-500 to-purple-500 text-white shadow-lg'
                  : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              }`}
            >
              <MessageSquare className="w-4 h-4 inline mr-2" />
              Chat
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-6 py-8">
        {activeTab === 'chat' ? (
          /* Chat Interface */
          <div className="bg-gray-800/50 backdrop-blur-sm rounded-2xl border border-gray-700 p-8 shadow-2xl flex flex-col" style={{ height: 'calc(100vh - 200px)' }}>
            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto mb-4 space-y-4">
              {chatMessages.length === 0 && (
                <div className="text-center mt-12">
                  <MessageSquare className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                  <h3 className="text-xl font-bold text-white mb-2">Start a Conversation</h3>
                  <p className="text-gray-400">Ask questions about academic papers</p>
                </div>
              )}

              {chatMessages.map((message) => (
                <div
                  key={message.id}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-3xl rounded-lg px-4 py-3 ${
                      message.role === 'user'
                        ? 'bg-gradient-to-br from-blue-500 to-purple-500 text-white'
                        : 'bg-gray-900 text-gray-100 border border-gray-700'
                    }`}
                  >
                    {message.role === 'user' && message.files && message.files.length > 0 && (
                      <div className="mt-2 mb-2 pt-2 border-t border-white/20">
                        <div className="text-xs font-semibold text-white/80 mb-1 flex items-center gap-1">
                          <Upload className="w-3 h-3" />
                          Files ({message.files.length})
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {message.files.map((file) => (
                            <div
                              key={file.id}
                              className="px-2 py-1 bg-white/20 rounded text-xs"
                            >
                              {file.name}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {message.role === 'assistant' && message.pdf_links && message.pdf_links.length > 0 && (
                      <div className="mb-2 pb-2 border-b border-gray-700">
                        <div className="text-xs font-semibold text-gray-400 mb-1">Related Papers:</div>
                        <div className="flex flex-wrap gap-1">
                          {message.pdf_links
                            .filter(link => link.url && link.url.startsWith('http'))
                            .map((link, idx) => (
                              <a
                                key={idx}
                                href={link.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="px-2 py-1 bg-blue-900/30 hover:bg-blue-900/50 text-blue-300 rounded text-xs"
                              >
                                {link.title || 'Paper'}
                              </a>
                            ))}
                        </div>
                      </div>
                    )}
                    <div className="whitespace-pre-wrap text-sm">{message.content}</div>
                    <div className="text-xs mt-2 opacity-70">
                      {message.timestamp.toLocaleTimeString()}
                    </div>
                  </div>
                </div>
              ))}

              {isLoading && (
                <div className="flex justify-start">
                  <div className="bg-gray-900 border border-gray-700 rounded-lg px-4 py-3">
                    <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="border-t border-gray-700 pt-4">
              {chatFiles.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-2">
                  {chatFiles.map((file) => (
                    <div
                      key={file.id}
                      className="px-2 py-1 bg-gray-700 rounded text-xs text-gray-300 flex items-center gap-2"
                    >
                      <FileText className="w-3 h-3" />
                      {file.name}
                      <button
                        onClick={() => removeFile(file.id)}
                        className="hover:text-red-400"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {error && (
                <div className="mb-2 p-2 bg-red-900/30 border border-red-700 rounded text-xs text-red-400">
                  {error}
                </div>
              )}
              <div className="flex gap-2">
                <div className="flex-1 relative">
                  <textarea
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyPress={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        sendChatMessage()
                      }
                    }}
                    placeholder="Ask about papers, request summaries, or ask any question..."
                    rows={3}
                    className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none pr-10"
                  />
                  <input
                    ref={chatFileInputRef}
                    type="file"
                    multiple
                    onChange={handleFileSelect}
                    className="hidden"
                    accept=".pdf,.txt,.doc,.docx"
                  />
                  <button
                    onClick={() => chatFileInputRef.current?.click()}
                    className="absolute top-2 right-2 p-1.5 text-gray-400 hover:text-gray-300"
                  >
                    <Paperclip className="w-4 h-4" />
                  </button>
                </div>
                <button
                  onClick={sendChatMessage}
                  disabled={(!chatInput.trim() && chatFiles.length === 0) || isLoading}
                  className="px-6 py-3 bg-gradient-to-r from-blue-500 to-purple-500 text-white rounded-lg hover:from-blue-600 hover:to-purple-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2"
                >
                  <Send className="w-4 h-4" />
                  Send
                </button>
              </div>
            </div>
          </div>
        ) : (
          /* Summary & Plagiarism Interface */
          <div className="bg-gray-800/50 backdrop-blur-sm rounded-2xl border border-gray-700 p-8 shadow-2xl">
            {/* Upload Window */}
            <div className="mb-8">
              <h2 className="text-xl font-bold text-white mb-4">
                {activeTab === 'summary' ? 'Paper Summary' : 'Plagiarism Detection'}
              </h2>
              
              {/* Input Type Selector */}
              {currentForm && (
                <>
                  <div className="flex gap-3 mb-4">
                    <button
                      onClick={() => {
                        if (activeTab === 'summary') {
                          setSummaryForm(prev => ({ ...prev, inputType: 'file' }))
                        } else if (activeTab === 'plagiarism') {
                          setPlagiarismForm(prev => ({ ...prev, inputType: 'file' }))
                        }
                      }}
                      className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                        currentForm.inputType === 'file'
                          ? 'bg-blue-500 text-white'
                          : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                      }`}
                    >
                      <File className="w-4 h-4 inline mr-2" />
                      Upload File
                    </button>
                    <button
                      onClick={() => {
                        if (activeTab === 'summary') {
                          setSummaryForm(prev => ({ ...prev, inputType: 'url' }))
                        } else if (activeTab === 'plagiarism') {
                          setPlagiarismForm(prev => ({ ...prev, inputType: 'url' }))
                        }
                      }}
                      className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                        currentForm.inputType === 'url'
                          ? 'bg-blue-500 text-white'
                          : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                      }`}
                    >
                      <Link className="w-4 h-4 inline mr-2" />
                      Paper URL
                    </button>
                    <button
                      onClick={() => {
                        if (activeTab === 'summary') {
                          setSummaryForm(prev => ({ ...prev, inputType: 'name' }))
                        } else if (activeTab === 'plagiarism') {
                          setPlagiarismForm(prev => ({ ...prev, inputType: 'name' }))
                        }
                      }}
                      className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                        currentForm.inputType === 'name'
                          ? 'bg-blue-500 text-white'
                          : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                      }`}
                    >
                      <FileText className="w-4 h-4 inline mr-2" />
                      Paper Name
                    </button>
                  </div>

                  {/* File Upload */}
                  {currentForm.inputType === 'file' && (
                    <div className="border-2 border-dashed border-gray-600 rounded-lg p-8 text-center hover:border-blue-500 transition-colors">
                      {currentForm.uploadedFile ? (
                        <div className="space-y-4">
                          <div className="flex items-center justify-center gap-3 p-4 bg-gray-700 rounded-lg">
                            <FileText className="w-8 h-8 text-blue-400" />
                            <div className="flex-1 text-left">
                              <p className="text-white font-medium">{currentForm.uploadedFile.name}</p>
                              <p className="text-gray-400 text-sm">{formatFileSize(currentForm.uploadedFile.size)}</p>
                            </div>
                            <button
                              onClick={() => removeFile()}
                              className="p-2 hover:bg-gray-600 rounded-lg transition-colors"
                            >
                              <X className="w-5 h-5 text-gray-400" />
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div>
                          <Upload className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                          <p className="text-gray-300 mb-2">Click to upload or drag and drop</p>
                          <p className="text-gray-500 text-sm mb-4">PDF, DOC, DOCX, TXT files</p>
                          <button
                            onClick={() => fileInputRef.current?.click()}
                            className="px-6 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
                          >
                            Select File
                          </button>
                        </div>
                      )}
                      <input
                        ref={fileInputRef}
                        type="file"
                        onChange={handleFileSelect}
                        className="hidden"
                        accept=".pdf,.txt,.doc,.docx"
                      />
                    </div>
                  )}

                  {/* URL Input */}
                  {currentForm.inputType === 'url' && (
                    <div className="space-y-2">
                      <label className="block text-sm font-medium text-gray-300">Paper URL</label>
                      <input
                        type="url"
                        value={currentForm.paperUrl}
                        onChange={(e) => {
                          if (activeTab === 'summary') {
                            setSummaryForm(prev => ({ ...prev, paperUrl: e.target.value }))
                          } else if (activeTab === 'plagiarism') {
                            setPlagiarismForm(prev => ({ ...prev, paperUrl: e.target.value }))
                          }
                          setError(null)
                        }}
                        placeholder="https://openreview.net/forum?id=..."
                        className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                  )}

                  {/* Name Input */}
                  {currentForm.inputType === 'name' && (
                    <div className="space-y-2">
                      <label className="block text-sm font-medium text-gray-300">Paper Name/Title</label>
                      <input
                        type="text"
                        value={currentForm.paperName}
                        onChange={(e) => {
                          if (activeTab === 'summary') {
                            setSummaryForm(prev => ({ ...prev, paperName: e.target.value }))
                          } else if (activeTab === 'plagiarism') {
                            setPlagiarismForm(prev => ({ ...prev, paperName: e.target.value }))
                          }
                          setError(null)
                        }}
                        placeholder="Enter the paper title or name"
                        className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                  )}
                </>
              )}

              {/* Submit Button */}
              <div className="mt-6">
                <button
                  onClick={handleSubmit}
                  disabled={isProcessing}
                  className="w-full px-6 py-3 bg-gradient-to-r from-blue-500 to-purple-500 text-white font-semibold rounded-lg hover:from-blue-600 hover:to-purple-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 flex items-center justify-center gap-2"
                >
                  {isProcessing ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      Processing...
                    </>
                  ) : (
                    <>
                      {activeTab === 'summary' ? 'Generate Summary' : 'Check for Plagiarism'}
                    </>
                  )}
                </button>
              </div>

              {/* Error Message */}
              {error && (
                <div className="mt-4 p-4 bg-red-900/30 border border-red-700 rounded-lg flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-red-400" />
                  <p className="text-red-400">{error}</p>
                </div>
              )}
            </div>

            {/* Results Display */}
            {currentResult && (
              <div className="mt-8 border-t border-gray-700 pt-8">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-bold text-white flex items-center gap-2">
                    {currentResult.type === 'summary' ? (
                      <>
                        <FileText className="w-5 h-5 text-blue-400" />
                        Analysis Result
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="w-5 h-5 text-purple-400" />
                        Plagiarism Analysis
                      </>
                    )}
                  </h3>
                  <button
                    onClick={clearResults}
                    className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg text-sm transition-colors"
                  >
                    New Analysis
                  </button>
                </div>
                
                <div className="bg-gray-900 rounded-lg p-6 border border-gray-700">
                  {currentResult.type === 'summary' ? (
                    <div className="prose prose-invert max-w-none">
                      <div className="text-gray-200 whitespace-pre-wrap leading-relaxed">
                        {currentResult.content}
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {currentResult.metadata?.methods && (
                        <div className="space-y-3">
                          {Object.entries(currentResult.metadata.methods).map(([method, data]: [string, any]) => (
                            <div key={method} className="bg-gray-800 rounded-lg p-4 border border-gray-700">
                              <div className="flex items-center justify-between mb-2">
                                <h4 className="font-semibold text-white capitalize">{method.replace('_', ' ')}</h4>
                                <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                                  data.detected ? 'bg-red-900/30 text-red-400' : 'bg-green-900/30 text-green-400'
                                }`}>
                                  {data.detected ? 'Detected' : 'Clear'}
                                </span>
                              </div>
                              <p className="text-gray-300 text-sm">{data.description}</p>
                              {data.details && (
                                <div className="mt-2 p-2 bg-gray-900 rounded text-xs text-gray-400">
                                  {data.details}
                                </div>
                              )}
                              <p className="text-xs text-gray-500 mt-2">
                                Difficulty to Bypass: {data.difficulty}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                      {currentResult.content && (
                        <div className="mt-4 p-4 bg-blue-900/20 border border-blue-700 rounded-lg">
                          <p className="text-gray-200 whitespace-pre-wrap">{currentResult.content}</p>
                        </div>
                      )}
                    </div>
                  )}
                  <div className="mt-4 text-xs text-gray-500">
                    Generated at {currentResult.timestamp.toLocaleString()}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
