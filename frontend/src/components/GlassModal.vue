<script>
let bodyLockCount = 0
let bodyLockState = null

function lockBodyScroll() {
  bodyLockCount += 1
  if (bodyLockCount > 1 || typeof document === 'undefined') return

  const body = document.body
  const scrollbarWidth = Math.max(0, window.innerWidth - document.documentElement.clientWidth)
  bodyLockState = {
    x: window.scrollX,
    y: window.scrollY,
    overflow: body.style.overflow,
    position: body.style.position,
    top: body.style.top,
    left: body.style.left,
    width: body.style.width,
    paddingRight: body.style.paddingRight,
  }

  body.style.overflow = 'hidden'
  body.style.position = 'fixed'
  body.style.top = `-${bodyLockState.y}px`
  body.style.left = '0'
  body.style.width = '100%'
  if (scrollbarWidth > 0) body.style.paddingRight = `${scrollbarWidth}px`
}

function unlockBodyScroll() {
  bodyLockCount = Math.max(0, bodyLockCount - 1)
  if (bodyLockCount > 0 || !bodyLockState || typeof document === 'undefined') return

  const body = document.body
  const state = bodyLockState
  bodyLockState = null
  body.style.overflow = state.overflow
  body.style.position = state.position
  body.style.top = state.top
  body.style.left = state.left
  body.style.width = state.width
  body.style.paddingRight = state.paddingRight
  window.scrollTo(state.x, state.y)
}
</script>

<script setup>
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])
const modalRef = ref(null)
const titleId = useId()
let previousActiveElement = null
let bodyLocked = false

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function focusElement(element) {
  try {
    element?.focus({ preventScroll: true })
  } catch {
    element?.focus()
  }
}

function getFocusableElements() {
  if (!modalRef.value) return []
  return [...modalRef.value.querySelectorAll(FOCUSABLE_SELECTOR)].filter(
    element => element.getAttribute('aria-hidden') !== 'true' && !element.closest('[inert]'),
  )
}

function close() {
  emit('update:modelValue', false)
}

function onBackdropClick(event) {
  if (event.target === event.currentTarget) close()
}

function onDocumentKeydown(event) {
  if (!props.modelValue) return

  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }

  if (event.key !== 'Tab') return
  const focusable = getFocusableElements()
  if (focusable.length === 0) {
    event.preventDefault()
    focusElement(modalRef.value)
    return
  }

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement
  if (active === modalRef.value) {
    event.preventDefault()
    focusElement(event.shiftKey ? last : first)
  } else if (event.shiftKey && (active === first || !modalRef.value?.contains(active))) {
    event.preventDefault()
    focusElement(last)
  } else if (!event.shiftKey && (active === last || !modalRef.value?.contains(active))) {
    event.preventDefault()
    focusElement(first)
  }
}

function releaseModal() {
  document.removeEventListener('keydown', onDocumentKeydown)
  if (bodyLocked) {
    bodyLocked = false
    unlockBodyScroll()
  }

  const target = previousActiveElement
  previousActiveElement = null
  if (target?.isConnected) {
    nextTick(() => focusElement(target))
  }
}

watch(
  () => props.modelValue,
  async (isOpen) => {
    if (!isOpen) {
      releaseModal()
      return
    }

    previousActiveElement = document.activeElement
    bodyLocked = true
    lockBodyScroll()
    document.addEventListener('keydown', onDocumentKeydown)
    await nextTick()

    const autofocusTarget = modalRef.value?.querySelector('[autofocus]')
    focusElement(autofocusTarget || modalRef.value)
  },
  { immediate: true },
)

onBeforeUnmount(releaseModal)
</script>

<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div
        v-if="modelValue"
        class="modal-backdrop"
        @click="onBackdropClick"
      >
        <div
          ref="modalRef"
          class="modal-card"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="title ? titleId : undefined"
          :aria-label="title ? undefined : '对话框'"
          tabindex="-1"
        >
          <h2 v-if="title" :id="titleId">{{ title }}</h2>
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.58);
  z-index: 300;
  display: flex;
  align-items: center;
  justify-content: center;
  overscroll-behavior: contain;
}

.modal-card {
  width: 92%;
  max-width: 480px;
  max-height: min(85dvh, calc(100dvh - var(--safe-top) - var(--safe-bottom) - 24px));
  overflow-y: auto;
  overscroll-behavior: contain;
  background: rgba(30, 30, 50, 0.98);
  backdrop-filter: blur(40px);
  border: 1px solid var(--glass-border);
  border-radius: 24px;
  padding: 28px 24px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.55);
  outline: none;
}

h2 {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 20px;
  text-align: center;
}

.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.2s ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}

@media (max-width: 720px) {
  .modal-backdrop {
    align-items: flex-end;
  }

  .modal-card {
    width: 100%;
    max-width: none;
    padding: 22px 16px calc(16px + var(--safe-bottom));
    border-radius: 20px 20px 0 0;
    max-height: calc(100dvh - var(--safe-top) - 12px);
  }

  h2 {
    font-size: 17px;
    margin-bottom: 16px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .modal-fade-enter-active,
  .modal-fade-leave-active {
    transition: none;
  }
}
</style>
