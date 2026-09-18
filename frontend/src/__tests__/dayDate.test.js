import { describe, expect, it } from 'vitest'
import { formatDayTitle, isIsoDate, photoDay, shiftIsoDate } from '../utils/dayDate'

describe('dayDate', () => {
  it('只接受真实存在的 ISO 日期', () => {
    expect(isIsoDate('2023-10-26')).toBe(true)
    expect(isIsoDate('2023-02-29')).toBe(false)
    expect(isIsoDate('2023-13-01')).toBe(false)
    expect(isIsoDate('2023-10-26T00:00:00')).toBe(false)
  })

  it('按本地日历前后翻一天', () => {
    expect(shiftIsoDate('2023-10-26', -1)).toBe('2023-10-25')
    expect(shiftIsoDate('2023-10-31', 1)).toBe('2023-11-01')
  })

  it('把日期格式化成中文标题', () => {
    expect(formatDayTitle('2023-10-26')).toContain('2023年10月26日')
    expect(formatDayTitle('2023-10-26')).toMatch(/星期[日一二三四五六]/)
  })

  it('从相册时间里取出归属日期', () => {
    expect(photoDay('2023-10-26 18:30:00')).toBe('2023-10-26')
    expect(photoDay('')).toBe('')
  })
})
