/** START 驱动任务(越久越重要) */
export interface StartTask {
  id: string
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
  id: string
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

/** GET /api/tasks/{id} 单任务详情 */
export interface TaskDetail {
  id: string
  title: string
  note: string | null
  /** start=越久越重要 / end=越近越急 */
  drive: 'start' | 'end'
  deadline: string | null
  anchor: string | null
  cycle_days: number | null
  is_cyclic: number
  priority: number
  status: string
  created: string
  tags: string[]
  importance: number
  /** end 类任务的人话倒计时 */
  countdown?: string
  /** start 类任务的距今天数 */
  days_since?: number
}

/** 一条提醒记录 */
export interface PushRecord {
  pushed_at: string
  /** gentle / escalating / crisis */
  stage: string
  /** null / done / snoozed */
  response: string | null
}

/** GET /api/tasks/{id}/pushes 返回 */
export interface PushesResponse {
  pushes: PushRecord[]
}

/** 新增任务表单(POST /api/tasks)。drive 创建时定死。 */
export interface AddTaskPayload {
  title: string
  drive: 'start' | 'end'
  deadline?: string | null
  anchor?: string | null
  /** 设置即视为周期任务 */
  cycle_days?: number | null
  priority?: number
  note?: string | null
  tags?: string[]
}

/** 编辑任务表单(PUT /api/tasks/{id}),全部可选。 */
export interface UpdateTaskPayload {
  title?: string
  note?: string | null
  priority?: number
  deadline?: string | null
  anchor?: string | null
  cycle_days?: number | null
}
