import type { TagInfo } from '@/types'

export interface TagNode extends TagInfo {
  children: TagNode[]
}

/** 平铺 [{name,parent}] → 树。parent 指向不在列表里的(数据异常)按根处理。 */
export function buildTree(tags: TagInfo[]): TagNode[] {
  const names = new Set(tags.map((t) => t.name))
  const byParent = new Map<string | null, TagInfo[]>()
  for (const t of tags) {
    const p = t.parent && names.has(t.parent) ? t.parent : null
    const arr = byParent.get(p) ?? []
    arr.push(t)
    byParent.set(p, arr)
  }
  const make = (t: TagInfo): TagNode => ({
    ...t,
    children: (byParent.get(t.name) ?? []).map(make),
  })
  return (byParent.get(null) ?? []).map(make)
}

/** name → 全部祖先名(近→远)。隐式继承筛选用:任务挂「科研」,筛「工作」命中。 */
export function ancestorsMap(tags: TagInfo[]): Map<string, string[]> {
  const parentOf = new Map(tags.map((t) => [t.name, t.parent]))
  const memo = new Map<string, string[]>()
  const get = (name: string, guard = 0): string[] => {
    const hit = memo.get(name)
    if (hit) return hit
    if (guard > 50) return [] // 环兜底,正常后端已防
    const p = parentOf.get(name)
    const res = p ? [p, ...get(p, guard + 1)] : []
    memo.set(name, res)
    return res
  }
  for (const t of tags) get(t.name)
  return memo
}

/** name → 全部子孙名(勾选父=整个子树用) */
export function descendantsMap(tags: TagInfo[]): Map<string, string[]> {
  const childrenOf = new Map<string, string[]>()
  for (const t of tags) {
    if (!t.parent) continue
    const arr = childrenOf.get(t.parent) ?? []
    arr.push(t.name)
    childrenOf.set(t.parent, arr)
  }
  const memo = new Map<string, string[]>()
  const get = (name: string): string[] => {
    const hit = memo.get(name)
    if (hit) return hit
    const kids = childrenOf.get(name) ?? []
    const res = [...kids, ...kids.flatMap((k) => get(k))]
    memo.set(name, res)
    return res
  }
  for (const t of tags) get(t.name)
  return memo
}

/** 每个标签的层级深度(表单缩进用),根=0 */
export function depthMap(tags: TagInfo[]): Map<string, number> {
  const anc = ancestorsMap(tags)
  const m = new Map<string, number>()
  for (const t of tags) m.set(t.name, anc.get(t.name)?.length ?? 0)
  return m
}
