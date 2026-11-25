import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive } from 'vue'
import { mount } from '@vue/test-utils'

const mockFetchWithAuth = vi.fn()
const authState = reactive({
  username: 'admin',
  isAdmin: false,
  user: null,
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

const aiStatus = {
  available: true,
  api_mode: 'responses',
}

describe('AiChatWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    authState.username = 'admin'
    authState.isAdmin = false
    authState.user = null
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

  it('使用统一 AI 接口，并能复用历史会话继续对话', async () => {
    let savedMessages = null
    let chatBody = null
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/conversations') {
        return jsonResponse([{ id: 11, title: 'AI 会话' }])
      }
      if (url === '/api/ai/conversations/11/messages' && !options.method) {
        return jsonResponse({
          messages: [
            { role: 'user', content: '历史消息' },
            { role: 'assistant', content: '历史回复' },
          ],
        })
      }
      if (url === '/api/ai/chat') {
        chatBody = JSON.parse(options.body)
        return streamResponse('data: "AI回复"\n\ndata: [DONE]\n\n', options.signal)
      }
      if (url === '/api/ai/conversations/11/messages' && options.method === 'POST') {
        savedMessages = JSON.parse(options.body)
        return jsonResponse({ ok: true })
      }
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="对话历史"]').trigger('click')
    await flushPromises()
    await wrapper.find('.history-item').trigger('click')
    await flushPromises()

    const assistantBrand = wrapper.get('.assistant-brand')
    expect(assistantBrand.text()).toContain('AI 助手')
    expect(assistantBrand.find('.status-dot').classes()).toContain('online')
    expect(wrapper.find('.provider-switcher').exists()).toBe(false)
    const historyRequest = mockFetchWithAuth.mock.calls.find(([url]) => (
      url === '/api/ai/conversations'
    ))
    expect(historyRequest).toBeTruthy()

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

    expect(chatBody).not.toHaveProperty('provider')
    expect(mockFetchWithAuth.mock.calls.every(([url]) => !String(url).includes('provider='))).toBe(true)
    expect(chatBody.skill_id).toBeNull()
    expect(wrapper.text()).toContain('AI回复')
    expect(savedMessages).toEqual([
      { role: 'user', content: '你好' },
      { role: 'assistant', content: 'AI回复' },
    ])
    expect(mockFetchWithAuth.mock.calls.some(([url, options]) => (
      url === '/api/ai/conversations' && options?.method === 'POST'
    ))).toBe(false)

    wrapper.unmount()
  })

  it('新建会话只提交标题', async () => {
    let createBody = null
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/conversations' && options.method === 'POST') {
        createBody = JSON.parse(options.body)
        return jsonResponse({ id: 22, title: '新对话' })
      }
      if (url === '/api/ai/conversations') return jsonResponse([])
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="对话历史"]').trigger('click')
    await flushPromises()
    await wrapper.find('.history-new-btn').trigger('click')
    await flushPromises()

    expect(createBody).toEqual({ title: '新对话' })

    wrapper.unmount()
  })

  it('停止生成会取消 typewriter RAF 并结束 loading', async () => {
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
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

  it('AI 接口配置支持默认 Responses、可选模型和 Chat Completions', async () => {
    authState.isAdmin = true
    let savedBody = null
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/memory') return jsonResponse({ facts: [] })
      if (url === '/api/ai/config/agent') {
        return jsonResponse({ show_tool_process: true, max_tool_rounds: 5 })
      }
      if (url === '/api/ai/config/model' && !options.method) {
        return jsonResponse({
          base_url: 'https://example.com/v1',
          api_key_configured: true,
          api_key_masked: 'sk-****',
          model: 'gpt-5.4-codex',
          api_mode: 'responses',
        })
      }
      if (url === '/api/ai/config/model' && options.method === 'POST') {
        savedBody = JSON.parse(options.body)
        return jsonResponse({ ok: true })
      }
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="配置"]').trigger('click')
    await flushPromises()

    const saveAI = wrapper.findAll('button').find((button) => button.text().includes('保存 AI 接口'))
    expect(saveAI).toBeTruthy()
    expect(saveAI.attributes('disabled')).toBeUndefined()
    const aiSection = wrapper.findAll('.config-section')
      .find((section) => section.text().includes('AI 接口'))
    expect(aiSection.findAll('label').map((label) => label.text())).toEqual([
      '接口类型',
      '请求地址',
      'API Key',
      '模型（可选）',
    ])
    const modeTrigger = aiSection.get('[aria-label="接口类型"]')
    expect(modeTrigger.text()).toContain('Responses API（默认）')
    const modelInput = aiSection.findAll('input').find((input) => (
      input.element.placeholder === '留空则由上游决定'
    ))
    expect(modelInput.element.value).toBe('gpt-5.4-codex')

    await modelInput.setValue('')
    await saveAI.trigger('click')
    await flushPromises()

    expect(savedBody).toEqual({
      base_url: 'https://example.com/v1',
      api_key: '',
      model: '',
      api_mode: 'responses',
    })

    await wrapper.get('[aria-label="接口类型"]').trigger('click')
    const chatOption = wrapper.findAll('.dark-select-option')
      .find((option) => option.text().includes('Chat Completions'))
    await chatOption.trigger('click')
    await flushPromises()
    await saveAI.trigger('click')
    await flushPromises()
    expect(savedBody.api_mode).toBe('chat_completions')

    wrapper.unmount()
  })

  it('可以获取可用模型并选择后保存', async () => {
    authState.isAdmin = true
    let modelsBody = null
    let savedBody = null
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/memory') return jsonResponse({ facts: [] })
      if (url === '/api/ai/config/agent') {
        return jsonResponse({ show_tool_process: true, max_tool_rounds: 5 })
      }
      if (url === '/api/ai/config/model' && !options.method) {
        return jsonResponse({
          base_url: 'https://example.com/v1',
          api_key_configured: true,
          api_key_masked: 'sk-****',
          model: '',
          api_mode: 'responses',
        })
      }
      if (url === '/api/ai/models' && options.method === 'POST') {
        modelsBody = JSON.parse(options.body)
        return jsonResponse({
          models: ['grok-4.20-fast', 'gpt-5.4-codex'],
        })
      }
      if (url === '/api/ai/config/model' && options.method === 'POST') {
        savedBody = JSON.parse(options.body)
        return jsonResponse({ ok: true })
      }
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="配置"]').trigger('click')
    await flushPromises()

    const fetchModels = wrapper.findAll('button')
      .find((button) => button.text().includes('获取模型'))
    expect(fetchModels.attributes('disabled')).toBeUndefined()
    await fetchModels.trigger('click')
    await flushPromises()

    expect(modelsBody).toEqual({
      base_url: 'https://example.com/v1',
      api_key: '',
    })
    expect(wrapper.get('[aria-label="选择模型"]').text()).toContain('留空（由上游决定）')
    await wrapper.get('[aria-label="选择模型"]').trigger('click')
    const modelOption = wrapper.findAll('.dark-select-option')
      .find((option) => option.text().includes('grok-4.20-fast'))
    await modelOption.trigger('click')
    await flushPromises()

    await wrapper.findAll('button')
      .find((button) => button.text().includes('保存 AI 接口'))
      .trigger('click')
    await flushPromises()

    expect(savedBody.model).toBe('grok-4.20-fast')

    wrapper.unmount()
  })

  it('获取模型失败时展示后端错误', async () => {
    authState.isAdmin = true
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/memory') return jsonResponse({ facts: [] })
      if (url === '/api/ai/config/agent') {
        return jsonResponse({ show_tool_process: true, max_tool_rounds: 5 })
      }
      if (url === '/api/ai/config/model' && !options.method) {
        return jsonResponse({
          base_url: 'https://example.com/v1',
          api_key_configured: true,
          model: '',
          api_mode: 'responses',
        })
      }
      if (url === '/api/ai/models' && options.method === 'POST') {
        return jsonResponse({ detail: '模型接口返回 502' }, 502)
      }
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="配置"]').trigger('click')
    await flushPromises()
    await wrapper.findAll('button')
      .find((button) => button.text().includes('获取模型'))
      .trigger('click')
    await flushPromises()

    expect(wrapper.get('.config-error').text()).toContain('模型接口返回 502')

    wrapper.unmount()
  })

  it('缺少 API Key 时禁用获取模型按钮', async () => {
    authState.isAdmin = true
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/memory') return jsonResponse({ facts: [] })
      if (url === '/api/ai/config/agent') {
        return jsonResponse({ show_tool_process: true, max_tool_rounds: 5 })
      }
      if (url === '/api/ai/config/model' && !options.method) {
        return jsonResponse({
          base_url: 'https://example.com/v1',
          api_key_configured: false,
          model: '',
          api_mode: 'responses',
        })
      }
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="配置"]').trigger('click')
    await flushPromises()

    const fetchModels = wrapper.findAll('button')
      .find((button) => button.text().includes('获取模型'))
    expect(fetchModels.attributes('disabled')).toBeDefined()

    await wrapper.findAll('input')
      .find((input) => input.element.type === 'password')
      .setValue('sk-test')
    expect(fetchModels.attributes('disabled')).toBeUndefined()

    wrapper.unmount()
  })

  it('获取模型期间显示加载态，空列表保留手动输入', async () => {
    authState.isAdmin = true
    let resolveModels
    const modelsResponse = new Promise((resolve) => {
      resolveModels = resolve
    })
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/memory') return jsonResponse({ facts: [] })
      if (url === '/api/ai/config/agent') {
        return jsonResponse({ show_tool_process: true, max_tool_rounds: 5 })
      }
      if (url === '/api/ai/config/model' && !options.method) {
        return jsonResponse({
          base_url: 'https://example.com/v1',
          api_key_configured: true,
          model: '',
          api_mode: 'responses',
        })
      }
      if (url === '/api/ai/models' && options.method === 'POST') {
        return modelsResponse
      }
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="配置"]').trigger('click')
    await flushPromises()

    const fetchModels = wrapper.findAll('button')
      .find((button) => button.text().includes('获取模型'))
    await fetchModels.trigger('click')
    await flushPromises()
    const loadingButton = wrapper.findAll('button')
      .find((button) => button.text().includes('获取中...'))
    expect(loadingButton.attributes('disabled')).toBeDefined()

    resolveModels(jsonResponse({ models: [] }))
    await flushPromises()

    expect(wrapper.find('[aria-label="选择模型"]').exists()).toBe(false)
    const manualModel = wrapper.findAll('input')
      .find((input) => input.element.placeholder === '留空则由上游决定')
    expect(manualModel.exists()).toBe(true)
    expect(wrapper.get('.config-error').text()).toContain('未获取到可用模型')

    wrapper.unmount()
  })

  it('AI 接口保存失败时展示后端错误', async () => {
    authState.isAdmin = true
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/memory') return jsonResponse({ facts: [] })
      if (url === '/api/ai/config/agent') {
        return jsonResponse({ show_tool_process: true, max_tool_rounds: 5 })
      }
      if (url === '/api/ai/config/model' && !options.method) {
        return jsonResponse({
          base_url: 'https://example.com/v1',
          api_key_configured: true,
          model: '',
          api_mode: 'responses',
        })
      }
      if (url === '/api/ai/config/model' && options.method === 'POST') {
        return jsonResponse({ detail: '请求地址无效' }, 400)
      }
      return jsonResponse({})
    })

    const wrapper = await mountWidget()
    await flushPromises()
    await wrapper.find('.ai-fab').trigger('click')
    await wrapper.find('[title="配置"]').trigger('click')
    await flushPromises()
    await wrapper.findAll('button')
      .find((button) => button.text().includes('保存 AI 接口'))
      .trigger('click')
    await flushPromises()

    expect(wrapper.get('.config-error').text()).toContain('请求地址无效')

    wrapper.unmount()
  })

  it('悬浮模式点击按钮后声明 dialog 语义并同步 visualViewport 高度', async () => {
    mockFetchWithAuth.mockImplementation(async (url) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
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
    await wrapper.find('.ai-fab').trigger('click')
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

  it('embedded 模式不渲染 FAB 和关闭按钮，返回只触发事件且面板保持渲染', async () => {
    mockFetchWithAuth.mockImplementation(async (url) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      return jsonResponse({})
    })

    const { default: AiChatWidget } = await import('../components/AiChatWidget.vue')
    const wrapper = mount(AiChatWidget, {
      props: { embedded: true },
      attachTo: document.body,
    })
    await flushPromises()

    expect(wrapper.find('.ai-fab').exists()).toBe(false)
    const panel = wrapper.get('.ai-chat-panel')
    expect(panel.classes()).toContain('is-embedded')
    expect(panel.attributes('role')).toBe('region')
    expect(panel.attributes('aria-modal')).toBeUndefined()
    expect(wrapper.find('.chat-header-close').exists()).toBe(false)
    expect(wrapper.get('.chat-header-back').text()).toContain('返回')

    await wrapper.get('.chat-header-back').trigger('click')
    expect(wrapper.emitted('back')).toHaveLength(1)
    expect(wrapper.find('.ai-chat-panel').exists()).toBe(true)

    wrapper.unmount()
  })

  it('删除历史对话前要求二次确认，取消时不会发删除请求', async () => {
    mockFetchWithAuth.mockImplementation(async (url, options = {}) => {
      if (url === '/api/ai/status') return jsonResponse(aiStatus)
      if (url === '/api/ai/skills') return jsonResponse([])
      if (url === '/api/ai/conversations') {
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
