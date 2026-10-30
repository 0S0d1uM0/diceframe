<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, errorMessage } from '@/api/client'
const props = defineProps<{ gameKey: string; actorId: string; isGm: boolean; refreshKey?: number }>()
const emit = defineEmits<{ refresh: [] }>()
interface Actor { actor_id: string; name: string; hp?: number; max_hp?: number; unconscious: boolean; dead: boolean }
interface Choice { type: string; actor_id: string; target_id?: string; weapon_id?: string; expected_revision: number }
interface Combat { status: string; revision?: number; round?: number; current?: string; actors?: Actor[]; pending_reaction?: { target_id: string } | null; limitations: string[] }
interface State { gameplay: { combat: Combat; run_id: string; npcs: { id: string; name: string }[] }; available_actions: Choice[] }
const state = ref<State | null>(null), busy = ref(false), error = ref(''), selectedNpcs = ref<string[]>([])
const encounter = computed(() => state.value?.gameplay.combat)
const names = computed(() => Object.fromEntries((encounter.value?.actors || []).map(row => [row.actor_id, row.name])))
async function load() {
  try { state.value = await api<State>(`/games/${encodeURIComponent(props.gameKey)}/available-actions`) }
  catch (e) { error.value = errorMessage(e) }
}
watch(() => [props.gameKey, props.refreshKey], load, { immediate: true })
async function act(intent: Record<string, unknown>) {
  busy.value = true; error.value = ''
  try {
    const result = await api<{ ok: boolean; error?: string }>(`/games/${encodeURIComponent(props.gameKey)}/intents`, { method: 'POST', body: JSON.stringify({ ...intent, expected_run_id: state.value?.gameplay.run_id }) })
    if (!result.ok) error.value = result.error || '战斗行动未通过校验'
    emit('refresh'); await load()
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
function label(choice: Choice) {
  const verb: Record<string, string> = { attack: '攻击', dodge: '闪避', fight_back: '反击', wait: '等待', flee: '逃离' }
  return `${verb[choice.type] || choice.type}${choice.target_id ? ` · ${names.value[choice.target_id] || choice.target_id}` : ''}${choice.weapon_id ? ` · ${choice.weapon_id === 'unarmed' ? '徒手' : choice.weapon_id}` : ''}`
}
</script>

<template>
  <section class="coc-combat">
    <h3>CoC 战斗</h3><p v-for="line in encounter?.limitations" :key="line">{{ line }}</p>
    <template v-if="encounter?.status === 'active'">
      <p>第 {{ encounter.round }} 轮 · {{ encounter.pending_reaction ? '等待防守反应' : '当前行动者' }}：{{ names[encounter.current || ''] }}</p>
      <ul><li v-for="actor in encounter.actors" :key="actor.actor_id">{{ actor.name }} · {{ actor.hp !== undefined ? `${actor.hp}/${actor.max_hp} HP` : '生命值未公开' }} {{ actor.dead ? '死亡' : actor.unconscious ? '昏迷' : '' }}</li></ul>
      <button v-for="(choice, index) in state?.available_actions" :key="index" type="button" :disabled="busy" @click="act({ ...choice })">{{ label(choice) }}</button>
      <p v-if="!state?.available_actions.length">等待当前行动者；不能替其他调查员决定。</p>
    </template>
    <template v-else-if="isGm">
      <p>选择已录入完整战斗属性的在场 NPC。缺少数据会拒绝开始，不自动编造数值。</p>
      <label v-for="npc in state?.gameplay.npcs" :key="npc.id"><input v-model="selectedNpcs" type="checkbox" :value="npc.id">{{ npc.name }}</label>
      <button type="button" :disabled="busy || !selectedNpcs.length" @click="act({ type: 'coc.combat.start', npc_ids: selectedNpcs })">开始遭遇</button>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.coc-combat { display: grid; gap: .75rem; } button { padding: .5rem; text-align: left; } label { display: flex; gap: .5rem; } [role=alert] { color: #f88; }
</style>
