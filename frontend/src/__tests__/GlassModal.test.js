import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import GlassModal from '../components/GlassModal.vue'

let wrapper = null

async function flushUi() {
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

describe('GlassModal', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'scrollY', {
      configurable: true,
      value: 240,
    })
    vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    document.body.style.cssText = ''
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.style.cssText = ''
    vi.restoreAllMocks()
  })

  it('关闭时不渲染对话框，打开后锁滚动并聚焦第一个控件', async () => {
    wrapper = mount(GlassModal, {
      props: {
        modelValue: false,
        title: '歌曲设置',
      },
      attachTo: document.body,
      slots: {
        default: '<button class="first-action">保存</button><button class="last-action">取消</button>',
      },
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' },
          Transition: false,
        },
      },
    })

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)

    await wrapper.setProps({ modelValue: true })
    await flushUi()

    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(dialog.attributes('aria-labelledby')).toBeTruthy()
    expect(document.body.style.position).toBe('fixed')
    expect(document.body.style.top).toBe('-240px')
    expect(document.body.style.overflow).toBe('hidden')
    expect(document.activeElement).toBe(dialog.element)

    const buttons = wrapper.findAll('button')
    document.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Tab',
      bubbles: true,
      cancelable: true,
    }))
    expect(document.activeElement).toBe(buttons[0].element)

    buttons[1].element.focus()
    document.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Tab',
      bubbles: true,
      cancelable: true,
    }))
    expect(document.activeElement).toBe(buttons[0].element)
  })

  it('支持 Escape 关闭，并恢复 body 样式与 scrollY', async () => {
    wrapper = mount(GlassModal, {
      props: {
        modelValue: false,
        title: '确认操作',
      },
      attachTo: document.body,
      slots: {
        default: '<button>确定</button>',
      },
      global: {
        stubs: {
          Teleport: { template: '<div><slot /></div>' },
          Transition: false,
        },
      },
    })

    await wrapper.setProps({ modelValue: true })
    await flushUi()

    document.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Escape',
      bubbles: true,
      cancelable: true,
    }))
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([false])

    await wrapper.setProps({ modelValue: false })
    await flushUi()

    expect(document.body.style.position).toBe('')
    expect(document.body.style.top).toBe('')
    expect(document.body.style.overflow).toBe('')
    expect(window.scrollTo).toHaveBeenCalledWith(0, 240)
  })
})
