import type { TagInfo } from '@/types'
import { ancestorsMap, buildTree, type TagNode } from '@/utils/tags'

/** 看板任务:两种驱动合并后的统一形态(卡片渲染用) */
export interface BoardTask {
  id: string
  title: string
  importance: number
  drive: 'start' | 'end'
  tags: string[]
  /** 卡片底部文案("X 天没做了"/"还剩 X 天"),由父组件算好传入 */
  footer: string
}

/** 一个标签分组;未标签组 name 用 UNTAGGED */
export interface TaskGroup {
  name: string
  depth: number
  tasks: BoardTask[]
}

export const UNTAGGED = '未标签'

/**
 * 按标签层级把任务分组成看板,组顺序 = 标签树前序遍历。
 *
 * 规则(与侧边栏勾选一致,"勾选什么样,面板就是什么样"):
 * - 没勾选 = 全部标签可见;勾了 = 只有勾选的可见(勾父已联动全选子,隐式继承天然成立)。
 * - 先按筛选语义过滤:任务任一直接标签被勾选、或有祖先被勾选才出现。
 * - 每个任务只出现一次:归到「可见标签里离它最近的祖先(含自己)」——
 *   对其每个标签沿祖先链找第一个可见标签,候选取层级最深者(多标签同深取先命中)。
 * - 够不到任何可见标签的任务只有"没勾选时的真无标签任务",进末尾「未标签」组。
 * - 空组(自己没任务且子孙组也没任务)不渲染。
 */
export function buildGroups(
  tasks: BoardTask[],
  tags: TagInfo[],
  selected: string[],
): TaskGroup[] {
  const anc = ancestorsMap(tags)
  const depthOf = new Map<string, number>()
  for (const t of tags) depthOf.set(t.name, anc.get(t.name)?.length ?? 0)

  const validSelected = selected.filter((s) => depthOf.has(s))
  const filtering = validSelected.length > 0
  const visible = new Set(filtering ? validSelected : tags.map((t) => t.name))

  /** 任务的归宿标签:可见标签里离它的标签们最近的祖先(含自己),取最深 */
  const ownerOf = (task: BoardTask): string | null => {
    let best: string | null = null
    let bestDepth = -1
    for (const tag of task.tags) {
      const chain = [tag, ...(anc.get(tag) ?? [])]
      const hit = chain.find((c) => visible.has(c))
      if (hit === undefined) continue
      const d = depthOf.get(hit) ?? 0
      if (d > bestDepth) {
        best = hit
        bestDepth = d
      }
    }
    return best
  }

  const byOwner = new Map<string, BoardTask[]>()
  const untagged: BoardTask[] = []
  for (const task of tasks) {
    // 勾选态:不匹配筛选的直接不出现(与旧筛选语义一致)
    if (filtering) {
      const sel = new Set(validSelected)
      const hit = task.tags.some(
        (t) => sel.has(t) || (anc.get(t) ?? []).some((a) => sel.has(a)),
      )
      if (!hit) continue
    }
    const owner = ownerOf(task)
    if (owner === null) untagged.push(task)
    else {
      const arr = byOwner.get(owner) ?? []
      arr.push(task)
      byOwner.set(owner, arr)
    }
  }

  // 组内按重要性降序(两种 importance 同量级:log 值)
  for (const list of byOwner.values()) list.sort((a, b) => b.importance - a.importance)
  untagged.sort((a, b) => b.importance - a.importance)

  // 树前序遍历产出组(父组在前,子组嵌后);剪掉整棵子树都没任务的节点。
  // 只勾子标签时父标签不可见:子组提升到顶层,深度按「可见祖先数」重算
  const visibleAnc = (name: string): number =>
    (anc.get(name) ?? []).filter((a) => visible.has(a)).length
  const build = (nodes: TagNode[]): TaskGroup[] =>
    nodes.flatMap((n) => {
      const kids = build(n.children)
      if (!visible.has(n.name)) return kids
      const own = byOwner.get(n.name) ?? []
      if (!own.length && !kids.length) return []
      return [{ name: n.name, depth: visibleAnc(n.name), tasks: own }, ...kids]
    })
  const groups = build(buildTree(tags))

  if (untagged.length) groups.push({ name: UNTAGGED, depth: 0, tasks: untagged })
  return groups
}
