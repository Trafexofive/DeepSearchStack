
import React, { createContext, useState, useEffect, useContext, ReactNode } from 'react';
import { AppMode, LlmProvider } from '../types';
import { getLlmProviders } from '../services/api';

interface SettingsContextType {
  mode: AppMode;
  setMode: (mode: AppMode) => void;
  llmProviders: LlmProvider[];
  selectedProvider: string | null;
  setSelectedProvider: (provider: string | null) => void;
  isSettingsOpen: boolean;
  setIsSettingsOpen: (isOpen: boolean) => void;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

export const SettingsProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [mode, setMode] = useState<AppMode>('search');
  const [llmProviders, setLlmProviders] = useState<LlmProvider[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  useEffect(() => {
    const fetchProviders = async () => {
      try {
        const providers = await getLlmProviders();
        const availableProviders = providers.filter(p => p.available);
        setLlmProviders(availableProviders);
        // Set default provider to 'ollama' if available, otherwise the first one.
        if (availableProviders.length > 0) {
            const ollamaProvider = availableProviders.find(p => p.id === 'ollama');
            setSelectedProvider(ollamaProvider ? 'ollama' : availableProviders[0].id);
        }
      } catch (error) {
        console.error("Failed to fetch LLM providers:", error);
      }
    };
    fetchProviders();
  }, []);

  return (
    <SettingsContext.Provider
      value={{
        mode,
        setMode,
        llmProviders,
        selectedProvider,
        setSelectedProvider,
        isSettingsOpen,
        setIsSettingsOpen,
      }}
    >
      {children}
    </SettingsContext.Provider>
  );
};

export const useSettings = (): SettingsContextType => {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error('useSettings must be used within a SettingsProvider');
  }
  return context;
};
