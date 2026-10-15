import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { selectionSummary } from './lib/directory.ts';

export type Option = { value: string; label: string; hint?: string };

/** A dropdown that lets you tick several values. Closed, it reads "Any" or a short summary of what is picked. */
export function MultiSelect({ label, options, value, onChange, searchable = false }: { label: string; options: Option[]; value: string[]; onChange: (next: string[]) => void; searchable?: boolean }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close); document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [open]);
  const shown = options.filter(o => !text.trim() || o.label.toLowerCase().includes(text.trim().toLowerCase()));
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter(x => x !== v) : [...value, v]);
  return <div className="ms" ref={box}>
    <span className="ms-label">{label}</span>
    <button type="button" className="ms-button" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}>
      <span>{selectionSummary(value, options)}</span><ChevronDown size={16} aria-hidden="true"/></button>
    {open && <div className="ms-pop" role="listbox" aria-multiselectable="true" aria-label={label}>
      {searchable && <input className="ms-search" autoFocus placeholder="Type to narrow" value={text} onChange={e => setText(e.target.value)} aria-label={`Search ${label}`}/>}
      {value.length > 0 && <button type="button" className="text-button ms-clear" onClick={() => onChange([])}>Clear ({value.length})</button>}
      <ul>{shown.map(o => <li key={o.value}><label className="ms-opt"><input type="checkbox" checked={value.includes(o.value)} onChange={() => toggle(o.value)}/>
        <span>{o.label}{o.hint && <small className="muted"> · {o.hint}</small>}</span></label></li>)}
        {!shown.length && <li className="muted small ms-empty">Nothing matches</li>}</ul>
    </div>}
  </div>;
}
