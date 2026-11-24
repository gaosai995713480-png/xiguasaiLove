import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../utils/markdown'
import { isSafeImageUrl } from '../utils/security'

function renderToDom(markdown) {
  const container = document.createElement('div')
  container.innerHTML = renderMarkdown(markdown)
  return container
}

describe('renderMarkdown XSS 防护', () => {
  it('普通文本和 HTML 实体会被转义，不创建可执行节点', () => {
    const payload = '<img src=x onerror="window.__markdownXss=1"> &lt;script&gt;'
    const container = renderToDom(payload)

    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.textContent).toContain(payload)
  })

  it('标题、列表和行内代码中的 HTML 都只作为文本显示', () => {
    const container = renderToDom([
      '# <img src=x onerror="window.__headingXss=1">',
      '- ` <svg onload="window.__codeXss=1"> `',
      '`<img src=x onerror="window.__inlineXss=1">`',
    ].join('\n'))

    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('svg')).toBeNull()
    expect(container.textContent).toContain('<img src=x')
  })

  it('拒绝 javascript 和 data 图片 URL', () => {
    const container = renderToDom([
      '![a](javascript:alert(1))',
      '![b](data:image/svg+xml,<svg onload=alert(1)>)',
    ].join('\n'))

    expect(container.querySelectorAll('img')).toHaveLength(0)
    expect(container.textContent).toContain('javascript:alert(1)')
    expect(container.textContent).toContain('data:image/svg+xml')
  })

  it('安全图片仍可渲染，危险属性注入会被转义', () => {
    const safe = renderToDom('![安全图](https://example.com/a.png)')
    const image = safe.querySelector('img')
    expect(image).not.toBeNull()
    expect(image.getAttribute('src')).toBe('https://example.com/a.png')
    expect(image.getAttribute('alt')).toBe('安全图')

    const injected = renderToDom('![x](https://example.com/a.png" onerror="window.__urlXss=1)')
    expect(injected.querySelectorAll('[onerror*="__urlXss"]')).toHaveLength(0)
  })

  it('代码块内容不会生成 HTML 节点', () => {
    const container = renderToDom('```html\n<img src=x onerror="window.__blockXss=1">\n```')

    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('pre code').textContent).toContain('<img src=x')
  })
})

describe('isSafeImageUrl', () => {
  it('只允许 http/https 和站内相对路径', () => {
    expect(isSafeImageUrl('https://example.com/a.png')).toBe(true)
    expect(isSafeImageUrl('/photos/a.png')).toBe(true)
    expect(isSafeImageUrl('./a.png')).toBe(true)
    expect(isSafeImageUrl('javascript:alert(1)')).toBe(false)
    expect(isSafeImageUrl('data:image/png;base64,AAAA')).toBe(false)
    expect(isSafeImageUrl('//example.com/a.png')).toBe(false)
  })
})
