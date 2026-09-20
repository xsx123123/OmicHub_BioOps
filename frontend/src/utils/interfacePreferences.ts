const FESTIVAL_EFFECTS_KEY = 'cygnusx-festival-effects'

export function isFestivalEffectsEnabled(): boolean {
  try {
    return localStorage.getItem(FESTIVAL_EFFECTS_KEY) !== 'false'
  } catch {
    return true
  }
}

export function setFestivalEffectsEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(FESTIVAL_EFFECTS_KEY, String(enabled))
  } catch {
    /* Storage is optional; the current session remains functional. */
  }
}
