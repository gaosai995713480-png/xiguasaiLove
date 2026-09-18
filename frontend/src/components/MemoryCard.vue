<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { dayApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { formatDayTitle } from '../utils/dayDate'

const TOGETHER_START = '2023-10-26'

const router = useRouter()
const authStore = useAuthStore()

const loading = ref(true)
const enabled = ref(true)
const memory = ref(null)
const toggling = ref(false)

const subtitle = computed(() => {
  const item = memory.value
  if (!item) return ''
  if (item.mood_emoji && item.mood_note) return `${item.mood_emoji} ${item.mood_note}`
  if (item.mood_emoji) return item.mood_emoji
  if (item.story_title) return item.story_title
  if (item.place_title) return item.place_title
  if (item.has_photos) return '那天留下了照片'
  return '那天留下了痕迹'
})

const togetherLabel = computed(() => {
  const item = memory.value
  if (!item?.date) return ''
  const start = new Date(`${TOGETHER_START}T00:00:00`)
  const day = new Date(`${item.date}T00:00:00`)
  const diff = Math.floor((day - start) / (1000 * 60 * 60 * 24))
  if (diff < 0) return ''
  return `在一起的第 ${diff + 1} 天`
})

const showSection = computed(() => {
  if (authStore.isAdmin) return true
  return enabled.value && Boolean(memory.value)
})

async function load() {
  loading.value = true
  try {
    const data = await dayApi.memory()
    enabled.value = data.enabled !== false
    memory.value = data.memory || null
  } catch {
    enabled.value = true
    memory.value = null
  } finally {
    loading.value = false
  }
}

async function toggle() {
  if (toggling.value) return
  toggling.value = true
  const next = !enabled.value
  try {
    const data = await dayApi.setMemory(next)
    enabled.value = data.enabled
    if (enabled.value) {
      await load()
    } else {
      memory.value = null
    }
  } catch {
    /* API 层已提示 */
  } finally {
    toggling.value = false
  }
}

function openDay() {
  if (!memory.value?.date) return
  router.push(`/day/${memory.value.date}`)
}

onMounted(load)
</script>

<template>
  <section v-if="showSection" class="memory-section" data-test="random-memory">
    <div class="memory-head">
      <h3>随机回忆</h3>
      <button
        v-if="authStore.isAdmin"
        type="button"
        class="memory-toggle"
        :aria-pressed="enabled ? 'true' : 'false'"
        :disabled="toggling"
        :title="enabled ? '关闭后首页不再展示随机回忆' : '开启后登录首页会看到随机一天'"
        @click="toggle"
      >
        {{ enabled ? '已开启' : '已关闭' }}
      </button>
    </div>

    <button
      v-if="enabled && memory"
      type="button"
      class="memory-card"
      @click="openDay"
    >
      <img
        v-if="memory.cover_url"
        class="memory-cover"
        :src="memory.cover_url"
        :alt="memory.story_title || memory.place_title || '那天的照片'"
      />
      <div class="memory-body">
        <p class="memory-date">{{ formatDayTitle(memory.date) }}</p>
        <p v-if="togetherLabel" class="memory-together">{{ togetherLabel }}</p>
        <p class="memory-sub">{{ subtitle }}</p>
      </div>
    </button>

    <p v-else-if="authStore.isAdmin && !enabled" class="memory-hint">关闭后，登录首页不再展示随机一天。</p>
    <p v-else-if="authStore.isAdmin && enabled && !loading && !memory" class="memory-hint">还没有可以回忆的日子。</p>
  </section>
</template>

<style scoped>
.memory-section {
  margin: 8px auto 28px;
  max-width: 420px;
  text-align: left;
}

.memory-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.memory-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.memory-toggle {
  min-width: var(--touch-min, 44px);
  min-height: var(--touch-min, 44px);
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--glass-border);
  background: rgba(255, 255, 255, 0.12);
  color: inherit;
  font-size: 13px;
  cursor: pointer;
}

.memory-toggle[aria-pressed="false"] {
  opacity: 0.7;
}

.memory-card {
  width: 100%;
  display: flex;
  gap: 14px;
  align-items: stretch;
  padding: 12px;
  border: 1px solid var(--glass-border);
  border-radius: 16px;
  background: var(--glass-bg);
  backdrop-filter: blur(20px);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.memory-cover {
  width: 88px;
  height: 88px;
  object-fit: cover;
  border-radius: 12px;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.08);
}

.memory-body {
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
}

.memory-date {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
}

.memory-together,
.memory-sub,
.memory-hint {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
  margin: 0;
}

.memory-sub {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

@media (max-width: 720px) {
  .memory-section {
    margin-left: 0;
    margin-right: 0;
    max-width: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .memory-card,
  .memory-toggle {
    transition: none;
  }
}
</style>
