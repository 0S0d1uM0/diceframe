<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api, errorMessage } from '@/api/client'

const props = defineProps<{ gameKey: string; revision?: string }>()
const emit = defineEmits<{ refresh: []; enabled: [value: boolean] }>()
interface Proposal { text: string; selected_skill: string; selected_attribute: string; target_text: string }
interface Plan { run_id: string; round: number; revision: number; roster: Record<string, { mode: string }>; messages: { uid: string; text: string }[]; proposals: Record<string, Proposal>; confirmed: string[]; committed: boolean; reviews?: Record<string, { confirmed: boolean; reason: string }> }
interface State { ok: boolean; enabled: boolean; plan: Plan; names: Record<string, string>; viewer_uid: string; is_gm: boolean; error?: string }
const state = ref<State | null>(null), busy = ref(false), error = ref(''), message = ref(''), proposal = ref('')
const running = ref(false), roundLimit = ref(3)
let stopRequested = false
let stopped = false, sequence = 0
onBeforeUnmount(() => { stopped = true; stopRequested = true; sequence++ })
const allAi = computed(() => !!state.value && Object.values(state.value.plan.roster).length > 0 && Object.values(state.value.plan.roster).every(row => row.mode === 'ai'))
const ownSeat = computed(() => !!state.value?.plan.roster[state.value.viewer_uid])
const canConfirm = computed(() => !!state.value?.plan.proposals[state.value.viewer_uid] && !state.value.plan.committed)
const ready = computed(() => {
  const plan = state.value?.plan
  return !!plan && Object.keys(plan.roster).length > 0 && Object.keys(plan.roster).every(uid => plan.proposals[uid] && plan.confirmed.includes(uid))
})
async function load() {
  if (busy.value || !props.gameKey) return
  const token = ++sequence
  try {
    const result = await api<State>(`/games/${encodeURIComponent(props.gameKey)}/party-plan`)
    if (!stopped && token === sequence) { state.value = result; emit('enabled', result.enabled) }
  } catch { /* Existing tables and read-only links need no planning surface. */ }
}
watch(() => [props.gameKey, props.revision], load, { immediate: true })
async function perform(operation: string, extra: Record<string, unknown> = {}) {
  if (!state.value || busy.value) return
  const current = state.value.plan
  busy.value = true; error.value = ''
  try {
    const result = await api<State>(`/games/${encodeURIComponent(props.gameKey)}/party-plan/${operation}`, { method: 'POST', body: JSON.stringify({ run_id: current.run_id, round: current.round, expected_revision: current.revision, ...extra }) })
    if (!result.ok) { error.value = result.error || '操作未完成'; return }
    state.value = result
    if (operation === 'message') message.value = ''
    emit('refresh')
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
async function advance() {
  busy.value = true; error.value = ''
  try {
    const result = await api<{ ok?: boolean; error?: string; narration?: string; phase?: string }>(`/games/${encodeURIComponent(props.gameKey)}/advance`, { method: 'POST', body: JSON.stringify({ force: false }) })
    if (result.ok === false || result.phase === 'luck') error.value = result.error || result.narration || '当前等待规则决定，连续运行已停止'
    emit('refresh')
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false; await load() }
}
async function runAi() {
  if (!allAi.value || running.value) return
  running.value = true; stopRequested = false
  try {
    const limit = Math.max(1, Math.min(20, Math.trunc(Number(roundLimit.value) || 1)))
    for (let index = 0; index < limit && !stopped && !stopRequested; index++) {
      await load()
      if (!allAi.value) break
      if (!state.value?.plan.committed) {
        await perform('generate')
        if (error.value || stopRequested || !ready.value) break
        await perform('commit')
        if (error.value || stopRequested) break
      }
      await advance()
      if (error.value) break
    }
  } finally { running.value = false; await load() }
}
</script>

<template>
  <section v-if="state?.enabled" class="party-planning" aria-label="队内讨论与计划">
    <header><h3>队内讨论 · 第 {{ state.plan.round }} 轮</h3><button type="button" :disabled="busy" @click="load">刷新</button></header>
    <p>先商量，再提交。讨论和提案不会掷骰、推进时间或触发 KP。新的意见或提案会清除原确认，请全员重新确认。</p>
    <div v-for="(row, index) in state.plan.messages" :key="index" class="message"><strong>{{ state.names[row.uid] }}</strong>：{{ row.text }}</div>
    <article v-for="uid in Object.keys(state.plan.roster)" :key="uid"><strong>{{ state.names[uid] }}</strong><span> · {{ state.plan.confirmed.includes(uid) ? '已确认当前计划' : '尚未确认' }}</span><p>{{ state.plan.proposals[uid]?.text || '尚无行动提案' }}</p><p v-if="state.plan.reviews?.[uid]?.reason">审核意见：{{ state.plan.reviews[uid]?.reason }}</p></article>
    <template v-if="!state.plan.committed">
      <template v-if="ownSeat && state.plan.roster[state.viewer_uid]?.mode === 'human'">
        <label>给队友的讨论消息<textarea v-model="message" maxlength="2000" /></label><button type="button" :disabled="busy || !message.trim()" @click="perform('message', { text: message })">发送讨论</button>
        <label>我拟采取的行动<textarea v-model="proposal" maxlength="2000" /></label><button type="button" :disabled="busy || !proposal.trim()" @click="perform('propose', { text: proposal })">更新我的提案</button>
        <button type="button" :disabled="busy || !canConfirm" @click="perform('confirm')">我同意当前全队计划</button>
      </template>
      <template v-if="state.is_gm"><button type="button" :disabled="busy" @click="perform('generate')">让 AI 调查员讨论并审核计划</button><button type="button" :disabled="busy || !ready" @click="perform('commit')">全员同意，正式提交给 KP</button></template>
    </template>
    <p v-else>计划已正式提交。<button v-if="state.is_gm" type="button" :disabled="busy" @click="advance">请 KP 结算本轮</button></p>
    <div v-if="state.is_gm && allAi"><label>全 AI 连续运行轮数（1–20）<input v-model.number="roundLimit" type="number" min="1" max="20" :disabled="running"></label><button type="button" :disabled="busy || running" @click="runAi">开始全 AI 运行</button><button v-if="running" type="button" @click="stopRequested = true">暂停（完成当前请求后停止）</button></div>
    <p v-if="busy" role="status">处理中，请稍候…</p><p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.party-planning { display: grid; gap: .75rem; margin-block: 1rem; padding: 1rem; border: 1px solid var(--border-color,#666); border-radius: 10px; } header { display: flex; justify-content: space-between; align-items: center; } h3,p { margin: 0; } article { padding: .75rem; border-left: 3px solid #8aafad; background: #8881; } label { display: grid; gap: .4rem; } textarea { min-height: 4rem; width: 100%; padding: .5rem; color: inherit; background: transparent; } button { padding: .5rem .75rem; } [role=alert] { color: #f88; }
</style>
