import type { TasksResponse } from '@/types'

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
