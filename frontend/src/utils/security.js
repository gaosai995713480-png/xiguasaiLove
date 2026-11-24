const HTML_ENTITY_MAP = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => HTML_ENTITY_MAP[char])
}

export function isSafeImageUrl(value) {
  const raw = String(value ?? '').trim()
  if (!raw) return false

  // 浏览器会忽略 URL scheme 中的控制字符和空白，检查前先归一化。
  const compact = raw.replace(/[\u0000-\u0020\u007f]+/g, '')
  if (/^https?:\/\//i.test(compact)) return true
  if (compact.startsWith('/') && !compact.startsWith('//')) return true
  return compact.startsWith('./') || compact.startsWith('../')
}
