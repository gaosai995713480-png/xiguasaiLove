import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const mockPush = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}))

function mountView() {
  return import('../views/AssistantView.vue').then(({ default: AssistantView }) => mount(AssistantView, {
    global: {
      stubs: {
        TopBar: { template: '<div class="top-bar-stub"><slot /></div>' },
        AiChatWidget: {
          props: { embedded: Boolean },
          emits: ['back'],
          template: `
            <button
              class="assistant-widget-stub"
              :data-embedded="String(embedded)"
              @click="$emit('back')"
            >AI</button>
          `,
        },
      },
    },
  }))
}

describe('AssistantView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('以 embedded 模式挂载唯一 AI 组件并处理返回', async () => {
    const wrapper = await mountView()

    const widget = wrapper.get('.assistant-widget-stub')
    expect(widget.attributes('data-embedded')).toBe('true')

    await widget.trigger('click')
    expect(mockPush).toHaveBeenCalledWith('/')

    wrapper.unmount()
  })
})
