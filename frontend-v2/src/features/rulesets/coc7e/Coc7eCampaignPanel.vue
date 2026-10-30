<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { api, errorMessage } from '@/api/client'
import { changeStory, generateStory } from '@/features/play/run-story/api'
import RunStoryPanel from '@/features/play/run-story/RunStoryPanel.vue'

const props = defineProps<{ gameKey: string; isGm: boolean; refreshKey?: number }>()
const emit = defineEmits<{ refresh: [] }>()
const state = ref<{ gameplay: { run_id: string; campaign: { revision?: number; mode?: string; premise?: string } } }>()
const premise = ref(''), busy = ref(false), error = ref(''), status = ref('')
let controller: AbortController | undefined
async function load() {
  try { state.value = await api(`/games/${encodeURIComponent(props.gameKey)}/available-actions`) }
  catch (e) { error.value = errorMessage(e) }
}
watch(() => [props.gameKey, props.refreshKey], load, { immediate: true })
onBeforeUnmount(() => controller?.abort())
async function configure(mode: 'regular' | 'endless') {
  if (!state.value) return
  busy.value = true; error.value = ''; status.value = ''
  try {
    const configured = await api<{ ok: boolean; error?: string }>(`/games/${encodeURIComponent(props.gameKey)}/intents`, { method: 'POST', body: JSON.stringify({ type: 'coc.campaign.configure', mode, premise: premise.value,
      expected_run_id: state.value.gameplay.run_id, expected_revision: state.value.gameplay.campaign.revision || 0 }) })
    if (!configured.ok) throw new Error(configured.error || '无法设置原创模式')
    if (mode === 'regular') {
      controller = new AbortController()
      const draft = await generateStory(props.gameKey, 'plan', { run_id: state.value.gameplay.run_id, token_consent: true,
        instructions: `常规CoC原创短团，请开局编好核心真相、调查目标、可替代的线索路径和可达终局。尊重已发生的公开事实。团队合作，不设置调查员叛徒。创意要求：${premise.value}` }, controller.signal, p => { status.value = p.stage })
      if (!draft.plan) throw new Error('KP未生成合法大纲，尚未采用计划，可重试')
      const adopted = await changeStory(props.gameKey, 'plan', { run_id: draft.run_id, revision: draft.revision, source: 'ai_original', plan: draft.plan })
      if (!adopted.ok) throw new Error(adopted.error || '大纲未通过采用校验')
      status.value = 'KP已创建并采用开局大纲。'
    } else status.value = '已启用无尽原创模式：无预设总终局，后续事件基于已有事实与玩家选择生长。'
    await load(); emit('refresh')
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
</script>

<template>
  <section>
    <h3>CoC 原创团</h3><p>请在第一轮正式行动前选择。模组团继续使用模组的真相和推进流程。</p>
    <p>当前模式：{{ state?.gameplay.campaign.mode === 'endless' ? '无尽原创' : state?.gameplay.campaign.mode === 'regular' ? '常规原创' : '尚未指定／现有场景' }}</p>
    <template v-if="isGm">
      <label>题材与开局想法<textarea v-model="premise" maxlength="2000" /></label>
      <button type="button" :disabled="busy" @click="configure('regular')">常规团：由 KP 生成并采用大纲</button>
      <button type="button" :disabled="busy" @click="configure('endless')">无尽团：不预设总终局</button>
      <button v-if="busy && controller" type="button" @click="controller.abort()">取消大纲生成</button>
      <p>{{ status }}</p><p v-if="error" role="alert">{{ error }}</p>
      <RunStoryPanel :game-key="gameKey" :revision="refreshKey || 0" @changed="emit('refresh')" />
    </template>
  </section>
</template>

<style scoped>
section { display: grid; gap: .75rem; } textarea { width: 100%; min-height: 5rem; padding: .5rem; color: inherit; background: transparent; } button { padding: .6rem; } [role=alert] { color: #f88; }
</style>
