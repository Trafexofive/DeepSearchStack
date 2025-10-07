'use client'

import { useState, useRef, useEffect } from 'react'
import { Search, Send, Loader2 } from 'lucide-react'

export default function Home() {
  const [query, setQuery] = useState('')
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState<any[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [progress, setProgress] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [answer])

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim() || isSearching) return

    setIsSearching(true)
    setAnswer('')
    setSources([])
    setProgress('Starting search...')

    try {
      const response = await fetch('/api/deepsearch', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query,
          stream: true,
          max_results: 30,
          enable_scraping: true,
          enable_rag: true,
        }),
      })

      if (!response.ok) throw new Error('Search failed')

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) throw new Error('No reader available')

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value)
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))

              if (data.type === 'progress') {
                setProgress(data.data.message)
              } else if (data.type === 'content') {
                setAnswer(prev => prev + data.data.content)
              } else if (data.type === 'sources') {
                setSources(data.data.sources)
              } else if (data.type === 'complete') {
                setProgress('Complete!')
              } else if (data.type === 'error') {
                setProgress(`Error: ${data.data.message}`)
              }
            } catch (e) {
              // Ignore JSON parse errors
            }
          }
        }
      }
    } catch (error) {
      setProgress(`Error: ${error}`)
    } finally {
      setIsSearching(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
      {/* Header */}
      <header className="border-b bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center gap-2">
            <Search className="w-6 h-6" />
            <h1 className="text-2xl font-bold">DeepSearch</h1>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-8 max-w-4xl">
        {/* Search Form */}
        <form onSubmit={handleSearch} className="mb-8">
          <div className="relative">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask anything..."
              className="w-full px-4 py-3 pr-12 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={isSearching}
            />
            <button
              type="submit"
              disabled={isSearching || !query.trim()}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSearching ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
        </form>

        {/* Progress */}
        {isSearching && (
          <div className="mb-4 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 text-blue-900 dark:text-blue-100">
            <div className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="text-sm">{progress}</span>
            </div>
          </div>
        )}

        {/* Answer */}
        {answer && (
          <div className="mb-6 p-6 rounded-lg bg-white dark:bg-slate-800 shadow-sm">
            <h2 className="text-lg font-semibold mb-3">Answer</h2>
            <div className="prose dark:prose-invert max-w-none">
              {answer.split('\n').map((line, i) => (
                <p key={i} className="mb-2">{line}</p>
              ))}
            </div>
          </div>
        )}

        {/* Sources */}
        {sources.length > 0 && (
          <div className="p-6 rounded-lg bg-white dark:bg-slate-800 shadow-sm">
            <h2 className="text-lg font-semibold mb-3">Sources ({sources.length})</h2>
            <div className="space-y-3">
              {sources.slice(0, 10).map((source, i) => (
                <div key={i} className="p-3 rounded border border-slate-200 dark:border-slate-700">
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 dark:text-blue-400 hover:underline font-medium"
                  >
                    [{i + 1}] {source.title}
                  </a>
                  <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
                    {source.description?.substring(0, 150)}...
                  </p>
                  <p className="text-xs text-slate-500 mt-1">{source.source}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>
    </div>
  )
}
