<script setup lang="ts">
/**
 * 通知浮窗页(/notify):pywebview 无框置顶窗的内容,列出通知层推来的任务。
 *
 * 被动响应:不主动查询、不轮询。经 WebSocket 订阅 /ws,收「notify」事件
 * (通知层 tick_push 挑好后推来的快照)就渲染;收「done/snooze」把对应项移除。
 * 用户点完成/推迟走 REST 回写,后端再经 WS 广播,各端同步。空了就提示可关窗。
 * 与通知层解耦:它不知道什么是冷却/定档,只渲染被推来的快照。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  doneTask,
  fetchSnoozeOptions,
  setDnd,
  snoozeTask,
} from '@/api/client'
import type { SnoozeOption, WillPushTask } from '@/types'

const tasks = ref<WillPushTask[]>([])
const options = ref<SnoozeOption[]>([])
const notes = ref<Record<string, string>>({})        // 每卡的留言草稿
const expandedSnooze = ref<Record<string, boolean>>({})
const busy = ref<Record<string, boolean>>({})
const dndBusy = ref(false)

const STAGE_LABEL: Record<string, string> = {
  gentle: '提醒',
  escalating: '催办',
  crisis: '紧急',
}

let ws: WebSocket | null = null
let retryTimer: number | undefined

function connect() {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${window.location.host}/ws`)
  ws.onmessage = (e) => {
    try {
      handle(JSON.parse(e.data))
    } catch { /* 忽略坏消息 */ }
  }
  ws.onclose = () => {
    // 断线重连(服务重启/浮窗重开时)
    retryTimer = window.setTimeout(connect, 2000)
  }
}

function handle(ev: { type: string; tasks?: WillPushTask[]; task_id?: string }) {
  if (ev.type === 'notify' && ev.tasks) {
    // 通知层推来新一轮快照:并集加入(已存在的保留其留言草稿)
    for (const t of ev.tasks) {
      if (!tasks.value.some((x) => x.id === t.id)) tasks.value.push(t)
    }
  } else if ((ev.type === 'done' || ev.type === 'snooze') && ev.task_id) {
    remove(ev.task_id)
  }
}

function remove(id: string) {
  tasks.value = tasks.value.filter((t) => t.id !== id)
}

async function onDone(t: WillPushTask) {
  busy.value[t.id] = true
  try {
    await doneTask(t.id, notes.value[t.id]?.trim() || undefined)
    remove(t.id)                      // 本地先移除;后端 WS 广播再兜底同步
    ElMessage.success(`已完成「${t.title}」`)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    busy.value[t.id] = false
  }
}

async function onSnooze(t: WillPushTask, until?: string | number) {
  busy.value[t.id] = true
  try {
    await snoozeTask(t.id, until, notes.value[t.id]?.trim() || undefined)
    expandedSnooze.value[t.id] = false
    remove(t.id)
    ElMessage.success(`已推迟「${t.title}」`)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    busy.value[t.id] = false
  }
}

function toggleSnooze(id: string) {
  expandedSnooze.value[id] = !expandedSnooze.value[id]
}

/** 关闭按钮:优先调 pywebview js_api 隐藏(显式桥,可靠);兜底 window.close()。 */
function hideWindow() {
  const api = (window as unknown as { pywebview?: { api?: { hide?: () => void } } }).pywebview?.api
  if (api?.hide) {
    api.hide()
  } else {
    window.close()
  }
}

/** 全部稍后:开 1 小时临时免打扰(复用 DND 总闸),用户随手关窗即可。 */
async function snoozeAll() {
  dndBusy.value = true
  try {
    const until = new Date(Date.now() + 3600 * 1000)
    const pad = (n: number) => String(n).padStart(2, '0')
    const str = `${until.getFullYear()}-${pad(until.getMonth() + 1)}-${pad(until.getDate())} ${pad(until.getHours())}:${pad(until.getMinutes())}`
    await setDnd(str)
    ElMessage.success('全部稍后 1 小时,可关窗')
    tasks.value = []
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    dndBusy.value = false
  }
}

onMounted(() => {
  connect()
  fetchSnoozeOptions().then((r) => (options.value = r.options)).catch(() => {})
})
onUnmounted(() => {
  window.clearTimeout(retryTimer)
  ws?.close()
})
</script>

<template>
  <div class="notify-page">
    <div class="np-head">
      <span class="np-title">🔔 待办</span>
      <span v-if="tasks.length" class="np-count">{{ tasks.length }}</span>
      <button class="np-close" title="隐藏(有通知再弹)" @click="hideWindow">×</button>
    </div>

    <div v-if="!tasks.length" class="np-empty">
      这会儿没有该催的了 🎉<br />可以关掉这个窗口
    </div>

    <div class="np-list">
      <div
        v-for="t in tasks"
        :key="t.id"
        class="np-card"
        :class="`stage-${t.stage}`"
      >
        <div class="np-card-top">
          <span class="np-stage">{{ STAGE_LABEL[t.stage] || t.stage }}</span>
          <span class="np-card-title">{{ t.title }}</span>
        </div>

        <input
          v-model="notes[t.id]"
          class="np-note"
          type="text"
          placeholder="顺手记一句:为什么…"
          :disabled="busy[t.id]"
        />

        <div class="np-actions">
          <button class="np-btn primary" :disabled="busy[t.id]" @click="onDone(t)">完成</button>
          <button class="np-btn" :disabled="busy[t.id]" @click="toggleSnooze(t.id)">稍后</button>
        </div>

        <div v-if="expandedSnooze[t.id]" class="np-snooze-opts">
          <button
            class="np-btn small"
            :disabled="busy[t.id]"
            @click="onSnooze(t)"
          >1 小时</button>
          <button
            v-for="o in options"
            :key="o.key"
            class="np-btn small"
            :disabled="busy[t.id]"
            @click="onSnooze(t, o.until)"
          >{{ o.label }}</button>
        </div>
      </div>
    </div>

    <button
      v-if="tasks.length"
      class="np-snooze-all"
      :disabled="dndBusy"
      @click="snoozeAll"
    >🌙 全部稍后 1 小时</button>
  </div>
</template>

<style scoped>
.notify-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f5f7fa;
  padding: 14px;
  box-sizing: border-box;
  font-family: 'Microsoft YaHei', sans-serif;
}
.np-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.np-title {
  font-size: 15px;
  font-weight: 600;
  color: #2c3e50;
}
.np-count {
  background: #e05252;
  color: #fff;
  font-size: 11px;
  border-radius: 10px;
  padding: 1px 7px;
}
.np-close {
  margin-left: auto;
  border: none;
  background: transparent;
  color: #909399;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 5px;
  font-family: inherit;
}
.np-close:hover {
  background: #eceff3;
  color: #555;
}
.np-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: #909399;
  font-size: 13px;
  line-height: 1.8;
}
.np-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.np-card {
  background: #fff;
  border-radius: 8px;
  padding: 10px 12px;
  border-left: 4px solid #5b9bd5;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.np-card.stage-escalating {
  border-left-color: #e8a33d;
}
.np-card.stage-crisis {
  border-left-color: #e05252;
}
.np-card-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.np-stage {
  font-size: 11px;
  font-weight: 600;
  color: #5b9bd5;
  flex-shrink: 0;
}
.stage-escalating .np-stage {
  color: #e8a33d;
}
.stage-crisis .np-stage {
  color: #e05252;
}
.np-card-title {
  font-size: 14px;
  color: #222;
  font-weight: 600;
  line-height: 1.4;
}
.np-note {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 12px;
  color: #606266;
  margin-bottom: 8px;
  outline: none;
  font-family: inherit;
}
.np-note:focus {
  border-color: #5b9bd5;
}
.np-actions {
  display: flex;
  gap: 8px;
}
.np-btn {
  border: 1px solid #dcdfe6;
  background: #fff;
  color: #333;
  border-radius: 6px;
  padding: 5px 14px;
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
}
.np-btn:hover:not(:disabled) {
  border-color: #5b9bd5;
  color: #5b9bd5;
}
.np-btn.primary {
  background: #5b9bd5;
  border-color: #5b9bd5;
  color: #fff;
}
.np-btn.primary:hover:not(:disabled) {
  background: #4a8ac8;
}
.np-btn.small {
  padding: 3px 10px;
  font-size: 11px;
}
.np-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.np-snooze-opts {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #eee;
}
.np-snooze-all {
  margin-top: 12px;
  width: 100%;
  border: 1px solid #c9d6ec;
  background: #eef3fb;
  color: #4a6a9c;
  border-radius: 8px;
  padding: 9px;
  font-size: 13px;
  cursor: pointer;
  font-family: inherit;
}
.np-snooze-all:hover:not(:disabled) {
  background: #e0eafa;
}
.np-snooze-all:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
