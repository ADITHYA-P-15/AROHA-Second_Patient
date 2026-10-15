import { describe, expect, it } from 'vitest';
import { OUTLINE, STATES, boxOf, bubbleRadius, clipToSite, easeInOut, lerpBox, pathOf, pointInPolygon, project, sectorLine, sectorOfState, stateShapes, tileState, toggleMapState, tooltipLines, type Pt } from './indiamap.ts';

describe('India map geometry', () => {
  const shapes = stateShapes();
  it('gives every state and territory a shape, unique codes', () => {
    expect(new Set(STATES.map(s => s.code)).size).toBe(STATES.length);
    for (const s of STATES) expect(shapes[s.state].length).toBeGreaterThanOrEqual(3);
  });
  it('puts each mainland state centre inside its own region and inside the outline', () => {
    const outline = OUTLINE.map(([lon, lat]) => project(lon, lat));
    for (const s of STATES.filter(x => !x.island)) {
      const p = project(s.lon, s.lat);
      expect(pointInPolygon(p, outline)).toBe(true);
      expect(pointInPolygon(p, shapes[s.state])).toBe(true);
    }
  });
  it('clips a square to the half nearer a site', () => {
    const square: Pt[] = [[0, 0], [10, 0], [10, 10], [0, 10]];
    const left = clipToSite(square, [2, 5], [8, 5]);
    expect(boxOf([left], 0)).toEqual({ x: 0, y: 0, w: 5, h: 10 });
    expect(pathOf([[0, 0], [5, 0], [5, 5]])).toBe('M0,0L5,0L5,5Z');
  });
  it('zooms smoothly between view boxes', () => {
    const a = { x: 0, y: 0, w: 100, h: 100 }, b = { x: 50, y: 20, w: 40, h: 30 };
    expect(lerpBox(a, b, 0)).toEqual(a);
    expect(lerpBox(a, b, 1)).toEqual(b);
    expect(lerpBox(a, b, 0.5)).toEqual({ x: 25, y: 10, w: 70, h: 65 });
    expect(easeInOut(0)).toBe(0); expect(easeInOut(1)).toBe(1); expect(easeInOut(0.5)).toBe(0.5);
  });
});

describe('India map interaction helpers', () => {
  it('colours states from the server sector map', () => {
    const map = sectorOfState([{ code: 'SOUTH', states: ['Karnataka', 'Kerala'] }, { code: 'NORTH', states: ['Delhi'] }]);
    expect(map['Karnataka']).toBe('SOUTH');
    expect(map['Goa']).toBeUndefined();
  });
  it('highlights the hovered or selected sector and softens the rest', () => {
    expect(tileState('SOUTH', '', '')).toBe('normal');
    expect(tileState('SOUTH', 'SOUTH', '')).toBe('active');
    expect(tileState('NORTH', 'SOUTH', '')).toBe('dim');
    expect(tileState('NORTH', 'SOUTH', 'NORTH')).toBe('active');
    expect(tileState(undefined, 'SOUTH', '')).toBe('none');
  });
  it('sizes bubbles by caretaker count', () => {
    expect(bubbleRadius(0, 10)).toBe(0);
    expect(bubbleRadius(10, 10)).toBe(14);
    expect(bubbleRadius(1, 10)).toBeLessThan(bubbleRadius(4, 10));
  });
  it('writes the tooltip and panel lines', () => {
    expect(tooltipLines('Kerala', 'South', 3, 'Coastal Care Collective')).toEqual(['Kerala', 'South region', '3 caretakers', 'Top agency: Coastal Care Collective']);
    expect(tooltipLines('Goa', undefined, 1, undefined)).toEqual(['Goa', 'Not in a region yet', '1 caretaker']);
    expect(sectorLine({ caretakers: 1, agency_count: 3 })).toBe('1 caretaker · 3 agencies');
  });
});

describe('clicking states on the map', () => {
  it('picks a state with its region, adds others in the region, and toggles off', () => {
    let f = { sector: '', state: [] as string[] };
    f = toggleMapState(f, 'Kerala', 'SOUTH');
    expect(f).toEqual({ sector: 'SOUTH', state: ['Kerala'] });
    f = toggleMapState(f, 'Karnataka', 'SOUTH');
    expect(f).toEqual({ sector: 'SOUTH', state: ['Kerala', 'Karnataka'] });
    f = toggleMapState(f, 'Kerala', 'SOUTH');
    expect(f).toEqual({ sector: 'SOUTH', state: ['Karnataka'] });
    expect(toggleMapState(f, 'Delhi', 'NORTH')).toEqual({ sector: 'NORTH', state: ['Delhi'] });
  });
});
