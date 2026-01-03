'use client'

import { useState, useEffect, useRef } from 'react'
import { Send, Search, BookOpen, MessageSquare, Sparkles, Loader2, Settings, Zap, Globe, X, Edit2, Upload, FileText, File, Paperclip } from 'lucide-react'
import axios from 'axios'

interface UploadedFile {
  id: string
  file: File
  name: string
  size: number
  type: string
  preview?: string
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  id?: string
  pdf_links?: Array<{ title: string; url: string; review_url?: string }>
  files?: UploadedFile[]
  requires_clarification?: boolean
}

interface Paper {
  id: string
  title: string
  authors: string[]
  abstract: string
  venue?: string
  forum?: string
  source: string
  url?: string
}

interface PaperContext {
  paper_id: string
  title: string
  authors: string[]
  abstract: string
  venue?: string
  reviews?: any[]
  metadata: any
}

interface Model {
  id: string
  name: string
  description: string
}

interface MultiModelResponse {
  model: string
  message: string | null
  usage: any
  error: string | null
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [currentPaper, setCurrentPaper] = useState<PaperContext | null>(null)
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [conversations, setConversations] = useState<Array<{id: string, title: string, messages: Message[]}>>([])
  const [activeConversation, setActiveConversation] = useState<string | null>(null)
  const [availableModels, setAvailableModels] = useState<Model[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('grok-4-fast')
  const [multiModelResponses, setMultiModelResponses] = useState<MultiModelResponse[]>([])
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null)
  const [leftColumnWidth, setLeftColumnWidth] = useState<number>(320) // Default 320px (w-80)
  const [isResizing, setIsResizing] = useState<boolean>(false)
  const [useOpenReview, setUseOpenReview] = useState<boolean>(false) // Toggle for OpenReview API
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([])
  const [isUploading, setIsUploading] = useState<boolean>(false)
  
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const resizeHandleRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    loadSuggestions()
    loadAvailableModels()
    // Create initial conversation
    const initialId = Date.now().toString()
    setActiveConversation(initialId)
    setConversations([{ id: initialId, title: 'New Conversation', messages: [] }])
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Handle resize functionality
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return
      
      const newWidth = Math.min(Math.max(240, e.clientX), window.innerWidth - 400) // Min 240px, max screen width - 400px
      setLeftColumnWidth(newWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
    }

    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [isResizing])

  // Handle Escape key to cancel editing
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && editingMessageId) {
        setEditingMessageId(null)
        setInput('')
      }
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [editingMessageId])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const loadSuggestions = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/suggestions`)
      setSuggestions(response.data.suggestions)
    } catch (error) {
      console.error('Failed to load suggestions:', error)
    }
  }

  const loadAvailableModels = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/models`)
      setAvailableModels(response.data.models || [])
    } catch (error) {
      console.error('Failed to load models:', error)
    }
  }


  const loadPaperContext = async (paperId: string) => {
    try {
      const response = await axios.post(`${API_BASE_URL}/api/get-paper-context`, { paper_id: paperId })
      setCurrentPaper(response.data)
      
      // Add system message about paper
      const paperMessage: Message = {
        role: 'assistant',
        content: `📄 Loaded paper: "${response.data.title}"\n\nAuthors: ${response.data.authors.join(', ')}\n\nAbstract: ${response.data.abstract.substring(0, 300)}...`,
        timestamp: new Date(),
        id: `msg-paper-${Date.now()}`
      }
      setMessages(prev => [...prev, paperMessage])
      
      // Update conversation with paper message
      if (activeConversation) {
        setConversations(prev => prev.map(conv => 
          conv.id === activeConversation 
            ? { ...conv, messages: [...conv.messages, paperMessage] }
            : conv
        ))
      }
    } catch (error) {
      console.error('Failed to load paper context:', error)
    }
  }

  const sendMessage = async () => {
    if ((!input.trim() && uploadedFiles.length === 0) || isLoading) return

    const messageId = editingMessageId || `msg-${Date.now()}`
    const userMessage: Message = {
      role: 'user',
      content: input || (uploadedFiles.length > 0 ? `Uploaded ${uploadedFiles.length} file(s)` : ''),
      timestamp: new Date(),
      id: messageId,
      files: uploadedFiles.length > 0 ? [...uploadedFiles] : undefined
    }

    // If editing, remove the edited message and all subsequent messages
    let messagesToSend: Message[]
    if (editingMessageId) {
      const editIndex = messages.findIndex(m => m.id === editingMessageId)
      if (editIndex !== -1) {
        // Keep messages before the edited one, add the new edited message
        messagesToSend = [...messages.slice(0, editIndex), userMessage]
        setMessages(messagesToSend)
      } else {
        messagesToSend = [...messages, userMessage]
        setMessages(messagesToSend)
      }
      setEditingMessageId(null)
    } else {
      messagesToSend = [...messages, userMessage]
      setMessages(messagesToSend)
    }

    const messageInput = input
    const filesToUpload = [...uploadedFiles]
    setInput('')
    setUploadedFiles([])
    setIsLoading(true)
    setIsUploading(filesToUpload.length > 0)
    setMultiModelResponses([])

    try {
      // If there are files, upload them first
      let uploadedFileIds: string[] = []
      if (filesToUpload.length > 0) {
        const formData = new FormData()
        filesToUpload.forEach(file => {
          formData.append('files', file.file)
        })

        try {
          const uploadResponse = await axios.post(`${API_BASE_URL}/api/upload-files`, formData, {
            headers: {
              'Content-Type': 'multipart/form-data'
            }
          })
          uploadedFileIds = uploadResponse.data.file_ids || []
        } catch (uploadError) {
          console.error('File upload error:', uploadError)
          // Continue with chat even if upload fails
        }
      }
      setIsUploading(false)

      // Single model response using selected model
      const useOpenReviewFlag = useOpenReview && selectedModel !== 'supermind-agent-v1'
      console.log('Sending chat request:', {
        useOpenReview: useOpenReview,
        selectedModel: selectedModel,
        useOpenReviewFlag: useOpenReviewFlag,
        messageCount: messagesToSend.length
      })
      
      const response = await axios.post(`${API_BASE_URL}/api/chat`, {
        messages: messagesToSend.map(m => ({ role: m.role, content: m.content })),
        model: selectedModel,
        paper_id: currentPaper?.paper_id,
        paper_context: currentPaper,
        use_openreview: useOpenReviewFlag,
        file_ids: uploadedFileIds.length > 0 ? uploadedFileIds : undefined
      })
      
      console.log('Chat response received:', {
        hasPdfLinks: !!response.data.pdf_links,
        pdfLinksCount: response.data.pdf_links?.length || 0
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
        setMessages(prev => [...prev, clarificationMessage])
        return
      }

      // Create assistant message
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.data.message,
        timestamp: new Date(),
        id: `msg-${Date.now()}`,
        pdf_links: response.data.pdf_links || undefined
      }
      setMessages(prev => [...prev, assistantMessage])
      
      // Update conversation
      if (activeConversation) {
        const updatedMessages = [...messagesToSend, assistantMessage]
        setConversations(prev => prev.map(conv => 
          conv.id === activeConversation 
            ? { ...conv, messages: updatedMessages, title: messagesToSend.length === 1 ? (messageInput || `Uploaded ${filesToUpload.length} file(s)`).substring(0, 50) : conv.title }
            : conv
        ))
      }
    } catch (error) {
      console.error('Chat error:', error)
      setIsUploading(false)
      const errorMessage: Message = {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date(),
        id: `msg-${Date.now()}`
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const editMessage = (messageId: string) => {
    const message = messages.find(m => m.id === messageId)
    if (message && message.role === 'user') {
      setInput(message.content)
      setEditingMessageId(messageId)
      inputRef.current?.focus()
    }
  }

  const cancelEdit = () => {
    setEditingMessageId(null)
    setInput('')
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
    setUploadedFiles(prev => [...prev, ...newFiles])
    // Reset input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const removeFile = (fileId: string) => {
    setUploadedFiles(prev => prev.filter(f => f.id !== fileId))
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  const getFileIcon = (type: string) => {
    if (type === 'application/pdf') {
      return <FileText className="w-3 h-3" />
    }
    return <File className="w-3 h-3" />
  }

  const handleSuggestionClick = (suggestion: string) => {
    setInput(suggestion)
    inputRef.current?.focus()
  }

  const createNewConversation = () => {
    const newId = Date.now().toString()
    setActiveConversation(newId)
    setMessages([])
    setCurrentPaper(null)
    setConversations(prev => [...prev, { id: newId, title: 'New Conversation', messages: [] }])
  }

  const switchConversation = (convId: string) => {
    setActiveConversation(convId)
    const conv = conversations.find(c => c.id === convId)
    if (conv) {
      // Ensure all messages have IDs
      const messagesWithIds = conv.messages.map((msg, idx) => ({
        ...msg,
        id: msg.id || `msg-${idx}-${Date.now()}`
      }))
      setMessages(messagesWithIds)
    }
    setEditingMessageId(null) // Cancel any active editing when switching conversations
  }

  const deleteConversation = (convId: string, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent triggering switchConversation
    setConversations(prev => prev.filter(conv => conv.id !== convId))
    if (activeConversation === convId) {
      // Switch to another conversation or create new one
      const remaining = conversations.filter(conv => conv.id !== convId)
      if (remaining.length > 0) {
        switchConversation(remaining[0].id)
      } else {
        createNewConversation()
      }
    }
  }


  return (
    <div className="flex h-screen bg-black">
      {/* Left Column - Conversations */}
      <div 
        className="bg-gray-900 border-r border-gray-700 flex flex-col relative"
        style={{ width: `${leftColumnWidth}px`, minWidth: '240px', maxWidth: '50%' }}
      >
        <div className="p-4 border-b border-gray-700 bg-gray-900">
          <div className="flex items-center gap-2 mb-4">
            <div className="p-1.5 bg-gradient-to-br from-elegant-primary to-elegant-secondary rounded-lg">
              <BookOpen className="w-4 h-4 text-white" />
            </div>
            <h1 className="text-lg font-bold bg-gradient-to-r from-elegant-primary to-elegant-secondary bg-clip-text text-transparent">
              Paper Chat
            </h1>
          </div>
          <button
            onClick={createNewConversation}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            <MessageSquare className="w-4 h-4" />
            New Conversation
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto p-3">
          {conversations.map(conv => (
            <div
              key={conv.id}
              className={`group relative w-full p-4 rounded-xl mb-2 transition-all duration-200 ${
                activeConversation === conv.id
                  ? 'bg-gray-800 border-2 border-elegant-primary/30 text-elegant-primary'
                  : 'hover:bg-gray-800 text-gray-300 border-2 border-transparent hover:border-gray-600'
              }`}
            >
              <button
                onClick={() => switchConversation(conv.id)}
                className="w-full text-left pr-8"
              >
                <div className="text-sm font-semibold truncate mb-1 text-gray-200">{conv.title}</div>
                <div className="text-[10px] text-gray-400">
                  {conv.messages.length} message{conv.messages.length !== 1 ? 's' : ''}
                </div>
              </button>
              <button
                onClick={(e) => deleteConversation(conv.id, e)}
                className="absolute top-2 right-2 p-1.5 opacity-0 group-hover:opacity-100 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg transition-all duration-200 text-red-600 dark:text-red-400"
                title="Delete conversation"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>

        {currentPaper && (
          <div className="p-3 m-2 border-t border-gray-700 bg-gray-800 rounded-lg border border-elegant-primary/20">
            <div className="text-[10px] font-semibold text-elegant-primary mb-1 flex items-center gap-1.5">
              <BookOpen className="w-2.5 h-2.5" />
              Current Paper
            </div>
            <div className="text-xs text-gray-300 truncate font-medium">{currentPaper.title}</div>
          </div>
        )}
        
        {/* Resize Handle */}
        <div
          ref={resizeHandleRef}
          onMouseDown={(e) => {
            e.preventDefault()
            setIsResizing(true)
          }}
          className={`absolute top-0 right-0 w-1 h-full cursor-col-resize group transition-all duration-200 ${
            isResizing 
              ? 'bg-elegant-primary w-1.5' 
              : 'bg-transparent hover:bg-elegant-primary/40 hover:w-1.5'
          }`}
          style={{ zIndex: 10 }}
          title="Drag to resize"
        >
          {/* Visual indicator dots */}
          <div className="absolute top-1/2 right-0 transform -translate-y-1/2 translate-x-1/2 flex flex-col gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="w-1 h-1 rounded-full bg-elegant-primary" />
            <div className="w-1 h-1 rounded-full bg-elegant-primary" />
            <div className="w-1 h-1 rounded-full bg-elegant-primary" />
          </div>
        </div>
      </div>

      {/* Right Column - Chat Interface */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="bg-gray-900 border-b border-gray-700 p-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-bold bg-gradient-to-r from-elegant-primary to-elegant-secondary bg-clip-text text-transparent">
                Summary for AI Frontiers
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">Ask questions about academic papers</p>
            </div>
            <div className="flex items-start gap-3">
              <div className="relative flex flex-col">
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="px-3 py-2 bg-gradient-to-r from-elegant-primary/10 to-elegant-secondary/10 hover:from-elegant-primary/20 hover:to-elegant-secondary/20 text-elegant-primary rounded-lg border border-elegant-primary/20 hover:border-elegant-primary/40 transition-all duration-200 font-semibold text-xs cursor-pointer focus:outline-none focus:ring-2 focus:ring-elegant-primary appearance-none pr-8 min-w-[180px]"
                  style={{
                    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%236366f1' d='M6 9L1 4h10z'/%3E%3C/svg%3E")`,
                    backgroundRepeat: 'no-repeat',
                    backgroundPosition: 'right 1rem center',
                    backgroundSize: '12px'
                  }}
                >
                  {availableModels.length > 0 ? (
                    availableModels.map((model) => (
                      <option key={model.id} value={model.id} className="bg-gray-900 text-gray-100 py-2">
                        {model.name}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="grok-4-fast">Grok-4 Fast</option>
                      <option value="gpt-5">GPT-5</option>
                      <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
                      <option value="gemini-3-flash-preview">Gemini 3 Flash</option>
                      <option value="deepseek">DeepSeek</option>
                      <option value="supermind-agent-v1">Supermind Agent</option>
                    </>
                  )}
                </select>
                {selectedModel === "supermind-agent-v1" && (
                  <div className="mt-1 flex items-center gap-1 text-[10px] text-gray-400">
                    <Search className="w-2.5 h-2.5" />
                    <span>Web search enabled</span>
                  </div>
                )}
              </div>
              {/* OpenReview Toggle */}
              <div className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-elegant-primary/10 to-elegant-secondary/10 rounded-lg border border-elegant-primary/20">
                <Globe className={`w-4 h-4 ${useOpenReview ? 'text-elegant-primary' : 'text-gray-400'}`} />
                <span className="text-xs font-medium text-gray-300">OpenReview</span>
                <button
                  onClick={() => setUseOpenReview(!useOpenReview)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-elegant-primary focus:ring-offset-2 ${
                    useOpenReview ? 'bg-elegant-primary' : 'bg-slate-300 dark:bg-slate-600'
                  }`}
                  role="switch"
                  aria-checked={useOpenReview}
                  aria-label="Toggle OpenReview search"
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      useOpenReview ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </button>
                {useOpenReview && selectedModel === 'supermind-agent-v1' && (
                  <span className="text-[10px] text-gray-400 ml-1">(disabled for this model)</span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-black">
          {messages.length === 0 && (
            <div className="text-center mt-12">
              <div className="inline-flex p-3 bg-gradient-to-br from-elegant-primary/10 to-elegant-secondary/10 rounded-2xl mb-4">
                <BookOpen className="w-8 h-8 text-elegant-primary" />
              </div>
              <h3 className="text-xl font-bold bg-gradient-to-r from-elegant-primary to-elegant-secondary bg-clip-text text-transparent mb-2">
                Welcome to Paper Analysis Chat
              </h3>
              <p className="text-gray-400 mb-6 text-sm">
                Ask a question about academic papers to get started
              </p>
              
              {suggestions.length > 0 && (
                <div className="max-w-3xl mx-auto">
                  <div className="text-xs font-semibold text-gray-400 mb-3 flex items-center justify-center gap-1.5">
                    <Sparkles className="w-3 h-3 text-elegant-primary" />
                    Try asking:
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {suggestions.slice(0, 6).map((suggestion, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleSuggestionClick(suggestion)}
                        className="p-3 text-left bg-gray-900 border border-gray-700 rounded-lg hover:border-elegant-primary hover:bg-gray-800 transition-all duration-200 text-xs text-gray-300 font-medium"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {messages.map((message, idx) => {
            // Check if this is a multi-model response
            const isMultiModel = message.content.startsWith('**[') && message.content.includes(']**')
            const modelMatch = message.content.match(/\*\*\[([^\]]+)\]\*\*/)
            const modelName = modelMatch ? modelMatch[1] : null
            const contentWithoutModel = modelMatch ? message.content.replace(/\*\*\[[^\]]+\]\*\*\n\n/, '') : message.content
            
            // Ensure message has an ID
            const messageId = message.id || `msg-${idx}-${Date.now()}`
            
            return (
              <div
                key={messageId}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'} group`}
              >
                <div
                  className={`relative max-w-2xl rounded-lg px-4 py-3 ${
                    message.role === 'user'
                      ? 'bg-gradient-to-br from-elegant-primary to-elegant-secondary text-white'
                      : isMultiModel
                      ? 'bg-gray-900 text-gray-100 border border-purple-700/50'
                      : 'bg-gray-900 text-gray-100 border border-gray-700'
                  }`}
                >
                  {message.role === 'user' && (
                    <button
                      onClick={() => editMessage(messageId)}
                      className="absolute -top-2 -right-2 p-1 opacity-0 group-hover:opacity-100 bg-gray-900 text-elegant-primary rounded border border-gray-700 hover:border-elegant-primary transition-all duration-200 z-10"
                      title="Edit and resubmit"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                  )}
                  {isMultiModel && modelName && (
                    <div className="flex items-center gap-1.5 mb-2 pb-2 border-b border-purple-700/50">
                      <Zap className="w-3 h-3 text-purple-400" />
                      <span className="text-[10px] font-bold text-purple-300">{modelName}</span>
                    </div>
                  )}
                  {message.role === 'user' && message.files && message.files.length > 0 && (
                    <div className="mt-3 mb-3 pt-3 border-t border-white/20">
                      <div className="text-[10px] font-semibold text-white/80 mb-1.5 flex items-center gap-1.5">
                        <Upload className="w-2.5 h-2.5" />
                        Attached Files ({message.files.length}):
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {message.files.map((file) => (
                          <div
                            key={file.id}
                            className="px-2 py-1.5 bg-white/20 hover:bg-white/30 rounded text-[10px] font-medium border border-white/30 flex items-center gap-1.5"
                          >
                            {getFileIcon(file.type)}
                            <span className="truncate max-w-[200px]">{file.name}</span>
                            <span className="text-white/60">({formatFileSize(file.size)})</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {message.role === 'assistant' && message.pdf_links && message.pdf_links.length > 0 && (
                    <div className="mb-3 pb-3 border-b border-gray-700">
                      <div className="text-[10px] font-semibold text-gray-400 mb-1.5 flex items-center gap-1.5">
                        <BookOpen className="w-2.5 h-2.5" />
                        Related Documents:
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {message.pdf_links
                          .filter(link => link.url && link.url.trim() && link.url.startsWith('http')) // Filter out invalid URLs
                          .map((link, linkIdx) => (
                            <div key={`${link.url}-${linkIdx}`} className="flex gap-1.5">
                              <a
                                href={link.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="px-2 py-1 bg-gradient-to-r from-elegant-primary/10 to-elegant-secondary/10 hover:from-elegant-primary/20 hover:to-elegant-secondary/20 text-elegant-primary rounded text-[10px] font-medium border border-elegant-primary/20 hover:border-elegant-primary/40 transition-all duration-200"
                              >
                                📄 {link.title && link.title.length > 40 ? link.title.substring(0, 40) + '...' : (link.title || 'Paper')}
                              </a>
                              {link.review_url && link.review_url.trim() && link.review_url.startsWith('http') && (
                                <a
                                  href={link.review_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded text-[10px] font-medium border border-gray-600 hover:border-gray-500 transition-all duration-200"
                                >
                                  💬 Reviews
                                </a>
                              )}
                            </div>
                          ))}
                      </div>
                    </div>
                  )}
                  {message.role === 'assistant' && message.requires_clarification && (
                    <div className="mb-3 p-3 bg-yellow-900/20 border border-yellow-700/40 rounded-lg">
                      <div className="text-xs font-semibold text-yellow-400 mb-2 flex items-center gap-1.5">
                        <MessageSquare className="w-3 h-3" />
                        Clarification Needed
                      </div>
                      <div className="text-sm text-gray-200 whitespace-pre-wrap">{message.content}</div>
                    </div>
                  )}
                  {!(message.role === 'assistant' && message.requires_clarification) && (
                    <div className="whitespace-pre-wrap leading-relaxed text-sm">{contentWithoutModel}</div>
                  )}
                  <div className={`text-[10px] mt-2 ${
                    message.role === 'user' ? 'text-white/70' : 'text-gray-400'
                  }`}>
                    {message.timestamp.toLocaleTimeString()}
                  </div>
                </div>
              </div>
            )
          })}
          
          {multiModelResponses.length > 0 && (
            <div className="mt-4 p-4 bg-gray-900 border border-purple-700/50 rounded-lg">
              <div className="flex items-center gap-2 mb-3">
                <div className="p-1.5 bg-gradient-to-br from-purple-500 to-blue-500 rounded-lg">
                  <Zap className="w-4 h-4 text-white" />
                </div>
                <span className="font-bold text-sm bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">Parallel Model Responses</span>
              </div>
              <div className="space-y-3">
                {multiModelResponses.map((response, idx) => (
                  <div key={idx} className="bg-gray-800 rounded-lg p-3 border border-purple-700/50 transition-all duration-200">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-bold bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">{response.model}</span>
                      {response.error && (
                        <span className="text-[10px] font-semibold text-red-400 bg-red-900/30 px-1.5 py-0.5 rounded">Error</span>
                      )}
                    </div>
                    {response.error ? (
                      <div className="text-xs text-red-400">{response.error}</div>
                    ) : (
                      <div className="text-xs text-gray-300 whitespace-pre-wrap leading-relaxed">{response.message}</div>
                    )}
                    {response.usage && (
                      <div className="text-[10px] text-gray-400 mt-2 pt-2 border-t border-gray-700">
                        Tokens: <span className="font-semibold">{response.usage.total_tokens}</span> (prompt: {response.usage.prompt_tokens}, completion: {response.usage.completion_tokens})
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {(isLoading || isUploading) && (
            <div className="flex justify-start">
              <div className="bg-gray-900 border border-elegant-primary/20 rounded-lg px-4 py-3">
                <div className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-elegant-primary" />
                  <span className="text-xs text-gray-400">
                    {isUploading ? 'Uploading files...' : 'Thinking...'}
                  </span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="p-4 bg-gray-900 border-t border-gray-700">
          {editingMessageId && (
            <div className="mb-2 flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-elegant-primary/10 to-elegant-secondary/10 rounded-lg border border-elegant-primary/20">
              <Edit2 className="w-3 h-3 text-elegant-primary" />
              <span className="text-xs text-elegant-primary font-semibold">Editing previous message - will regenerate from this point</span>
              <button
                onClick={cancelEdit}
                className="ml-auto text-[10px] text-gray-400 hover:text-gray-300 transition-colors px-1.5 py-0.5 hover:bg-gray-800 rounded"
              >
                Cancel (Esc)
              </button>
            </div>
          )}
          {uploadedFiles.length > 0 && (
            <div className="mb-2 p-2 bg-gradient-to-r from-elegant-primary/10 to-elegant-secondary/10 rounded-lg border border-elegant-primary/20">
              <div className="text-[10px] font-semibold text-elegant-primary mb-1.5 flex items-center gap-1.5">
                <Upload className="w-2.5 h-2.5" />
                Attached Files ({uploadedFiles.length}):
              </div>
              <div className="flex flex-wrap gap-1.5">
                {uploadedFiles.map((file) => (
                  <div
                    key={file.id}
                    className="group relative px-2 py-1.5 bg-gray-800 rounded border border-elegant-primary/20 hover:border-elegant-primary/40 transition-all duration-200 flex items-center gap-1.5"
                  >
                    <div className="text-elegant-primary">
                      {getFileIcon(file.type)}
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="text-[10px] font-medium text-gray-300 truncate max-w-[180px]">
                        {file.name}
                      </span>
                      <span className="text-[10px] text-gray-400">
                        {formatFileSize(file.size)}
                      </span>
                    </div>
                    <button
                      onClick={() => removeFile(file.id)}
                      className="ml-1.5 p-0.5 hover:bg-red-900/30 rounded transition-colors text-red-400 opacity-0 group-hover:opacity-100"
                      title="Remove file"
                    >
                      <X className="w-2.5 h-2.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    sendMessage()
                  }
                }}
                placeholder="Ask about the paper, request a summary, or ask any question..."
                rows={3}
                className="input-elegant resize-none pr-8"
              />
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileSelect}
                className="hidden"
                accept=".pdf,.txt,.doc,.docx"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isLoading || isUploading}
                className="absolute top-2 right-2 p-1.5 text-gray-400 hover:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title="Upload files"
              >
                <Paperclip className="w-3.5 h-3.5" />
              </button>
            </div>
            <button
              onClick={sendMessage}
              disabled={(!input.trim() && uploadedFiles.length === 0) || isLoading || isUploading}
              className="btn-primary flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-3 text-xs"
            >
              <Send className="w-4 h-4" />
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

