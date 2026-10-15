import { useState } from 'react';
import { SECTOR_ORDER, TILES, mapSize, sectorLine, sectorOfState, tileBox, tileState } from './lib/indiamap.ts';
import type { Sector } from './lib/directory.ts';
import type { Match } from './lib/teambuilder.ts';

export type SectorSummary = { code: string; name: string; caretakers: number; states: Record<string, number>; agency_count: number;
  top_agencies: { id: string; name: string; city: string; caretakers: number; average_rating: number | null }[] };

/** India by sector: click a region (on the map or its button) to filter; the right panel shows its top caretakers and agencies. */
export function IndiaMap({ sectors, summary, selected, onSelect, top, onProfile, onAgency }: {
  sectors: Sector[]; summary: SectorSummary[]; selected: string; onSelect: (code: string) => void;
  top: Match[]; onProfile: (id: string) => void; onAgency: (id: string, sector: string) => void;
}) {
  const [hovered, setHovered] = useState('');
  const sectorOf = sectorOfState(sectors);
  const { width, height } = mapSize();
  const focus = summary.find(s => s.code === (hovered || selected));
  const pick = (code: string) => onSelect(code === selected ? '' : code);
  return <section className="card im" aria-label="Map of India by sector">
    <div className="im-legend" role="group" aria-label="Choose a region">
      <button type="button" className={`cp-filter${!selected ? ' on' : ''}`} aria-pressed={!selected} onClick={() => onSelect('')}>All India</button>
      {SECTOR_ORDER.map(code => { const s = summary.find(x => x.code === code); return <button key={code} type="button" className={`cp-filter im-key im-${code.toLowerCase()}${selected === code ? ' on' : ''}`}
        aria-pressed={selected === code} onClick={() => pick(code)} onMouseEnter={() => setHovered(code)} onMouseLeave={() => setHovered('')} onFocus={() => setHovered(code)} onBlur={() => setHovered('')}>
        <i aria-hidden="true"/>{s?.name ?? code}</button>; })}
    </div>
    <div className="im-body">
      <svg className="im-map" viewBox={`-4 -4 ${width + 8} ${height + 8}`} role="img" aria-label={`Schematic map of India, ${selected ? `${selected.toLowerCase()} selected` : 'all regions'}`} onMouseLeave={() => setHovered('')}>
        {TILES.map(t => { const b = tileBox(t); const sector = sectorOf[t.state]; const look = tileState(sector, selected, hovered); const n = summary.find(s => s.code === sector)?.states[t.state] ?? 0;
          return <g key={t.code} className={`im-tile im-${(sector ?? 'none').toLowerCase()} im-${look}`} onClick={() => sector && pick(sector)} onMouseEnter={() => sector && setHovered(sector)}>
            <title>{`${t.state}${sector ? ` · ${sector[0]}${sector.slice(1).toLowerCase()}` : ''} · ${n} caretaker${n === 1 ? '' : 's'}`}</title>
            <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={8}/>
            <text x={b.x + b.w / 2} y={b.y + 19} textAnchor="middle" className="im-code">{t.code}</text>
            {n > 0 && <text x={b.x + b.w / 2} y={b.y + 34} textAnchor="middle" className="im-n">{n}</text>}
          </g>; })}
      </svg>
      <aside className="im-panel" aria-live="polite">
        {focus ? <>
          <h4>{focus.name} India</h4>
          <p className="muted small">{sectorLine(focus)}{hovered && hovered !== selected ? ' · click to choose' : ''}</p>
          {selected === focus.code && <><h5>Top caretakers</h5>
            {top.length ? <ol className="im-list">{top.slice(0, 5).map(m => <li key={m.caregiver_id}><button type="button" className="im-link" onClick={() => onProfile(m.caregiver_id)}>
              <span>{m.name}</span><small>{m.score} pts{m.composite !== null ? ` · ★ ${Math.round(m.composite)}` : ''}</small></button></li>)}</ol> : <p className="muted small">No one fits the current filters.</p>}</>}
          <h5>Top agencies</h5>
          {focus.top_agencies.length ? <ol className="im-list">{focus.top_agencies.map(a => <li key={a.id}><button type="button" className="im-link" onClick={() => onAgency(a.id, focus.code)}>
            <span>{a.name}</span><small>{a.average_rating ? `${a.average_rating.toFixed(1)}★ · ` : ''}{a.caretakers} caretaker{a.caretakers === 1 ? '' : 's'} · {a.city}</small></button></li>)}</ol> : <p className="muted small">No agencies listed here yet.</p>}
        </> : <>
          <h4>All India</h4>
          <ul className="im-list">{summary.map(s => <li key={s.code}><button type="button" className="im-link" onClick={() => pick(s.code)}><span><i className={`im-dot im-${s.code.toLowerCase()}`} aria-hidden="true"/>{s.name}</span><small>{sectorLine(s)}</small></button></li>)}</ul>
          <p className="muted small">Choose a region to see its top caretakers and agencies.</p>
        </>}
      </aside>
    </div>
  </section>;
}
