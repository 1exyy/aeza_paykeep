/** The month shown in the calendar, or its whole year. */
export function exportRange(month: string, scope: 'month' | 'year'): { from: string; to: string } {
  const [year, value] = month.split('-').map(Number)
  if (scope === 'year') return { from: `${year}-01-01`, to: `${year}-12-31` }
  const last = new Date(Date.UTC(year!, value!, 0)).getUTCDate()
  return { from: `${month}-01`, to: `${month}-${String(last).padStart(2, '0')}` }
}
