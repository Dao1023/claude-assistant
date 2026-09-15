import type {
  AddTaskPayload,
  AiHistoryResponse,
  EditableSetting,
  FunnelResponse,
  PushesResponse,
  RulesResponse,
  SnoozeOptionsResponse,
  TagsResponse,
  TaskDetail,
  TasksResponse,
  UpdateTaskPayload,
} from '@/types'

/**
 * 拉取面板数据。开发模式经 Vite 代理到 FastAPI,生产模式同源。
 * 失败时抛错,由调用方用 el-message 提示。
 */
export async function fetchTasks(): Promise<TasksResponse> {
  const res = await fetch('/api/tasks', {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) {
    throw new Error(`请求失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as TasksResponse
}

/** 拉取单任务详情。404 时抛错,由调用方提示。 */
export async function fetchTaskDetail(id: string): Promise<TaskDetail> {
  const res = await fetch(`/api/tasks/${id}`, {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) {
    throw new Error(res.status === 404 ? '任务不存在' : `请求失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as TaskDetail
}

/** 拉取任务的提醒记录(已按时间倒序)。 */
export async function fetchTaskPushes(id: string): Promise<PushesResponse> {
  const res = await fetch(`/api/tasks/${id}/pushes`, {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) {
    throw new Error(`请求失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as PushesResponse
}

/** 任务动作(完成/关闭),统一走 POST /api/tasks/{id}/{action}。可带 note 留言。 */
async function postAction(id: string, action: 'done' | 'close', note?: string): Promise<void> {
  const res = await fetch(`/api/tasks/${id}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(note ? { note } : {}),
  })
  if (!res.ok) {
    throw new Error(res.status === 404 ? '任务不存在' : `操作失败:${res.status} ${res.statusText}`)
  }
}

/** 完成任务(周期任务自动克隆下一个)。note 为留言。 */
export const doneTask = (id: string, note?: string) => postAction(id, 'done', note)
/** 关闭任务(不再催,周期任务不再克隆)。 */
export const closeTask = (id: string) => postAction(id, 'close')

/** 推迟任务。until 为 'YYYY-MM-DD HH:MM' 字符串(snooze-options 返回的边界格式),缺省 1 小时;note 为留言。 */
export async function snoozeTask(id: string, until?: string, note?: string): Promise<void> {
  const body: Record<string, string> = {}
  if (until !== undefined) body.until = until
  if (note) body.note = note
  const res = await fetch(`/api/tasks/${id}/snooze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(res.status === 404 ? '任务不存在' : `操作失败:${res.status} ${res.statusText}`)
  }
}

/** 拉取某任务的推迟选项(start=预期×系数,end=剩余×系数);taskId 缺省给兜底。 */
export async function fetchSnoozeOptions(taskId?: string): Promise<SnoozeOptionsResponse> {
  const url = taskId ? `/api/snooze-options?task_id=${encodeURIComponent(taskId)}` : '/api/snooze-options'
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`请求失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as SnoozeOptionsResponse
}

/** 清除推迟(恢复正常催促节奏)。 */
export async function unsnoozeTask(id: string): Promise<void> {
  const res = await fetch(`/api/tasks/${id}/snooze`, { method: 'DELETE' })
  if (!res.ok) {
    throw new Error(res.status === 404 ? '任务不存在' : `操作失败:${res.status} ${res.statusText}`)
  }
}

/** 新增任务。成功返回 { task_id, title }。 */
export async function addTask(payload: AddTaskPayload): Promise<{ task_id: string }> {
  const res = await fetch('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    throw new Error(`新增失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as { task_id: string }
}

/** 编辑任务(只传要改的字段)。 */
export async function updateTask(id: string, payload: UpdateTaskPayload): Promise<void> {
  const res = await fetch(`/api/tasks/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    throw new Error(res.status === 404 ? '任务不存在' : `保存失败:${res.status} ${res.statusText}`)
  }
}

/** 读后端 400 的 detail(中文提示)给调用方展示。 */
async function _detail(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `请求失败:${res.status}`
}

/** 完整标签树(管理页)。 */
export async function fetchTags(): Promise<TagsResponse> {
  const res = await fetch('/api/tags', { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(await _detail(res))
  return (await res.json()) as TagsResponse
}

/** 建标签;parentId 缺省=根级。重名/防环抛后端中文提示。 */
export async function createTag(name: string, parentId?: number | null): Promise<{ id: number }> {
  const res = await fetch('/api/tags', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, parent_id: parentId ?? null }),
  })
  if (!res.ok) throw new Error(await _detail(res))
  return (await res.json()) as { id: number }
}

/** 改标签:改名 / 移父(parentId 传 null=回根级)。不传=不动。 */
export async function updateTag(id: number, patch: { name?: string; parent_id?: number | null }): Promise<void> {
  const res = await fetch(`/api/tags/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!res.ok) {
    throw new Error(res.status === 404 ? '标签不存在' : await _detail(res))
  }
}

/** 删标签:子标签提升到它的父级 + 任务断关联。 */
export async function deleteTag(id: number): Promise<void> {
  const res = await fetch(`/api/tags/${id}`, { method: 'DELETE' })
  if (!res.ok) {
    throw new Error(res.status === 404 ? '标签不存在' : `删除失败:${res.status}`)
  }
}

/** 拉取全部通知规则(可编辑 + 只读说明)。 */
export async function fetchRules(): Promise<RulesResponse> {
  const res = await fetch('/api/settings', { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`请求失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as RulesResponse
}

/** 更新通知规则。values 为 { key: value };400 时抛后端 detail。 */
export async function updateSettings(values: Record<string, number>): Promise<EditableSetting[]> {
  const res = await fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ? JSON.stringify(detail.detail) : `保存失败:${res.status}`)
  }
  const body = (await res.json()) as { editable: EditableSetting[] }
  return body.editable
}

/** 拉取通知漏斗实时数据(每层筛掉了哪些任务)。 */
export async function fetchFunnel(): Promise<FunnelResponse> {
  const res = await fetch('/api/funnel', { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`请求失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as FunnelResponse
}

/** 开临时免打扰。until 为 'YYYY-MM-DD HH:MM' 到期时刻。 */
export async function setDnd(until: string): Promise<void> {
  const res = await fetch('/api/dnd', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ until }),
  })
  if (!res.ok) {
    throw new Error(`设置失败:${res.status} ${res.statusText}`)
  }
}

/** 立即恢复:清掉临时免打扰。 */
export async function clearDnd(): Promise<void> {
  const res = await fetch('/api/dnd', { method: 'DELETE' })
  if (!res.ok) {
    throw new Error(`恢复失败:${res.status} ${res.statusText}`)
  }
}

/** 拉取对话历史(供浮窗重载后回填对话流)。正序,只含 user/ai 两类。 */
export async function fetchAiHistory(limit = 50): Promise<AiHistoryResponse> {
  const res = await fetch(`/api/ai/history?limit=${limit}`, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`请求失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as AiHistoryResponse
}

/** 用户在浮窗回 AI 一句。 */
export async function replyAi(text: string): Promise<void> {
  const res = await fetch('/api/ai/reply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) {
    throw new Error(`发送失败:${res.status} ${res.statusText}`)
  }
}

/** AI 助手总开关当前状态(浮窗启动时决定显隐左列)。 */
export async function fetchAiStatus(): Promise<{ enabled: boolean }> {
  const res = await fetch('/api/ai/status', { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`请求失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as { enabled: boolean }
}

/** 开/关 AI 助手。enabled=false → 后端 judge 不再发 LLM 请求(省费用)。 */
export async function setAiEnabled(enabled: boolean): Promise<{ enabled: boolean }> {
  const res = await fetch('/api/ai/toggle', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
  if (!res.ok) {
    throw new Error(`切换失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as { enabled: boolean }
}
