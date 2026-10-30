import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('../src/api/client', () => ({ api: mocks.api, errorMessage: String }))
import Panel from '../src/features/play/party/PartyPlanningPanel.vue'

function state(allAi = false) {
  return { ok: true, enabled: true, is_gm: allAi, viewer_uid: 'h', names: { h: '林照', a: '周衡' },
    plan: { run_id: 'run', round: 1, revision: 2, roster: { h: { mode: allAi ? 'ai' : 'human' }, a: { mode: 'ai' } },
      proposals: { h: { text: '我检查门锁' }, a: { text: '我警戒' } }, messages: [], confirmed: ['a'], committed: false } }
}

describe('party planning consent', () => {
  beforeEach(() => mocks.api.mockReset())
  it('confirms only the current human seat and does not submit or advance the Keeper', async () => {
    mocks.api.mockResolvedValue(state())
    const wrapper = mount(Panel, { props: { gameKey: 'table' } })
    await flushPromises()
    const button = wrapper.findAll('button').find(row => row.text() === '我同意当前全队计划')!
    await button.trigger('click'); await flushPromises()
    expect(mocks.api.mock.calls.map(row => row[0])).toEqual(['/games/table/party-plan', '/games/table/party-plan/confirm'])
    expect(JSON.parse(mocks.api.mock.calls[1]![1].body)).toEqual({ run_id: 'run', round: 1, expected_revision: 2 })
    expect(wrapper.text()).not.toContain('正式提交给 KP')
    wrapper.unmount()
  })
  it('stops continuous AI play when an investigator withholds consent and displays the objection', async () => {
    const response = { ...state(true), plan: { ...state(true).plan, reviews: { h: { confirmed: false, reason: '分工重复' } } } }
    mocks.api.mockResolvedValue(response)
    const wrapper = mount(Panel, { props: { gameKey: 'table' } })
    await flushPromises()
    await wrapper.findAll('button').find(row => row.text() === '开始全 AI 运行')!.trigger('click')
    await flushPromises()
    const paths = mocks.api.mock.calls.map(row => String(row[0]))
    expect(paths.filter(path => path.endsWith('/generate'))).toHaveLength(1)
    expect(paths.some(path => path.endsWith('/commit') || path.endsWith('/advance'))).toBe(false)
    expect(wrapper.text()).toContain('审核意见：分工重复')
    wrapper.unmount()
  })
})
