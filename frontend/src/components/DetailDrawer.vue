<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { closeTask, doneTask, fetchTaskDetail, fetchTaskPushes, snoozeTask } from '@/api/client'
import type { PushRecord, TaskDetail } from '@/types'

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
    return d.expected_days ? `约每 ${d.expected_days} 天` : null
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
    const fn = { done: doneTask, snooze: snoozeTask, close: closeTask }[action]
    await fn(detail.value.id)
    const msg = { done: '已完成', snooze: '已稍后', close: '已关闭' }[action]
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
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    size="420px"
    :with-header="false"
    @update:model-value="handleUpdate"
  >
    <div v-loading="loading" class="drawer-body">
      <template v-if="detail">
        <!-- 标题区 -->
        <div class="head">
          <h2 class="head-title">{{ detail.title }}</h2>
          <span class="imp-badge" :class="importanceClass">{{ importanceText }}</span>
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
          <el-button :loading="acting" @click="act('snooze')">稍后</el-button>
          <el-button type="danger" plain :loading="acting" @click="act('close')">关闭</el-button>
        </div>

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
