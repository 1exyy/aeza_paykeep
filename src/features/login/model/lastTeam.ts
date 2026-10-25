const KEY = 'paykeep:last-team'

/** The team typed at the last successful login (a per-browser convenience). */
export function readLastTeam(): string {
  try {
    return window.localStorage.getItem(KEY) ?? ''
  } catch {
    return ''
  }
}

export function saveLastTeam(team: string): void {
  try {
    window.localStorage.setItem(KEY, team.trim())
  } catch {
    // private mode or blocked storage: the field simply starts empty next time
  }
}
