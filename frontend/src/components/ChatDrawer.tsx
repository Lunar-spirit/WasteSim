import { useMutation } from '@tanstack/react-query'
import { Bot, Loader2, Send, Sparkles, User, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createChatSession, sendChatQuery } from '../api/endpoints'
import { useAppContext } from '../context/AppContext'
import type { ChatMessage } from '../types/api'

const QUICK_PROMPTS = ['Summarize 10-year budget', 'Are there any vehicle shortages?']

interface LocalMessage {
  id: string | number
  role: 'USER' | 'ASSISTANT'
  content: string
  citations?: ChatMessage['citations']
}

export default function ChatDrawer() {
  const { isCopilotOpen, setIsCopilotOpen, currentHabitationId, activeRunId } = useAppContext()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<LocalMessage[]>([])
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const sessionMutation = useMutation({
    mutationFn: () => createChatSession(currentHabitationId),
    onSuccess: (session) => setSessionId(session.id),
  })

  // A fresh session per habitation, created lazily the first time the
  // drawer opens for it (design: "the session is bound to one habitation").
  useEffect(() => {
    if (isCopilotOpen && !sessionId && !sessionMutation.isPending) {
      sessionMutation.mutate()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isCopilotOpen])

  useEffect(() => {
    setSessionId(null)
    setMessages([])
  }, [currentHabitationId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const queryMutation = useMutation({
    mutationFn: (text: string) => sendChatQuery(sessionId as string, text, activeRunId),
    onSuccess: (assistantMessage) => {
      setMessages((prev) => [
        ...prev,
        { id: assistantMessage.id, role: 'ASSISTANT', content: assistantMessage.content, citations: assistantMessage.citations },
      ])
    },
    onError: (error: Error) => {
      setMessages((prev) => [...prev, { id: `err-${Date.now()}`, role: 'ASSISTANT', content: `Error: ${error.message}` }])
    },
  })

  function handleSend(text: string) {
    const trimmed = text.trim()
    if (!trimmed || !sessionId || queryMutation.isPending) return
    setMessages((prev) => [...prev, { id: `local-${Date.now()}`, role: 'USER', content: trimmed }])
    setInput('')
    queryMutation.mutate(trimmed)
  }

  return (
    <>
      {isCopilotOpen && (
        <button
          type="button"
          aria-label="Close copilot"
          onClick={() => setIsCopilotOpen(false)}
          className="fixed inset-0 z-40 bg-slate-900/20"
        />
      )}
      <aside
        className={`fixed right-0 top-0 z-50 flex h-full w-[380px] flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform duration-300 ${
          isCopilotOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-emerald-600" />
            <h2 className="text-sm font-semibold text-slate-800">AI Copilot</h2>
          </div>
          <button
            type="button"
            onClick={() => setIsCopilotOpen(false)}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {sessionMutation.isPending && (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Starting session…
            </div>
          )}
          {messages.length === 0 && !sessionMutation.isPending && (
            <p className="text-sm text-slate-400">
              Ask about this habitation's budget, coverage, findings, or anything else grounded in its stored runs.
            </p>
          )}
          {messages.map((message) => (
            <div key={message.id} className={`flex gap-2 ${message.role === 'USER' ? 'flex-row-reverse' : ''}`}>
              <div
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                  message.role === 'USER' ? 'bg-slate-800 text-white' : 'bg-emerald-100 text-emerald-700'
                }`}
              >
                {message.role === 'USER' ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
              </div>
              <div
                className={`max-w-[260px] rounded-2xl px-3 py-2 text-sm ${
                  message.role === 'USER'
                    ? 'rounded-tr-sm bg-slate-800 text-white'
                    : 'rounded-tl-sm bg-slate-100 text-slate-800'
                }`}
              >
                <p className="whitespace-pre-wrap">{message.content}</p>
                {message.citations && message.citations.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {message.citations.map((citation, idx) => {
                      const label = citation.indicator ?? citation.field ?? (citation.job_id ? 'job' : 'source')
                      return (
                        <span
                          key={idx}
                          title={JSON.stringify(citation)}
                          className="cursor-default rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-medium text-emerald-700 ring-1 ring-emerald-200"
                        >
                          [{label}]
                        </span>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          ))}
          {queryMutation.isPending && (
            <div className="flex items-center gap-2 pl-8 text-xs text-slate-400">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Thinking…
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5 border-t border-slate-100 px-4 pt-3">
          {QUICK_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => handleSend(prompt)}
              disabled={!sessionId || queryMutation.isPending}
              className="rounded-full border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600 transition hover:border-emerald-300 hover:text-emerald-700 disabled:opacity-50"
            >
              {prompt}
            </button>
          ))}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            handleSend(input)
          }}
          className="flex items-center gap-2 border-t border-slate-200 p-3"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask the copilot…"
            disabled={!sessionId}
            className="flex-1 rounded-full border border-slate-300 px-4 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:bg-slate-50"
          />
          <button
            type="submit"
            disabled={!sessionId || !input.trim() || queryMutation.isPending}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-white transition hover:bg-emerald-700 disabled:opacity-50"
            aria-label="Send"
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
      </aside>
    </>
  )
}
