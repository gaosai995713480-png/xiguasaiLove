<script setup>
import { useRouter } from 'vue-router'
import TopBar from '../components/TopBar.vue'
import AiChatWidget from '../components/AiChatWidget.vue'

const router = useRouter()

function backHome() {
  router.push('/')
}
</script>

<template>
  <TopBar
    title="AI 助手"
    subtitle="对话、技能与长期记忆"
    @back="backHome"
  />

  <main class="assistant-page">
    <AiChatWidget embedded @back="backHome" />
  </main>
</template>

<style scoped>
.assistant-page {
  position: relative;
  z-index: 2;
  width: min(1040px, calc(100% - 2 * var(--page-pad-x)));
  margin: 0 auto;
  padding: var(--page-pad-top) 0 8px;
}

@media (max-width: 720px) {
  .assistant-page {
    padding-bottom: calc(var(--tabbar-height) + 12px);
  }
}
</style>
