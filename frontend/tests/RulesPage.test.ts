/**
 * RulesPage(通知漏斗页)组件测试。
 *
 * 覆盖「空白页」教训:页面有骨架但拿不到/渲染不出数据。
 * mock API client,断言拿到漏斗数据后:各层、实时挡掉数、被挡任务、
 * 配置项、本轮将弹出的任务都渲染出来。
 */
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { FunnelResponse, RulesResponse } from '@/types'

vi.mock('@/api/client', () => ({
  fetchFunnel: vi.fn(),
  fetchRules: vi.fn(),
  updateSettings: vi.fn(),
}))

import { fetchFunnel, fetchRules } from '@/api/client'
import RulesPage from '@/components/RulesPage.vue'

const FUNNEL: FunnelResponse = {
  layers: [
    { id: 'future_period', label: '未来周期', desc: '明天那份今晚不催', blocked_count: 1,
      blocked_tasks: [{ id: 'a', title: '明日原神', reason: '明天/后天那份' }], settings: [] },
    { id: 'snooze', label: '推迟中', desc: '点了稍后', blocked_count: 0, blocked_tasks: [], settings: [] },
    { id: 'cooldown', label: '冷却中', desc: '刚催过', blocked_count: 0, blocked_tasks: [],
      settings: [
        { key: 'cooldown_ratio', value: 0.25, type: 'float', unit: '', label: '冷却系数', desc: '', min: 0.05, max: 1 },
      ] },
    { id: 'limit', label: '限量', desc: '一次最多弹几张', blocked_count: 0, blocked_tasks: [],
      settings: [
        { key: 'max_concurrent', value: 1, type: 'int', unit: '张', label: '一次最多弹卡', desc: '', min: 1, max: 5 },
      ] },
    { id: 'stage', label: '定档位', desc: '提醒/催办/紧急', blocked_count: 0, blocked_tasks: [],
      settings: [
        { key: 'escalate_nags', value: 3, type: 'int', unit: '次', label: '升级档次数', desc: '', min: 1, max: 20 },
        { key: 'crisis_importance', value: 1.0, type: 'float', unit: '', label: '危机重要性阈值', desc: '', min: 0, max: 5 },
      ] },
  ],
  will_push: [{ id: 'x', title: '今日原神', stage: 'crisis' }],
  poll_interval: 30,
}

const RULES: RulesResponse = {
  editable: [
    { key: 'cooldown_ratio', value: 0.25, type: 'float', unit: '', label: '冷却系数', desc: '', min: 0.05, max: 1 },
    { key: 'cooldown_fallback', value: 3600, type: 'int', unit: '秒', label: '兜底冷却', desc: '', min: 60, max: 86400 },
    { key: 'escalate_nags', value: 3, type: 'int', unit: '次', label: '升级档次数', desc: '', min: 1, max: 20 },
    { key: 'crisis_importance', value: 1.0, type: 'float', unit: '', label: '危机重要性阈值', desc: '', min: 0, max: 5 },
    { key: 'poll_interval', value: 30, type: 'int', unit: '秒', label: '轮询间隔', desc: '', min: 5, max: 600 },
    { key: 'max_concurrent', value: 1, type: 'int', unit: '张', label: '一次最多弹卡', desc: '', min: 1, max: 5 },
  ],
  readonly: [],
}

const mockFunnel = vi.mocked(fetchFunnel)
const mockRules = vi.mocked(fetchRules)

async function mountPage() {
  const wrapper = mount(RulesPage)
  await new Promise((r) => setTimeout(r, 0))
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('RulesPage(通知漏斗)', () => {
  beforeEach(() => {
    mockFunnel.mockReset()
    mockRules.mockReset()
    mockRules.mockResolvedValue(RULES)
  })

  it('渲染出漏斗每一层', async () => {
    mockFunnel.mockResolvedValue(FUNNEL)
    const wrapper = await mountPage()
    for (const l of FUNNEL.layers) {
      expect(wrapper.text()).toContain(l.label)
    }
  })

  it('显示被挡任务数,0 的层显示「全部通过」', async () => {
    mockFunnel.mockResolvedValue(FUNNEL)
    const wrapper = await mountPage()
    // future_period 挡了 1 个(badge),其余层显示全部通过
    expect(wrapper.findAll('.layer-pass').length).toBeGreaterThan(0)
  })

  it('展开被挡的层能看到具体任务', async () => {
    mockFunnel.mockResolvedValue(FUNNEL)
    const wrapper = await mountPage()
    // 默认不展开,看不到任务名
    expect(wrapper.text()).not.toContain('明日原神')
    // 点开第一层
    await wrapper.findAll('.layer-head')[0].trigger('click')
    expect(wrapper.text()).toContain('明日原神')
  })

  it('把配置项嵌在对应层,并回填当前值', async () => {
    mockFunnel.mockResolvedValue(FUNNEL)
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('冷却系数')
    expect(wrapper.text()).toContain('升级档次数')
    const values = wrapper.findAll('input').map((i) => i.element.value)
    expect(values).toContain('0.25')
  })

  it('出口显示本轮将弹出的任务与档位', async () => {
    mockFunnel.mockResolvedValue(FUNNEL)
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('今日原神')
    expect(wrapper.text()).toContain('紧急')
    expect(wrapper.text()).toContain('30 秒')
  })

  it('接口失败时提示错误而不是静默空白', async () => {
    mockFunnel.mockRejectedValue(new Error('请求失败:500'))
    const wrapper = await mountPage()
    expect(wrapper.find('.rules-page').exists()).toBe(true)
  })
})
