'use client'

import { useState, useCallback } from 'react'
import { MessageSquare, Image } from 'lucide-react'
import { SummaryTab } from '@/components/SummaryTab'
import { ImageTab } from '@/components/ImageTab'
import { ChatTab } from '@/components/ChatTab'
import type { PaperFormState } from '@/lib/types'
import { INITIAL_FORM_STATE } from '@/lib/types'

type TabType = 'summary' | 'chat' | 'image'

const tabLabels: { id: TabType; label: string; icon?: typeof MessageSquare }[] = [
  { id: 'summary', label: 'Summary' },
  { id: 'image', label: 'Generate Image', icon: Image },
  { id: 'chat', label: 'Chat', icon: MessageSquare },
]

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabType>('summary')
  const [formByTab, setFormByTab] = useState<Record<string, PaperFormState>>({
    summary: { ...INITIAL_FORM_STATE },
    image: { ...INITIAL_FORM_STATE },
  })

  const summaryForm = formByTab.summary ?? INITIAL_FORM_STATE
  const imageForm = formByTab.image ?? INITIAL_FORM_STATE

  const setSummaryForm = useCallback((updater: PaperFormState | ((p: PaperFormState) => PaperFormState)) => {
    setFormByTab((prev) => ({
      ...prev,
      summary: typeof updater === 'function' ? updater(prev.summary ?? INITIAL_FORM_STATE) : updater,
    }))
  }, [])

  const setImageForm = useCallback((updater: PaperFormState | ((p: PaperFormState) => PaperFormState)) => {
    setFormByTab((prev) => ({
      ...prev,
      image: typeof updater === 'function' ? updater(prev.image ?? INITIAL_FORM_STATE) : updater,
    }))
  }, [])

  const switchTab = useCallback((tab: TabType) => setActiveTab(tab), [])

  return (
    <div className="min-h-screen bg-gray-900">
      <header className="bg-gray-900/95 border-b border-gray-700 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent mb-4">
            Paper Analysis Tool
          </h1>
          <div className="flex gap-2">
            {tabLabels.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => switchTab(id)}
                className={`px-6 py-2 rounded-lg font-semibold transition-colors ${
                  activeTab === id
                    ? 'bg-gradient-to-r from-blue-500 to-purple-500 text-white shadow-lg'
                    : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                }`}
              >
                {Icon && <Icon className="w-4 h-4 inline mr-2" />}
                {label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        {activeTab === 'summary' && <SummaryTab form={summaryForm} setForm={setSummaryForm} />}
        {activeTab === 'image' && <ImageTab form={imageForm} setForm={setImageForm} />}
        {activeTab === 'chat' && <ChatTab />}
      </main>
    </div>
  )
}
