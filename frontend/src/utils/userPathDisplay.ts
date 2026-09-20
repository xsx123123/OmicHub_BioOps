const USER_HOME_PREFIX = /^\/data\/cygnusx\/users\/[^/]+(?=\/|$)/
const USER_HOME_PREFIX_IN_TEXT = /\/data\/cygnusx\/users\/[^/]+(?=\/|$)/g

/**
 * Produces the path users see in the workbench without exposing the platform's
 * per-user storage root. Paths outside a user home are intentionally unchanged.
 */
export function formatUserPath(path: string | null | undefined): string {
  const value = path?.trim()
  if (!value) return ''

  const relativePath = value.replace(USER_HOME_PREFIX, '')
  return relativePath || '/'
}

/** Removes every user-home prefix embedded in user-facing status text. */
export function redactUserHomePaths(text: string | null | undefined): string {
  if (!text) return ''
  return text.replace(USER_HOME_PREFIX_IN_TEXT, '')
}
