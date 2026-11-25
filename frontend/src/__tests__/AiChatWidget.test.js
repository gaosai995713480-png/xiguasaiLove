import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive } from 'vue'
import { mount } from '@vue/test-utils'

const mockFetchWithAuth = vi.fn()
const authState = reactive({
  username: 'admin',
  isAdmin: false,
})

vi.mock('../api/index.js', () => ({
  fetchWithAuth: (...args) => mockFetchWithAuth(...args),
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('../stores/context', () => ({
  useContextStore: () => ({
    getFormattedContext: () => 'context',
  }),
}))

const flushPromises = async () => {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  }
}

function streamResponse(text, signal) {
  const encoded = new TextEncoder().encode(text)
  let readCount = 0
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => {
          if (signal?.aborted) {
            throw Object.assign(new Error('aborted'), { name: 'AbortError' })
          }
          if (readCount === 0) {
            readCount += 1
            return { done: false, value: encoded }
          }
          return { done: true, value: undefined }
        },
      }),
    },
  }
}

function pendingStreamResponse(signal) {
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: () => new Promise((_, reject) => {
          signal.addEventListener('abort', () => {
            reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
          }, { once: true })
        }),
      }),
    },
  }
}

let rafQueue = []
let rafId = 0

async function runAnimationFrames() {
  const start = performance.now()
  for (let frame = 0; frame < 30 && rafQueue.length; frame += 1) {
    const jobs = rafQueue
    rafQueue = []
    jobs.forEach(({ callback }) => callback(start + frame * 20))
    await flushPromises()
  }
}

async function mountWidget() {
  const { default: AiChatWidget } = await import('../components/AiChatWidget.vue')
  return mount(AiChatWidget, {
    global: {
      stubs: {
        Teleport: { template: '<div><slot /></div>' },
      },
    },
  })
}

const providerStatus = {
  claude: { available: true, model: 'claude' },
  codex: { available: true, model: 'codex' },
  glm: { available: true, model: 'glm' },
  grok: { available: true, model: 'grok' },
}

describe('AiChatWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    authState.username = 'admin'
    authState.isAdmin = false
    rafQueue = []
    rafId = 0
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback) => {
      rafId += 1
      rafQueue.push({ id: rafId, callback })
      return rafId
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn((id) => {
      rafQueue = rafQueue.filter((job) => job.id !== id)
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('切换 provider 后不会复用另一 provider 的 conversationId', async () => {
    let savedMessages = null
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(providerStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/conversations?provider=codex') {
        return jsonResponse([{ id: 11, title: 'Codex 会话' }])
      }
      if (url === '/api/ai/conversations/11/messages' && !options.method) {
        return jsonResponse({ messages: [{ role: 'user', content: '历史消息' }] })
      }
      if (url === '/api/ai/chat') {
        return streamResponse('data: "Claude回复"\n\ndata: [DONE]\n\n', options.signal)
      }
      if (url === '/api/ai/conversations' && options.method === 'POST') {
        return jsonResponse({ id: 22, title: '新对话', provider: 'claude' })
      }
      if (url === '/api/ai/conversations/22/messages' && options.method === 'POST') {
        savedMessages = JSON.parse(options.body)
        return jsonResponse({ ok: true })
      }
      if (url === '/api/ai/conversations/22/title') return jsonResponse({ ok: true })
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="对话历史"]').trigger('click')
    await flushPromises()
    await wrapper.find('.history-item').trigger('click')
    await flushPromises()

    const claudeTab = wrapper.findAll('.provider-tab').find((tab) => tab.text().includes('Claude'))
    await claudeTab.trigger('click')
    await wrapper.find('.chat-input').setValue('你好')
    await wrapper.find('.chat-send').trigger('click')
    await flushPromises()

    for (let i = 0; i < 20; i += 1) {
      await runAnimationFrames()
      await flushPromises()
    }

    await vi.waitFor(() => {
      expect(savedMessages).not.toBeNull()
    }, { timeout: 1000, interval: 10 })

    const postUrls = mockFetchWithAuth.mock.calls
      .filter(([, options]) => options?.method === 'POST')
      .map(([url]) => url)
    expect(postUrls).not.toContain('/api/ai/conversations/11/messages')
    expect(postUrls).toContain('/api/ai/conversations')
    expect(postUrls).toContain('/api/ai/conversations/22/messages')
    expect(wrapper.text()).toContain('Claude回复')
    expect(savedMessages).toEqual([
      { role: 'user', content: '你好' },
      { role: 'assistant', content: 'Claude回复' },
    ])

    wrapper.unmount()
  })

  it('停止生成会取消 typewriter RAF 并结束 loading', async () => {
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(providerStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/chat') return pendingStreamResponse(options.signal)
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('.chat-input').setValue('开始生成')
    await wrapper.find('.chat-send').trigger('click')
    await flushPromises()

    expect(wrapper.find('.chat-stop').exists()).toBe(true)
    expect(rafQueue.length).toBeGreaterThan(0)
    await wrapper.find('.chat-stop').trigger('click')
    await flushPromises()

    expect(cancelAnimationFrame).toHaveBeenCalled()
    expect(wrapper.find('.chat-stop').exists()).toBe(false)
    expect(wrapper.text()).toContain('已停止生成')

    wrapper.unmount()
  })

  it('已有 API Key 时无需重新输入即可保存模型配置', async () => {
    authState.isAdmin = true
    mockFetchWithAuth.mockImplementation(async (url) => {
      if (url === '/api/ai/status') return jsonResponse(providerStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/memory') return jsonResponse({ facts: [] })
      if (url === '/api/ai/config/agent') {
        return jsonResponse({ show_tool_process: true, max_tool_rounds: 5 })
      }
      if (url.startsWith('/api/ai/config/')) {
        return jsonResponse({
          base_url: 'https://api.example.com',
          model: 'model-a',
          api_key_configured: true,
          api_key_masked: 'sk-****',
        })
      }
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="配置"]').trigger('click')
    await flushPromises()

    const saveCodex = wrapper.findAll('button').find((button) => button.text().includes('保存 Codex'))
    expect(saveCodex).toBeTruthy()
    expect(saveCodex.attributes('disabled')).toBeUndefined()

    wrapper.unmount()
  })

  it('响应全局打开事件，声明 dialog 语义并同步 visualViewport 高度', async () => {
    mockFetchWithAuth.mockImplementation(async (url) => {
      if (url === '/api/ai/status') return jsonResponse(providerStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      return jsonResponse({})
    })
    vi.stubGlobal('visualViewport', {
      height: 512,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })

    const wrapper = await mountWidget()
    await flushPromises()
    window.dispatchEvent(new CustomEvent('ai-chat:open'))
    await nextTick()

    const panel = wrapper.get('.ai-chat-panel')
    expect(panel.attributes('role')).toBe('dialog')
    expect(panel.attributes('aria-modal')).toBe('true')
    expect(panel.attributes('tabindex')).toBe('-1')
    expect(panel.attributes('style')).toContain('--ai-viewport-height: 512px')
    expect(wrapper.findAll('.chat-header-actions button')).toHaveLength(4)
    expect(wrapper.get('[aria-label="关闭 AI 助手"]').exists()).toBe(true)

    await panel.trigger('keydown', { key: 'Escape' })
    await nextTick()
    expect(wrapper.find('.ai-chat-panel').exists()).toBe(false)

    wrapper.unmount()
  })

  it('删除历史对话前要求二次确认，取消时不会发删除请求', async () => {
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(providerStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/conversations?provider=codex') {
        return jsonResponse([{ id: 77, title: '待删除对话' }])
      }
      if (url === '/api/ai/conversations/77' && options.method === 'DELETE') {
        return jsonResponse({ ok: true })
      }
      return jsonResponse({})
    })
    const confirm = vi.spyOn(window, 'confirm')
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true)

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="对话历史"]').trigger('click')
    await flushPromises()

    await wrapper.find('.history-item-delete').trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(mockFetchWithAuth.mock.calls.some(([url, options]) => (
      url === '/api/ai/conversations/77' && options?.method === 'DELETE'
    ))).toBe(false)

    await wrapper.find('.history-item-delete').trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(2)
    expect(mockFetchWithAuth.mock.calls.some(([url, options]) => (
      url === '/api/ai/conversations/77' && options?.method === 'DELETE'
    ))).toBe(true)

    wrapper.unmount()
  })
})
