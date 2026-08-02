<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchRules, updateSettings } from '@/api/client'
import type { EditableSetting, ReadonlyRule } from '@/types'

const editable = ref<EditableSetting[]>([])
const readonlyRules = ref<ReadonlyRule[]>([])
const loading = ref(false)
const saving = ref(false)
// 表单草稿:key -> 数字(el-input-number 直接绑定)
const draft = reactive<Record<string, number>>({})

async function load() {
  loading.value = true
  try {
    const data = await fetchRules()
    editable.value = data.editable
    readonlyRules.value = data.readonly
    for (const s of data.editable) draft[s.key] = s.value
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
    for (const s of editable.value) payload[s.key] = Number(draft[s.key])
    editable.value = await updateSettings(payload)
    ElMessage.success('已保存,下一轮调度生效')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="rules-page" v-loading="loading">
    <!-- 只读:全部规则说明 -->
    <section class="rules-readonly">
      <h2 class="section-title">通知规则(算法 · 只读)</h2>
      <div class="rule-cards">
        <el-card v-for="r in readonlyRules" :key="r.title" shadow="never" class="rule-card">
          <template #header><span class="rule-title">{{ r.title }}</span></template>
          <p class="rule-desc">{{ r.desc }}</p>
        </el-card>
      </div>
    </section>

    <!-- 可编辑:数值阈值 -->
    <section class="rules-editable">
      <h2 class="section-title">可配置项</h2>
      <el-form label-width="140px" class="settings-form">
        <el-form-item v-for="s in editable" :key="s.key" :label="s.label">
          <div class="setting-row">
            <el-input-number
              v-model="draft[s.key]"
              :min="s.min"
              :max="s.max"
              :step="s.type === 'float' ? 0.05 : 1"
              controls-position="right"
              class="setting-input"
            />
            <span class="setting-unit">{{ s.unit }}</span>
            <span class="setting-desc">{{ s.desc }}(范围 {{ s.min }} ~ {{ s.max }})</span>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
          <el-button @click="load">还原</el-button>
        </el-form-item>
      </el-form>
    </section>
  </div>
</template>

<style scoped>
.rules-page {
  padding: 16px 20px;
  overflow: auto;
}
.section-title {
  margin: 8px 0 12px;
  font-size: 15px;
  font-weight: 700;
  color: #2c3e50;
}
.rule-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.rule-title {
  font-weight: 600;
  color: #2c3e50;
}
.rule-desc {
  margin: 0;
  font-size: 13px;
  color: #5a6b7b;
  line-height: 1.6;
}
.setting-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.setting-input {
  width: 140px;
}
.setting-unit {
  color: #909399;
  font-size: 13px;
}
.setting-desc {
  color: #909399;
  font-size: 12px;
}
</style>
