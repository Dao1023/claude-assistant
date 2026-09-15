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
  /** 平铺标签(带父指针,parent 为父标签名,根为 null),筛选栏/表单据此建树 */
  tags: TagInfo[]
}

/** 平铺标签(层级) */
export interface TagInfo {
  name: string
  parent: string | null
}

/** 管理页标签树节点(count=直接活跃任务数) */
export interface TagTreeNode {
  id: number
  name: string
  parent_id: number | null
  count: number
  children: TagTreeNode[]
}

/** GET /api/tags 返回(完整标签树,含无活跃任务的) */
export interface TagsResponse {
  tree: TagTreeNode[]
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
  /** 到点时刻('YYYY-MM-DD HH:MM',边界字符串,发回后端 to_ts 转 int) */
  until: string
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

/** 免打扰总闸当前状态 */
export interface DndStatus {
  /** 此刻是否冻结中(夜间窗口或临时 DND 任一命中) */
  active: boolean
  /** 临时 DND 到期时间戳(Unix 秒),无则 null */
  until: number | null
  /** until 的人话字符串,供直接显示 */
  until_str: string | null
  /** 夜间免打扰恢复到几点(0-23) */
  night_end: number
}

/** GET /api/funnel 返回 */
export interface FunnelResponse {
  layers: FunnelLayer[]
  will_push: WillPushTask[]
  poll_interval: number
  dnd: DndStatus
}

/** 对话时间线一条(供浮窗重载后回填)。role: user=你说 / ai=AI 说 / system=旁观判断 */
export interface AiHistoryEntry {
  role: 'user' | 'ai' | 'system'
  text: string
  ts?: number
  /** system 行细分:observe=一次判断 / silent=选择沉默 / llm_error=模型失败 */
  kind?: 'observe' | 'silent' | 'llm_error'
  /** observe: AI 当时看到的完整上下文(任务清单+事件流原文),前端全展开 */
  prompt?: string
  /** observe: 触发这次判断的事件 */
  trigger?: Record<string, unknown>
}

/** GET /api/ai/history 返回(正序,最新在尾) */
export interface AiHistoryResponse {
  entries: AiHistoryEntry[]
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
