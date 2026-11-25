<script>
let nextTopBarId = 0
let activeTopBarId = 0
</script>

<script setup>
import { getCurrentInstance, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ThemeSwitcher from './ThemeSwitcher.vue'

const props = defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  showBack: { type: Boolean, default: true },
  showTheme: { type: Boolean, default: true },
})

const emit = defineEmits(['back'])
const router = useRouter()
const instance = getCurrentInstance()
const barRef = ref(null)
const topBarId = ++nextTopBarId
let resizeObserver = null

function updateActualHeight() {
  const height = barRef.value?.getBoundingClientRect().height
  if (!height) return
  document.documentElement.style.setProperty('--topbar-actual-height', `${Math.ceil(height)}px`)
}

onMounted(async () => {
  activeTopBarId = topBarId
  await nextTick()
  updateActualHeight()

  if (typeof ResizeObserver !== 'undefined' && barRef.value) {
    resizeObserver = new ResizeObserver(updateActualHeight)
    resizeObserver.observe(barRef.value)
  }
  window.addEventListener('resize', updateActualHeight)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', updateActualHeight)

  if (activeTopBarId === topBarId) {
    activeTopBarId = 0
    document.documentElement.style.removeProperty('--topbar-actual-height')
  }
})

watch(
  () => [props.title, props.subtitle],
  async () => {
    await nextTick()
    updateActualHeight()
  },
)

function hasCustomBackListener() {
  const listener = instance?.vnode?.props?.onBack
  return typeof listener === 'function' || Array.isArray(listener)
}

function handleBack() {
  emit('back')
  if (hasCustomBackListener()) return
  if (router?.back) {
    router.back()
    return
  }
  if (window.history.length > 1) {
    window.history.back()
    return
  }
  window.location.assign('/')
}
</script>

<template>
  <div ref="barRef" class="top-bar">
    <a v-if="showBack" class="back-btn" @click.prevent="handleBack" href="#">← 返回</a>
    <div class="title-block">
      <h1>{{ title }}</h1>
      <p v-if="subtitle" class="subtitle">{{ subtitle }}</p>
    </div>
    <slot />
    <ThemeSwitcher v-if="showTheme" />
  </div>
</template>

<style scoped>
.top-bar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: var(--topbar-height);
  padding: calc(10px + var(--safe-top)) calc(20px + var(--safe-right)) 10px calc(20px + var(--safe-left));
  background: var(--glass-bg);
  backdrop-filter: blur(30px);
  border-bottom: 1px solid var(--glass-border);
}

.back-btn {
  text-decoration: none;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  padding: 8px 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  transition: all 0.2s ease;
  cursor: pointer;
}

.back-btn:hover {
  background: rgba(255, 255, 255, 0.18);
  transform: translateY(-1px);
}

.title-block {
  min-width: 0;
}

h1 {
  font-size: 18px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.subtitle {
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 720px) {
  .top-bar {
    padding: calc(8px + var(--safe-top)) calc(12px + var(--safe-right)) 8px calc(12px + var(--safe-left));
    gap: 8px;
    flex-wrap: wrap;
  }

  .back-btn {
    font-size: 13px;
    padding: 8px 12px;
    border-radius: 8px;
    flex-shrink: 0;
    min-height: var(--touch-min);
    display: inline-flex;
    align-items: center;
  }

  h1 {
    font-size: 15px;
  }
}
</style>
