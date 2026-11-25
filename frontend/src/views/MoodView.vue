<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import TopBar from '../components/TopBar.vue'
import GlassModal from '../components/GlassModal.vue'
import { moodApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { todayInShanghai } from '../utils/dayDate'

const router = useRouter()
const authStore = useAuthStore()
const MOODS = ['😆', '😊', '😌', '😐', '😢', '😤', '🥰', '😴', '🤔', '🎉']
const LEVEL_LABELS = ['低落', '一般', '还行', '开心', '超开心']

const currentYear = ref(new Date().getFullYear())
const currentMonth = ref(new Date().getMonth() + 1)
const moodData = ref({})
const showModal = ref(false)
const selectedDate = ref('')
const selectedEmoji = ref('😊')
const selectedLevel = ref(3)
const noteInput = ref('')
const loadError = ref('')
const monthLoading = ref(false)
let monthRequestId = 0

const weekdays = ['日', '一', '二', '三', '四', '五', '六']

async function loadMonth() {
  const requestId = ++monthRequestId
  const year = currentYear.value
  const month = currentMonth.value
  monthLoading.value = true
  loadError.value = ''
  try {
    const items = await moodApi.list(year, month)
    if (requestId !== monthRequestId) return
    const map = {}
    items.forEach(item => { map[item.mood_date] = item })
    moodData.value = map
  } catch (error) {
    if (requestId !== monthRequestId) return
    moodData.value = {}
    loadError.value = error?.message || '心情记录加载失败，请重试'
  } finally {
    if (requestId === monthRequestId) monthLoading.value = false
  }
}

function getCalendarDays() {
  const firstDay = new Date(currentYear.value, currentMonth.value - 1, 1).getDay()
  const daysInMonth = new Date(currentYear.value, currentMonth.value, 0).getDate()
  const today = todayInShanghai()
  const days = []
  for (let i = 0; i < firstDay; i++) days.push({ empty: true })
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${currentYear.value}-${String(currentMonth.value).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    const mood = moodData.value[dateStr]
    days.push({ day: d, dateStr, isToday: dateStr === today, mood })
  }
  return days
}

function getStats() {
  const entries = Object.values(moodData.value)
  const count = entries.length
  const avgLevel = count ? (entries.reduce((s, e) => s + e.level, 0) / count).toFixed(1) : '-'
  const emojiCount = {}
  entries.forEach(e => { emojiCount[e.emoji] = (emojiCount[e.emoji] || 0) + 1 })
  const topEmoji = Object.entries(emojiCount).sort((a, b) => b[1] - a[1])[0]
  return { count, avgLevel, topEmoji, avgLabel: count ? LEVEL_LABELS[Math.round(avgLevel) - 1] || '' : '' }
}

function openPicker(dateStr, existing) {
  if (!authStore.isAdmin) return
  selectedDate.value = dateStr
  selectedEmoji.value = existing ? existing.emoji : '😊'
  selectedLevel.value = existing ? existing.level : 3
  noteInput.value = existing ? (existing.note || '') : ''
  showModal.value = true
}

async function save() {
  if (!authStore.isAdmin) return
  try {
    await moodApi.save({ mood_date: selectedDate.value, emoji: selectedEmoji.value, note: noteInput.value, level: selectedLevel.value })
    showModal.value = false
    loadMonth()
  } catch { alert('保存失败') }
}

function onDayClick(cell) {
  if (cell.empty) return
  if (authStore.isAdmin) {
    openPicker(cell.dateStr, cell.mood)
  } else {
    router.push(`/day/${cell.dateStr}`)
  }
}

function prevMonth() {
  currentMonth.value--
  if (currentMonth.value < 1) { currentMonth.value = 12; currentYear.value-- }
  loadMonth()
}

function nextMonth() {
  currentMonth.value++
  if (currentMonth.value > 12) { currentMonth.value = 1; currentYear.value++ }
  loadMonth()
}

onMounted(loadMonth)
onUnmounted(() => {
  monthRequestId += 1
})
</script>

<template>
  <TopBar title="😊 心情日历" @back="router.push('/')" />

  <div class="container">
    <!-- Stats -->
    <div class="stats" v-if="!loadError && !monthLoading">
      <div class="stat-card"><div class="label">打卡天数</div><div class="value">{{ getStats().count }}</div></div>
      <div class="stat-card"><div class="label">平均心情</div><div class="value">{{ getStats().avgLevel }}</div><div class="sub">{{ getStats().avgLabel }}</div></div>
      <div class="stat-card"><div class="label">最常心情</div><div class="value">{{ getStats().topEmoji ? getStats().topEmoji[0] : '-' }}</div><div class="sub">{{ getStats().topEmoji ? getStats().topEmoji[1] + '次' : '' }}</div></div>
    </div>

    <!-- Calendar Header -->
    <div class="cal-header">
      <button @click="prevMonth">‹</button>
      <span class="month-label">{{ currentYear }}年{{ currentMonth }}月</span>
      <button @click="nextMonth">›</button>
    </div>

    <div v-if="loadError" class="month-state is-error" role="alert">
      <p>{{ currentYear }}年{{ currentMonth }}月心情记录加载失败：{{ loadError }}</p>
      <button type="button" class="retry-btn" @click="loadMonth">重试</button>
    </div>
    <div v-else-if="monthLoading" class="month-state" role="status">正在加载本月心情…</div>

    <!-- Calendar Grid -->
    <div v-else class="cal-grid">
      <div v-for="w in weekdays" :key="w" class="weekday">{{ w }}</div>
      <div
        v-for="(cell, i) in getCalendarDays()"
        :key="i"
        class="cal-day"
        :class="{
          'is-empty': cell.empty,
          'is-today': cell.isToday,
          'has-mood': cell.mood,
          [`level-${cell.mood?.level}`]: cell.mood,
        }"
        @click="onDayClick(cell)"
      >
        <span v-if="cell.mood" class="emoji">{{ cell.mood.emoji }}</span>
        <span class="day-num" :style="{ fontSize: cell.mood ? '11px' : '14px' }">{{ cell.day }}</span>
      </div>
    </div>
  </div>

  <!-- Mood Picker Modal -->
  <GlassModal v-if="authStore.isAdmin" v-model="showModal" title="今天心情如何？">
    <div class="date-info">{{ selectedDate }}</div>
    <div class="emoji-picker">
      <button
        v-for="emoji in MOODS"
        :key="emoji"
        class="emoji-option"
        :class="{ 'is-selected': selectedEmoji === emoji }"
        @click="selectedEmoji = emoji"
      >{{ emoji }}</button>
    </div>
    <div>
      <label class="picker-label">心情等级</label>
      <div class="level-picker">
        <button
          v-for="lv in 5"
          :key="lv"
          class="level-btn"
          :class="{ 'is-selected': selectedLevel === lv }"
          :data-level="lv"
          :title="LEVEL_LABELS[lv - 1]"
          @click="selectedLevel = lv"
        >{{ lv }}</button>
      </div>
    </div>
    <input class="note-input" v-model="noteInput" placeholder="一句话记录今天..." maxlength="200" />
    <div class="modal-actions">
      <button class="btn-cancel" @click="showModal = false">取消</button>
      <button class="btn-cancel" type="button" @click="router.push(`/day/${selectedDate}`)">查看这一天</button>
      <button class="btn-primary" @click="save">打卡</button>
    </div>
  </GlassModal>
</template>

<style scoped>
.container {
  max-width: 700px; min-width: 0; margin: 0 auto;
  padding: var(--page-pad-top) var(--page-pad-x) var(--page-pad-bottom);
  overflow-wrap: anywhere; word-break: break-word;
}

.stats { display: flex; gap: 14px; margin-bottom: 28px; flex-wrap: wrap; }
.stat-card { flex: 1; min-width: 120px; padding: 18px; border-radius: 16px; background: var(--glass-bg); backdrop-filter: blur(20px); border: 1px solid var(--glass-border); text-align: center; }
.stat-card .label { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.stat-card .value { font-size: 28px; font-weight: 700; }
.stat-card .sub { font-size: 13px; color: var(--text-secondary); margin-top: 4px; }

.cal-header { display: flex; align-items: center; justify-content: center; gap: 20px; margin-bottom: 20px; }
.cal-header button { width: var(--touch-min); height: var(--touch-min); border-radius: 50%; border: none; background: rgba(255, 255, 255, 0.1); color: #fff; font-size: 18px; cursor: pointer; transition: all 0.2s; }
.cal-header button:hover { background: rgba(255, 255, 255, 0.2); }
.month-label { font-size: 20px; font-weight: 700; min-width: 140px; text-align: center; }

.cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; padding: 20px; border-radius: 20px; background: var(--glass-bg); backdrop-filter: blur(20px); border: 1px solid var(--glass-border); }
.weekday { text-align: center; font-size: 12px; color: var(--text-secondary); font-weight: 600; padding: 4px 0; }

.cal-day { min-width: 0; aspect-ratio: 1; border-radius: 12px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; font-size: 13px; cursor: pointer; transition: all 0.2s; background: rgba(255, 255, 255, 0.03); }
.cal-day:hover { background: rgba(255, 255, 255, 0.12); transform: scale(1.05); }
.cal-day.is-today { border: 2px solid var(--primary); box-shadow: 0 0 12px rgba(255, 107, 157, 0.3); }
.cal-day.is-empty { pointer-events: none; background: transparent; }
.cal-day .emoji { font-size: 18px; line-height: 1; }
.cal-day .day-num { font-size: 11px; color: var(--text-secondary); }

.cal-day.level-1 { background: rgba(100, 130, 180, 0.35); }
.cal-day.level-2 { background: rgba(150, 160, 200, 0.3); }
.cal-day.level-3 { background: rgba(200, 180, 150, 0.3); }
.cal-day.level-4 { background: rgba(255, 160, 130, 0.3); }
.cal-day.level-5 { background: rgba(255, 107, 157, 0.4); box-shadow: 0 0 8px rgba(255, 107, 157, 0.2); }

/* Modal content */
.date-info { font-size: 13px; color: var(--text-secondary); margin-bottom: 18px; text-align: center; }
.emoji-picker { display: flex; justify-content: center; gap: 12px; margin-bottom: 18px; flex-wrap: wrap; }
.emoji-option { width: 52px; height: 52px; border-radius: 14px; border: 2px solid transparent; background: rgba(255, 255, 255, 0.06); font-size: 26px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; }
.emoji-option:hover { background: rgba(255, 255, 255, 0.15); transform: scale(1.1); }
.emoji-option.is-selected { border-color: var(--primary); background: rgba(255, 107, 157, 0.15); }

.picker-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; display: block; }
.level-picker { display: flex; justify-content: center; gap: 8px; margin-bottom: 16px; }
.level-btn { width: 40px; height: 40px; border-radius: 10px; border: 2px solid transparent; font-size: 14px; font-weight: 700; cursor: pointer; transition: all 0.2s; color: #fff; }
.level-btn:hover { transform: scale(1.1); }
.level-btn.is-selected { border-color: #fff; }
.level-btn[data-level="1"] { background: rgba(100, 130, 180, 0.5); }
.level-btn[data-level="2"] { background: rgba(150, 160, 200, 0.5); }
.level-btn[data-level="3"] { background: rgba(200, 180, 150, 0.5); }
.level-btn[data-level="4"] { background: rgba(255, 160, 130, 0.5); }
.level-btn[data-level="5"] { background: rgba(255, 107, 157, 0.6); }

.note-input { width: 100%; min-height: 44px; padding: 10px 14px; border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.2); background: rgba(255, 255, 255, 0.06); color: #fff; font-size: 14px; outline: none; margin-bottom: 16px; }
.note-input:focus { border-color: var(--primary); }

.modal-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.modal-actions button { flex: 1; min-height: 44px; padding: 10px; border-radius: 12px; border: none; font-size: 14px; font-weight: 600; cursor: pointer; }
.btn-cancel { background: rgba(255, 255, 255, 0.1); color: #fff; }

.month-state {
  display: flex; flex-direction: column; align-items: center; gap: 12px;
  padding: 24px 18px; border-radius: 20px;
  background: var(--glass-bg); border: 1px solid var(--glass-border);
  color: var(--text-secondary); font-size: 14px; line-height: 1.6; text-align: center;
}
.month-state p { margin: 0; overflow-wrap: anywhere; word-break: break-word; }
.month-state.is-error { color: #ffd2dc; border-color: rgba(255, 120, 140, 0.35); }
.retry-btn {
  min-width: 88px; min-height: 44px; padding: 8px 18px;
  border: 1px solid rgba(255, 255, 255, 0.3); border-radius: 999px;
  background: rgba(255, 255, 255, 0.12); color: #fff;
  font: inherit; font-weight: 600; cursor: pointer;
}

@media (max-width: 720px) {
  .container {
    padding-left: 12px;
    padding-right: 12px;
  }

  .cal-grid {
    padding: 8px;
    gap: 4px;
  }

  .cal-day .emoji {
    font-size: 15px;
  }

  .stat-card {
    min-width: 80px;
    padding: 14px 10px;
  }

  .stat-card .value {
    font-size: 22px;
  }

  .emoji-picker {
    gap: 8px;
  }

  .emoji-option {
    width: 44px;
    height: 44px;
    font-size: 22px;
    border-radius: 12px;
  }

  .level-btn {
    width: var(--touch-min);
    height: var(--touch-min);
    font-size: 13px;
  }

  .month-label {
    font-size: 16px;
    min-width: 0;
  }
}

@media (max-width: 380px) {
  .cal-day .emoji {
    font-size: 13px;
  }

  .cal-day .day-num {
    font-size: 10px;
  }
}
</style>
