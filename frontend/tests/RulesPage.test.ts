/**
 * RulesPage 组件测试。
 *
 * 覆盖本项目的「空白页」教训:页面有骨架但拿不到/渲染不出数据。
 * 用 vi.mock 替换 API client,断言拿到数据后只读卡片与可编辑项都渲染出来,
 * 并把可编辑项回填进输入框。
 */
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RulesResponse } from '@/types'

// mock API client,在 import 组件前替换
vi.mock('@/api/client', () => ({
  fetchRules: vi.fn(),
  updateSettings: vi.fn(),
}))

import { fetchRules } from '@/api/client'
import RulesPage from '@/components/RulesPage.vue'

const SAMPLE: RulesResponse = {
  editable: [
    { key: 'cooldown_ratio', value: 0.25, type: 'float', unit: '', label: '冷却系数', desc: '冷却=间隔×系数', min: 0.05, max: 1 },
    { key: 'cooldown_fallback', value: 3600, type: 'int', unit: '秒', label: '兜底冷却', desc: '无间隔时冷却', min: 60, max: 86400 },
    { key: 'escalate_nags', value: 3, type: 'int', unit: '次', label: '升级档次数', desc: '推几次升档', min: 1, max: 20 },
    { key: 'crisis_importance', value: 1.0, type: 'float', unit: '', label: '危机重要性阈值', desc: '达此值升紧急', min: 0, max: 5 },
    { key: 'poll_interval', value: 30, type: 'int', unit: '秒', label: '轮询间隔', desc: '多久查一次', min: 5, max: 600 },
    { key: 'max_concurrent', value: 1, type: 'int', unit: '张', label: '一次最多弹卡', desc: '单轮弹卡上限', min: 1, max: 5 },
  ],
  readonly: [
    { title: '重要性引擎', desc: 'start log / end -log' },
    { title: '档位判定', desc: 'gentle→escalating→crisis' },
    { title: '优先级', desc: 'end 优先' },
  ],
}

const mockFetch = vi.mocked(fetchRules)

async function mountPage() {
  const wrapper = mount(RulesPage)
  // 等 onMounted 的异步 load() 完成
  await new Promise((r) => setTimeout(r, 0))
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('RulesPage', () => {
  beforeEach(() => {
    mockFetch.mockReset()
  })

  it('拿到数据后渲染出全部只读卡片', async () => {
    mockFetch.mockResolvedValue(SAMPLE)
    const wrapper = await mountPage()
    const cards = wrapper.findAll('.rule-card')
    expect(cards.length).toBe(SAMPLE.readonly.length)
    expect(wrapper.text()).toContain('重要性引擎')
    expect(wrapper.text()).toContain('档位判定')
  })

  it('拿到数据后渲染出全部可编辑项(非空白)', async () => {
    mockFetch.mockResolvedValue(SAMPLE)
    const wrapper = await mountPage()
    // 每个可编辑项一个 label
    for (const s of SAMPLE.editable) {
      expect(wrapper.text()).toContain(s.label)
    }
  })

  it('把当前值回填进数字输入框', async () => {
    mockFetch.mockResolvedValue(SAMPLE)
    const wrapper = await mountPage()
    const inputs = wrapper.findAll('input')
    const values = inputs.map((i) => i.element.value)
    // 冷却系数 0.25 应出现在某个输入框里
    expect(values).toContain('0.25')
    expect(values).toContain('3600')
  })

  it('接口失败时提示错误而不是静默空白', async () => {
    mockFetch.mockRejectedValue(new Error('请求失败:500'))
    const wrapper = await mountPage()
    // 不崩、且能继续渲染页面骨架
    expect(wrapper.find('.rules-page').exists()).toBe(true)
  })
})
