'use client'

import { useState, useEffect, useRef } from 'react'
import { Send, Search, BookOpen, MessageSquare, Sparkles, Loader2, Settings, Zap, Globe, X, Edit2 } from 'lucide-react'
import axios from 'axios'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  id?: string
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
  
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

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

  // Handle Escape key to cancel editing
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && editingMessageId) {
        cancelEdit()
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
        id: `msg-${Date.now()}`
      }
      setMessages(prev => [...prev, paperMessage])
    } catch (error) {
      console.error('Failed to load paper context:', error)
    }
  }

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return

    const messageId = editingMessageId || `msg-${Date.now()}`
    const userMessage: Message = {
      role: 'user',
      content: input,
      timestamp: new Date(),
      id: messageId
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
    setInput('')
    setIsLoading(true)
    setMultiModelResponses([])

    try {
      // Single model response using selected model
      const response = await axios.post(`${API_BASE_URL}/api/chat`, {
        messages: messagesToSend.map(m => ({ role: m.role, content: m.content })),
        model: selectedModel,
        paper_id: currentPaper?.paper_id,
        paper_context: currentPaper
      })

      const assistantMessage: Message = {
        role: 'assistant',
        content: response.data.message,
        timestamp: new Date(),
        id: `msg-${Date.now()}`
      }

      setMessages(prev => [...prev, assistantMessage])
      
      // Update conversation
      if (activeConversation) {
        const updatedMessages = [...messagesToSend, assistantMessage]
        setConversations(prev => prev.map(conv => 
          conv.id === activeConversation 
            ? { ...conv, messages: updatedMessages, title: messagesToSend.length === 1 ? messageInput.substring(0, 50) : conv.title }
            : conv
        ))
      }
    } catch (error) {
      console.error('Chat error:', error)
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
    <div className="flex h-screen bg-gradient-to-br from-slate-50 via-blue-50/30 to-indigo-50/30 dark:from-slate-900 dark:via-slate-800 dark:to-slate-900">
      {/* Left Column - Conversations */}
      <div className="w-80 bg-white/80 dark:bg-slate-800/90 backdrop-blur-sm border-r border-slate-200/50 dark:border-slate-700/50 flex flex-col shadow-elegant">
        <div className="p-6 border-b border-slate-200/50 dark:border-slate-700/50 bg-gradient-to-r from-elegant-primary/5 to-elegant-secondary/5">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-gradient-to-br from-elegant-primary to-elegant-secondary rounded-xl shadow-elegant">
              <BookOpen className="w-6 h-6 text-white" />
            </div>
            <h1 className="text-2xl font-bold bg-gradient-to-r from-elegant-primary to-elegant-secondary bg-clip-text text-transparent">
              Paper Chat
            </h1>
          </div>
          <button
            onClick={createNewConversation}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            <MessageSquare className="w-5 h-5" />
            New Conversation
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto p-3">
          {conversations.map(conv => (
            <div
              key={conv.id}
              className={`group relative w-full p-4 rounded-xl mb-2 transition-all duration-200 ${
                activeConversation === conv.id
                  ? 'bg-gradient-to-r from-elegant-primary/10 to-elegant-secondary/10 border-2 border-elegant-primary/30 text-elegant-primary dark:text-elegant-primary shadow-elegant'
                  : 'hover:bg-slate-100/50 dark:hover:bg-slate-700/50 text-slate-700 dark:text-slate-300 border-2 border-transparent hover:border-slate-200 dark:hover:border-slate-600'
              }`}
            >
              <button
                onClick={() => switchConversation(conv.id)}
                className="w-full text-left pr-8"
              >
                <div className="font-semibold truncate mb-1">{conv.title}</div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
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
          <div className="p-4 m-3 border-t border-slate-200/50 dark:border-slate-700/50 bg-gradient-to-br from-elegant-primary/5 to-elegant-secondary/5 rounded-xl border-2 border-elegant-primary/20">
            <div className="text-xs font-semibold text-elegant-primary dark:text-elegant-primary mb-2 flex items-center gap-2">
              <BookOpen className="w-3 h-3" />
              Current Paper
            </div>
            <div className="text-sm text-slate-700 dark:text-slate-300 truncate font-medium">{currentPaper.title}</div>
          </div>
        )}
      </div>

      {/* Right Column - Chat Interface */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm border-b border-slate-200/50 dark:border-slate-700/50 p-6 shadow-elegant">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold bg-gradient-to-r from-elegant-primary to-elegant-secondary bg-clip-text text-transparent">
                Paper Analysis Assistant
              </h2>
              <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">Ask questions about academic papers</p>
            </div>
            <div className="flex items-center gap-3">
              <div className="relative">
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="px-4 py-2.5 bg-gradient-to-r from-elegant-primary/10 to-elegant-secondary/10 hover:from-elegant-primary/20 hover:to-elegant-secondary/20 text-elegant-primary dark:text-elegant-primary rounded-xl border-2 border-elegant-primary/20 hover:border-elegant-primary/40 transition-all duration-200 shadow-elegant hover:shadow-elegant-lg font-semibold text-sm cursor-pointer focus:outline-none focus:ring-2 focus:ring-elegant-primary appearance-none pr-10 min-w-[200px]"
                  style={{
                    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%236366f1' d='M6 9L1 4h10z'/%3E%3C/svg%3E")`,
                    backgroundRepeat: 'no-repeat',
                    backgroundPosition: 'right 1rem center',
                    backgroundSize: '12px'
                  }}
                >
                  {availableModels.length > 0 ? (
                    availableModels.map((model) => (
                      <option key={model.id} value={model.id} className="bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 py-2">
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
              </div>
              <div className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-elegant-primary/10 to-elegant-secondary/10 rounded-xl border border-elegant-primary/20">
                <Sparkles className="w-5 h-5 text-elegant-primary" />
                <span className="text-sm font-medium text-elegant-primary">AI Builder API</span>
              </div>
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 && (
            <div className="text-center mt-20">
              <div className="inline-flex p-4 bg-gradient-to-br from-elegant-primary/10 to-elegant-secondary/10 rounded-3xl mb-6 shadow-elegant-lg">
                <BookOpen className="w-16 h-16 text-elegant-primary" />
              </div>
              <h3 className="text-3xl font-bold bg-gradient-to-r from-elegant-primary to-elegant-secondary bg-clip-text text-transparent mb-3">
                Welcome to Paper Analysis Chat
              </h3>
              <p className="text-slate-500 dark:text-slate-400 mb-8 text-lg">
                Ask a question about academic papers to get started
              </p>
              
              {suggestions.length > 0 && (
                <div className="max-w-3xl mx-auto">
                  <div className="text-sm font-semibold text-slate-600 dark:text-slate-400 mb-4 flex items-center justify-center gap-2">
                    <Sparkles className="w-4 h-4 text-elegant-primary" />
                    Try asking:
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {suggestions.slice(0, 6).map((suggestion, idx) => (
                      <button
                        key={idx}
                        onClick={() => handleSuggestionClick(suggestion)}
                        className="p-4 text-left bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm border-2 border-slate-200/50 dark:border-slate-700/50 rounded-xl hover:border-elegant-primary hover:bg-gradient-to-r hover:from-elegant-primary/5 hover:to-elegant-secondary/5 hover:shadow-elegant-lg transition-all duration-200 text-sm text-slate-700 dark:text-slate-300 font-medium hover:scale-[1.02]"
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
                  className={`relative max-w-3xl rounded-2xl px-5 py-4 shadow-elegant-lg ${
                    message.role === 'user'
                      ? 'bg-gradient-to-br from-elegant-primary to-elegant-secondary text-white'
                      : isMultiModel
                      ? 'bg-gradient-to-br from-purple-50/80 to-blue-50/80 dark:from-purple-950/80 dark:to-blue-950/80 text-slate-900 dark:text-slate-100 border-2 border-purple-300/50 dark:border-purple-700/50 backdrop-blur-sm'
                      : 'bg-white/90 dark:bg-slate-800/90 text-slate-900 dark:text-slate-100 border-2 border-slate-200/50 dark:border-slate-700/50 backdrop-blur-sm'
                  }`}
                >
                  {message.role === 'user' && (
                    <button
                      onClick={() => editMessage(messageId)}
                      className="absolute -top-2 -right-2 p-1.5 opacity-0 group-hover:opacity-100 bg-white/90 dark:bg-slate-800/90 text-elegant-primary rounded-lg shadow-elegant hover:shadow-elegant-lg transition-all duration-200 hover:scale-110 z-10"
                      title="Edit message"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                  )}
                  {isMultiModel && modelName && (
                    <div className="flex items-center gap-2 mb-3 pb-3 border-b border-purple-300/50 dark:border-purple-700/50">
                      <Zap className="w-4 h-4 text-purple-600 dark:text-purple-400" />
                      <span className="text-xs font-bold text-purple-700 dark:text-purple-300">{modelName}</span>
                    </div>
                  )}
                  <div className="whitespace-pre-wrap leading-relaxed">{contentWithoutModel}</div>
                  <div className={`text-xs mt-3 ${
                    message.role === 'user' ? 'text-white/70' : 'text-slate-400'
                  }`}>
                    {message.timestamp.toLocaleTimeString()}
                  </div>
                </div>
              </div>
            )
          })}
          
          {multiModelResponses.length > 0 && (
            <div className="mt-6 p-6 bg-gradient-to-br from-purple-50/90 to-blue-50/90 dark:from-purple-950/90 dark:to-blue-950/90 backdrop-blur-sm border-2 border-purple-300/50 dark:border-purple-700/50 rounded-2xl shadow-elegant-xl">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 bg-gradient-to-br from-purple-500 to-blue-500 rounded-xl">
                  <Zap className="w-5 h-5 text-white" />
                </div>
                <span className="font-bold text-lg bg-gradient-to-r from-purple-600 to-blue-600 bg-clip-text text-transparent">Parallel Model Responses</span>
              </div>
              <div className="space-y-4">
                {multiModelResponses.map((response, idx) => (
                  <div key={idx} className="bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm rounded-xl p-4 border-2 border-purple-200/50 dark:border-purple-700/50 shadow-elegant hover:shadow-elegant-lg transition-all duration-200">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-sm font-bold bg-gradient-to-r from-purple-600 to-blue-600 bg-clip-text text-transparent">{response.model}</span>
                      {response.error && (
                        <span className="text-xs font-semibold text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950 px-2 py-1 rounded-lg">Error</span>
                      )}
                    </div>
                    {response.error ? (
                      <div className="text-sm text-red-600 dark:text-red-400">{response.error}</div>
                    ) : (
                      <div className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap leading-relaxed">{response.message}</div>
                    )}
                    {response.usage && (
                      <div className="text-xs text-slate-500 dark:text-slate-400 mt-3 pt-3 border-t border-slate-200/50 dark:border-slate-700/50">
                        Tokens: <span className="font-semibold">{response.usage.total_tokens}</span> (prompt: {response.usage.prompt_tokens}, completion: {response.usage.completion_tokens})
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm border-2 border-elegant-primary/20 rounded-2xl px-5 py-4 shadow-elegant">
                <Loader2 className="w-5 h-5 animate-spin text-elegant-primary" />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="p-6 bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm border-t border-slate-200/50 dark:border-slate-700/50 shadow-elegant-lg">
          {editingMessageId && (
            <div className="mb-3 flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-elegant-primary/10 to-elegant-secondary/10 rounded-lg border border-elegant-primary/20">
              <Edit2 className="w-4 h-4 text-elegant-primary" />
              <span className="text-sm text-elegant-primary font-medium">Editing message</span>
              <button
                onClick={cancelEdit}
                className="ml-auto text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
              >
                Cancel (Esc)
              </button>
            </div>
          )}
          <div className="flex gap-3">
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
              className="input-elegant flex-1 resize-none"
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || isLoading}
              className="btn-primary flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Send className="w-5 h-5" />
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

