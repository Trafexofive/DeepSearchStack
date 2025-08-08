'use client';

import { useState, useRef, useEffect } from 'react';
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

interface Source {
  title: string;
  url: string;
}

export default function Chat() {
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<{
    role: 'user' | 'assistant';
    content: string;
    sources?: Source[];
  }[]>([]);
  const [loading, setLoading] = useState(false);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  const handleSearch = async () => {
    if (!query.trim()) return;

    setLoading(true);
    const userMessage = { role: 'user' as const, content: query };
    setMessages(prev => [...prev, userMessage]);

    const response = await fetch('/api/search/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query }),
    });

    if (!response.body) {
      setLoading(false);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let assistantMessage = { role: 'assistant' as const, content: '', sources: [] as Source[] };
    setMessages(prev => [...prev, assistantMessage]);

    reader.read().then(function processText({ done, value }): Promise<void> {
      if (done) {
        setLoading(false);
        return Promise.resolve();
      }

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n\n');

      lines.forEach(line => {
        if (line.startsWith('data:')) {
          try {
            const data = JSON.parse(line.substring(5));
            if (data.type === 'sources') {
              assistantMessage.sources = data.payload;
            } else if (data.type === 'content') {
              assistantMessage.content += data.payload;
            }
            setMessages(prev => [...prev.slice(0, -1), { ...assistantMessage }]);
          } catch (e) {
            console.error("Error parsing stream data:", e);
          }
        }
      });

      return reader.read().then(processText);
    });

    setQuery('');
  };

  useEffect(() => {
    if (scrollAreaRef.current) {
      scrollAreaRef.current.scrollTo({ top: scrollAreaRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [messages]);

  return (
    <div className="flex flex-col h-full bg-white dark:bg-gray-800 rounded-lg shadow-lg">
      <ScrollArea className="flex-1 p-4" ref={scrollAreaRef}>
        <div className="space-y-4">
          {messages.map((message, index) => (
            <div key={index} className={`flex items-start gap-4 ${message.role === 'user' ? 'justify-end' : ''}`}>
              {message.role === 'assistant' && (
                <div className="w-8 h-8 rounded-full bg-gray-300 dark:bg-gray-700 flex items-center justify-center font-bold">A</div>
              )}
              <div className={`rounded-lg p-3 max-w-[75%] ${message.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-200 dark:bg-gray-700'}`}>
                <p className="text-sm">{message.content}</p>
                {message.sources && message.sources.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-gray-300 dark:border-gray-600">
                    <h4 className="text-xs font-bold mb-1">Sources:</h4>
                    <ul className="list-disc pl-4 space-y-1">
                      {message.sources.map((source, i) => (
                        <li key={i} className="text-xs">
                          <a href={source.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                            {source.title}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              {message.role === 'user' && (
                <div className="w-8 h-8 rounded-full bg-gray-400 dark:bg-gray-600 flex items-center justify-center font-bold">U</div>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>
      <div className="p-4 border-t dark:border-gray-700">
        <div className="flex items-center space-x-2">
          <Input
            type="text"
            placeholder="Ask a question..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && !loading && handleSearch()}
            className="flex-1"
            disabled={loading}
          />
          <Button type="submit" onClick={handleSearch} disabled={loading}>
            {loading ? 'Searching...' : 'Send'}
          </Button>
        </div>
      </div>
    </div>
  );
}