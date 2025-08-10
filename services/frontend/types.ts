
export interface Source {
  title: string;
  url: string;
  description: string;
  source: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
}

export interface StreamChunk {
    content: string;
    finished: boolean;
    sources?: Source[];
}

export type AppMode = 'search' | 'chat';

export interface LlmProvider {
  id: string;
  available: boolean;
}
