
import React from 'react';
import { useSettings } from '../contexts/SettingsContext';
import { CloseIcon } from './Icons';

export const SettingsPanel: React.FC = () => {
  const { isSettingsOpen, setIsSettingsOpen, llmProviders, selectedProvider, setSelectedProvider } = useSettings();

  if (!isSettingsOpen) {
    return null;
  }

  return (
    <>
      <div 
        className="fixed inset-0 bg-black/50 z-40 transition-opacity"
        onClick={() => setIsSettingsOpen(false)}
      ></div>
      <div className="fixed top-0 right-0 h-full w-80 bg-white dark:bg-gray-800 shadow-xl z-50 transform transition-transform translate-x-0">
        <div className="p-4 flex justify-between items-center border-b border-border-light dark:border-border-dark">
          <h2 className="text-lg font-semibold text-text-light dark:text-text-dark">Settings</h2>
          <button onClick={() => setIsSettingsOpen(false)} className="p-1 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700">
            <CloseIcon className="w-6 h-6 text-gray-600 dark:text-gray-300" />
          </button>
        </div>
        <div className="p-4">
          <h3 className="text-md font-semibold text-text-light dark:text-text-dark mb-3">LLM Provider</h3>
          <div className="space-y-2">
            {llmProviders.length > 0 ? (
                llmProviders.map(provider => (
                <label key={provider.id} className="flex items-center p-3 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                  <input
                    type="radio"
                    name="llmProvider"
                    value={provider.id}
                    checked={selectedProvider === provider.id}
                    onChange={() => setSelectedProvider(provider.id)}
                    className="w-4 h-4 text-primary bg-gray-100 border-gray-300 focus:ring-primary dark:focus:ring-blue-600 dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600"
                  />
                  <span className="ml-3 text-sm font-medium text-text-light dark:text-text-dark capitalize">{provider.id}</span>
                </label>
                ))
            ) : (
                <p className="text-sm text-gray-500">No available providers found.</p>
            )}
          </div>
        </div>
      </div>
    </>
  );
};
