
import React from 'react';
import { Source } from '../types';
import { LinkIcon } from './Icons';

interface SourceListProps {
  sources: Source[];
}

export const SourceList: React.FC<SourceListProps> = ({ sources }) => {
  return (
    <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-600">
      <h4 className="text-sm font-semibold mb-2">Sources:</h4>
      <div className="space-y-2">
        {sources.map((source, index) => (
          <a
            key={index}
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-start gap-3 p-2 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition-colors group"
          >
            <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center bg-gray-200 dark:bg-gray-700 rounded text-xs font-mono mt-1">
              {index + 1}
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium group-hover:text-primary transition-colors">
                {source.title}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 break-all">
                {source.url}
              </p>
            </div>
             <LinkIcon className="w-4 h-4 text-gray-400 dark:text-gray-500 group-hover:text-primary transition-colors flex-shrink-0 mt-1" />
          </a>
        ))}
      </div>
    </div>
  );
};
