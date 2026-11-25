<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '请选择' },
  ariaLabel: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'change'])

const rootRef = ref(null)
const triggerRef = ref(null)
const optionRefs = ref([])
const open = ref(false)
const activeIndex = ref(-1)
const menuId = `dark-select-${Math.random().toString(36).slice(2, 9)}`

const normalizedOptions = computed(() => (
  (props.options || []).map((option) => (
    typeof option === 'string'
      ? { value: option, label: option }
      : {
          value: String(option?.value ?? ''),
          label: String(option?.label ?? option?.value ?? ''),
        }
  ))
))

const selectedIndex = computed(() => (
  normalizedOptions.value.findIndex((option) => option.value === props.modelValue)
))

const selectedLabel = computed(() => (
  normalizedOptions.value[selectedIndex.value]?.label || props.placeholder
))

function optionId(index) {
  return `${menuId}-option-${index}`
}

function setOptionRef(element, index) {
  if (element) optionRefs.value[index] = element
}

function scrollActiveIntoView() {
  optionRefs.value[activeIndex.value]?.scrollIntoView?.({ block: 'nearest' })
}

function openMenu() {
  if (props.disabled || open.value) return
  open.value = true
  activeIndex.value = selectedIndex.value >= 0 ? selectedIndex.value : 0
  nextTick(scrollActiveIntoView)
}

function closeMenu({ restoreFocus = false } = {}) {
  open.value = false
  activeIndex.value = -1
  if (restoreFocus) nextTick(() => triggerRef.value?.focus())
}

function toggleMenu() {
  if (open.value) closeMenu()
  else openMenu()
}

function moveActive(step) {
  if (!normalizedOptions.value.length) return
  const start = activeIndex.value < 0 ? 0 : activeIndex.value
  activeIndex.value = (
    start + step + normalizedOptions.value.length
  ) % normalizedOptions.value.length
  nextTick(scrollActiveIntoView)
}

function selectOption(option) {
  emit('update:modelValue', option.value)
  emit('change', option.value)
  closeMenu({ restoreFocus: true })
}

function selectActive() {
  const option = normalizedOptions.value[activeIndex.value]
  if (option) selectOption(option)
}

function handleKeydown(event) {
  if (props.disabled) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (open.value) moveActive(1)
    else openMenu()
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (open.value) moveActive(-1)
    else openMenu()
  } else if (event.key === 'Home' && open.value) {
    event.preventDefault()
    activeIndex.value = 0
    nextTick(scrollActiveIntoView)
  } else if (event.key === 'End' && open.value) {
    event.preventDefault()
    activeIndex.value = normalizedOptions.value.length - 1
    nextTick(scrollActiveIntoView)
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (open.value) selectActive()
    else openMenu()
  } else if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    closeMenu({ restoreFocus: true })
  } else if (event.key === 'Tab') {
    closeMenu()
  }
}

function handleOutsidePointer(event) {
  if (open.value && !rootRef.value?.contains(event.target)) {
    closeMenu()
  }
}

watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) closeMenu()
  },
)

watch(
  () => props.options,
  () => {
    if (!open.value) return
    activeIndex.value = Math.min(
      Math.max(activeIndex.value, 0),
      Math.max(normalizedOptions.value.length - 1, 0),
    )
  },
  { deep: true },
)

onMounted(() => {
  document.addEventListener('pointerdown', handleOutsidePointer)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', handleOutsidePointer)
})
</script>

<template>
  <div
    ref="rootRef"
    class="dark-select"
    :class="{ 'is-open': open, 'is-disabled': disabled }"
    @keydown="handleKeydown"
  >
    <button
      ref="triggerRef"
      type="button"
      class="dark-select-trigger"
      :aria-label="ariaLabel || undefined"
      :aria-expanded="open"
      aria-haspopup="listbox"
      :aria-controls="menuId"
      :aria-activedescendant="open && activeIndex >= 0 ? optionId(activeIndex) : undefined"
      :disabled="disabled"
      @click="toggleMenu"
    >
      <span class="dark-select-value">{{ selectedLabel }}</span>
      <span class="dark-select-chevron" aria-hidden="true">⌄</span>
    </button>

    <Transition name="dark-select-pop">
      <div v-if="open" :id="menuId" class="dark-select-menu" role="listbox">
        <button
          v-for="(option, index) in normalizedOptions"
          :id="optionId(index)"
          :key="`${option.value}-${index}`"
          :ref="(element) => setOptionRef(element, index)"
          type="button"
          class="dark-select-option"
          :class="{
            'is-active': index === activeIndex,
            'is-selected': option.value === modelValue,
          }"
          role="option"
          :aria-selected="option.value === modelValue"
          tabindex="-1"
          @mouseenter="activeIndex = index"
          @click="selectOption(option)"
        >
          <span>{{ option.label }}</span>
          <span v-if="option.value === modelValue" class="dark-select-check" aria-hidden="true">✓</span>
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.dark-select {
  position: relative;
  width: 100%;
  min-width: 0;
}

.dark-select-trigger {
  width: 100%;
  min-height: 38px;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  outline: none;
  transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
}

.dark-select-trigger:hover:not(:disabled),
.dark-select-trigger:focus-visible {
  border-color: rgba(102, 126, 234, 0.55);
  background: rgba(255, 255, 255, 0.09);
}

.dark-select.is-open .dark-select-trigger {
  border-color: rgba(102, 126, 234, 0.65);
  box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.12);
}

.dark-select-trigger:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.dark-select-value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dark-select-chevron {
  flex: 0 0 auto;
  color: var(--text-secondary);
  font-size: 14px;
  transition: transform 0.2s;
}

.dark-select.is-open .dark-select-chevron {
  transform: rotate(180deg);
}

.dark-select-menu {
  margin-top: 6px;
  padding: 4px;
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 10px;
  background: #20202c;
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.55);
}

.dark-select-option {
  width: 100%;
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: rgba(255, 255, 255, 0.82);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.dark-select-option.is-active {
  border-color: rgba(102, 126, 234, 0.3);
  background: rgba(102, 126, 234, 0.16);
  color: #fff;
}

.dark-select-option.is-selected {
  color: #c7d2fe;
  font-weight: 600;
}

.dark-select-check {
  color: #a5b4fc;
}

.dark-select-menu::-webkit-scrollbar {
  width: 5px;
}

.dark-select-menu::-webkit-scrollbar-thumb {
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.16);
}

.dark-select-pop-enter-active,
.dark-select-pop-leave-active {
  transition: opacity 0.14s ease, transform 0.14s ease;
  transform-origin: top;
}

.dark-select-pop-enter-from,
.dark-select-pop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.985);
}

@media (max-width: 720px) {
  .dark-select-trigger,
  .dark-select-option {
    min-height: 44px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .dark-select-trigger,
  .dark-select-chevron,
  .dark-select-pop-enter-active,
  .dark-select-pop-leave-active {
    transition: none;
  }
}
</style>
