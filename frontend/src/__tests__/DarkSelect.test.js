import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import DarkSelect from '../components/DarkSelect.vue'

const options = [
  { value: 'responses', label: 'Responses API（默认）' },
  { value: 'chat_completions', label: 'Chat Completions' },
]

function mountSelect(modelValue = 'responses') {
  return mount(DarkSelect, {
    props: {
      modelValue,
      options,
      ariaLabel: '接口类型',
    },
    attachTo: document.body,
  })
}

describe('DarkSelect', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('点击选项后更新值并关闭', async () => {
    const wrapper = mountSelect()
    await wrapper.get('[aria-label="接口类型"]').trigger('click')

    const option = wrapper.findAll('.dark-select-option')
      .find((item) => item.text().includes('Chat Completions'))
    await option.trigger('click')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['chat_completions'])
    expect(wrapper.find('.dark-select-menu').exists()).toBe(false)

    wrapper.unmount()
  })

  it('支持上下键和 Enter 选择', async () => {
    const wrapper = mountSelect()
    const trigger = wrapper.get('[aria-label="接口类型"]')

    await trigger.trigger('keydown', { key: 'ArrowDown' })
    await trigger.trigger('keydown', { key: 'ArrowUp' })
    await trigger.trigger('keydown', { key: 'Enter' })

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['chat_completions'])
    expect(wrapper.find('.dark-select-menu').exists()).toBe(false)

    wrapper.unmount()
  })

  it('Escape 和外部点击会关闭菜单', async () => {
    const wrapper = mountSelect()
    const trigger = wrapper.get('[aria-label="接口类型"]')

    await trigger.trigger('click')
    expect(wrapper.find('.dark-select-menu').exists()).toBe(true)
    await trigger.trigger('keydown', { key: 'Escape' })
    await nextTick()
    expect(wrapper.find('.dark-select-menu').exists()).toBe(false)

    await trigger.trigger('click')
    expect(wrapper.find('.dark-select-menu').exists()).toBe(true)
    document.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.dark-select-menu').exists()).toBe(false)

    wrapper.unmount()
  })

  it('显示当前选项中文标签并支持留空', async () => {
    const wrapper = mountSelect('responses')
    expect(wrapper.get('[aria-label="接口类型"]').text()).toContain('Responses API（默认）')
    wrapper.unmount()

    const blankWrapper = mount(DarkSelect, {
      props: {
        modelValue: '',
        options: [{ value: '', label: '留空（由上游决定）' }, ...options],
        ariaLabel: '选择模型',
      },
    })
    expect(blankWrapper.get('[aria-label="选择模型"]').text()).toContain('留空（由上游决定）')
    blankWrapper.unmount()
  })
})
