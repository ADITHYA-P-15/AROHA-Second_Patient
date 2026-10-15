/** A simplified map of India drawn in-house, with no map data, tiles or CDN, so it works offline and carries no licence.
 *
 * The outline is a hand-traced approximation of India's mainland (about 70 points, lon/lat). Each state is the part of
 * that outline nearer to its own centre point than to any other state's (a Voronoi split), so shapes and neighbours
 * look familiar without being real borders. Island territories are small separate shapes. Good for choosing a region,
 * not for distances or borders.
 */
export type Pt = [number, number];
export type StateSite = { state: string; code: string; lon: number; lat: number; island?: boolean };

// Mainland outline, clockwise from Kutch (lon, lat). Approximate, simplified.
export const OUTLINE: Pt[] = [
  [68.2, 23.7], [69.0, 22.4], [70.5, 20.8], [72.6, 21.1], [72.8, 19.0], [73.4, 16.0], [74.1, 14.8], [74.8, 12.8], [75.8, 11.2], [76.3, 9.5],
  [77.0, 8.3], [77.5, 8.08], [78.2, 8.9], [79.3, 10.3], [79.8, 11.9], [80.3, 13.1], [80.2, 15.5], [81.3, 16.3], [82.3, 17.0], [83.3, 17.7],
  [84.9, 19.3], [86.6, 20.3], [87.1, 21.5], [88.2, 21.6], [89.0, 21.9], [88.9, 22.9], [88.7, 24.0], [88.1, 24.5], [88.5, 25.2], [88.3, 26.0],
  [89.8, 25.9], [90.5, 25.2], [92.0, 25.1], [92.3, 24.4], [91.3, 24.0], [91.4, 23.2], [91.8, 22.9], [92.6, 21.95], [93.2, 22.8], [94.2, 23.8],
  [94.7, 25.0], [95.2, 26.0], [96.6, 27.4], [97.4, 28.2], [95.5, 29.2], [93.9, 28.7], [92.0, 27.9], [91.6, 27.8], [91.7, 26.8], [89.8, 26.7],
  [88.9, 27.1], [88.8, 28.0], [88.1, 27.9], [88.1, 26.7], [86.0, 26.5], [84.0, 27.4], [82.0, 27.6], [80.5, 28.7], [80.9, 30.2], [79.5, 31.1],
  [78.7, 31.8], [78.4, 32.6], [79.3, 32.5], [79.0, 34.0], [78.0, 35.5], [77.8, 35.7], [76.0, 36.0], [75.0, 36.5], [74.0, 35.5], [73.6, 34.3],
  [74.6, 32.8], [75.4, 32.3], [74.6, 31.2], [74.0, 30.4], [73.4, 29.9], [72.5, 28.0], [70.4, 27.8], [69.6, 26.6], [70.5, 25.6], [71.1, 24.4], [69.1, 24.2],
];

export const STATES: StateSite[] = [
  { state: 'Jammu and Kashmir', code: 'JK', lon: 75.0, lat: 33.7 }, { state: 'Ladakh', code: 'LA', lon: 77.6, lat: 34.3 },
  { state: 'Himachal Pradesh', code: 'HP', lon: 77.2, lat: 31.9 }, { state: 'Punjab', code: 'PB', lon: 75.3, lat: 30.9 },
  { state: 'Chandigarh', code: 'CH', lon: 76.8, lat: 30.75 }, { state: 'Haryana', code: 'HR', lon: 76.1, lat: 29.2 },
  { state: 'Delhi', code: 'DL', lon: 77.15, lat: 28.6 }, { state: 'Uttarakhand', code: 'UK', lon: 79.1, lat: 30.1 },
  { state: 'Uttar Pradesh', code: 'UP', lon: 80.9, lat: 27.0 }, { state: 'Rajasthan', code: 'RJ', lon: 73.8, lat: 26.6 },
  { state: 'Gujarat', code: 'GJ', lon: 71.6, lat: 22.7 }, { state: 'Madhya Pradesh', code: 'MP', lon: 78.2, lat: 23.5 },
  { state: 'Maharashtra', code: 'MH', lon: 75.7, lat: 19.5 }, { state: 'Dadra and Nagar Haveli and Daman and Diu', code: 'DD', lon: 72.9, lat: 20.5 },
  { state: 'Goa', code: 'GA', lon: 74.05, lat: 15.35 }, { state: 'Karnataka', code: 'KA', lon: 76.2, lat: 14.5 },
  { state: 'Kerala', code: 'KL', lon: 76.4, lat: 10.3 }, { state: 'Tamil Nadu', code: 'TN', lon: 78.4, lat: 11.1 },
  { state: 'Puducherry', code: 'PY', lon: 79.75, lat: 11.9 }, { state: 'Andhra Pradesh', code: 'AP', lon: 79.7, lat: 15.8 },
  { state: 'Telangana', code: 'TS', lon: 79.0, lat: 17.9 }, { state: 'Chhattisgarh', code: 'CG', lon: 82.0, lat: 21.3 },
  { state: 'Odisha', code: 'OD', lon: 84.5, lat: 20.4 }, { state: 'Jharkhand', code: 'JH', lon: 85.5, lat: 23.6 },
  { state: 'Bihar', code: 'BR', lon: 85.6, lat: 25.8 }, { state: 'West Bengal', code: 'WB', lon: 87.9, lat: 23.6 },
  { state: 'Sikkim', code: 'SK', lon: 88.45, lat: 27.5 }, { state: 'Assam', code: 'AS', lon: 92.6, lat: 26.3 },
  { state: 'Arunachal Pradesh', code: 'AR', lon: 94.6, lat: 28.0 }, { state: 'Nagaland', code: 'NL', lon: 94.4, lat: 26.0 },
  { state: 'Manipur', code: 'MN', lon: 93.9, lat: 24.7 }, { state: 'Mizoram', code: 'MZ', lon: 92.8, lat: 23.2 },
  { state: 'Tripura', code: 'TR', lon: 91.7, lat: 23.8 }, { state: 'Meghalaya', code: 'ML', lon: 91.2, lat: 25.5 },
  { state: 'Andaman and Nicobar Islands', code: 'AN', lon: 92.8, lat: 11.8, island: true }, { state: 'Lakshadweep', code: 'LD', lon: 72.7, lat: 10.6, island: true },
];

export const SECTOR_ORDER = ['NORTH', 'SOUTH', 'EAST', 'WEST'] as const;
const SCALE = 20;  // px per degree

/** Equirectangular projection, stretched a little in y so India keeps its familiar shape. */
export function project(lon: number, lat: number): Pt {
  return [round((lon - 67.5) * SCALE), round((37.2 - lat) * SCALE * 1.08)];
}
const round = (v: number) => Math.round(v * 10) / 10;

/** Keep the part of a polygon on `site`'s side of the perpendicular bisector between `site` and `other` (Sutherland–Hodgman). */
export function clipToSite(poly: Pt[], site: Pt, other: Pt): Pt[] {
  const [ax, ay] = site, [bx, by] = other;
  const nx = bx - ax, ny = by - ay, c = (bx * bx + by * by - ax * ax - ay * ay) / 2;  // inside: nx*x + ny*y <= c
  const inside = (p: Pt) => nx * p[0] + ny * p[1] <= c + 1e-9;
  const cross = (p: Pt, q: Pt): Pt => { const t = (c - nx * p[0] - ny * p[1]) / (nx * (q[0] - p[0]) + ny * (q[1] - p[1])); return [p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])]; };
  const out: Pt[] = [];
  for (let i = 0; i < poly.length; i++) {
    const cur = poly[i], prev = poly[(i + poly.length - 1) % poly.length];
    if (inside(cur)) { if (!inside(prev)) out.push(cross(prev, cur)); out.push(cur); }
    else if (inside(prev)) out.push(cross(prev, cur));
  }
  return out;
}

/** Each mainland state's region: the outline, cut down to the area nearer its own centre than any other's. */
export function stateShapes(): Record<string, Pt[]> {
  const outline = OUTLINE.map(([lon, lat]) => project(lon, lat));
  const mainland = STATES.filter(s => !s.island).map(s => ({ ...s, p: project(s.lon, s.lat) }));
  const out: Record<string, Pt[]> = {};
  for (const s of mainland) {
    let poly = outline;
    for (const o of mainland) if (o !== s) { poly = clipToSite(poly, s.p, o.p); if (!poly.length) break; }
    out[s.state] = poly;
  }
  for (const s of STATES.filter(x => x.island)) {
    const [x, y] = project(s.lon, s.lat);
    out[s.state] = s.code === 'AN' ? [[x - 6, y - 40], [x + 6, y - 40], [x + 8, y + 40], [x - 4, y + 40]] : [[x - 7, y - 7], [x + 7, y - 7], [x + 7, y + 7], [x - 7, y + 7]];
  }
  return out;
}

export function pathOf(poly: Pt[]): string {
  return poly.length ? `M${poly.map(p => `${round(p[0])},${round(p[1])}`).join('L')}Z` : '';
}

export function pointInPolygon([x, y]: Pt, poly: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export type Box = { x: number; y: number; w: number; h: number };

export function boxOf(polys: Pt[][], pad = 12): Box {
  const pts = polys.flat();
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const x = Math.min(...xs) - pad, y = Math.min(...ys) - pad;
  return { x: round(x), y: round(y), w: round(Math.max(...xs) + pad - x), h: round(Math.max(...ys) + pad - y) };
}

/** Linear step between two view boxes (t from 0 to 1) for a smooth zoom. */
export function lerpBox(a: Box, b: Box, t: number): Box {
  const k = Math.min(1, Math.max(0, t));
  return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, w: a.w + (b.w - a.w) * k, h: a.h + (b.h - a.h) * k };
}

export const easeInOut = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

/** state -> sector code, from the sector list the server returns (the configurable state map). */
export function sectorOfState(sectors: { code: string; states: string[] }[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const s of sectors) for (const st of s.states) out[st] = s.code;
  return out;
}

/** How a state looks: its sector's colour, softened when another sector is in focus. */
export function tileState(sector: string | undefined, selected: string, hovered: string): 'active' | 'dim' | 'normal' | 'none' {
  if (!sector) return 'none';
  const focus = hovered || selected;
  if (!focus) return 'normal';
  return sector === focus ? 'active' : 'dim';
}

/** Bubble radius for a state's caretaker count: area grows with the count, 0 hides it. */
export function bubbleRadius(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0;
  return round(4 + 10 * Math.sqrt(count / max));
}

/** One line under the sector name in the side panel. */
export function sectorLine(s: { caretakers: number; agency_count: number }): string {
  return `${s.caretakers} caretaker${s.caretakers === 1 ? '' : 's'} · ${s.agency_count} agenc${s.agency_count === 1 ? 'y' : 'ies'}`;
}

/** The text of a state's tooltip. */
export function tooltipLines(state: string, sectorName: string | undefined, count: number, topAgency: string | undefined): string[] {
  return [state, sectorName ? `${sectorName} region` : 'Not in a region yet', `${count} caretaker${count === 1 ? '' : 's'}`, topAgency ? `Top agency: ${topAgency}` : ''].filter(Boolean);
}

/** Clicking a state on the map: pick it (and its region) or, if already picked, drop it. States from another region are cleared. */
export function toggleMapState(current: { sector: string; state: string[] }, state: string, sector: string): { sector: string; state: string[] } {
  const same = current.sector === sector ? current.state : [];
  return { sector, state: same.includes(state) ? same.filter(s => s !== state) : [...same, state] };
}
