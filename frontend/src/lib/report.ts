export type ReportFact = { id: string; section: string; key: string; text: string };
export type ReportSentence = { text: string; facts: string[] };
export type ProgressReport = {
  patient_id: string; days: number; as_of: string; facts: ReportFact[]; limits: string[]; summary: ReportSentence[];
  narrated_by: 'ai' | 'template'; provider: string | null; dropped: number; status: 'DRAFT'; reviewed: boolean; notice: string;
};

export const SECTION_LABEL: Record<string, string> = {
  course: 'Course of treatment', adherence: 'Doses and adherence', appointments: 'Appointments', requests: 'Help requests',
  checkins: 'Wellbeing check-ins', monitoring: 'What is being monitored',
};
export const SECTION_ORDER = ['course', 'adherence', 'appointments', 'requests', 'checkins', 'monitoring'];

export function groupFacts(facts: ReportFact[]): { section: string; label: string; facts: ReportFact[] }[] {
  return SECTION_ORDER.map(section => ({ section, label: SECTION_LABEL[section] ?? section, facts: facts.filter(f => f.section === section) })).filter(g => g.facts.length);
}

/** Plain text for pasting into a note. Starts with the draft notice so it is never mistaken for a signed report. */
export function reportToText(report: ProgressReport, patientName: string): string {
  const lines = [`DRAFT progress report: ${patientName}`, `Period: last ${report.days} days`, report.notice, '', 'Summary'];
  for (const s of report.summary) lines.push(`- ${s.text} [${s.facts.join(', ')}]`);
  for (const group of groupFacts(report.facts)) {
    lines.push('', group.label);
    for (const f of group.facts) lines.push(`- ${f.text} [${f.id}]`);
  }
  lines.push('', ...report.limits);
  return lines.join('\n');
}
