
import { StreamChunk, ChatMessage, LlmProvider } from '../types';

const handleStream = async (
  response: Response,
  onChunk: (chunk: StreamChunk) => void,
  onError: (error: Error) => void,
  onComplete: () => void
) => {
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API Error: ${response.status} ${errorText}`);
  }

  if (!response.body) {
    throw new Error('Response body is empty');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let cancelled = false;

  const processStream = async () => {
    while (!cancelled) {
      try {
        const { done, value } = await reader.read();
        if (done) break;

        const chunkText = decoder.decode(value, { stream: true });
        const lines = chunkText.split('\n\n').filter(line => line.trim());
        
        for (const line of lines) {
          if (line.startsWith('data:')) {
            try {
              const jsonData = line.substring(5);
              const chunk = JSON.parse(jsonData);

              if (chunk.type === 'error') {
                  throw new Error(chunk.payload || 'An unknown stream error occurred');
              }
              
              onChunk(chunk as StreamChunk);

              if (chunk.finished) {
                 cancelled = true;
                 reader.cancel();
                 break; 
              }
            } catch (e) {
              console.error('Failed to parse stream chunk:', line, e);
              // Propagate parsing errors
              onError(e instanceof Error ? e : new Error('Failed to parse stream data'));
            }
          }
        }
      } catch (e) {
        console.error("Error reading from stream:", e);
        if (!cancelled) {
            onError(e instanceof Error ? e : new Error('Stream read error'));
            cancelled = true;
        }
        break;
      }
    }
  };

  await processStream();
  onComplete();
};


export const getLlmProviders = async (): Promise<LlmProvider[]> => {
    // CORRECTED: Points to the web-api proxy endpoint
    const response = await fetch('/api/providers');
    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Failed to fetch LLM providers: ${response.status} ${errorText}`);
    }
    const data: Record<string, { available: boolean }> = await response.json();
    return Object.entries(data).map(([id, { available }]) => ({ id, available }));
};


export const streamSearch = async (
  query: string,
  provider: string | null,
  onChunk: (chunk: StreamChunk) => void,
  onError: (error: Error) => void,
  onComplete: () => void
) => {
  try {
    // CORRECTED: This path correctly points to the web-api proxy
    const response = await fetch('/api/search/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, llm_provider: provider }),
    });
    await handleStream(response, onChunk, onError, onComplete);
  } catch (error) {
    console.error('Streaming search failed:', error);
    onError(error instanceof Error ? error : new Error('An unknown error occurred during search setup'));
  }
};


export const streamChat = async (
  messages: ChatMessage[],
  provider: string | null,
  onChunk: (chunk: StreamChunk) => void,
  onError: (error: Error) => void,
  onComplete: () => void
) => {
  try {
    // The backend expects role and content only.
    const payloadMessages = messages.map(({ role, content }) => ({ role, content }));
    // CORRECTED: Points to the new web-api proxy endpoint for completions
    const response = await fetch('/api/completion/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: payloadMessages, provider }),
    });
    await handleStream(response, onChunk, onError, onComplete);
  } catch (error) {
    console.error('Streaming chat failed:', error);
    onError(error instanceof Error ? error : new Error('An unknown error occurred during chat setup'));
  }
};
