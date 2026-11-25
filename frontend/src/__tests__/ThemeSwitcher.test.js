import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import ThemeSwitcher from '../components/ThemeSwitcher.vue'
import { clickOutside } from '../directives/clickOutside'
import { useThemeStore } from '../stores/theme'

let wrapper = null

function mountSwitcher() {
  return mount(ThemeSwitcher, {
    attachTo: document.body,
    global: { directives: { 'click-outside': clickOutside } },
  })
}

describe('ThemeSwitcher', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ''
  })

  it('触发按钮和主题项使用可访问的 button 语义', async () => {
    wrapper = mountSwitcher()
    const trigger = wrapper.get('.ts-btn')

    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(wrapper.get('.ts-dropdown').attributes('aria-hidden')).toBe('true')
    expect(wrapper.get('.ts-dropdown').attributes('inert')).toBeDefined()

    await trigger.trigger('click')

    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('.ts-dropdown').attributes('inert')).toBeUndefined()
    const swatches = wrapper.findAll('button.ts-swatch')
    expect(swatches).toHaveLength(13)
    expect(swatches[0].attributes('aria-label')).toContain('切换主题')
  })

  it('选择主题后更新 store、收起菜单并把焦点还给触发按钮', async () => {
    wrapper = mountSwitcher()
    const store = useThemeStore()

    await wrapper.get('.ts-btn').trigger('click')
    await wrapper.findAll('button.ts-swatch')[1].trigger('click')
    await nextTick()

    expect(store.currentName).toBe('夏')
    expect(wrapper.get('.ts-btn').attributes('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(wrapper.get('.ts-btn').element)
  })
})
