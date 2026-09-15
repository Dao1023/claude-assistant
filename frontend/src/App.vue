<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'

import { fetchTasks } from '@/api/client'
import type { EndTask, StartTask, TagInfo, TaskDetail } from '@/types'
import DetailDrawer from '@/components/DetailDrawer.vue'
import TaskForm from '@/components/TaskForm.vue'
import RulesPage from '@/components/RulesPage.vue'
import TagsSidebar from '@/components/TagsSidebar.vue'
import TagBoard from '@/components/TagBoard.vue'

const activeTab = ref<string>('board')

const starts = ref<StartTask[]>([])
const ends = ref<EndTask[]>([])
const allTags = ref<TagInfo[]>([])
const selectedTags = ref<string[]>([])
const loading = ref(false)

/** 勾选任一选中标签(或其祖先,隐式继承)的任务才显示;不选则全部显示。
 *  分组/过滤都在 TagBoard 内做(与侧边栏勾选同源),这里只传原始数据 */
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
    <!-- 顶部 Tab:任务看板 | 通知规则 -->
    <el-tabs v-model="activeTab" class="page-tabs">
      <el-tab-pane label="任务看板" name="board" />
      <el-tab-pane label="通知规则" name="rules" />
    </el-tabs>

    <!-- 看板视图:左标签栏(筛选+管理) + 右双列任务 -->
    <div v-show="activeTab === 'board'" class="board flex-1" style="min-height: 0" v-loading="loading">
      <TagsSidebar v-model="selectedTags" class="sidebar" @changed="load" />

      <div class="main-col">
        <!-- 顶部:标题 + 刷新 -->
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
        </header>

        <!-- 按标签分组的卡片看板 -->
        <main class="board-main">
          <TagBoard
            :starts="starts"
            :ends="ends"
            :tags="allTags"
            :selected="selectedTags"
            @select="openDetail"
          />
        </main>
      </div>
    </div>

    <!-- 规则视图 -->
    <RulesPage v-show="activeTab === 'rules'" class="flex-1" style="min-height: 0" />

    <DetailDrawer v-model="drawerVisible" :task-id="activeTaskId" @changed="load" @edit="openEdit" />
    <TaskForm v-model="formVisible" :task="editingTask" :all-tags="allTags" @saved="load" @tags-changed="load" />
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

/* 看板:左标签栏 + 右主区。窄屏标签栏变顶部横条,宽屏回左侧栏 */
.board {
  display: flex;
  flex-direction: column;
}

.board .sidebar {
  width: 100%;
  max-height: 220px;
  border-right: none;
  border-bottom: 1px solid #eceef3;
}

.board .main-col {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

/* 卡片看板占满主区并自己滚动 */
.board-main {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

@media (min-width: 768px) {
  .board {
    flex-direction: row;
  }

  .board .sidebar {
    width: 224px;
    max-height: none;
    flex-shrink: 0;
    border-right: 1px solid #eceef3;
    border-bottom: none;
  }
}
</style>
