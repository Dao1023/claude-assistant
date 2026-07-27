import type {
  AddTaskPayload,
  PushesResponse,
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

/** 任务动作(完成/稍后/关闭),统一走 POST /api/tasks/{id}/{action}。 */
async function postAction(id: string, action: 'done' | 'snooze' | 'close'): Promise<void> {
  const res = await fetch(`/api/tasks/${id}/${action}`, { method: 'POST' })
  if (!res.ok) {
    throw new Error(res.status === 404 ? '任务不存在' : `操作失败:${res.status} ${res.statusText}`)
  }
}

/** 完成任务(周期任务自动克隆下一个)。 */
export const doneTask = (id: string) => postAction(id, 'done')
/** 稍后(记一条 push_log,冷却期内不催)。 */
export const snoozeTask = (id: string) => postAction(id, 'snooze')
/** 关闭任务(不再催,周期任务不再克隆)。 */
export const closeTask = (id: string) => postAction(id, 'close')

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
