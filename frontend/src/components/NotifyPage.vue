<script setup lang="ts">
/**
 * 通知浮窗页(/notify):pywebview 无框置顶窗,两列布局。
 *
 * 右列「待办」:通知层推来的任务快照(被动接收 /ws 的 notify/done/snooze),
 *   完成/推迟/留言走 REST,后端广播同步。
 * 左列「AI 助手」:第四层旁观 Agent 的对话记录 + 调用过程。
 *   ai_message 事件(经 /ws)追加 AI 气泡;用户回复走 /api/ai/reply;
 *   「AI 看了啥」展开拉 /api/ai/log 看它每次判断读了什么、为何说话/沉默。
 * 两列解耦:通知列不知什么是冷却/定档;AI 列不知什么是任务过滤,只渲染对话与日志。
 */
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  doneTask,
  fetchAiLog,
  fetchSnoozeOptions,
  replyAi,
  setDnd,
  snoozeTask,
} from '@/api/client'
import type { AiLogEntry, SnoozeOption, WillPushTask } from '@/types'

const tasks = ref<WillPushTask[]>([])
const options = ref<SnoozeOption[]>([])
const notes = ref<Record<string, string>>({})        // 每卡的留言草稿
const expandedSnooze = ref<Record<string, boolean>>({})
const busy = ref<Record<string, boolean>>({})
const dndBusy = ref(false)

// ---- AI 列 ----
interface ChatMsg { role: 'ai' | 'user'; text: string; ts: number }
const chat = ref<ChatMsg[]>([])
const replyDraft = ref('')
const replyBusy = ref(false)
const chatListEl = ref<HTMLElement | null>(null)
const replyInputEl = ref<HTMLInputElement | null>(null)   // 回复框 ref:发送后保持焦点
const showProcess = ref(false)                        // 「AI 看了啥」展开与否
const aiLog = ref<AiLogEntry[]>([])

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
    retryTimer = window.setTimeout(connect, 2000)
  }
}

function handle(ev: {
  type: string; tasks?: WillPushTask[]; task_id?: string
  text?: string; kind?: string; ts?: number
}) {
  if (ev.type === 'notify' && ev.tasks) {
    for (const t of ev.tasks) {
      if (!tasks.value.some((x) => x.id === t.id)) tasks.value.push(t)
    }
  } else if ((ev.type === 'done' || ev.type === 'snooze') && ev.task_id) {
    remove(ev.task_id)
  } else if (ev.type === 'ai_message' && ev.text) {
    pushChat('ai', ev.text, ev.ts)
  }
}

function remove(id: string) {
  tasks.value = tasks.value.filter((t) => t.id !== id)
}

// ---- AI 对话 ----

function pushChat(role: 'ai' | 'user', text: string, ts?: number) {
  chat.value.push({ role, text, ts: ts ?? Date.now() / 1000 })
  nextTick(() => {
    chatListEl.value?.scrollTo({ top: chatListEl.value.scrollHeight, behavior: 'smooth' })
  })
}

async function onReply() {
  const text = replyDraft.value.trim()
  if (!text) return
  replyBusy.value = true
  try {
    pushChat('user', text)
    replyDraft.value = ''
    await replyAi(text)               // AI 接话后经 /ws 推 ai_message 回来
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '发送失败')
  } finally {
    replyBusy.value = false
    // 发送后光标留在对话框,不用重新点(disabled 会丢焦点,恢复后补回)
    nextTick(() => replyInputEl.value?.focus())
  }
}

async function toggleProcess() {
  showProcess.value = !showProcess.value
  if (showProcess.value) {
    try {
      aiLog.value = (await fetchAiLog(50)).entries
    } catch { aiLog.value = [] }
  }
}

function fmtTime(ts?: number) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const LOG_KIND_LABEL: Record<string, string> = {
  observe: '👀 观察',
  silent: '🤫 沉默',
  speak: '💬 AI',
  user_reply: '🗣 用户回复',
  llm_error: '⚠️ 模型错误',
  error: '⚠️ 错误',
}

// ---- 待办列(完成/推迟/全部稍后) ----

async function onDone(t: WillPushTask) {
  busy.value[t.id] = true
  try {
    await doneTask(t.id, notes.value[t.id]?.trim() || undefined)
    remove(t.id)
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

function hideWindow() {
  const api = (window as unknown as { pywebview?: { api?: { hide?: () => void } } }).pywebview?.api
  if (api?.hide) {
    api.hide()
  } else {
    window.close()
  }
}

/** Esc = 点 ×(隐藏浮窗)。 */
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') hideWindow()
}

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
  window.addEventListener('keydown', onKeydown)   // Esc 隐藏
})
onUnmounted(() => {
  window.clearTimeout(retryTimer)
  window.removeEventListener('keydown', onKeydown)
  ws?.close()
})
</script>

<template>
  <div class="notify-page">
    <div class="np-head pywebview-drag-region">
      <span class="np-title">🔔 弹窗</span>
      <span v-if="tasks.length" class="np-count">{{ tasks.length }}</span>
      <button class="np-close" title="隐藏(有通知再弹)" @click="hideWindow">×</button>
    </div>

    <div class="np-cols">
      <!-- 左列:AI 助手对话 -->
      <section class="np-ai">
        <div class="np-ai-head">
          <span class="np-col-title">🤖 AI 助手</span>
          <button class="np-link" @click="toggleProcess">
            {{ showProcess ? '收起过程' : 'AI 看了啥' }}
          </button>
        </div>

        <!-- 调用过程(可展开) -->
        <div v-if="showProcess" class="np-process">
          <div v-if="!aiLog.length" class="np-process-empty">还没有观察记录</div>
          <div v-for="(e, i) in aiLog" :key="i" class="np-process-item">
            <span class="np-process-kind">{{ LOG_KIND_LABEL[e.kind] || e.kind }}</span>
            <span class="np-process-time">{{ fmtTime(e.ts) }}</span>
            <div v-if="e.text" class="np-process-text">{{ e.text }}</div>
            <div v-else-if="e.reason" class="np-process-text dim">{{ e.reason }}</div>
            <details v-if="e.prompt" class="np-process-prompt">
              <summary>看到的上下文</summary>
              <pre>{{ e.prompt }}</pre>
            </details>
          </div>
        </div>

        <!-- 对话流 -->
        <div ref="chatListEl" class="np-chat">
          <div v-if="!chat.length" class="np-chat-empty">
            AI 在后台看着你的任务动静。<br />觉得你不对劲时会在这里说话。
          </div>
          <div
            v-for="(m, i) in chat"
            :key="i"
            class="np-msg"
            :class="m.role"
          >
            <div class="np-bubble">{{ m.text }}</div>
            <span class="np-msg-time">{{ fmtTime(m.ts) }}</span>
          </div>
        </div>

        <!-- 回复框 -->
        <div class="np-reply">
          <input
            ref="replyInputEl"
            v-model="replyDraft"
            class="np-reply-input"
            type="text"
            placeholder="回 AI 一句…"
            :disabled="replyBusy"
            @keyup.enter="onReply"
          />
          <button class="np-btn primary small" :disabled="replyBusy || !replyDraft.trim()" @click="onReply">
            发
          </button>
        </div>
      </section>

      <!-- 右列:待办通知 -->
      <section class="np-tasks">
        <div class="np-col-title np-tasks-title">📋 待办</div>
        <div v-if="!tasks.length" class="np-empty">
          这会儿没有该催的了 🎉
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
              <button class="np-btn small" :disabled="busy[t.id]" @click="onSnooze(t)">1 小时</button>
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
      </section>
    </div>
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
  /* 顶部标题栏 = 拖拽把手:pywebview 认 pywebview-drag-region 类(非 Electron 的 app-region)。
     整窗 easy_drag 已关,只这里可拖,正文正常选文本。 */
  cursor: move;
  user-select: none;
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

/* 两列布局 */
.np-cols {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  min-height: 0;
}
.np-col-title {
  font-size: 13px;
  font-weight: 600;
  color: #2c3e50;
}
.np-ai,
.np-tasks {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #fff;
  border-radius: 10px;
  padding: 10px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.np-ai-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.np-link {
  border: none;
  background: transparent;
  color: #5b9bd5;
  font-size: 11px;
  cursor: pointer;
  padding: 2px 4px;
  font-family: inherit;
}
.np-link:hover {
  text-decoration: underline;
}

/* AI 调用过程 */
.np-process {
  max-height: 140px;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 6px;
  margin-bottom: 8px;
  background: #fafbfc;
}
.np-process-empty {
  color: #c0c4cc;
  font-size: 11px;
  text-align: center;
  padding: 8px 0;
}
.np-process-item {
  font-size: 11px;
  margin-bottom: 6px;
  color: #606266;
}
.np-process-kind {
  font-weight: 600;
}
.np-process-time {
  color: #c0c4cc;
  margin-left: 6px;
  font-size: 10px;
}
.np-process-text {
  margin-top: 2px;
  line-height: 1.4;
}
.np-process-text.dim {
  color: #909399;
}
.np-process-prompt summary {
  cursor: pointer;
  color: #5b9bd5;
  font-size: 10px;
}
.np-process-prompt pre {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 10px;
  color: #909399;
  max-height: 80px;
  overflow-y: auto;
  margin: 4px 0 0;
}

/* AI 对话流 */
.np-chat {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px 2px;
  min-height: 0;
}
.np-chat-empty {
  color: #c0c4cc;
  font-size: 12px;
  text-align: center;
  line-height: 1.8;
  margin: auto;
}
.np-msg {
  display: flex;
  flex-direction: column;
  max-width: 85%;
}
.np-msg.ai {
  align-self: flex-start;
}
.np-msg.user {
  align-self: flex-end;
  align-items: flex-end;
}
.np-bubble {
  padding: 7px 11px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
  /* 正文可选中复制(easy_drag 已关,天然可选;显式声明保险) */
  user-select: text;
  cursor: text;
}
.np-msg.ai .np-bubble {
  background: #f0f4f9;
  color: #2c3e50;
  border-top-left-radius: 2px;
}
.np-msg.user .np-bubble {
  background: #5b9bd5;
  color: #fff;
  border-top-right-radius: 2px;
}
.np-msg-time {
  font-size: 10px;
  color: #c0c4cc;
  margin-top: 2px;
}

/* 回复框 */
.np-reply {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.np-reply-input {
  flex: 1;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 6px 9px;
  font-size: 12px;
  color: #606266;
  outline: none;
  font-family: inherit;
}
.np-reply-input:focus {
  border-color: #5b9bd5;
}

/* 待办列 */
.np-tasks-title {
  margin-bottom: 8px;
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
  min-height: 0;
}
.np-card {
  background: #fff;
  border-radius: 8px;
  padding: 10px 12px;
  border-left: 4px solid #5b9bd5;
  border-top: 1px solid #f0f2f5;
  border-right: 1px solid #f0f2f5;
  border-bottom: 1px solid #f0f2f5;
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
