export function isIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(year, month - 1, day)
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day
}

export function formatIsoDate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function shiftIsoDate(value, days) {
  if (!isIsoDate(value)) return value
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(year, month - 1, day)
  date.setDate(date.getDate() + days)
  return formatIsoDate(date)
}

export function formatDayTitle(value) {
  if (!isIsoDate(value)) return value || ''
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(year, month - 1, day)
  const week = ['日', '一', '二', '三', '四', '五', '六'][date.getDay()]
  return `${year}年${month}月${day}日 星期${week}`
}

export function photoDay(createdAt) {
  if (!createdAt) return ''
  const date = String(createdAt).split(' ')[0]
  return isIsoDate(date) ? date : ''
}
