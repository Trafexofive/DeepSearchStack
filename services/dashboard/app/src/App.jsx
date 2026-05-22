import { useState, useCallback, useRef } from 'react';
import {
  ReactFlow, Controls, Background, MiniMap,
  addEdge, useNodesState, useEdgesState,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { InferenceNode, HumanizerNode, VideoExtractNode, SummarizeNode, BlogGenerateNode, OutputNode } from './nodes.jsx';

const NODE_TYPES = {
  inference: InferenceNode,
  humanizer: HumanizerNode,
  'video-extract': VideoExtractNode,
  summarize: SummarizeNode,
  'blog-generate': BlogGenerateNode,
  output: OutputNode,
};

const PALETTE = [
  { type: 'inference', label: 'Inference', dot: '#89b4fa', desc: 'Prompt → LLM response' },
  { type: 'humanizer', label: 'Humanizer', dot: '#a6e3a1', desc: 'Text → humanized' },
  { type: 'video-extract', label: 'Video Extract', dot: '#f9e2af', desc: 'URL → transcript' },
  { type: 'summarize', label: 'Summarize', dot: '#cba6f7', desc: 'Transcript → summary' },
  { type: 'blog-generate', label: 'Blog Generate', dot: '#f38ba8', desc: 'Topic → draft' },
  { type: 'output', label: 'Output', dot: '#6c7086', desc: 'View final result' },
];

let _id = 0;
const nextId = (t) => `${t}-${++_id}`;

export default function App() {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const rf = useRef(null);
  const [inst, setInst] = useState(null);

  const onConnect = useCallback((p) => setEdges(eds => addEdge({
    ...p, animated: true,
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6c7086' },
    style: { stroke: '#6c7086', strokeWidth: 1.5 },
  }, eds)), [setEdges]);

  const onDragOver = useCallback(e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }, []);
  const onDrop = useCallback(e => {
    e.preventDefault();
    const type = e.dataTransfer.getData('application/node-type');
    if (!type || !inst) return;
    const pos = inst.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const id = nextId(type);
    setNodes(nds => nds.concat({ id, type, position: pos, data: { id } }));
  }, [inst, setNodes]);

  const ctx = useCallback((id) => ({
    id, nodes, setNodes, edges, setEdges,
    addEdge: (src, tgt) => setEdges(eds => addEdge({
      source: src, target: tgt, animated: true,
      markerEnd: { type: MarkerType.ArrowClosed, color: '#6c7086' },
      style: { stroke: '#6c7086', strokeWidth: 1.5 },
    }, eds)),
  }), [nodes, setNodes, edges, setEdges]);

  return (
    <div style={{ height: '100vh', display: 'flex' }}>
      <aside className="sidebar">
        <h2>🧩 Agentic Canvas</h2>
        {PALETTE.map(p => (
          <div key={p.type} className="node-palette-item" draggable
            onDragStart={e => { e.dataTransfer.setData('application/node-type', p.type); e.dataTransfer.effectAllowed = 'move'; }}>
            <span className="palette-dot" style={{ background: p.dot }} />
            <div><div style={{ fontWeight: 600 }}>{p.label}</div><div style={{ fontSize: 10, color: 'var(--text-dim)' }}>{p.desc}</div></div>
          </div>
        ))}
      </aside>
      <div ref={rf} style={{ flex: 1 }}>
        <ReactFlow
          nodes={nodes.map(n => ({ ...n, data: { ...n.data, ctx: ctx(n.id) } }))}
          edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onConnect={onConnect} onInit={setInst} onDrop={onDrop} onDragOver={onDragOver}
          nodeTypes={NODE_TYPES} fitView deleteKeyCode={['Backspace', 'Delete']}>
          <Background color="#1e1e2e" gap={20} />
          <Controls />
          <MiniMap nodeColor={n => n.type === 'inference' ? '#89b4fa' : n.type === 'output' ? '#6c7086' : '#f9e2af'} style={{ background: 'var(--surface)' }} />
        </ReactFlow>
      </div>
    </div>
  );
}
