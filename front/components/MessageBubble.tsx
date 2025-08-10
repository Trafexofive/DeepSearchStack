
import React from 'react';
import { ChatMessage } from '../types';
import { BotIcon, UserIcon } from './Icons';
import { SourceList } from './SourceList';

interface MessageBubbleProps {
  message: ChatMessage;
  isLoading?: boolean;
}

const BlinkingCursor: React.FC = () => (
  <span className="inline-block w-2 h-5 bg-primary animate-pulse ml-1" />
);

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message, isLoading = false }) => {
  const isUser = message.role === 'user';
  
  // A simple markdown to HTML converter for bold text
  const formatContent = (text: string) => {
    const html = text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') // Bold
      .replace(/\n/g, '<br />'); // Newlines
    return { __html: html };
  };

  return (
    <div className={`flex items-start gap-4 ${isUser ? 'justify-end' : ''}`}>
      {!isUser && (
        <div className="flex-shrink-0 w-10 h-10 rounded-full bg-primary/10 dark:bg-primary/20 flex items-center justify-center text-primary">
          <BotIcon className="w-6 h-6" />
        </div>
      )}

      <div className={`max-w-[75%] rounded-2xl p-4 ${isUser ? 'bg-primary text-white rounded-br-lg' : 'bg-assistant-bg dark:bg-dark-assistant-bg text-text-light dark:text-text-dark rounded-bl-lg'}`}>
        <div className="prose prose-sm dark:prose-invert max-w-none text-inherit leading-relaxed" dangerouslySetInnerHTML={formatContent(message.content)} />
        {isLoading && message.content.length > 0 && <BlinkingCursor />}
        {message.sources && message.sources.length > 0 && (
          <SourceList sources={message.sources} />
        )}
      </div>

      {isUser && (
        <div className="flex-shrink-0 w-10 h-10 rounded-full bg-gray-200 dark:bg-gray-600 flex items-center justify-center">
          <UserIcon className="w-6 h-6 text-gray-600 dark:text-gray-300" />
        </div>
      )}
    </div>
  );
};
