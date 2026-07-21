import { describe, expect, it } from 'vitest'
import { translations } from './i18n'

describe('translations', () => {
  it('has an English value for every normative Indonesian key', () => {
    expect(Object.keys(translations.en).sort()).toEqual(Object.keys(translations.id).sort())
    for (const [key, value] of Object.entries(translations.en)) {
      expect(value, key).not.toBe('')
    }
  })
})
