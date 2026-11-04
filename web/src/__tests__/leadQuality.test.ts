import { describe, expect, it } from 'vitest'
import { isInactiveComparator } from '../lib/leadQuality'

describe('lead quality helpers', () => {
  it('recognizes trial comparators but not real products', () => {
    expect(['Placebo', 'Vehicle Cream', 'Matching placebo tablet'].every(isInactiveComparator)).toBe(true)
    expect(['Ritonavir', 'Estradiol Vaginal Cream', null].some(isInactiveComparator)).toBe(false)
  })
})
