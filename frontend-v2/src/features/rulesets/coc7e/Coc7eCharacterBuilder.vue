<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '@/api/client'
import type { CharacterSheet, RulesetExperience } from '@/api/types'

const props = withDefaults(defineProps<{ ruleId: string; language?: string; initial?: CharacterSheet; embedded?: boolean; experience: RulesetExperience }>(), { language: 'zh-CN', embedded: false })
const emit = defineEmits<{ submit: [character: CharacterSheet]; cancel: [] }>()
interface Draft { schema_version: number; name: string; age: number; method: string; occupation: string; luck: number; attributes: Record<string, number>; occupation_spends: Record<string, number>; interest_spends: Record<string, number>; profile: Record<string, string> }
interface Choices { attributes: string[]; occupations: { id: string; name: string; skills: string[]; credit: number[] }[]; skills: { id: string; name: string; base: number }[]; draft_example: Draft }
const choices = ref<Choices | null>(null)
const draft = ref<Draft | null>(null)
const error = ref(''), busy = ref(false), prompt = ref('一位谨慎、忠于团队的调查员，有清楚的调查动机与个人背景。')
const zh = computed(() => props.language.startsWith('zh'))
const text = (cn: string, en: string) => zh.value ? cn : en
const labels: Record<string, string> = { str: '力量 STR', con: '体质 CON', siz: '体型 SIZ', dex: '敏捷 DEX', app: '外貌 APP', int: '智力 INT', pow: '意志 POW', edu: '教育 EDU' }
const occupationLimit = computed(() => {
  const d = draft.value
  if (!d) return 0
  return d.occupation === 'private_detective' ? 2 * (d.attributes.edu! + Math.max(d.attributes.str!, d.attributes.dex!)) : d.attributes.edu! * 4
})
const spent = (rows: Record<string, number>) => Object.values(rows).reduce((sum, value) => sum + (Number(value) || 0), 0)
function base(id: string, value: number) { return id === 'own_language' ? draft.value?.attributes.edu : id === 'dodge' ? Math.floor((draft.value?.attributes.dex || 0) / 2) : value }
onMounted(async () => {
  try {
    const result = await api<{ choices: Choices }>(`/rules/${encodeURIComponent(props.ruleId)}/builder/choices?language=${encodeURIComponent(props.language)}`, { method: 'POST', body: '{}' })
    choices.value = result.choices
    const initial = props.initial?.ruleset_character as { draft?: Draft } | undefined
    draft.value = structuredClone(initial?.draft || result.choices.draft_example)
  } catch (e) { error.value = errorMessage(e) }
})
async function generate() {
  busy.value = true; error.value = ''
  try {
    const result = await api<{ ok: boolean; draft?: Draft; error?: string }>('/generate-character', { method: 'POST', body: JSON.stringify({ rule_id: props.ruleId, language: props.language, prompt: prompt.value }) })
    if (result.draft) draft.value = result.draft
    if (!result.ok) error.value = result.error || text('请检查AI填写的表格', 'Review the model draft')
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
async function submit() {
  busy.value = true; error.value = ''
  try {
    const result = await api<{ ok: boolean; character: CharacterSheet; errors?: string[]; error?: string }>(`/rules/${encodeURIComponent(props.ruleId)}/builder/finalize`, { method: 'POST', body: JSON.stringify(draft.value) })
    if (!result.ok) { error.value = result.errors?.join('；') || result.error || 'Invalid investigator'; return }
    emit('submit', result.character)
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
</script>

<template>
  <form class="coc-builder" @submit.prevent="submit">
    <h2>{{ text('CoC 7e 调查员表', 'CoC 7e investigator form') }}</h2>
    <p>{{ text('当前支持20–39岁及四类职业。技能表填写投入点，最终数值由服务端计算。手动属性用于录入已获KP认可的数值。', 'Currently supports ages 20–39 and four occupations. Enter skill point investments; the server calculates final values. Manual attributes require Keeper approval.') }}</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <template v-if="draft && choices">
      <div class="fields">
        <label>{{ text('姓名', 'Name') }}<input v-model="draft.name" maxlength="120" required></label>
        <label>{{ text('年龄', 'Age') }}<input v-model.number="draft.age" type="number" min="20" max="39" required></label>
        <label>{{ text('职业', 'Occupation') }}<select v-model="draft.occupation"><option v-for="job in choices.occupations" :key="job.id" :value="job.id">{{ job.name }}</option></select></label>
        <label>{{ text('属性方法', 'Attribute method') }}<select v-model="draft.method"><option value="quick">{{ text('快速数组', 'Quick array') }}</option><option value="manual">{{ text('手动录入', 'Manual entry') }}</option></select></label>
        <label>{{ text('初始幸运', 'Initial Luck') }}<input v-model.number="draft.luck" type="number" min="15" max="90" step="5" required></label>
      </div>
      <fieldset><legend>{{ text('属性 · 快速数组40/50/50/50/60/60/70/80', 'Attributes · quick array 40/50/50/50/60/60/70/80') }}</legend>
        <div class="fields"><label v-for="key in choices.attributes" :key="key">{{ labels[key] || key }}<input v-model.number="draft.attributes[key]" type="number" min="15" max="90" required></label></div>
      </fieldset>
      <p>{{ text('职业点', 'Occupation') }} {{ spent(draft.occupation_spends) }} / {{ occupationLimit }} · {{ text('兴趣点', 'Interests') }} {{ spent(draft.interest_spends) }} / {{ (draft.attributes.int || 0) * 2 }}</p>
      <p>{{ text('职业技能', 'Occupational skills') }}：{{ choices.occupations.find(job => job.id === draft?.occupation)?.skills.map(id => choices?.skills.find(skill => skill.id === id)?.name || id).join('、') }}</p>
      <table><thead><tr><th>{{ text('技能', 'Skill') }}</th><th>{{ text('基础', 'Base') }}</th><th>{{ text('职业投入', 'Occupation points') }}</th><th>{{ text('兴趣投入', 'Interest points') }}</th></tr></thead>
        <tbody><tr v-for="skill in choices.skills.filter(row => row.id !== 'cthulhu_mythos')" :key="skill.id"><th scope="row">{{ skill.name }}</th><td>{{ base(skill.id, skill.base) }}</td><td><input v-model.number="draft.occupation_spends[skill.id]" :aria-label="`${skill.name} occupation`" type="number" min="0" max="99"></td><td><input v-model.number="draft.interest_spends[skill.id]" :aria-label="`${skill.name} interest`" type="number" min="0" max="99" :disabled="skill.id === 'credit_rating'"></td></tr></tbody>
      </table>
      <label>{{ text('性格与团队关系', 'Personality and party ties') }}<textarea v-model="draft.profile.personality" maxlength="5000" /></label>
      <label>{{ text('背景与调查动机', 'Background and motivation') }}<textarea v-model="draft.profile.backstory" maxlength="5000" /></label>
      <fieldset><legend>{{ text('让AI填写同一张表', 'Have AI fill this form') }}</legend><textarea v-model="prompt" maxlength="4000" /><button type="button" :disabled="busy" @click="generate">{{ text('AI填写草稿', 'Generate draft') }}</button></fieldset>
      <div class="buttons"><button type="button" :disabled="busy" @click="emit('cancel')">{{ text('取消', 'Cancel') }}</button><button type="submit" :disabled="busy">{{ busy ? text('处理中…', 'Working…') : text('校验并使用调查员', 'Validate and use investigator') }}</button></div>
    </template>
  </form>
</template>

<style scoped>
.coc-builder { display: grid; gap: 1rem; padding: 1.25rem; max-width: 960px; margin: auto; }
.fields { display: grid; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap: .75rem; }
label { display: grid; gap: .4rem; } input,select,textarea { width: 100%; padding: .5rem; border: 1px solid var(--border-color,#555); border-radius: 6px; background: var(--bg-card,#222); color: inherit; }
fieldset { border: 1px solid var(--border-color,#555); padding: 1rem; border-radius: 8px; } table { width: 100%; border-collapse: collapse; } td,th { padding: .35rem; text-align: left; } td input { max-width: 95px; } .buttons { display: flex; gap: .75rem; justify-content: flex-end; } button { padding: .6rem 1rem; border-radius: 6px; } .error { color: #f88; } textarea { min-height: 5rem; }
</style>
