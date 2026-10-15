/** A schematic tile map of India: one tile per state or union territory, placed roughly where it lies.
 * Drawn in-house (no map data, tiles or CDN), so it works offline and has no licence attached. It shows sectors, not borders. */
export type Tile = { state: string; code: string; col: number; row: number };

export const TILES: Tile[] = [
  { state: 'Jammu and Kashmir', code: 'JK', col: 2, row: 0 }, { state: 'Ladakh', code: 'LA', col: 3, row: 0 },
  { state: 'Chandigarh', code: 'CH', col: 1, row: 1 }, { state: 'Punjab', code: 'PB', col: 2, row: 1 }, { state: 'Himachal Pradesh', code: 'HP', col: 3, row: 1 },
  { state: 'Haryana', code: 'HR', col: 2, row: 2 }, { state: 'Delhi', code: 'DL', col: 3, row: 2 }, { state: 'Uttarakhand', code: 'UK', col: 4, row: 2 },
  { state: 'Sikkim', code: 'SK', col: 6, row: 2 }, { state: 'Arunachal Pradesh', code: 'AR', col: 8, row: 2 },
  { state: 'Rajasthan', code: 'RJ', col: 1, row: 3 }, { state: 'Uttar Pradesh', code: 'UP', col: 3, row: 3 }, { state: 'Bihar', code: 'BR', col: 5, row: 3 },
  { state: 'Assam', code: 'AS', col: 7, row: 3 }, { state: 'Nagaland', code: 'NL', col: 8, row: 3 },
  { state: 'Gujarat', code: 'GJ', col: 0, row: 4 }, { state: 'Madhya Pradesh', code: 'MP', col: 2, row: 4 }, { state: 'Jharkhand', code: 'JH', col: 4, row: 4 },
  { state: 'West Bengal', code: 'WB', col: 5, row: 4 }, { state: 'Meghalaya', code: 'ML', col: 7, row: 4 }, { state: 'Manipur', code: 'MN', col: 8, row: 4 },
  { state: 'Dadra and Nagar Haveli and Daman and Diu', code: 'DD', col: 0, row: 5 }, { state: 'Maharashtra', code: 'MH', col: 1, row: 5 },
  { state: 'Chhattisgarh', code: 'CG', col: 3, row: 5 }, { state: 'Odisha', code: 'OD', col: 4, row: 5 }, { state: 'Tripura', code: 'TR', col: 7, row: 5 }, { state: 'Mizoram', code: 'MZ', col: 8, row: 5 },
  { state: 'Goa', code: 'GA', col: 1, row: 6 }, { state: 'Telangana', code: 'TS', col: 2, row: 6 }, { state: 'Andhra Pradesh', code: 'AP', col: 3, row: 6 },
  { state: 'Karnataka', code: 'KA', col: 1, row: 7 }, { state: 'Puducherry', code: 'PY', col: 3, row: 7 }, { state: 'Andaman and Nicobar Islands', code: 'AN', col: 6, row: 7 },
  { state: 'Lakshadweep', code: 'LD', col: 0, row: 8 }, { state: 'Kerala', code: 'KL', col: 1, row: 8 }, { state: 'Tamil Nadu', code: 'TN', col: 2, row: 8 },
];

export const SECTOR_ORDER = ['NORTH', 'SOUTH', 'EAST', 'WEST'] as const;
export const TILE = { w: 62, h: 42, gap: 6 };

/** state -> sector code, from the sector list the server returns (the configurable state map). */
export function sectorOfState(sectors: { code: string; states: string[] }[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const s of sectors) for (const st of s.states) out[st] = s.code;
  return out;
}

export function tileBox(t: Pick<Tile, 'col' | 'row'>): { x: number; y: number; w: number; h: number } {
  return { x: t.col * (TILE.w + TILE.gap), y: t.row * (TILE.h + TILE.gap), w: TILE.w, h: TILE.h };
}

export function mapSize(tiles: Tile[] = TILES): { width: number; height: number } {
  const cols = Math.max(...tiles.map(t => t.col)) + 1, rows = Math.max(...tiles.map(t => t.row)) + 1;
  return { width: cols * (TILE.w + TILE.gap) - TILE.gap, height: rows * (TILE.h + TILE.gap) - TILE.gap };
}

/** How a tile looks: its sector's colour, dimmed when another sector is selected or hovered. */
export function tileState(sector: string | undefined, selected: string, hovered: string): 'active' | 'dim' | 'normal' | 'none' {
  if (!sector) return 'none';
  const focus = hovered || selected;
  if (!focus) return 'normal';
  return sector === focus ? 'active' : 'dim';
}

/** One line under the sector name in the side panel. */
export function sectorLine(s: { caretakers: number; agency_count: number }): string {
  return `${s.caretakers} caretaker${s.caretakers === 1 ? '' : 's'} · ${s.agency_count} agenc${s.agency_count === 1 ? 'y' : 'ies'}`;
}
