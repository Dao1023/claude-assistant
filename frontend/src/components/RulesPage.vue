<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  clearDnd,
  fetchFunnel,
  fetchLlmConfig,
  fetchRules,
  saveLlmConfig,
  setDnd,
  testLlmConfig,
  updateSettings,
} from '@/api/client'
import type { EditableSetting, FunnelResponse, LlmConfig } from '@/types'
import NightBand from './NightBand.vue'

const funnel = ref<FunnelResponse | null>(null)
const editable = ref<EditableSetting[]>([])
const loading = ref(false)
const saving = ref(false)
const expanded = ref<Record<string, boolean>>({})
const draft = ref<Record<string, number>>({})
const tempHours = ref(0)               // 临时免打扰拖的小时数(0~5,0=不开)
const dndOperating = ref(false)

// ---- LLM 配置 ----
const llm = ref<LlmConfig | null>(null)
const llmDraft = ref({ base_url: '', api_key: '', model: '' })
const llmSaving = ref(false)
const llmTesting = ref(false)

async function load() {
  loading.value = true
  try {
    const [f, r, l] = await Promise.all([fetchFunnel(), fetchRules(), fetchLlmConfig()])
    funnel.value = f
    editable.value = r.editable
    for (const s of r.editable) draft.value[s.key] = s.value
    llm.value = l
    // 生效值作 placeholder(空框也能看到「现在用的是什么」),输入框留空待改
    llmDraft.value = { base_url: '', api_key: '', model: '' }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载规则失败')
  } finally {
    loading.value = false
  }
}

/** 存 LLM 配置。三项留空=不动现有;填了=覆盖该项。 */
async function saveLlm() {
  llmSaving.value = true
  try {
    const payload: Record<string, string> = {}
    if (llmDraft.value.base_url.trim()) payload.base_url = llmDraft.value.base_url.trim()
    if (llmDraft.value.api_key.trim()) payload.api_key = llmDraft.value.api_key.trim()
    if (llmDraft.value.model.trim()) payload.model = llmDraft.value.model.trim()
    llm.value = await saveLlmConfig(payload)
    llmDraft.value = { base_url: '', api_key: '', model: '' }   // 清空,回显靠 placeholder
    ElMessage.success('LLM 配置已保存,即时生效')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '保存失败')
  } finally {
    llmSaving.value = false
  }
}

async function testLlm() {
  llmTesting.value = true
  try {
    const r = await testLlmConfig()
    if (r.ok) ElMessage.success(`连通正常:${r.sample}`)
    else ElMessage.error(`连不通:${r.error}`)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '测试失败')
  } finally {
    llmTesting.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload: Record<string, number> = {}
    for (const s of editable.value) payload[s.key] = Number(draft.value[s.key])
    await updateSettings(payload)
    ElMessage.success('已保存,下一轮调度生效')
    await load() // 重新拉漏斗,让实时数字反映新阈值
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '保存失败')
  } finally {
    saving.value = false
  }
}

/** 拖动条松手:>0 则开临时免打扰 N 小时。 */
async function applyTempDnd(hours: number) {
  if (!hours) return
  dndOperating.value = true
  try {
    const until = new Date(Date.now() + hours * 3600 * 1000)
    const pad = (n: number) => String(n).padStart(2, '0')
    const str = `${until.getFullYear()}-${pad(until.getMonth() + 1)}-${pad(until.getDate())} ${pad(until.getHours())}:${pad(until.getMinutes())}`
    await setDnd(str)
    ElMessage.success(`免打扰 ${hours} 小时,到 ${str.slice(11)}`)
    tempHours.value = 0
    await load()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '设置失败')
  } finally {
    dndOperating.value = false
  }
}

async function restoreDnd() {
  dndOperating.value = true
  try {
    await clearDnd()
    ElMessage.success('已恢复提醒')
    await load()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '恢复失败')
  } finally {
    dndOperating.value = false
  }
}

/** 夜间横带拖动:松手即落库(总闸的一环,不应要求再点底部「保存配置」)。 */
async function saveNightEnd(hour: number) {
  try {
    await updateSettings({ dnd_night_end: hour })
    await load()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '保存失败')
  }
}

function toggle(id: string) {
  expanded.value[id] = !expanded.value[id]
}

// 免打扰是总闸,单独在顶部渲染成交互卡片,不进通用层循环
const flowLayers = computed(() => funnel.value?.layers.filter((l) => l.id !== 'dnd') ?? [])

const STAGE_LABEL: Record<string, string> = {
  gentle: '提醒',
  escalating: '催办',
  crisis: '紧急',
}

onMounted(load)
</script>

<template>
  <div class="rules-page" v-loading="loading">
    <p class="page-intro">
      你的每个任务,都会从上往下流过这条「漏斗」。每一层是一道筛选,
      通过所有层、且排到前面的,才会弹出催办小卡。数字是<strong>此刻</strong>的真实统计。
    </p>

    <!-- 免打扰总闸:整条流水线的开关,置顶。上下两块,形态自解释,不靠小字。 -->
    <div v-if="funnel" class="dnd-card" :class="{ frozen: funnel.dnd.active }">
      <div class="dnd-head">
        <span class="dnd-icon">🌙</span>
        <span class="dnd-title">免打扰</span>
        <span v-if="funnel.dnd.active" class="dnd-state frozen">冻结中</span>
        <span v-else class="dnd-state clear">畅通</span>
      </div>

      <!-- 夜间·每天:一段时间,用横带表达 -->
      <div class="dnd-block">
        <div class="dnd-block-label">夜间 · 每天</div>
        <NightBand v-model="draft['dnd_night_end']" @change="saveNightEnd" />
        <div class="dnd-block-hint">深色段不打扰,拖到亮处尽头调整;{{ draft['dnd_night_end'] === 0 ? '已关闭' : `0 点到 ${draft['dnd_night_end']} 点` }}</div>
      </div>

      <!-- 临时·这一次:一段时长,用拖动条表达 -->
      <div class="dnd-block">
        <div class="dnd-block-label">临时 · 这一次</div>
        <div v-if="funnel.dnd.until" class="dnd-active">
          <span class="dnd-active-dot">●</span>
          免打扰到 {{ funnel.dnd.until_str }}
          <el-button size="small" :loading="dndOperating" @click="restoreDnd">恢复</el-button>
        </div>
        <div v-else class="dnd-slider">
          <el-slider
            v-model="tempHours"
            :min="0"
            :max="5"
            :step="0.5"
            :format-tooltip="(h: number) => (h ? `${h} 小时` : '不开')"
            :disabled="dndOperating"
            class="dnd-slider-bar"
            @change="applyTempDnd"
          />
          <span class="dnd-slider-text">{{ tempHours ? `接下来 ${tempHours} 小时` : '拖动开启' }}</span>
        </div>
      </div>
    </div>

    <!-- LLM 配置:AI 教练的大脑。api_key 只写不回显,留空表示不动现有 key。 -->
    <div v-if="llm" class="llm-card">
      <div class="llm-head">
        <span class="dnd-icon">🤖</span>
        <span class="dnd-title">AI 教练 · 模型配置</span>
        <span v-if="llm.configured" class="dnd-state clear">已配置</span>
        <span v-else class="dnd-state frozen">未配置</span>
        <span v-if="llm.configured" class="llm-source">
          {{ llm.from_settings ? '生效自本页' : '生效自 data/key.md' }}
        </span>
      </div>
      <div class="llm-rows">
        <div class="llm-row">
          <span class="llm-label">端点</span>
          <el-input v-model="llmDraft.base_url" :placeholder="llm.base_url || 'https://api.deepseek.com/anthropic'" class="llm-input" />
        </div>
        <div class="llm-row">
          <span class="llm-label">Key</span>
          <el-input
            v-model="llmDraft.api_key"
            type="password"
            show-password
            :placeholder="llm.api_key ? `当前 ${llm.api_key}(留空不变)` : 'sk-...'"
            class="llm-input"
          />
        </div>
        <div class="llm-row">
          <span class="llm-label">模型</span>
          <el-input v-model="llmDraft.model" :placeholder="llm.model || 'deepseek-v4-pro'" class="llm-input" />
        </div>
      </div>
      <div class="llm-actions">
        <el-button type="primary" size="small" :loading="llmSaving" @click="saveLlm">保存</el-button>
        <el-button size="small" :loading="llmTesting" :disabled="!llm.configured" @click="testLlm">测试连通</el-button>
      </div>
      <p class="llm-hint">存在本地数据库(不进 git)。留空=不动现有值;改模型省钱可用 deepseek-v4-flash。</p>
    </div>

    <!-- 漏斗各层 -->
    <div v-if="funnel" class="funnel">
      <div v-for="(layer, i) in flowLayers" :key="layer.id" class="layer-wrap">
        <div class="layer-card">
          <div class="layer-head" @click="toggle(layer.id)">
            <span class="layer-idx">{{ i + 1 }}</span>
            <span class="layer-label">{{ layer.label }}</span>
            <el-badge
              v-if="layer.blocked_count > 0"
              :value="layer.blocked_count"
              type="warning"
              class="layer-badge"
            />
            <span v-else class="layer-pass">全部通过</span>
            <span
              v-if="layer.blocked_count > 0"
              class="layer-caret"
            >{{ expanded[layer.id] ? '▲' : '▼' }}</span>
          </div>
          <p class="layer-desc">{{ layer.desc }}</p>

          <!-- 展开:被这层挡住的任务 -->
          <ul v-if="expanded[layer.id] && layer.blocked_count > 0" class="blocked-list">
            <li v-for="t in layer.blocked_tasks" :key="t.id">
              <span class="blocked-title">{{ t.title }}</span>
              <span class="blocked-reason">{{ t.reason }}</span>
            </li>
          </ul>

          <!-- 该层的配置项 -->
          <div v-if="layer.settings.length" class="layer-settings">
            <div v-for="s in layer.settings" :key="s.key" class="setting-row">
              <span class="setting-label">{{ s.label }}</span>
              <el-input-number
                v-model="draft[s.key]"
                :min="s.min"
                :max="s.max"
                :step="s.type === 'float' ? 0.05 : 1"
                controls-position="right"
                class="setting-input"
              />
              <span class="setting-unit">{{ s.unit }}</span>
            </div>
          </div>
        </div>
        <div v-if="i < flowLayers.length - 1" class="layer-arrow">↓</div>
      </div>
    </div>

    <!-- 出口:本轮将弹出 -->
    <div v-if="funnel" class="outlet">
      <div class="outlet-title">本轮将弹出 {{ funnel.will_push.length }} 张卡</div>
      <ul v-if="funnel.will_push.length" class="will-list">
        <li v-for="t in funnel.will_push" :key="t.id">
          {{ t.title }}<span class="will-stage">{{ STAGE_LABEL[t.stage] || t.stage }}</span>
        </li>
      </ul>
      <p v-else class="will-none">现在没有到点该催的任务。</p>
      <p class="poll">引擎每 {{ funnel.poll_interval }} 秒检查一轮</p>
    </div>

    <div class="actions">
      <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
      <el-button @click="load">还原</el-button>
    </div>
  </div>
</template>

<style scoped>
.rules-page {
  padding: 16px 20px 32px;
  overflow: auto;
}
.page-intro {
  margin: 4px 0 16px;
  font-size: 13px;
  color: #5a6b7b;
  line-height: 1.7;
}
.funnel {
  display: flex;
  flex-direction: column;
}
.dnd-card {
  background: #fff;
  border: 1px solid #eceef3;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}
.dnd-card.frozen {
  background: #f4f6fb;
  border-color: #c9d6ec;
}
.dnd-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dnd-icon {
  font-size: 16px;
}
.dnd-title {
  font-weight: 600;
  color: #2c3e50;
  font-size: 14px;
}
.dnd-state {
  font-size: 12px;
  margin-left: 4px;
}
.dnd-state.frozen {
  color: #5b9bd5;
}
.dnd-state.clear {
  color: #67c23a;
}
.dnd-block {
  margin: 14px 0 0 24px;
}
.dnd-block-label {
  font-size: 12px;
  font-weight: 600;
  color: #5a6b7b;
  margin-bottom: 6px;
}
.dnd-block-hint {
  font-size: 11px;
  color: #a0a8b5;
  margin-top: 4px;
}
.dnd-slider {
  display: flex;
  align-items: center;
  gap: 12px;
}
.dnd-slider-bar {
  flex: 1;
  max-width: 320px;
}
.dnd-slider-text {
  font-size: 12px;
  color: #5a6b7b;
  white-space: nowrap;
}
.dnd-active {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #2c3e50;
}
.dnd-active-dot {
  color: #5b9bd5;
  font-size: 10px;
}
.llm-card {
  background: #fff;
  border: 1px solid #eceef3;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}
.llm-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.llm-source {
  margin-left: auto;
  font-size: 11px;
  color: #a0a8b5;
}
.llm-rows {
  margin: 14px 0 0 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.llm-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.llm-label {
  font-size: 13px;
  color: #5a6b7b;
  width: 44px;
  flex-shrink: 0;
}
.llm-input {
  max-width: 420px;
}
.llm-actions {
  margin: 14px 0 0 24px;
  display: flex;
  gap: 8px;
}
.llm-hint {
  margin: 10px 0 0 24px;
  font-size: 11px;
  color: #a0a8b5;
}
.layer-wrap {
  display: flex;
  flex-direction: column;
}
.layer-card {
  background: #fff;
  border: 1px solid #eceef3;
  border-radius: 8px;
  padding: 12px 14px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}
.layer-head {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}
.layer-idx {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #5b9bd5;
  color: #fff;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.layer-label {
  font-weight: 600;
  color: #2c3e50;
  font-size: 14px;
}
.layer-badge {
  margin-left: 4px;
}
.layer-pass {
  margin-left: 4px;
  font-size: 12px;
  color: #67c23a;
}
.layer-caret {
  margin-left: auto;
  color: #909399;
  font-size: 12px;
}
.layer-desc {
  margin: 8px 0 0 28px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
.blocked-list {
  margin: 10px 0 0 28px;
  padding: 0;
  list-style: none;
}
.blocked-list li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
  border-top: 1px dashed #f0f0f0;
}
.blocked-title {
  color: #2c3e50;
}
.blocked-reason {
  color: #909399;
  font-size: 12px;
}
.layer-settings {
  margin: 10px 0 0 28px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.setting-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.setting-label {
  font-size: 13px;
  color: #5a6b7b;
  width: 110px;
}
.setting-input {
  width: 130px;
}
.setting-unit {
  color: #909399;
  font-size: 12px;
}
.layer-arrow {
  text-align: center;
  color: #c0c4cc;
  font-size: 16px;
  line-height: 1.4;
  padding: 2px 0;
}
.outlet {
  margin-top: 14px;
  background: #f0f7ff;
  border: 1px solid #d6e4f7;
  border-radius: 8px;
  padding: 12px 14px;
}
.outlet-title {
  font-weight: 600;
  color: #2c3e50;
  font-size: 14px;
}
.will-list {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}
.will-list li {
  font-size: 13px;
  color: #2c3e50;
  padding: 3px 0;
}
.will-stage {
  margin-left: 6px;
  font-size: 12px;
  color: #e8a33d;
}
.will-none {
  margin: 8px 0 0;
  font-size: 13px;
  color: #67c23a;
}
.poll {
  margin: 8px 0 0;
  font-size: 12px;
  color: #909399;
}
.actions {
  margin-top: 16px;
}
</style>
