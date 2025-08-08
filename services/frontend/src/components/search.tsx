'use client';

import { useState } from 'react';
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface SearchResult {
  answer: string;
  sources: {
    title: string;
    url: string;
  }[];
}

export default function Search() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSearch = async () => {
    setLoading(true);
    const response = await fetch('/api/search', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query }),
    });
    const data = await response.json();
    setResults(data);
    setLoading(false);
  };

  return (
    <div className="w-full max-w-2xl">
      <div className="flex w-full items-center space-x-2">
        <Input
          type="text"
          placeholder="Search..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button type="submit" onClick={handleSearch} disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </Button>
      </div>
      {results && (
        <div className="mt-8">
          <h2 className="text-2xl font-bold">Answer</h2>
          <p className="mt-2">{results.answer}</p>
          <h3 className="mt-4 text-xl font-bold">Sources</h3>
          <ul className="mt-2 list-disc space-y-2 pl-5">
            {results.sources.map((source, index) => (
              <li key={index}>
                <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">
                  {source.title}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}