/** START 驱动任务(越久越重要) */
export interface StartTask {
  id: number
  title: string
  importance: number
  /** 距上次多少天 */
  days_since: number | null
  tags: string[]
  anchor?: string
  cycle_days?: number
}

/** DDL 驱动任务(越近越急) */
export interface EndTask {
  id: number
  title: string
  importance: number
  /** 人话倒计时,如 "还剩 4 小时" / "已过期" / "还剩 2 天" */
  countdown: string
  tags: string[]
  deadline?: string
}

/** GET /api/tasks 返回 */
export interface TasksResponse {
  starts: StartTask[]
  ends: EndTask[]
  tags: string[]
}
