import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react';
import { RotateCcw } from 'lucide-react';
import { SECTOR_ORDER, STATES, boxOf, bubbleRadius, easeInOut, lerpBox, pathOf, project, sectorLine, sectorOfState, stateShapes, tileState, tooltipLines, type Box } from './lib/indiamap.ts';
import type { Sector } from './lib/directory.ts';
import type { Match } from './lib/teambuilder.ts';

export type SectorSummary = { code: string; name: string; caretakers: number; states: Record<string, number>; state_top_agency?: Record<string, string>;
  agency_count: number; top_agencies: { id: string; name: string; city: string; caretakers: number; average_rating: number | null }[] };

const reducedMotion = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** Counts up to `value` when it changes (instant when the viewer prefers reduced motion). */
function useCountUp(value: number, ms = 450): number {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    if (reducedMotion() || from.current === value) { from.current = value; setShown(value); return; }
    const start = performance.now(), a = from.current;
    let frame = 0;
    const step = (t: number) => { const k = Math.min(1, (t - start) / ms); setShown(Math.round(a + (value - a) * easeInOut(k))); if (k < 1) frame = requestAnimationFrame(step); else from.current = value; };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value, ms]);
  return shown;
}

/** Smoothly moves the SVG view box (a zoom) to `target`. */
function useViewBox(target: Box, ms = 550): Box {
  const [box, setBox] = useState(target);
  const current = useRef(target);
  useEffect(() => {
    if (reducedMotion()) { current.current = target; setBox(target); return; }
    const start = performance.now(), a = current.current;
    let frame = 0;
    const step = (t: number) => { const k = easeInOut(Math.min(1, (t - start) / ms)); const next = lerpBox(a, target, k); current.current = next; setBox(next); if (k < 1) frame = requestAnimationFrame(step); };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target.x, target.y, target.w, target.h, ms]);  // target is compared by value, not identity
  return box;
}

/** India by region: hover for details, click a state to filter by it, choose a region to zoom in. The panel lists its top caretakers and agencies. */
export function IndiaMap({ sectors, summary, selected, selectedStates, onSelect, onState, top, onProfile, onAgency }: {
  sectors: Sector[]; summary: SectorSummary[]; selected: string; selectedStates: string[]; onSelect: (code: string) => void; onState: (state: string, sector: string) => void;
  top: Match[]; onProfile: (id: string) => void; onAgency: (id: string, sector: string) => void;
}) {
  const shapes = useMemo(() => stateShapes(), []);
  const sectorOf = sectorOfState(sectors);
  const [hovered, setHovered] = useState('');
  const [tip, setTip] = useState<{ state: string; x: number; y: number } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const full = useMemo(() => boxOf(Object.values(shapes), 14), [shapes]);
  const target = useMemo(() => {
    if (!selected) return full;
    const polys = STATES.filter(s => sectorOf[s.state] === selected && !s.island).map(s => shapes[s.state]);
    if (!polys.length) return full;
    const b = boxOf(polys, 30), ratio = full.w / full.h;  // keep the frame's shape so the map does not stretch
    return b.w / b.h > ratio ? { ...b, y: b.y - (b.w / ratio - b.h) / 2, h: b.w / ratio } : { ...b, x: b.x - (b.h * ratio - b.w) / 2, w: b.h * ratio };
  }, [selected, shapes, full, sectors]);
  const view = useViewBox(target);
  const counts: Record<string, number> = Object.assign({}, ...summary.map(s => s.states));
  const topAgency: Record<string, string> = Object.assign({}, ...summary.map(s => s.state_top_agency ?? {}));
  const max = Math.max(1, ...Object.values(counts));
  const focus = summary.find(s => s.code === (hovered || selected));
  const shownCaretakers = useCountUp(focus?.caretakers ?? summary.reduce((n, s) => n + s.caretakers, 0));
  const pickSector = (code: string) => onSelect(code === selected ? '' : code);
  const sectorName = (code?: string) => summary.find(s => s.code === code)?.name;

  function showTip(e: MouseEvent, state: string) {
    const r = wrap.current?.getBoundingClientRect();
    if (r) setTip({ state, x: e.clientX - r.left, y: e.clientY - r.top });
  }
  function keyState(e: KeyboardEvent, state: string, sector?: string) {
    if ((e.key === 'Enter' || e.key === ' ') && sector) { e.preventDefault(); onState(state, sector); }
  }
  return <section className="card im" aria-label="Map of India by region">
    <div className="im-legend" role="group" aria-label="Choose a region">
      <button type="button" className={`cp-filter${!selected ? ' on' : ''}`} aria-pressed={!selected} onClick={() => onSelect('')}><RotateCcw size={13} aria-hidden="true"/>All India</button>
      {SECTOR_ORDER.map(code => { const s = summary.find(x => x.code === code); return <button key={code} type="button" className={`cp-filter im-key im-${code.toLowerCase()}${selected === code ? ' on' : ''}`}
        aria-pressed={selected === code} onClick={() => pickSector(code)} onMouseEnter={() => setHovered(code)} onMouseLeave={() => setHovered('')} onFocus={() => setHovered(code)} onBlur={() => setHovered('')}>
        <i aria-hidden="true"/>{s?.name ?? code}<small>{s ? ` ${s.caretakers}` : ''}</small></button>; })}
    </div>
    <div className="im-body">
      <div className="im-stage" ref={wrap} onMouseLeave={() => { setHovered(''); setTip(null); }}>
        <svg className="im-map" viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} role="group" aria-label={`Map of India${selected ? `, ${sectorName(selected)} region shown` : ''}. Choose a state to filter by it.`}>
          <defs><filter id="im-glow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.28"/></filter></defs>
          {SECTOR_ORDER.map(code => <g key={code} className={`im-sector im-${code.toLowerCase()} im-${tileState(code, selected, hovered)}`}>
            {STATES.filter(s => sectorOf[s.state] === code).map(s => { const n = counts[s.state] ?? 0; const on = selectedStates.includes(s.state);
              return <path key={s.code} d={pathOf(shapes[s.state])} className={`im-state${on ? ' im-picked' : ''}`} tabIndex={0} role="button" aria-pressed={on}
                aria-label={`${s.state}, ${sectorName(code) ?? ''} region, ${n} caretaker${n === 1 ? '' : 's'}`}
                onClick={() => onState(s.state, code)} onKeyDown={e => keyState(e, s.state, code)}
                onMouseEnter={e => { setHovered(code); showTip(e, s.state); }} onMouseMove={e => showTip(e, s.state)}
                onFocus={() => { setHovered(code); setTip({ state: s.state, x: 12, y: 12 }); }} onBlur={() => setTip(null)}/>; })}
          </g>)}
          {STATES.filter(s => !sectorOf[s.state]).map(s => <path key={s.code} d={pathOf(shapes[s.state])} className="im-state im-unassigned"/>)}
          <g className="im-bubbles" aria-hidden="true">
            {STATES.map(s => { const n = counts[s.state] ?? 0; const r = bubbleRadius(n, max); const [x, y] = project(s.lon, s.lat); const code = sectorOf[s.state];
              return <g key={s.code} className={`im-bubble im-${tileState(code, selected, hovered)}`}>
                {r > 0 && <circle cx={x} cy={y} r={r}/>}
                <text x={x} y={y + 3.5} textAnchor="middle">{r > 7 ? n : ''}</text>
              </g>; })}
          </g>
        </svg>
        {tip && <div className="im-tip" style={{ left: Math.min(tip.x + 14, (wrap.current?.clientWidth ?? 400) - 190), top: Math.max(0, tip.y - 10) }} role="tooltip">
          {tooltipLines(tip.state, sectorName(sectorOf[tip.state]), counts[tip.state] ?? 0, topAgency[tip.state]).map((l, i) => i === 0 ? <strong key={l}>{l}</strong> : <span key={l}>{l}</span>)}
        </div>}
        <p className="im-note">Simplified map, not exact borders. Bubbles show listed caretakers per state.</p>
      </div>
      <aside className="im-panel" aria-live="polite">
        <p className="im-big"><span key={focus?.code ?? 'all'} className="im-pop">{shownCaretakers}</span> caretakers</p>
        {focus ? <>
          <h4><i className={`im-dot im-${focus.code.toLowerCase()}`} aria-hidden="true"/>{focus.name} India</h4>
          <p className="muted small">{sectorLine(focus)}{selectedStates.length ? ` · showing ${selectedStates.join(', ')}` : ''}</p>
          {selected === focus.code && <><h5>Top caretakers</h5>
            {top.length ? <ol className="im-list">{top.slice(0, 5).map((m, i) => <li key={m.caregiver_id} style={{ animationDelay: `${i * 40}ms` }}><button type="button" className="im-link" onClick={() => onProfile(m.caregiver_id)}>
              <span>{m.name}</span><small>{m.score} pts{m.composite !== null ? ` · ★ ${Math.round(m.composite)}` : ''} · {m.city}</small></button></li>)}</ol> : <p className="muted small">No one fits the current filters.</p>}</>}
          <h5>Top agencies</h5>
          {focus.top_agencies.length ? <ol className="im-list">{focus.top_agencies.map(a => <li key={a.id}><button type="button" className="im-link" onClick={() => onAgency(a.id, focus.code)}>
            <span>{a.name}</span><small>{a.average_rating ? `${a.average_rating.toFixed(1)}★ · ` : ''}{a.caretakers} caretaker{a.caretakers === 1 ? '' : 's'} · {a.city}</small></button></li>)}</ol> : <p className="muted small">No agencies listed here yet.</p>}
        </> : <>
          <h4>All India</h4>
          <ul className="im-list">{summary.map(s => <li key={s.code}><button type="button" className="im-link" onClick={() => pickSector(s.code)}><span><i className={`im-dot im-${s.code.toLowerCase()}`} aria-hidden="true"/>{s.name}</span><small>{sectorLine(s)}</small></button></li>)}</ul>
          <p className="muted small">Hover a state for details. Choose a region to zoom in, or a state to filter by it.</p>
        </>}
      </aside>
    </div>
  </section>;
}
