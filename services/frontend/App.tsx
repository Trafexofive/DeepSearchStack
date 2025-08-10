
import React from 'react';
import Chat from './components/Chat';
import { SparklesIcon, SettingsIcon } from './components/Icons';
import { SettingsProvider, useSettings } from './contexts/SettingsContext';
import { SettingsPanel } from './components/SettingsPanel';

const AppContent: React.FC = () => {
  const { setIsSettingsOpen } = useSettings();

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100 dark:bg-background-dark p-4 font-sans">
      <div className="w-full max-w-4xl h-[90vh] flex flex-col bg-background-light dark:bg-gray-800 rounded-2xl shadow-2xl border border-border-light dark:border-border-dark overflow-hidden">
        <header className="p-4 border-b border-border-light dark:border-border-dark flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <SparklesIcon className="w-7 h-7 text-primary" />
            <h1 className="text-2xl font-bold text-text-light dark:text-text-dark">
              DeepSearch AI
            </h1>
          </div>
          <button 
            onClick={() => setIsSettingsOpen(true)}
            className="p-2 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
            aria-label="Open settings"
          >
            <SettingsIcon className="w-6 h-6 text-gray-600 dark:text-gray-300" />
          </button>
        </header>
        <Chat />
      </div>
      <SettingsPanel />
      <footer className="text-center mt-4 text-xs text-gray-400 dark:text-gray-500">
          <p>Powered by DeepSearchStack. Your private, self-hosted AI reasoning engine.</p>
      </footer>
    </div>
  );
};

const App: React.FC = () => {
  return (
    <SettingsProvider>
      <AppContent />
    </SettingsProvider>
  );
};

export default App;
