
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { ChatMessage } from '../types';
import { streamSearch, streamChat } from '../services/api';
import { SendIcon } from './Icons';
import { MessageBubble } from './MessageBubble';
import { useSettings } from '../contexts/SettingsContext';

const ModeSelector: React.FC = () => {
    const { mode, setMode } = useSettings();
    const commonClasses = "px-4 py-2 text-sm font-semibold rounded-md transition-colors focus:outline-none";
    const activeClasses = "bg-primary text-white";
    const inactiveClasses = "bg-gray-200 dark:bg-gray-700 text-text-light dark:text-text-dark hover:bg-gray-300 dark:hover:bg-gray-600";
    
    return (
        <div className="flex justify-center p-2 bg-gray-100 dark:bg-gray-900/50">
            <div className="flex space-x-2 p-1 bg-gray-200 dark:bg-gray-700 rounded-lg">
                <button 
                    onClick={() => setMode('search')}
                    className={`${commonClasses} ${mode === 'search' ? activeClasses : inactiveClasses}`}
                >
                    AI Search
                </button>
                <button 
                    onClick={() => setMode('chat')}
                    className={`${commonClasses} ${mode === 'chat' ? activeClasses : inactiveClasses}`}
                >
                    Direct Chat
                </button>
            </div>
        </div>
    );
};


const Chat: React.FC = () => {
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const { mode, selectedProvider } = useSettings();

  const scrollToBottom = () => {
    if (scrollAreaRef.current) {
      scrollAreaRef.current.scrollTo({
        top: scrollAreaRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = useCallback(async () => {
    if (!query.trim() || isLoading) return;

    setIsLoading(true);

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: query,
    };
    
    // Add user message to state, and create history for API call
    const historyWithUserMessage = [...messages, userMessage];
    setMessages(historyWithUserMessage);
    setQuery('');
    
    const assistantMessageId = (Date.now() + 1).toString();
    const assistantMessage: ChatMessage = {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        sources: [],
    };
    setMessages(prev => [...prev, assistantMessage]);

    const handleChunk = (chunk: any) => {
         setMessages(prev =>
          prev.map(msg =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: msg.content + chunk.content,
                  sources: chunk.sources && chunk.sources.length > 0 ? chunk.sources : msg.sources,
                }
              : msg
          )
        );
    };

    const handleError = (error: Error) => {
        setMessages(prev =>
          prev.map(msg =>
            msg.id === assistantMessageId
              ? { ...msg, content: msg.content + `\n\n**Error:** ${error.message}` }
              : msg
          )
        );
        setIsLoading(false);
    };

    const handleComplete = () => setIsLoading(false);
    
    if (mode === 'search') {
        streamSearch(query, selectedProvider, handleChunk, handleError, handleComplete);
    } else { // mode === 'chat'
        streamChat(historyWithUserMessage, selectedProvider, handleChunk, handleError, handleComplete);
    }

  }, [query, isLoading, mode, messages, selectedProvider]);

  const placeholderText = mode === 'search' 
    ? "Ask a question to search and summarize..."
    : `Chat directly with ${selectedProvider || 'the LLM'}...`;

  return (
    <div className="flex flex-col h-full bg-white dark:bg-gray-800 relative">
      <ModeSelector />
      <div ref={scrollAreaRef} className="flex-1 p-6 overflow-y-auto space-y-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center text-gray-400 dark:text-gray-500">
            <h3 className="text-lg font-semibold capitalize">{mode} Mode</h3>
            <p>
                {mode === 'search' 
                    ? 'The AI will search multiple sources and provide a synthesized answer with citations.'
                    : 'You are talking directly to the AI model. No search will be performed.'
                }
            </p>
            <p className="mt-4">Start a conversation by asking a question below.</p>
          </div>
        )}
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {isLoading && messages[messages.length - 1]?.role === 'assistant' && (
           <div className="flex items-start gap-4">
              <MessageBubble message={{ id: 'loading', role: 'assistant', content: messages[messages.length-1].content }} isLoading={true} />
           </div>
        )}
      </div>

      <div className="p-4 bg-white dark:bg-gray-800 border-t border-border-light dark:border-border-dark">
        <div className="relative">
          <textarea
            rows={1}
            placeholder={placeholderText}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            className="w-full pl-4 pr-12 py-3 rounded-xl border border-border-light dark:border-border-dark bg-assistant-bg dark:bg-dark-assistant-bg text-text-light dark:text-text-dark focus:outline-none focus:ring-2 focus:ring-primary resize-none"
            disabled={isLoading}
          />
          <button
            onClick={handleSubmit}
            disabled={isLoading || !query.trim()}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-2 rounded-lg bg-primary text-white disabled:bg-gray-300 dark:disabled:bg-gray-600 hover:bg-primary-hover disabled:cursor-not-allowed transition-colors"
            aria-label="Send message"
          >
            <SendIcon className="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default Chat;
