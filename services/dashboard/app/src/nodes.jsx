import { useState, useCallback, useRef } from 'react';
import { Handle, Position } from '@xyflow/react';
import { streamApi, humanize } from './api.js';

function Card({ color, icon, label, children, running, error }) {
  return (
    <div className={`node-card${running ? ' running' : ''}${error ? ' error' : ''}`}>
      <Handle type="target" position={Position.Left} className="node-handle" />
      <div className="node-header">
        <span className="palette-dot" style={{ background: color }} />
        <span>{icon} {label}</span>
      </div>
      <div className="node-body">{children}</div>
      <Handle type="source" position={Position.Right} className="node-handle" />
    </div>
  );
}

function UpstreamSelect({ ctx, value, onChange }) {
  const upstreams = ctx.nodes
    .filter(n => n.id !== ctx.id && n.type !== 'output')
    .filter(n => n.data?.output);
  if (!upstreams.length) return null;
  return (
    <label>Upstream source
      <select value={value || ''} onChange={e => onChange(e.target.value || null)}>
        <option value="">— none —</option>
        {upstreams.map(n => (
          <option key={n.id} value={n.id}>{n.type} — {n.id}</option>
        ))}
      </select>
    </label>
  );
}

function useNodeState(ctx, initial = {}) {
  const [state, setState] = useState(initial);
  const update = useCallback((patch) => {
    setState(s => ({ ...s, ...patch }));
    ctx.setNodes(nds => nds.map(n => n.id === ctx.id ? { ...n, data: { ...n.data, ...patch } } : n));
  }, [ctx]);
  return [state, update];
}

// ─── Inference Node ──────────────────────────────────────────

export function InferenceNode({ data }) {
  const ctx = data.ctx;
  const [prompt, setPrompt] = useState('');
  const [model, setModel] = useState('deepseek-chat');
  const [temp, setTemp] = useState(0.7);
  const [output, setOutput] = useState(data.output || '');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');

  const run = async () => {
    if (!prompt.trim()) return;
    setRunning(true); setError(''); setOutput('');
    try {
      let text = '';
      await streamApi('/api/inference/v1/chat/completions', {
        model, temperature: temp, max_tokens: 1024,
        messages: [{ role: 'user', content: prompt }],
        stream: true,
      }, chunk => { text += chunk; setOutput(text); });
      ctx.setNodes(nds => nds.map(n => n.id === ctx.id ? { ...n, data: { ...n.data, output: text } } : n));
    } catch (e) { setError(e.message); }
    setRunning(false);
  };

  return (
    <Card color="#89b4fa" icon="🧠" label="Inference" running={running} error={!!error}>
      <label>Prompt<textarea value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Write a haiku about Docker..." /></label>
      <label>Model<select value={model} onChange={e => setModel(e.target.value)}><option>deepseek-chat</option><option>deepseek-reasoner</option></select></label>
      <label>Temperature<input type="range" min="0" max="2" step="0.1" value={temp} onChange={e => setTemp(+e.target.value)} /><span style={{fontSize:10,color:'var(--text-dim)'}}>{temp}</span></label>
      <button onClick={run} disabled={running}>{running ? 'Streaming...' : '▶ Run'}</button>
      {error && <div style={{color:'var(--red)',fontSize:11}}>{error}</div>}
      {output && <div className={`node-output${running ? ' streaming' : ''}`}>{output}</div>}
    </Card>
  );
}

// ─── Humanizer Node ──────────────────────────────────────────

export function HumanizerNode({ data }) {
  const ctx = data.ctx;
  const [inputText, setInputText] = useState('');
  const [style, setStyle] = useState('neutral');
  const [intensity, setIntensity] = useState(0.5);
  const [output, setOutput] = useState(data.output || '');
  const [confidence, setConfidence] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [upstream, setUpstream] = useState(null);

  const loadUpstream = () => {
    if (!upstream) return;
    const src = ctx.nodes.find(n => n.id === upstream);
    if (src?.data?.output) setInputText(src.data.output);
  };

  const run = async () => {
    const text = inputText.trim();
    if (!text) return;
    setRunning(true); setError('');
    try {
      const res = await humanize(text, style, intensity);
      setOutput(res.text); setConfidence(res.confidence);
      ctx.setNodes(nds => nds.map(n => n.id === ctx.id ? { ...n, data: { ...n.data, output: res.text, confidence: res.confidence } } : n));
    } catch (e) { setError(e.message); }
    setRunning(false);
  };

  return (
    <Card color="#a6e3a1" icon="✍️" label="Humanizer" running={running} error={!!error}>
      <UpstreamSelect ctx={ctx} value={upstream} onChange={v => { setUpstream(v); if (v) loadUpstream(); }} />
      <label>Text<textarea value={inputText} onChange={e => setInputText(e.target.value)} placeholder="Paste AI-generated text..." /></label>
      <label>Style<select value={style} onChange={e => setStyle(e.target.value)}><option>neutral</option><option>casual</option><option>professional</option><option>blunt</option><option>conversational</option></select></label>
      <label>Intensity<input type="range" min="0" max="1" step="0.1" value={intensity} onChange={e => setIntensity(+e.target.value)} /><span style={{fontSize:10,color:'var(--text-dim)'}}>{intensity}</span></label>
      <button onClick={run} disabled={running}>{running ? 'Humanizing...' : '▶ Humanize'}</button>
      {confidence !== null && <div className="node-meta">Confidence: {(confidence * 100).toFixed(0)}%</div>}
      {error && <div style={{color:'var(--red)',fontSize:11}}>{error}</div>}
      {output && <div className="node-output">{output}</div>}
    </Card>
  );
}

// ─── Video Extract Node ──────────────────────────────────────

export function VideoExtractNode({ data }) {
  const ctx = data.ctx;
  const [url, setUrl] = useState('');
  const [meta, setMeta] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');

  const run = async () => {
    if (!url.trim()) return;
    setRunning(true); setError(''); setMeta(null);
    try {
      const res = await fetch(`http://localhost:8021/videos/metadata?video_url=${encodeURIComponent(url)}`);
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setMeta(data);
      const output = `Title: ${data.title}\nChannel: ${data.channel}\nDuration: ${data.duration}s\nViews: ${data.view_count}\n\nTranscript: ${(data.transcript || '').slice(0, 2000)}${data.transcript?.length > 2000 ? '...' : ''}`;
      ctx.setNodes(nds => nds.map(n => n.id === ctx.id ? { ...n, data: { ...n.data, output, transcript: data.transcript } } : n));
    } catch (e) { setError(e.message); }
    setRunning(false);
  };

  return (
    <Card color="#f9e2af" icon="📹" label="Video Extract" running={running} error={!!error}>
      <label>YouTube URL<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=..." /></label>
      <button onClick={run} disabled={running}>{running ? 'Extracting...' : '▶ Extract'}</button>
      {meta && <div className="node-meta">{meta.title} · {meta.channel} · {meta.duration}s · {meta.view_count} views · {meta.transcript?.length || 0} chars transcript</div>}
      {error && <div style={{color:'var(--red)',fontSize:11}}>{error}</div>}
    </Card>
  );
}

// ─── Summarize Node ──────────────────────────────────────────

export function SummarizeNode({ data }) {
  const ctx = data.ctx;
  const [style, setStyle] = useState('bullet');
  const [output, setOutput] = useState(data.output || '');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [upstream, setUpstream] = useState(null);
  const [upstreamOutput, setUpstreamOutput] = useState('');

  const run = async () => {
    const src = ctx.nodes.find(n => n.id === upstream);
    const transcript = src?.data?.transcript || upstreamOutput;
    if (!transcript) return;
    setRunning(true); setError(''); setOutput('');
    const stylePrompts = {
      bullet: `Summarize in 5-7 bullet points:\n\n${transcript.slice(0, 8000)}`,
      paragraph: `Write a 2-paragraph summary:\n\n${transcript.slice(0, 8000)}`,
      'tl;dr': `Single-sentence TL;DR + 3 takeaways:\n\n${transcript.slice(0, 8000)}`,
    };
    try {
      let text = '';
      await streamApi('/api/inference/v1/chat/completions', {
        model: 'deepseek-chat', temperature: 0.7, max_tokens: 512,
        messages: [{ role: 'system', content: 'You summarize YouTube videos concisely.' }, { role: 'user', content: stylePrompts[style] }],
        stream: true,
      }, chunk => { text += chunk; setOutput(text); });
      ctx.setNodes(nds => nds.map(n => n.id === ctx.id ? { ...n, data: { ...n.data, output: text } } : n));
    } catch (e) { setError(e.message); }
    setRunning(false);
  };

  return (
    <Card color="#cba6f7" icon="📝" label="Summarize" running={running} error={!!error}>
      <UpstreamSelect ctx={ctx} value={upstream} onChange={v => { setUpstream(v); if (v) { const src = ctx.nodes.find(n => n.id === v); setUpstreamOutput(src?.data?.transcript || src?.data?.output || ''); }}} />
      <label>Transcript<textarea value={upstreamOutput} onChange={e => setUpstreamOutput(e.target.value)} placeholder="Or paste transcript directly..." /></label>
      <label>Style<select value={style} onChange={e => setStyle(e.target.value)}><option>bullet</option><option>paragraph</option><option>tl;dr</option></select></label>
      <button onClick={run} disabled={running}>{running ? 'Summarizing...' : '▶ Summarize'}</button>
      {error && <div style={{color:'var(--red)',fontSize:11}}>{error}</div>}
      {output && <div className={`node-output${running ? ' streaming' : ''}`}>{output}</div>}
    </Card>
  );
}

// ─── Blog Generate Node ──────────────────────────────────────

export function BlogGenerateNode({ data }) {
  const ctx = data.ctx;
  const [topic, setTopic] = useState('');
  const [output, setOutput] = useState(data.output || '');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [upstream, setUpstream] = useState(null);

  const run = async () => {
    const src = ctx.nodes.find(n => n.id === upstream);
    const prompt = topic || src?.data?.output || '';
    if (!prompt.trim()) return;
    setRunning(true); setError(''); setOutput('');
    try {
      const system = 'You are a technical blogger. Write an engaging, well-structured blog post. Use markdown.';
      let text = '';
      await streamApi('/api/inference/v1/chat/completions', {
        model: 'deepseek-chat', temperature: 0.8, max_tokens: 2048,
        messages: [{ role: 'system', content: system }, { role: 'user', content: `Write a blog post about: ${prompt}` }],
        stream: true,
      }, chunk => { text += chunk; setOutput(text); });
      ctx.setNodes(nds => nds.map(n => n.id === ctx.id ? { ...n, data: { ...n.data, output: text } } : n));
    } catch (e) { setError(e.message); }
    setRunning(false);
  };

  return (
    <Card color="#f38ba8" icon="📰" label="Blog Generate" running={running} error={!!error}>
      <UpstreamSelect ctx={ctx} value={upstream} onChange={setUpstream} />
      <label>Topic / source<textarea value={topic} onChange={e => setTopic(e.target.value)} placeholder="Or select upstream source..." /></label>
      <button onClick={run} disabled={running}>{running ? 'Generating...' : '▶ Generate'}</button>
      {error && <div style={{color:'var(--red)',fontSize:11}}>{error}</div>}
      {output && <div className={`node-output${running ? ' streaming' : ''}`}>{output}</div>}
    </Card>
  );
}

// ─── Output Node ─────────────────────────────────────────────

export function OutputNode({ data }) {
  const ctx = data.ctx;
  const [upstream, setUpstream] = useState(null);

  const src = ctx.nodes.find(n => n.id === upstream);
  const output = src?.data?.output || '';
  const label = src ? `${src.type} → output` : 'Connect a source';

  return (
    <Card color="#6c7086" icon="📤" label="Output">
      <UpstreamSelect ctx={ctx} value={upstream} onChange={setUpstream} />
      {upstream && (
        <>
          {src && <div className="node-meta">Source: {src.type} — {src.id}</div>}
          <div className="node-output" style={{ maxHeight: 400 }}>
            {output || '(empty — upstream has no output yet)'}
          </div>
          {output && (
            <button onClick={() => navigator.clipboard.writeText(output)} style={{ background: 'var(--border)', color: 'var(--text)', marginTop: 4 }}>
              📋 Copy
            </button>
          )}
        </>
      )}
    </Card>
  );
}
