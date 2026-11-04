import { describe, expect, it } from 'vitest'
import { neutralizeBrand } from '../lib/displayBrand'

describe('dashboard copy', () => {
  it('removes the old organization name from stored narrative text', () => {
    expect(neutralizeBrand('SVAK supports custom impurity synthesis. Why might SVAK help?')).toBe('Our team supports custom impurity synthesis. Why might our team help?')
    expect(neutralizeBrand('SVAK may reduce turnaround')).toBe('Our team may reduce turnaround')
  })

  it('leaves unrelated words and empty values alone', () => {
    expect(neutralizeBrand('Analytical services')).toBe('Analytical services')
    expect(neutralizeBrand(null)).toBe('')
  })
})
