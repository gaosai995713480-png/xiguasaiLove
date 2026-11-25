<script setup>
import { nextTick, ref } from 'vue'
import { useThemeStore } from '../stores/theme'

const themeStore = useThemeStore()
const open = ref(false)
const triggerRef = ref(null)

function toggle() {
  open.value = !open.value
}

async function select(theme) {
  themeStore.applyTheme(theme.name)
  open.value = false
  await nextTick()
  triggerRef.value?.focus()
}

// 点击外部关闭
function onClickOutside() {
  open.value = false
}

async function closeAndFocus() {
  open.value = false
  await nextTick()
  triggerRef.value?.focus()
}
</script>

<template>
  <div class="ts-wrap" v-click-outside="onClickOutside" @keydown.esc.stop.prevent="closeAndFocus">
    <button
      ref="triggerRef"
      class="ts-btn"
      type="button"
      title="切换主题"
      aria-label="切换主题"
      aria-haspopup="true"
      aria-controls="theme-switcher-menu"
      :aria-expanded="open"
      @click.stop="toggle"
    >
      🎨
    </button>
    <div
      id="theme-switcher-menu"
      class="ts-dropdown"
      :class="{ 'is-open': open }"
      role="group"
      aria-label="主题选择"
      :aria-hidden="!open"
      :inert="open ? null : ''"
    >
      <button
        v-for="theme in themeStore.themes"
        :key="theme.name"
        class="ts-swatch"
        :class="{ 'is-active': themeStore.currentName === theme.name }"
        :style="{ background: theme.color }"
        :title="theme.name"
        type="button"
        :aria-label="`切换主题：${theme.name}`"
        :aria-pressed="themeStore.currentName === theme.name"
        @click="select(theme)"
      >
        <span class="ts-emoji">{{ theme.emoji }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.ts-wrap {
  position: relative;
  margin-left: auto;
}

.ts-btn {
  width: var(--touch-min);
  height: var(--touch-min);
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.ts-btn:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: scale(1.05);
}

.ts-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  background: rgba(20, 20, 30, 0.92);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 14px;
  padding: 10px;
  display: flex;
  flex-wrap: wrap;
  max-width: 220px;
  gap: 8px;
  opacity: 0;
  pointer-events: none;
  transform: translateY(-6px);
  transition: all 0.2s ease;
  z-index: 50;
}

.ts-dropdown.is-open {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0);
}

.ts-swatch {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  border: 2px solid transparent;
  padding: 0;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  appearance: none;
}

.ts-swatch:hover {
  transform: scale(1.12);
}

.ts-swatch.is-active {
  border-color: #fff;
  box-shadow: 0 0 12px rgba(255, 255, 255, 0.3);
}

.ts-emoji {
  font-size: 16px;
}
</style>
