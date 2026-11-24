import { escapeHtml, isSafeImageUrl } from './security'

const INLINE_TOKEN_START = '\uE000'
const INLINE_TOKEN_END = '\uE001'

function imageTag(url, alt, className, withFallback = false) {
  const safeUrl = escapeHtml(url)
  const safeAlt = escapeHtml(alt)
  if (withFallback) {
    return `<img src="${safeUrl}" alt="${safeAlt}" class="${className}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='block'" />`
  }
  return `<img src="${safeUrl}" alt="${safeAlt}" class="${className}" loading="lazy" />`
}

function renderInline(rawText) {
  const tokens = []
  const token = (html) => {
    const key = `${INLINE_TOKEN_START}${tokens.length}${INLINE_TOKEN_END}`
    tokens.push(html)
    return key
  }

  // 行内代码优先占位，避免代码中的 Markdown 图片语法被当作 HTML 渲染。
  let text = String(rawText ?? '').replace(
    /`([^`]+)`/g,
    (_, code) => token(`<code class="inline-code">${escapeHtml(code)}</code>`),
  )

  text = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, rawUrl) => {
    const url = rawUrl.trim()
    if (!isSafeImageUrl(url)) return match
    return token(imageTag(url, alt, 'md-img-inline'))
  })

  // 剩余内容先整体转义，再做受控的强调语法替换。
  text = escapeHtml(text)
  text = text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')

  tokens.forEach((html, index) => {
    text = text.replace(`${INLINE_TOKEN_START}${index}${INLINE_TOKEN_END}`, html)
  })
  return text
}

function renderStandaloneImage(line) {
  const match = line.trim().match(/^!\[([^\]]*)\]\(([^)]+)\)$/)
  if (!match) return null

  const url = match[2].trim()
  if (!isSafeImageUrl(url)) {
    return `<p class="md-p">${escapeHtml(line)}</p>`
  }

  return `<div class="md-img-wrap">${imageTag(url, match[1], 'md-img', true)}<span class="md-img-error" style="display:none">⚠️ 图片加载失败</span></div>`
}

export function renderMarkdown(text) {
  if (!text) return ''

  // 代码块先提取，代码内容只做转义，不再参与 Markdown 或 HTML 解析。
  const codeBlocks = []
  let source = String(text).replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const safeCode = encodeURIComponent(code)
    const copySvg = `<svg class="copy-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 5H6C4.89543 5 4 5.89543 4 7V19C4 20.1046 4.89543 21 6 21H16C17.1046 21 18 20.1046 18 19V17M8 5C8 6.10457 8.89543 7 10 7H12C13.1046 7 14 6.10457 14 5M8 5C8 3.89543 8.89543 3 10 3H12C13.1046 3 14 3.89543 14 5M14 5H16C17.1046 5 18 5.89543 18 7V10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><rect x="14" y="14" width="6" height="6" rx="1" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
    const block = `
      <div class="code-block-wrapper">
        <div class="code-block-header">
          <span class="code-lang">${escapeHtml(lang || '')}</span>
          <button class="code-copy-btn" data-code="${safeCode}" title="复制代码">
            ${copySvg}
          </button>
        </div>
        <pre><code>${escapeHtml(code)}</code></pre>
      </div>
    `
    codeBlocks.push(block)
    return `%%CODE_BLOCK_${codeBlocks.length - 1}%%`
  })

  const lines = source.split('\n')
  const result = []
  let inList = false
  let listType = ''

  const closeList = () => {
    if (!inList) return
    result.push(listType === 'ul' ? '</ul>' : '</ol>')
    inList = false
  }

  for (const originalLine of lines) {
    let line = originalLine

    if (line.match(/%%CODE_BLOCK_\d+%%/)) {
      closeList()
      result.push(line)
      continue
    }

    if (/^---+$/.test(line.trim())) {
      closeList()
      result.push('<hr class="md-hr">')
      continue
    }

    const standaloneImage = renderStandaloneImage(line)
    if (standaloneImage !== null) {
      closeList()
      result.push(standaloneImage)
      continue
    }

    const h3 = line.match(/^### (.+)/)
    if (h3) {
      closeList()
      result.push(`<h4 class="md-h3">${renderInline(h3[1])}</h4>`)
      continue
    }

    const h2 = line.match(/^## (.+)/)
    if (h2) {
      closeList()
      result.push(`<h3 class="md-h2">${renderInline(h2[1])}</h3>`)
      continue
    }

    const h1 = line.match(/^# (.+)/)
    if (h1) {
      closeList()
      result.push(`<h2 class="md-h1">${renderInline(h1[1])}</h2>`)
      continue
    }

    const ul = line.match(/^[-*] (.+)/)
    if (ul) {
      if (!inList || listType !== 'ul') {
        closeList()
        result.push('<ul class="md-list">')
        inList = true
        listType = 'ul'
      }
      result.push(`<li>${renderInline(ul[1])}</li>`)
      continue
    }

    const ol = line.match(/^\d+\. (.+)/)
    if (ol) {
      if (!inList || listType !== 'ol') {
        closeList()
        result.push('<ol class="md-list">')
        inList = true
        listType = 'ol'
      }
      result.push(`<li>${renderInline(ol[1])}</li>`)
      continue
    }

    if (inList && line.trim() === '') {
      closeList()
    }

    if (line.trim()) {
      result.push(`<p class="md-p">${renderInline(line)}</p>`)
    } else if (!inList) {
      result.push('')
    }
  }
  closeList()

  let html = result.join('\n')
  codeBlocks.forEach((block, index) => {
    html = html.replace(`%%CODE_BLOCK_${index}%%`, block)
  })
  return html
}
