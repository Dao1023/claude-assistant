<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close } from '@element-plus/icons-vue'

import { closeTask, doneTask, fetchSnoozeOptions, fetchTaskDetail, fetchTaskPushes, snoozeTask, unsnoozeTask } from '@/api/client'
import type { PushRecord, SnoozeOption, TaskDetail } from '@/types'

interface Props {
  /** 抽屉是否可见(v-model) */
  modelValue: boolean
  /** 当前要展示的任务 id;null 表示未选中 */
  taskId: string | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  /** 任务被操作(完成/稍后/关闭)后,通知父组件刷新列表 */
  changed: []
  /** 点"编辑":把当前任务详情交给父组件去开编辑表单 */
  edit: [task: TaskDetail]
}>()

const detail = ref<TaskDetail | null>(null)
const pushes = ref<PushRecord[]>([])
const loading = ref(false)
/** 动作按钮防重复点击 */
const acting = ref(false)

/** 手机端抽屉整屏(100%),桌面 420px。整屏后没有"点外面"可关,故需显式关闭按钮。 */
const MOBILE = '(max-width: 767px)'
const isMobile = ref(false)
let mql: MediaQueryList | null = null
function onMql(e: MediaQueryListEvent) {
  isMobile.value = e.matches
}
onMounted(() => {
  mql = window.matchMedia(MOBILE)
  isMobile.value = mql.matches
  mql.addEventListener('change', onMql)
})
onBeforeUnmount(() => mql?.removeEventListener('change', onMql))

/** 与 TaskCard 一致的重要性着色 */
const importanceClass = computed(() => {
  const v = detail.value?.importance ?? 0
  if (v >= 1.0) return 'imp-red'
  if (v >= 0.3) return 'imp-orange'
  if (v >= 0) return 'imp-blue'
  return 'imp-gray'
})

const importanceText = computed(() => (detail.value?.importance ?? 0).toFixed(2))

const driveText = computed(() => {
  if (!detail.value) return ''
  return detail.value.drive === 'start' ? 'START · 越久越重要' : 'DDL · 越近越急'
})

/** 周期间隔说明(start 预期 / end 重复) */
const cycleText = computed(() => {
  const d = detail.value
  if (!d) return null
  if (d.drive === 'start') {
    return d.expected_days ? `约 ${d.expected_days} 天完成` : null
  }
  return d.recurrence_days ? `每 ${d.recurrence_days} 天重复` : null
})

const statusText = computed(() => {
  const map: Record<string, string> = {
    active: '进行中',
    done: '已完成',
    archived: '已归档',
  }
  return detail.value ? (map[detail.value.status] ?? detail.value.status) : ''
})

/** stage → 中文 + 时间轴 dot 颜色 */
const stageMap: Record<string, { text: string; color: string }> = {
  gentle: { text: '提醒', color: '#5b9bd5' },
  escalating: { text: '催办', color: '#e6a23c' },
  crisis: { text: '紧急', color: '#e05252' },
}

function stageText(stage: string): string {
  return stageMap[stage]?.text ?? stage
}
function stageColor(stage: string): string {
  return stageMap[stage]?.color ?? '#909399'
}

function responseText(response: string | null): string {
  if (response === 'done') return '已完成'
  if (response === 'snoozed') return '稍后'
  return '未响应'
}

async function load(id: string) {
  loading.value = true
  detail.value = null
  pushes.value = []
  try {
    const [d, p] = await Promise.all([fetchTaskDetail(id), fetchTaskPushes(id)])
    detail.value = d
    pushes.value = p.pushes
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载任务详情失败')
  } finally {
    loading.value = false
  }
}

/** 打开抽屉且有任务 id 时加载;关闭时清空 */
watch(
  () => [props.modelValue, props.taskId] as const,
  ([visible, id]) => {
    if (visible && id) {
      load(id)
    } else if (!visible) {
      detail.value = null
      pushes.value = []
    }
  },
  { immediate: true },
)

function handleUpdate(value: boolean) {
  emit('update:modelValue', value)
}

/** 只有进行中的任务才显示动作按钮 */
const isActive = computed(() => detail.value?.status === 'active')

/** 执行动作:完成/稍后/关闭。成功后关抽屉 + 通知父组件刷新。 */
async function act(action: 'done' | 'snooze' | 'close') {
  if (!detail.value || acting.value) return

  // 关闭是不可逆操作(周期任务不再克隆),先确认
  if (action === 'close') {
    try {
      await ElMessageBox.confirm(
        `确定关闭「${detail.value.title}」吗?关闭后不再提醒。`,
        '关闭任务',
        { confirmButtonText: '关闭', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return // 用户取消
    }
  }

  acting.value = true
  try {
    const fn = { done: doneTask, close: closeTask }[action as 'done' | 'close']
    await fn(detail.value.id)
    const msg = { done: '已完成', close: '已关闭' }[action as 'done' | 'close']
    // 完成会克隆下一个的:start 周期(is_cyclic)或 end 周期(recurrence_days 非空)
    const d = detail.value
    const willClone =
      action === 'done' &&
      (d.drive === 'start' ? Boolean(d.is_cyclic) : d.recurrence_days != null)
    ElMessage.success(willClone ? `${msg},已生成下一个周期任务` : msg)
    emit('update:modelValue', false) // 关抽屉
    emit('changed')                  // 让父组件刷新列表
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    acting.value = false
  }
}

// ---------- 推迟(稍后) ----------

/** 推迟选项弹窗状态 */
const snoozeVisible = ref(false)
const snoozeOptions = ref<SnoozeOption[]>([])
/** 自定义推迟时间('YYYY-MM-DD HH:mm') */
const customUntil = ref('')

/** 打开推迟选择:按当前任务拉预设(start=预期×系数,end=剩余×系数) */
async function openSnooze() {
  snoozeVisible.value = true
  customUntil.value = ''
  try {
    const res = await fetchSnoozeOptions(detail.value?.id)
    snoozeOptions.value = res.options
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载推迟选项失败')
  }
}

/** 执行推迟。until 为 'YYYY-MM-DD HH:mm' 字符串,缺省(空)按 1 小时。 */
async function doSnooze(until?: string) {
  if (!detail.value || acting.value) return
  acting.value = true
  try {
    await snoozeTask(detail.value.id, until || undefined)
    ElMessage.success('已推迟')
    snoozeVisible.value = false
    emit('update:modelValue', false)
    emit('changed')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '推迟失败')
  } finally {
    acting.value = false
  }
}

/** 选预设:until 已是 'YYYY-MM-DD HH:mm' 边界字符串,直接透传(与弹窗同源) */
function pickPreset(until: string) {
  doSnooze(until)
}

/** 取消推迟:恢复正常催促,刷新详情 */
async function doUnsnooze() {
  if (!detail.value || acting.value) return
  acting.value = true
  try {
    await unsnoozeTask(detail.value.id)
    ElMessage.success('已取消推迟')
    emit('changed')
    await load(detail.value.id)   // 刷新详情,清掉"已推迟到 X"
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    :size="isMobile ? '100%' : '420px'"
    :with-header="false"
    @update:model-value="handleUpdate"
  >
    <div v-loading="loading" class="drawer-body">
      <template v-if="detail">
        <!-- 标题区 -->
        <div class="head">
          <h2 class="head-title">{{ detail.title }}</h2>
          <div class="head-right">
            <span class="imp-badge" :class="importanceClass">{{ importanceText }}</span>
            <el-button
              class="head-close"
              :icon="Close"
              text
              size="small"
              title="关闭"
              @click="handleUpdate(false)"
            />
          </div>
        </div>

        <!-- 详情区 -->
        <dl class="meta">
          <div class="meta-row">
            <dt>类型</dt>
            <dd>{{ driveText }}</dd>
          </div>
          <div v-if="detail.tags.length" class="meta-row">
            <dt>标签</dt>
            <dd>
              <span v-for="t in detail.tags" :key="t" class="tag-chip">#{{ t }}</span>
            </dd>
          </div>
          <div class="meta-row">
            <dt>优先级</dt>
            <dd>{{ detail.priority }}</dd>
          </div>
          <div class="meta-row">
            <dt>状态</dt>
            <dd>{{ statusText }}</dd>
          </div>
          <div v-if="cycleText" class="meta-row">
            <dt>周期</dt>
            <dd>{{ cycleText }}</dd>
          </div>
          <div v-if="detail.anchor" class="meta-row">
            <dt>锚点</dt>
            <dd>{{ detail.anchor }}</dd>
          </div>
          <div v-if="detail.deadline" class="meta-row">
            <dt>截止</dt>
            <dd>{{ detail.deadline }}</dd>
          </div>
          <div v-if="detail.snooze_until" class="meta-row">
            <dt>已推迟</dt>
            <dd>
              到 {{ detail.snooze_until }}
              <el-button link type="primary" size="small" :loading="acting" @click="doUnsnooze">
                取消推迟
              </el-button>
            </dd>
          </div>
          <div class="meta-row">
            <dt>创建时间</dt>
            <dd>{{ detail.created }}</dd>
          </div>
          <div v-if="detail.note" class="meta-row">
            <dt>备注</dt>
            <dd class="note">{{ detail.note }}</dd>
          </div>
        </dl>

        <!-- 动作按钮区(仅进行中的任务) -->
        <div v-if="isActive" class="actions">
          <el-button :loading="acting" @click="emit('edit', detail!)">编辑</el-button>
          <el-button type="success" :loading="acting" @click="act('done')">完成</el-button>
          <el-button :loading="acting" @click="openSnooze">稍后</el-button>
          <el-button type="danger" plain :loading="acting" @click="act('close')">关闭</el-button>
        </div>

        <!-- 推迟时长选择弹窗 -->
        <el-dialog v-model="snoozeVisible" title="推迟到什么时候" width="360px" append-to-body>
          <div class="snooze-presets">
            <el-button
              v-for="opt in snoozeOptions"
              :key="opt.key"
              @click="pickPreset(opt.until)"
            >
              {{ opt.label }}
            </el-button>
          </div>
          <el-divider content-position="left">或自定义</el-divider>
          <el-date-picker
            v-model="customUntil"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm"
            placeholder="选择推迟到的时间"
            style="width: 100%"
          />
          <template #footer>
            <el-button @click="snoozeVisible = false">取消</el-button>
            <el-button type="primary" :disabled="!customUntil" :loading="acting" @click="doSnooze(customUntil)">
              推迟
            </el-button>
          </template>
        </el-dialog>

        <!-- 提醒记录区 -->
        <h3 class="section-title">提醒记录</h3>
        <el-timeline v-if="pushes.length" class="push-timeline">
          <el-timeline-item
            v-for="(p, i) in pushes"
            :key="i"
            :color="stageColor(p.stage)"
            :timestamp="p.pushed_at"
            placement="top"
          >
            <div class="push-line">
              <span class="push-stage" :style="{ color: stageColor(p.stage) }">
                {{ stageText(p.stage) }}
              </span>
              <span class="push-response">{{ responseText(p.response) }}</span>
            </div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="还没有提醒记录" :image-size="70" />
      </template>

      <el-empty v-else-if="!loading" description="未加载到任务详情" :image-size="80" />
    </div>
  </el-drawer>
</template>

<style scoped>
.drawer-body {
  padding: 4px 4px 16px;
  min-height: 200px;
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid #f0f1f5;
}
.head-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.head-close {
  color: #909399;
}
.head-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.4;
  color: #2c3e50;
  word-break: break-word;
}

.imp-badge {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  padding: 1px 7px;
  border-radius: 6px;
  line-height: 1.5;
}
.imp-red {
  color: #e05252;
  background: rgba(224, 82, 82, 0.1);
}
.imp-orange {
  color: #e6a23c;
  background: rgba(230, 162, 60, 0.12);
}
.imp-blue {
  color: #5b9bd5;
  background: rgba(91, 155, 213, 0.12);
}
.imp-gray {
  color: #909399;
  background: rgba(144, 147, 153, 0.12);
}

.meta {
  margin: 14px 0 0;
}
.meta-row {
  display: flex;
  gap: 12px;
  padding: 5px 0;
  font-size: 13px;
  line-height: 1.6;
}
.meta-row dt {
  flex-shrink: 0;
  width: 64px;
  color: #909399;
}
.meta-row dd {
  margin: 0;
  color: #2c3e50;
  word-break: break-word;
}
.meta-row .note {
  white-space: pre-wrap;
}

.tag-chip {
  display: inline-block;
  font-size: 11px;
  color: #5b9bd5;
  background: rgba(91, 155, 213, 0.1);
  border-radius: 5px;
  padding: 0 5px;
  line-height: 1.6;
  white-space: nowrap;
  margin-right: 4px;
}

.actions {
  display: flex;
  gap: 10px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid #f0f1f5;
}

.snooze-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.snooze-presets .el-button {
  margin-left: 0;
  flex: 1 1 calc(50% - 8px);
}
.actions .el-button {
  flex: 1;
  margin-left: 0;
}

.section-title {
  margin: 20px 0 12px;
  font-size: 14px;
  font-weight: 700;
  color: #2c3e50;
  padding-top: 14px;
  border-top: 1px solid #f0f1f5;
}

.push-timeline {
  padding-left: 2px;
}
.push-line {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}
.push-stage {
  font-weight: 600;
}
.push-response {
  color: #909399;
  font-size: 12px;
}
</style>
