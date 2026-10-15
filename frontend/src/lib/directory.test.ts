import { describe, expect, it } from 'vitest';
import { buildDirectoryQuery, cardText, cityOptions, experienceText, pageLabel, selectionSummary, splitLanguages, type CaretakerCard } from './directory.ts';

const card: CaretakerCard = {
  id: 'c1', name: 'Asha Nair', gender: 'FEMALE', gender_label: 'Female', origin_state: 'Kerala', origin_city: 'Thrissur', current_state: 'Maharashtra', current_city: 'Pune',
  sector: 'WEST', agency: { id: 'a1', name: 'Sahyadri Caregivers' }, languages: ['Malayalam', 'English'], capabilities: ['MEDICATION_ASSIST', 'TRANSPORT'], years_experience: 6, is_synthetic: true,
};

describe('directory query building', () => {
  it('drops blanks and defaults, trims text and keeps each filter', () => {
    expect(buildDirectoryQuery({})).toBe('');
    expect(buildDirectoryQuery({ sector: 'NORTH', city: '  Pune ', gender: '', language: 'Tamil', sort: 'name', offset: 0 })).toBe('?sector=NORTH&city=Pune&language=Tamil');
    expect(buildDirectoryQuery({ agency: 'a1', state: 'Kerala', capability: 'LAB_ESCORT', available_on: '2026-10-17', sort: 'experience' }))
      .toBe('?agency=a1&state=Kerala&capability=LAB_ESCORT&available_on=2026-10-17&sort=experience');
  });
  it('combines filters in a stable order and encodes text', () => {
    expect(buildDirectoryQuery({ language: 'Konkani', sector: 'WEST', city: 'Navi Mumbai', min_experience: '5' })).toBe('?sector=WEST&city=Navi+Mumbai&language=Konkani&min_experience=5');
  });
  it('sends several states, cities, languages and skills as repeated parameters', () => {
    expect(buildDirectoryQuery({ state: ['Kerala', 'Goa'], city: ['Kochi', ' kochi ', 'Panaji'], language: [], capability: ['TRANSPORT', 'LAB_ESCORT'] }))
      .toBe('?state=Kerala&state=Goa&city=Kochi&city=Panaji&capability=TRANSPORT&capability=LAB_ESCORT');
    expect(buildDirectoryQuery({ language: ['Tamil'], sector: 'SOUTH' })).toBe('?sector=SOUTH&language=Tamil');
  });
  it('keeps paging and experience inside the server bounds', () => {
    expect(buildDirectoryQuery({ limit: 500 })).toBe('?limit=50');
    expect(buildDirectoryQuery({ limit: 0, offset: -10 })).toBe('?limit=12');
    expect(buildDirectoryQuery({ offset: 24.7 })).toBe('?offset=24');
    expect(buildDirectoryQuery({ min_experience: 0 })).toBe('');
    expect(buildDirectoryQuery({ min_experience: 'abc' })).toBe('');
    expect(buildDirectoryQuery({ min_experience: 99 })).toBe('?min_experience=60');
    expect(buildDirectoryQuery({ min_agency_rating: '4' })).toBe('?min_agency_rating=4');
    expect(buildDirectoryQuery({ min_agency_rating: '' })).toBe('');
    expect(buildDirectoryQuery({ min_agency_rating: 9 })).toBe('?min_agency_rating=5');
  });
});

describe('directory card text', () => {
  it('reads as a short profile without contact details', () => {
    const text = cardText(card);
    expect(text.title).toBe('Asha Nair');
    expect(text.lines).toEqual(['Female · from Thrissur, Kerala', 'Lives in Pune, Maharashtra', 'Agency: Sahyadri Caregivers', 'Speaks Malayalam, English', '6 years of experience']);
    expect(text.skills).toEqual(['Medicines', 'Transport']);
    expect(JSON.stringify(text)).not.toMatch(/phone|\+91/i);
  });
  it('handles a local, independent, new caretaker', () => {
    const text = cardText({ ...card, origin_city: 'Pune', origin_state: 'Maharashtra', agency: null, languages: [], years_experience: 0 });
    expect(text.lines).toEqual(['Female', 'Lives in Pune, Maharashtra', 'Independent caretaker', 'New to caretaking']);
    expect(cardText({ ...card, current_city: '', current_state: '' }).lines[1]).toBe('Location not given');
    expect(cardText({ ...card, agency_rating: 4.5 }).lines[2]).toBe('Agency: Sahyadri Caregivers · rated 4.5★ by the agency');
  });
  it('labels experience, pages and language lists', () => {
    expect(experienceText(1)).toBe('1 year of experience');
    expect(pageLabel({ total: 30, limit: 12, offset: 12 }, 12)).toBe('13–24 of 30');
    expect(pageLabel({ total: 0, limit: 12, offset: 0 }, 0)).toBe('No caretakers match');
    expect(splitLanguages('Tamil, english , ,Hindi')).toEqual(['Tamil', 'english', 'Hindi']);
  });
});

describe('multi-select helpers', () => {
  const opts = [{ value: 'Pune', label: 'Pune' }, { value: 'Mumbai', label: 'Mumbai' }, { value: 'Goa', label: 'Goa' }, { value: 'TRANSPORT', label: 'Transport' }];
  it('summarises the picks when closed', () => {
    expect(selectionSummary([], opts)).toBe('Any');
    expect(selectionSummary(['TRANSPORT'], opts)).toBe('Transport');
    expect(selectionSummary(['Pune', 'Mumbai', 'Goa', 'X'], opts)).toBe('Pune, Mumbai +2');
  });
  it('offers the cities of the picked states and keeps picked ones', () => {
    const all = [{ city: 'Pune', state: 'Maharashtra' }, { city: 'Mumbai', state: 'Maharashtra' }, { city: 'Kochi', state: 'Kerala' }];
    expect(cityOptions(all, []).map(c => c.value)).toEqual(['Pune', 'Mumbai', 'Kochi']);
    expect(cityOptions(all, ['Kerala']).map(c => c.value)).toEqual(['Kochi']);
    expect(cityOptions(all, ['Kerala'], ['Pune']).map(c => c.value)).toEqual(['Kochi', 'Pune']);
    expect(cityOptions(all, ['Kerala'])[0].hint).toBe('Kerala');
  });
});
