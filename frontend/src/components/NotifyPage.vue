<script setup lang="ts">
/**
 * 通知浮窗页(/notify):pywebview 无框置顶窗,两列布局。
 *
 * 右列「待办」:通知层推来的任务快照(被动接收 /ws 的 notify/done/snooze),
 *   完成/推迟/留言走 REST,后端广播同步。
 * 左列「AI 助手」:第四层旁观 Agent 的对话记录 + 调用过程。
 *   ai_message 事件(经 /ws)追加 AI 气泡;用户回复走 /api/ai/reply;
 *   「AI 看了啥」展开拉 /api/ai/log 看它每次判断读了什么、为何说话/沉默。
 * 两列解耦:通知列不知什么是过滤/定档;AI 列不知什么是任务过滤,只渲染对话与日志。
 */
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import {
  doneTask,
  fetchAiHistory,
  fetchAiLog,
  fetchRules,
  fetchSnoozeOptions,
  replyAi,
  setDnd,
  snoozeTask,
  updateSettings,
} from '@/api/client'
import type { AiLogEntry, SnoozeOption, WillPushTask } from '@/types'

const tasks = ref<WillPushTask[]>([])
const snoozeOptions = ref<Record<string, SnoozeOption[]>>({})   // 每任务的推迟选项(点「稍后」时按任务现取)
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
const showProcess = ref(false)                        // 「AI 上下文」展开与否
const aiLog = ref<AiLogEntry[]>([])

// ---- 浮窗尺寸设置(无边框无拖边,用滑条调宽高) ----
const showSize = ref(false)
const sizeW = ref(720)
const sizeH = ref(560)
const SIZE_RANGE = { w: [480, 1600] as const, h: [360, 1200] as const }

async function toggleSize() {
  showSize.value = !showSize.value
  if (showSize.value) {
    try {
      const r = await fetchRules()
      const find = (k: string) => r.editable.find((s) => s.key === k)?.value
      sizeW.value = find('window_width') ?? 720
      sizeH.value = find('window_height') ?? 560
    } catch { /* 用当前值即可 */ }
  }
}

/** 拖动即生效:本地 resize + 持久化到设置。防抖避免拖动时刷接口。 */
let sizeTimer: number | undefined
function applySize() {
  window.clearTimeout(sizeTimer)
  sizeTimer = window.setTimeout(async () => {
    try {
      await updateSettings({ window_width: sizeW.value, window_height: sizeH.value })
      const api = (window as unknown as { pywebview?: { api?: { resize?: (w: number, h: number) => void } } }).pywebview?.api
      api?.resize?.(sizeW.value, sizeH.value)
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : '保存失败')
    }
  }, 300)
}

// ---- 输入历史(终端式 ↑↓ 翻) ----
const history = ref<string[]>([])                     // 用户发过的消息,新的在后
const historyIdx = ref(-1)                            // -1=没在翻;否则=当前翻到的下标
const draftBackup = ref('')                           // 开始翻之前暂存的草稿

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

// marked:换行即 <br>(gfm 默认要两个空格才换行,聊天里不直观);async:false 同步解析
marked.use({ breaks: true, gfm: true })

/**
 * AI 气泡渲染为 Markdown HTML。marked 不消毒,这里剥掉危险标签/属性兜底
 * (内容是本地 AI 返回,风险低,但 v-html 就得上保险)。用户消息不走这,纯文本。
 */
function renderMd(text: string): string {
  const html = marked.parse(text, { async: false }) as string
  return html
    .replace(/<\/?(script|iframe|object|embed|form|link|meta)[^>]*>/gi, '')
    .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')   // on*= 事件属性
    .replace(/(href|src)\s*=\s*(["']?)\s*javascript:[^"'>]*\2/gi, '$1="#"')
}

function pushChat(role: 'ai' | 'user', text: string, ts?: number) {
  chat.value.push({ role, text, ts: ts ?? Date.now() / 1000 })
  nextTick(() => {
    chatListEl.value?.scrollTo({ top: chatListEl.value.scrollHeight, behavior: 'smooth' })
  })
}

async function onReply() {
  const text = replyDraft.value.trim()
  if (!text || replyBusy.value) return    // 忙时防 Enter 重入(按钮已 disabled)
  replyBusy.value = true
  try {
    pushChat('user', text)
    history.value.push(text)              // 记入输入历史(供 ↑↓ 翻)
    historyIdx.value = -1                 // 重置翻阅状态
    draftBackup.value = ''
    replyDraft.value = ''
    await replyAi(text)               // AI 接话后经 /ws 推 ai_message 回来
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '发送失败')
  } finally {
    replyBusy.value = false
    // 输入框已不随忙碌禁用,焦点本不丢;此处再补回保险(点发送按钮后焦点回输入框)
    nextTick(() => replyInputEl.value?.focus())
  }
}

/** ↑↓ 翻输入历史(终端式)。↑ 往旧的翻,↓ 往新的翻,翻过最新恢复暂存草稿。 */
function onHistoryKey(e: KeyboardEvent) {
  if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
  const n = history.value.length
  if (!n) return
  e.preventDefault()                       // 拦住光标移到行首/行尾,翻历史更像终端
  if (e.key === 'ArrowUp') {
    if (historyIdx.value === -1) {
      draftBackup.value = replyDraft.value  // 首次上翻,暂存当前草稿
      historyIdx.value = n - 1              // 跳到最新一条
    } else if (historyIdx.value > 0) {
      historyIdx.value--                    // 往旧的翻
    }
  } else {                                  // ArrowDown
    if (historyIdx.value === -1) return     // 没在翻,忽略
    if (historyIdx.value < n - 1) {
      historyIdx.value++                    // 往新的翻
    } else {
      historyIdx.value = -1                 // 翻过最新,恢复草稿
      replyDraft.value = draftBackup.value
      return
    }
  }
  replyDraft.value = history.value[historyIdx.value]
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

async function onSnooze(t: WillPushTask, until?: string) {
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

async function toggleSnooze(id: string) {
  expandedSnooze.value[id] = !expandedSnooze.value[id]
  // 展开时按这个任务现取推迟选项(start=预期×系数,end=剩余×系数)
  if (expandedSnooze.value[id]) {
    try {
      snoozeOptions.value[id] = (await fetchSnoozeOptions(id)).options
    } catch {
      snoozeOptions.value[id] = []
    }
  }
}

// 推迟选项 label 形如「3 天(×0.1)」或兜底「1 小时后」;拆成时长 + 算式两块显示
function snoozeDur(label: string): string {
  return label.split('(')[0].trim()
}
function snoozeRatio(label: string): string {
  const m = label.match(/×([\d.]+)/)
  return m ? `= 间隔 × ${m[1]}` : ''
}

function hideWindow() {
  const api = (window as unknown as { pywebview?: { api?: { hide?: () => void } } }).pywebview?.api
  if (api?.hide) {
    api.hide()
  } else {
    window.close()
  }
}

/** Esc = 点 ×(隐藏浮窗);Ctrl+R = 重载页面(浮窗只隐藏不销毁,需手动刷新拿新构建)。 */
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    hideWindow()
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'r') {
    e.preventDefault()               // 拦住默认(某些环境默认 reload 不可靠),统一走 location
    location.reload()
  }
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
  window.addEventListener('keydown', onKeydown)   // Esc 隐藏
  // 回填历史对话:浮窗重载后 chat 从后端日志恢复,之后 /ws 增量追加
  fetchAiHistory(50)
    .then((r) => {
      chat.value = r.entries.map((e) => ({ role: e.role, text: e.text, ts: e.ts ?? Date.now() / 1000 }))
      // 历史里的用户消息也进 ↑↓ 翻历史栈
      history.value = r.entries.filter((e) => e.role === 'user').map((e) => e.text)
      nextTick(() => chatListEl.value?.scrollTo({ top: chatListEl.value.scrollHeight }))
    })
    .catch(() => {})
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
      <button class="np-gear" title="窗口大小" @click.stop="toggleSize">⚙</button>
      <button class="np-close" title="隐藏(Esc;有通知再弹)。Ctrl+R 重载拿新构建" @click="hideWindow">×</button>
    </div>

    <!-- 窗口大小设置:无边框窗口没有拖边,用两条滑条调宽高,拖动即生效 -->
    <div v-if="showSize" class="np-size-pop" @click.stop>
      <label class="np-size-row">
        <span class="np-size-name">宽 {{ sizeW }}px</span>
        <input v-model.number="sizeW" type="range" :min="SIZE_RANGE.w[0]" :max="SIZE_RANGE.w[1]" step="10" @input="applySize" />
      </label>
      <label class="np-size-row">
        <span class="np-size-name">高 {{ sizeH }}px</span>
        <input v-model.number="sizeH" type="range" :min="SIZE_RANGE.h[0]" :max="SIZE_RANGE.h[1]" step="10" @input="applySize" />
      </label>
    </div>

    <div class="np-cols">
      <!-- 左列:AI 助手对话 -->
      <section class="np-ai">
        <div class="np-ai-head">
          <span class="np-col-title">🤖 AI 助手</span>
          <button class="np-link" @click="toggleProcess">
            AI 上下文
          </button>
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
            <!-- AI 气泡渲染 Markdown;用户气泡保持纯文本 -->
            <div v-if="m.role === 'ai'" class="np-bubble np-md" v-html="renderMd(m.text)"></div>
            <div v-else class="np-bubble">{{ m.text }}</div>
            <span class="np-msg-time">{{ fmtTime(m.ts) }}</span>
          </div>
        </div>

        <!-- 回复框 -->
        <div class="np-reply">
          <!-- 输入框永不禁用:AI 在答时也能继续打下一句,只禁发送按钮。 -->
          <input
            ref="replyInputEl"
            v-model="replyDraft"
            class="np-reply-input"
            type="text"
            placeholder="回 AI 一句…(↑↓ 翻历史)"
            @keyup.enter="onReply"
            @keydown="onHistoryKey"
          />
          <button
            class="np-send"
            :disabled="replyBusy || !replyDraft.trim()"
            title="发送"
            @click="onReply"
          >
            <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" aria-hidden="true">
              <path d="M3 11.5 21 3l-7.5 18-2.8-7.2L3 11.5z" />
            </svg>
          </button>
        </div>
      </section>

      <!-- 右列:待办通知 -->
      <section class="np-tasks">
        <div class="np-tasks-head">
          <span class="np-col-title">📋 待办</span>
          <!-- 一键全推迟:整列操作入口,放顶部一眼可见,不用滚到底 -->
          <button
            v-if="tasks.length"
            class="np-snooze-all"
            :disabled="dndBusy"
            title="全部任务推迟 1 小时,可关窗"
            @click="snoozeAll"
          >🌙 全部稍后 1 小时</button>
        </div>
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
              <button
                v-for="o in snoozeOptions[t.id] || []"
                :key="o.key"
                class="np-snooze-opt"
                :disabled="busy[t.id]"
                @click="onSnooze(t, o.until)"
              >
                <span class="np-snooze-dur">推迟 {{ snoozeDur(o.label) }}</span>
                <span class="np-snooze-ratio">{{ snoozeRatio(o.label) }}</span>
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- AI 上下文:模态弹框,浮在上方不挤压对话区,能显示更大 -->
    <div v-if="showProcess" class="np-modal-mask" @click.self="toggleProcess">
      <div class="np-modal">
        <div class="np-modal-head">
          <span class="np-modal-title">AI 上下文</span>
          <button class="np-close" title="关闭" @click="toggleProcess">×</button>
        </div>
        <div class="np-modal-body">
          <div v-if="!aiLog.length" class="np-process-empty">还没有上下文记录</div>
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
      </div>
    </div>
  </div>
</template>

<style scoped>
.notify-page {
  position: relative;
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
.np-gear {
  margin-left: auto;
  border: none;
  background: transparent;
  color: #909399;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 5px;
  font-family: inherit;
}
.np-gear:hover {
  background: #eceff3;
  color: #555;
}
.np-close {
  margin-left: 0;
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

/* 窗口大小设置弹层 */
.np-size-pop {
  position: absolute;
  top: 44px;
  right: 12px;
  z-index: 40;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.14);
  padding: 12px 14px;
  width: 230px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.np-size-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.np-size-name {
  font-size: 12px;
  color: #606266;
  font-weight: 500;
}
.np-size-row input[type='range'] {
  width: 100%;
  accent-color: #5b9bd5;
  cursor: pointer;
}

/* 两列布局 */
.np-cols {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  min-height: 0;
  /* 正文统一可选:对话/过程面板/待办,按住都能框选复制。
     唯一不可选的是顶部拖拽把手(.np-head 单独 user-select:none)。 */
  user-select: text;
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

/* AI 上下文:模态弹框(浮在对话区上方,不再挤压布局) */
.np-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(30, 41, 59, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
  padding: 16px;
}
.np-modal {
  width: min(560px, 92%);
  height: min(480px, 86%);
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.22);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.np-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid #ebeef5;
  flex-shrink: 0;
}
.np-modal-title {
  font-size: 13px;
  font-weight: 600;
  color: #2c3e50;
}
.np-modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 14px;
  min-height: 0;
  user-select: text;
}
.np-process-empty {
  color: #c0c4cc;
  font-size: 11px;
  text-align: center;
  padding: 20px 0;
}
.np-process-item {
  font-size: 11px;
  margin-bottom: 10px;
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
  max-height: 120px;
  overflow-y: auto;
  margin: 4px 0 0;
  /* 显式开选择:pre 默认不继承,这里补死,确保 prompt 原文可复制 */
  user-select: text;
  cursor: text;
}

/* AI 对话流 */
.np-chat {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  /* gap 改由各 .np-msg 的 margin-bottom 承担,保证框选连续 */
  padding: 4px 2px;
  min-height: 0;
  /* 整个对话区可框选:用户能从第一条一路拖到最后一条全选复制,
     而不是一次只能圈一条气泡。 */
  user-select: text;
  cursor: text;
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
  /* 用 margin 而非容器 gap 做间隔:gap 间隙不属任何子元素,会切断鼠标框选;
     margin 让消息块相邻,能从头拖到尾连续全选。 */
  margin-bottom: 8px;
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
  /* 保留换行(用户气泡纯文本 / AI 气泡纯文本回退时);AI 走 Markdown 时由 marked 管换行 */
  white-space: pre-wrap;
  /* 正文可选中复制(easy_drag 已关,天然可选;显式声明保险) */
  user-select: text;
  cursor: text;
}
.np-msg.ai .np-bubble {
  background: #f0f4f9;
  color: #2c3e50;
  border-top-left-radius: 2px;
}
/* AI 气泡里的 Markdown:收紧 marked 生成的块级元素边距,贴合气泡 */
.np-md {
  white-space: normal;    /* marked 已用 <br>/<p> 管换行,别再 pre-wrap 显形 HTML 里的换行 */
}
.np-md :deep(p) {
  margin: 0 0 6px;
}
.np-md :deep(p:last-child) {
  margin-bottom: 0;
}
.np-md :deep(ul),
.np-md :deep(ol) {
  margin: 4px 0;
  padding-left: 18px;
}
.np-md :deep(li) {
  margin: 2px 0;
}
.np-md :deep(strong) {
  color: #1a4a7a;
}
.np-md :deep(h1),
.np-md :deep(h2),
.np-md :deep(h3),
.np-md :deep(h4) {
  margin: 8px 0 4px;
  font-size: 13px;
}
.np-md :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  border-radius: 3px;
  padding: 0 3px;
  font-size: 12px;
}
.np-md :deep(a) {
  color: #4a8ac8;
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
/* 圆形发送图标按钮:替代原「发」文字按钮 */
.np-send {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: #5b9bd5;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
}
.np-send:hover:not(:disabled) {
  background: #4a8ac8;
}
.np-send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 待办列 */
.np-tasks-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
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
/* 推迟选项:一行一行,左时长右算式(借鉴冷却层被挡任务的样式) */
.np-snooze-opts {
  display: flex;
  flex-direction: column;
  margin-top: 8px;
  padding-top: 4px;
  border-top: 1px dashed #eee;
}
.np-snooze-opt {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
  border: none;
  border-bottom: 1px dashed #f0f0f0;
  background: transparent;
  cursor: pointer;
  font-family: inherit;
  text-align: left;
}
.np-snooze-opt:last-child {
  border-bottom: none;
}
.np-snooze-opt:hover:not(:disabled) {
  background: #f5f8fc;
}
.np-snooze-opt:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.np-snooze-dur {
  font-size: 13px;
  color: #2c3e50;
}
.np-snooze-ratio {
  font-size: 12px;
  color: #909399;
}
/* 一键全推迟:顶部小按钮(整列操作入口),不再压底部 */
.np-snooze-all {
  flex-shrink: 0;
  border: 1px solid #c9d6ec;
  background: #eef3fb;
  color: #4a6a9c;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
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
