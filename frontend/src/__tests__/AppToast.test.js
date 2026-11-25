import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from '@vue/test-utils'

const toast = reactive({
  visible: true,
  type: 'error',
  message: '保存失败',
})

vi.mock('../composables/useToast', () => ({
  useToast: () => ({ toast }),
}))

describe('AppToast', () => {
  beforeEach(() => {
    toast.visible = true
    toast.type = 'error'
    toast.message = '保存失败'
  })

  it('通过 status/live region 向辅助技术播报提示', async () => {
    const { default: AppToast } = await import('../components/AppToast.vue')
    const wrapper = mount(AppToast, {
      global: { stubs: { Transition: false } },
    })

    const element = wrapper.get('.app-toast')
    expect(element.attributes('role')).toBe('status')
    expect(element.attributes('aria-live')).toBe('polite')
    expect(element.attributes('aria-atomic')).toBe('true')
    expect(element.text()).toContain('保存失败')
  })
})
