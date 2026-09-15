/**
 * buildGroups(看板分组)纯函数测试。
 *
 * 核心语义("勾选什么样,面板就是什么样"):
 * - 不勾 = 全部标签可见;勾了 = 只有勾选的可见(勾父已联动全选子)。
 * - 每个任务只出现一次:归到可见标签里离它最近的祖先(含自己),多标签取最深。
 * - 勾选态下不匹配筛选的任务不出现;没勾时的真无标签任务进末尾「未标签」组。
 * - 组顺序 = 树前序(父组在前),组内按 importance 降序;空组不渲染。
 */
import { describe, expect, it } from 'vitest'

import type { TagInfo } from '@/types'
import { buildGroups, UNTAGGED, type BoardTask } from '@/utils/taskGroups'

/** 工作 → 科研 → 论文;健康(根) */
const TAGS: TagInfo[] = [
  { name: '工作', parent: null },
  { name: '健康', parent: null },
  { name: '科研', parent: '工作' },
  { name: '论文', parent: '科研' },
]

function task(id: string, tags: string[], importance = 0): BoardTask {
  return { id, title: id, importance, drive: 'end', tags, footer: '' }
}

describe('buildGroups', () => {
  it('不勾选 = 全部标签可见,任务归到最深标签', () => {
    const gs = buildGroups(
      [task('a', ['论文'], 1), task('b', ['健康'], 2), task('c', [], 3)],
      TAGS,
      [],
    )
    const byName = Object.fromEntries(gs.map((g) => [g.name, g.tasks.map((t) => t.id)]))
    expect(byName).toEqual({
      工作: [],            // 无直接任务,但子组有 → 作为父组保留
      科研: [],
      论文: ['a'],
      健康: ['b'],
      [UNTAGGED]: ['c'],
    })
    // 父组在前序位置先于子组
    expect(gs.map((g) => g.name)).toEqual(['工作', '科研', '论文', '健康', UNTAGGED])
  })

  it('勾选父标签 = 整个子树分组出现(联动全选)', () => {
    const gs = buildGroups([task('a', ['论文'])], TAGS, ['工作', '科研', '论文'])
    expect(gs.map((g) => g.name)).toEqual(['工作', '科研', '论文'])
  })

  it('只勾子标签:任务归子组,父组不出现;兄弟标签的任务被筛掉', () => {
    const gs = buildGroups(
      [task('a', ['论文']), task('b', ['健康'])],
      TAGS,
      ['科研', '论文'], // 勾科研(联动论文),不勾健康
    )
    const byName = Object.fromEntries(gs.map((g) => [g.name, g.tasks.map((t) => t.id)]))
    expect(byName).toEqual({ 科研: [], 论文: ['a'] }) // b 被筛掉,健康组不出现
    // 父标签不可见:科研提升为顶层(depth 0),论文 depth 1
    expect(gs.map((g) => [g.name, g.depth])).toEqual([
      ['科研', 0],
      ['论文', 1],
    ])
  })

  it('任务挂子标签、勾父:经祖先命中,归到最近的可见祖先', () => {
    // 只勾「工作」,任务只挂「论文」→ 归到工作(可见的最近祖先)
    const gs = buildGroups([task('a', ['论文'])], TAGS, ['工作'])
    expect(gs.map((g) => g.name)).toEqual(['工作'])
    expect(gs[0].tasks.map((t) => t.id)).toEqual(['a'])
  })

  it('多标签任务:归到层级最深的可见标签,只出现一次', () => {
    const gs = buildGroups([task('a', ['论文', '健康'])], TAGS, [])
    const total = gs.reduce((n, g) => n + g.tasks.length, 0)
    expect(total).toBe(1)
    // 论文深度 2 > 健康深度 0 → 归论文组
    expect(gs.find((g) => g.name === '论文')?.tasks.map((t) => t.id)).toEqual(['a'])
  })

  it('组内按 importance 降序', () => {
    const gs = buildGroups(
      [task('a', ['健康'], 0.1), task('b', ['健康'], 1.5), task('c', ['健康'], 0.8)],
      TAGS,
      [],
    )
    expect(gs.find((g) => g.name === '健康')?.tasks.map((t) => t.id)).toEqual(['b', 'c', 'a'])
  })

  it('整棵子树都没任务的标签组被剪掉', () => {
    const gs = buildGroups([task('a', ['健康'])], TAGS, [])
    expect(gs.map((g) => g.name)).toEqual(['健康']) // a 有标签,不产生未标签组
  })

  it('深度正确(子组 depth=父+1),未标签组 depth=0', () => {
    const gs = buildGroups([task('a', ['论文']), task('b', [])], TAGS, [])
    const depthOf = Object.fromEntries(gs.map((g) => [g.name, g.depth]))
    expect(depthOf).toEqual({ 工作: 0, 科研: 1, 论文: 2, [UNTAGGED]: 0 })
  })
})
