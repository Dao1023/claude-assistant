<script setup lang="ts">
/**
 * 通知浮窗页(/notify):pywebview 无框置顶窗的内容,列出当前该催的任务。
 *
 * 与面板同一份前端代码,但形态不同:无导航、滚动列表、即点即处理。
 * 数据来自 /api/funnel 的 will_push(与真实推送同源,保证「弹的就是该催的」)。
 * 按钮走已测过的 REST API(完成/稍后带留言);底部「全部稍后」复用临时免打扰。
 * 处理完一个就重拉;空了就提示——浮窗由用户随手关掉(easy_drag 可拖)。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  doneTask,
  fetchFunnel,
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
const loaded = ref(false)

const STAGE_LABEL: Record<string, string> = {
  gentle: '提醒',
  escalating: '催办',
  crisis: '紧急',
}

async function load() {
  try {
    const f = await fetchFunnel()
    tasks.value = f.will_push
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载失败')
  } finally {
    loaded.value = true
  }
}

async function onDone(t: WillPushTask) {
  busy.value[t.id] = true
  try {
    await doneTask(t.id, notes.value[t.id]?.trim() || undefined)
    ElMessage.success(`已完成「${t.title}」`)
    await load()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    busy.value[t.id] = false
  }
}

async function onSnooze(t: WillPushTask, until?: string) {
  busy.value[t.id] = true
  try {
    await snoozeTask(t.id, until, notes.value[t.id]?.trim() || undefined)
    expandedSnooze.value[t.id] = false
    ElMessage.success(`已推迟「${t.title}」`)
    await load()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    busy.value[t.id] = false
  }
}

function toggleSnooze(id: string) {
  expandedSnooze.value[id] = !expandedSnooze.value[id]
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

// 每 30s 轻刷一次,跟着调度节奏;窗口关了就停了,无需精确
let timer: number | undefined
onMounted(async () => {
  await load()
  fetchSnoozeOptions().then((r) => (options.value = r.options)).catch(() => {})
  timer = window.setInterval(load, 30000)
})
onUnmounted(() => window.clearInterval(timer))
</script>

<template>
  <div class="notify-page">
    <div class="np-head">
      <span class="np-title">🔔 待办</span>
      <span v-if="tasks.length" class="np-count">{{ tasks.length }}</span>
    </div>

    <div v-if="loaded && !tasks.length" class="np-empty">
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
