<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'

import { fetchTasks } from '@/api/client'
import type { EndTask, StartTask, TagInfo, TaskDetail } from '@/types'
import { ancestorsMap } from '@/utils/tags'
import TagFilter from '@/components/TagFilter.vue'
import TaskColumn from '@/components/TaskColumn.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import TaskForm from '@/components/TaskForm.vue'
import RulesPage from '@/components/RulesPage.vue'
import TagsPage from '@/components/TagsPage.vue'

const activeTab = ref<string>('board')

const starts = ref<StartTask[]>([])
const ends = ref<EndTask[]>([])
const allTags = ref<TagInfo[]>([])
const selectedTags = ref<string[]>([])
const loading = ref(false)

const drawerVisible = ref(false)
const activeTaskId = ref<string | null>(null)

// 新增/编辑表单
const formVisible = ref(false)
const editingTask = ref<TaskDetail | null>(null)

function openDetail(id: string) {
  activeTaskId.value = id
  drawerVisible.value = true
}

/** 打开新增表单(空白) */
function openAdd() {
  editingTask.value = null
  formVisible.value = true
}

/** 从详情抽屉发起编辑:带上当前任务数据预填,关抽屉开表单 */
function openEdit(task: TaskDetail) {
  editingTask.value = task
  drawerVisible.value = false
  formVisible.value = true
}

/** 勾选任一选中标签(或其祖先,隐式继承)的任务才显示;不选则全部显示 */
const ancMap = computed(() => ancestorsMap(allTags.value))

function matchTags(taskTags: string[]): boolean {
  if (!selectedTags.value.length) return true
  const sel = new Set(selectedTags.value)
  return taskTags.some((t) => sel.has(t) || (ancMap.value.get(t) ?? []).some((a) => sel.has(a)))
}

const filteredStarts = computed(() => starts.value.filter((t) => matchTags(t.tags)))
const filteredEnds = computed(() => ends.value.filter((t) => matchTags(t.tags)))

function startFooter(task: StartTask): string {
  if (task.days_since === null || task.days_since === undefined) return '还没做过'
  if (task.days_since <= 0) return '今天做过'
  return `${task.days_since.toFixed(1)} 天没做了`
}

function endFooter(task: EndTask): string {
  // 后端只给 deadline 时间字符串,倒计时文案前端自己算(数据归后端,文案归前端)。
  if (!task.deadline) return '无截止时间'
  const secs = Math.floor((new Date(task.deadline.replace(' ', 'T')).getTime() - Date.now()) / 1000)
  if (secs <= 0) return '已过期'
  const days = Math.floor(secs / 86400)
  if (days >= 1) return `还剩 ${days} 天`
  const h = Math.floor(secs / 3600)
  if (h >= 1) return `还剩 ${h} 小时`
  return `还剩 ${Math.floor(secs / 60)} 分钟`
}

async function load() {
  loading.value = true
  try {
    const data = await fetchTasks()
    starts.value = data.starts
    ends.value = data.ends
    allTags.value = data.tags
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载任务失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- 顶部 Tab:任务看板 | 通知规则 | 标签管理 -->
    <el-tabs v-model="activeTab" class="page-tabs">
      <el-tab-pane label="任务看板" name="board" />
      <el-tab-pane label="通知规则" name="rules" />
      <el-tab-pane label="标签管理" name="tags" />
    </el-tabs>

    <!-- 看板视图 -->
    <div v-show="activeTab === 'board'" class="flex flex-1 flex-col" style="min-height: 0" v-loading="loading">
      <!-- 顶部:标题 + 筛选 + 刷新 -->
      <header class="topbar">
        <div class="flex items-center gap-3">
          <h1 class="app-title">Claude Assistant · 任务面板</h1>
          <el-button
            :icon="Refresh"
            circle
            size="small"
            :loading="loading"
            title="刷新"
            @click="load"
          />
          <el-button
            class="add-btn"
            type="primary"
            size="small"
            :icon="Plus"
            @click="openAdd"
          >
            新增任务
          </el-button>
        </div>
        <TagFilter v-model="selectedTags" :tags="allTags" />
      </header>

      <!-- 两栏 -->
      <main class="grid flex-1 grid-cols-1 gap-4 p-4 md:grid-cols-2" style="min-height: 0">
        <TaskColumn
          heading="START · 越久越重要"
          accent="#5b9bd5"
          :tasks="filteredStarts"
          :footer-of="startFooter"
          @select="openDetail"
        />
        <TaskColumn
          heading="DDL · 越近越急"
          accent="#e05252"
          :tasks="filteredEnds"
          :footer-of="endFooter"
          @select="openDetail"
        />
      </main>
    </div>

    <!-- 规则视图 -->
    <RulesPage v-show="activeTab === 'rules'" class="flex-1" style="min-height: 0" />

    <!-- 标签管理 -->
    <TagsPage v-show="activeTab === 'tags'" class="flex-1" style="min-height: 0" @changed="load" />

    <DetailDrawer v-model="drawerVisible" :task-id="activeTaskId" @changed="load" @edit="openEdit" />
    <TaskForm v-model="formVisible" :task="editingTask" :all-tags="allTags" @saved="load" />
  </div>
</template>

<style scoped>
.page-tabs {
  padding: 8px 20px 0;
  background: #fff;
}

.page-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

.page-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
}

.topbar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 20px 12px;
  background: #ffffff;
  border-bottom: 1px solid #eceef3;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.app-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: #2c3e50;
  letter-spacing: 0.01em;
}

.add-btn {
  margin-left: auto;
}
</style>
