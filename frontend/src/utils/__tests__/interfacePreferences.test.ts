// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest'
import {
  isFestivalEffectsEnabled,
  setFestivalEffectsEnabled,
} from '@/utils/interfacePreferences'

const FESTIVAL_EFFECTS_KEY = 'omichub-festival-effects'

afterEach(() => {
  localStorage.removeItem(FESTIVAL_EFFECTS_KEY)
})

describe('festival effect preference', () => {
  it('enables effects by default until the user opts out', () => {
    expect(isFestivalEffectsEnabled()).toBe(true)
  })

  it('preserves an explicit user choice', () => {
    setFestivalEffectsEnabled(false)
    expect(isFestivalEffectsEnabled()).toBe(false)

    setFestivalEffectsEnabled(true)
    expect(isFestivalEffectsEnabled()).toBe(true)
  })
})
