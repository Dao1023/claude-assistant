<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchFunnel, fetchRules, updateSettings } from '@/api/client'
import type { EditableSetting, FunnelResponse } from '@/types'

const funnel = ref<FunnelResponse | null>(null)
const editable = ref<EditableSetting[]>([])
const loading = ref(false)
const saving = ref(false)
const expanded = ref<Record<string, boolean>>({})
const draft = ref<Record<string, number>>({})

async function load() {
  loading.value = true
  try {
    const [f, r] = await Promise.all([fetchFunnel(), fetchRules()])
    funnel.value = f
    editable.value = r.editable
    for (const s of r.editable) draft.value[s.key] = s.value
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载规则失败')
  } finally {
    loading.value = false
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

function toggle(id: string) {
  expanded.value[id] = !expanded.value[id]
}

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

    <!-- 漏斗各层 -->
    <div v-if="funnel" class="funnel">
      <div v-for="(layer, i) in funnel.layers" :key="layer.id" class="layer-wrap">
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
        <div v-if="i < funnel.layers.length - 1" class="layer-arrow">↓</div>
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
  max-width: 640px;
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
