/** START 驱动任务(越久越重要) */
export interface StartTask {
  id: string
  title: string
  importance: number
  /** 距上次多少天 */
  days_since: number | null
  /** 预期间隔(天),重要性归一化分母 */
  expected_days?: number | null
  tags: string[]
  anchor?: string
}

/** DDL 驱动任务(越近越急) */
export interface EndTask {
  id: string
  title: string
  importance: number
  /** 重复间隔(天),空=非周期 */
  recurrence_days?: number | null
  tags: string[]
  /** 'YYYY-MM-DD HH:MM',倒计时由前端据此自算 */
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
  /** start:预期间隔(天) */
  expected_days?: number | null
  /** end:重复间隔(天),空=非周期 */
  recurrence_days?: number | null
  /** 仅 start:完成后是否重置 */
  is_cyclic: number
  /** 推迟到此时间(字符串),null=未推迟 */
  snooze_until?: string | null
  priority: number
  status: string
  created: string
  tags: string[]
  importance: number
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

/** 一个推迟预设选项 */
export interface SnoozeOption {
  key: string
  label: string
  /** 到点的 Unix 秒 */
  until: number
}

/** GET /api/snooze-options 返回 */
export interface SnoozeOptionsResponse {
  options: SnoozeOption[]
}

/** 一项可编辑的通知规则 */
export interface EditableSetting {
  key: string
  value: number
  type: 'float' | 'int'
  unit: string
  label: string
  desc: string
  min: number
  max: number
}

/** 一段只读规则说明 */
export interface ReadonlyRule {
  title: string
  desc: string
}

/** GET /api/settings 返回 */
export interface RulesResponse {
  editable: EditableSetting[]
  readonly: ReadonlyRule[]
}

/** 漏斗一层(实时统计) */
export interface FunnelLayer {
  id: string
  label: string
  desc: string
  /** 这层当前筛掉了几个任务 */
  blocked_count: number
  /** 被这层挡住的任务(供展开) */
  blocked_tasks: { id: string; title: string; reason: string }[]
  /** 挂在该层的配置项 */
  settings: EditableSetting[]
}

/** 本轮将弹出的任务 */
export interface WillPushTask {
  id: string
  title: string
  stage: string
}

/** GET /api/funnel 返回 */
export interface FunnelResponse {
  layers: FunnelLayer[]
  will_push: WillPushTask[]
  poll_interval: number
}

/** 新增任务表单(POST /api/tasks)。drive 创建时定死。 */
export interface AddTaskPayload {
  title: string
  drive: 'start' | 'end'
  deadline?: string | null
  anchor?: string | null
  /** start:预期间隔(天) */
  expected_days?: number | null
  /** end:重复间隔(天),空=非周期 */
  recurrence_days?: number | null
  /** 仅 start:完成后是否重置 */
  is_cyclic?: number
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
  expected_days?: number | null
  recurrence_days?: number | null
  is_cyclic?: number
  /** 传了则覆盖式更新;空数组=清空;不传=不动 */
  tags?: string[]
}
