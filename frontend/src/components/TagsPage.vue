<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Edit, Rank, Delete } from '@element-plus/icons-vue'

import { createTag, deleteTag, fetchTags, updateTag } from '@/api/client'
import type { TagTreeNode } from '@/types'

const emit = defineEmits<{
  /** 任何变更后通知父组件刷新看板数据(标签名/结构变了) */
  changed: []
}>()

const tree = ref<TagTreeNode[]>([])
const loading = ref(false)

/** 渲染用的平铺行(深度决定缩进) */
interface Row {
  node: TagTreeNode
  depth: number
}

function flatten(nodes: TagTreeNode[], depth = 0): Row[] {
  return nodes.flatMap((n) => [{ node: n, depth }, ...flatten(n.children, depth + 1)])
}

const rows = computed(() => flatten(tree.value))

const selected = ref<TagTreeNode | null>(null)

function select(node: TagTreeNode) {
  selected.value = node
}

async function load() {
  loading.value = true
  try {
    tree.value = (await fetchTags()).tree
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载标签失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ---------- 名字对话框(新建根/新建子/改名三复用) ----------

type NameMode = 'create-root' | 'create-child' | 'rename'
const nameDialog = ref(false)
const nameMode = ref<NameMode>('create-root')
const nameInput = ref('')
const nameSaving = ref(false)

const nameTitle = computed(() =>
  nameMode.value === 'rename' ? '改名' : nameMode.value === 'create-child' ? '新建子标签' : '新建根标签',
)

function openName(mode: NameMode) {
  nameMode.value = mode
  nameInput.value = mode === 'rename' && selected.value ? selected.value.name : ''
  nameDialog.value = true
}

async function submitName() {
  const name = nameInput.value.trim()
  if (!name) {
    ElMessage.warning('标签名不能为空')
    return
  }
  nameSaving.value = true
  try {
    if (nameMode.value === 'create-root') await createTag(name)
    else if (nameMode.value === 'create-child' && selected.value)
      await createTag(name, selected.value.id)
    else if (nameMode.value === 'rename' && selected.value)
      await updateTag(selected.value.id, { name })
    ElMessage.success('已保存')
    nameDialog.value = false
    await load()
    emit('changed')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '保存失败')
  } finally {
    nameSaving.value = false
  }
}

// ---------- 移动对话框 ----------

const moveDialog = ref(false)
const moveTarget = ref<number | null>(null)
const moveSaving = ref(false)

/** 可当作新父级的标签:排除自己+自己的子孙(防环,后端再兜一道) */
const moveOptions = computed(() => {
  if (!selected.value) return []
  const banned = subtreeIds(selected.value)
  const out: TagTreeNode[] = []
  const walk = (nodes: TagTreeNode[]) => {
    for (const n of nodes) {
      if (!banned.has(n.id)) out.push(n)
      walk(n.children)
    }
  }
  walk(tree.value)
  return out
})

function openMove() {
  moveTarget.value = selected.value?.parent_id ?? null
  moveDialog.value = true
}

async function submitMove() {
  if (!selected.value) return
  moveSaving.value = true
  try {
    await updateTag(selected.value.id, { parent_id: moveTarget.value })
    ElMessage.success('已移动')
    moveDialog.value = false
    selected.value = null
    await load()
    emit('changed')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '移动失败')
  } finally {
    moveSaving.value = false
  }
}

// ---------- 删除 ----------

async function doDelete() {
  if (!selected.value) return
  const n = selected.value
  try {
    await ElMessageBox.confirm(
      `删除「${n.name}」?它的子标签会提升到原父级,任务会断开此标签。`,
      '删除标签',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteTag(n.id)
    ElMessage.success('已删除')
    selected.value = null
    await load()
    emit('changed')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '删除失败')
  }
}

// ---------- 拖拽调整层次 ----------

const dragging = ref<TagTreeNode | null>(null)
/** 当前悬停的合法落点:节点 id 或 'root'(顶部根级区) */
const dropTarget = ref<number | 'root' | null>(null)

function subtreeIds(n: TagTreeNode): Set<number> {
  return new Set([n.id, ...n.children.flatMap((c) => [...subtreeIds(c)])])
}

function onDragStart(node: TagTreeNode) {
  dragging.value = node
}

/** 能否落到该节点上:不是自己、不是自己的子孙(防环) */
function canDropOn(node: TagTreeNode): boolean {
  return !!dragging.value && dragging.value.id !== node.id && !subtreeIds(dragging.value).has(node.id)
}

function onDragOver(node: TagTreeNode, e: DragEvent) {
  if (!canDropOn(node)) return
  e.preventDefault()
  dropTarget.value = node.id
}

async function onDrop(node: TagTreeNode) {
  if (!dragging.value || !canDropOn(node)) return
  try {
    await updateTag(dragging.value.id, { parent_id: node.id })
    await load()
    emit('changed')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '移动失败')
  } finally {
    dragging.value = null
    dropTarget.value = null
  }
}

function onRootDragOver(e: DragEvent) {
  if (!dragging.value) return
  e.preventDefault()
  dropTarget.value = 'root'
}

async function onRootDrop() {
  if (!dragging.value) return
  try {
    await updateTag(dragging.value.id, { parent_id: null })
    await load()
    emit('changed')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '移动失败')
  } finally {
    dragging.value = null
    dropTarget.value = null
  }
}

function onDragEnd() {
  dragging.value = null
  dropTarget.value = null
}
</script>

<template>
  <div class="tags-page" v-loading="loading">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-button type="primary" size="small" :icon="Plus" @click="openName('create-root')">
        新建根标签
      </el-button>
      <el-button size="small" :icon="Plus" :disabled="!selected" @click="openName('create-child')">
        新建子标签
      </el-button>
      <el-button size="small" :icon="Edit" :disabled="!selected" @click="openName('rename')">
        改名
      </el-button>
      <el-button size="small" :icon="Rank" :disabled="!selected" @click="openMove">
        移动
      </el-button>
      <el-button size="small" type="danger" plain :icon="Delete" :disabled="!selected" @click="doDelete">
        删除
      </el-button>
      <span class="hint">拖拽行到另一行上 = 成为它的子标签;拖到顶部条 = 移回根级</span>
    </div>

    <!-- 根级投放区 -->
    <div
      class="root-drop"
      :class="{ active: dropTarget === 'root' }"
      @dragover="onRootDragOver"
      @dragleave="dropTarget === 'root' && (dropTarget = null)"
      @drop="onRootDrop"
    >
      拖到此处移回根级
    </div>

    <!-- 树形列表 -->
    <div class="tree" @dragend="onDragEnd">
      <div
        v-for="row in rows"
        :key="row.node.id"
        class="row"
        :class="{
          selected: selected?.id === row.node.id,
          dropping: dropTarget === row.node.id,
        }"
        :style="{ paddingLeft: 12 + row.depth * 24 + 'px' }"
        draggable="true"
        @click="select(row.node)"
        @dragstart="onDragStart(row.node)"
        @dragover="onDragOver(row.node, $event)"
        @dragleave="dropTarget === row.node.id && (dropTarget = null)"
        @drop="onDrop(row.node)"
      >
        <span class="name">{{ row.node.name }}</span>
        <span class="count">{{ row.node.count }}</span>
      </div>
      <el-empty v-if="!rows.length" description="还没有标签,在任务表单里打标签,或点上方新建" :image-size="80" />
    </div>

    <!-- 名字对话框 -->
    <el-dialog v-model="nameDialog" :title="nameTitle" width="360px">
      <el-input v-model="nameInput" placeholder="标签名" maxlength="20" @keyup.enter="submitName" />
      <template #footer>
        <el-button @click="nameDialog = false">取消</el-button>
        <el-button type="primary" :loading="nameSaving" @click="submitName">确定</el-button>
      </template>
    </el-dialog>

    <!-- 移动对话框 -->
    <el-dialog v-model="moveDialog" title="移动到" width="360px">
      <el-select v-model="moveTarget" placeholder="选择新父级" style="width: 100%">
        <el-option label="(根级)" :value="null" />
        <el-option v-for="o in moveOptions" :key="o.id" :label="o.name" :value="o.id" />
      </el-select>
      <template #footer>
        <el-button @click="moveDialog = false">取消</el-button>
        <el-button type="primary" :loading="moveSaving" @click="submitMove">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tags-page {
  display: flex;
  flex-direction: column;
  padding: 16px 20px;
  gap: 10px;
  overflow: auto;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.hint {
  font-size: 12px;
  color: #9aa0aa;
  margin-left: auto;
}

.root-drop {
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 12px;
  color: #9aa0aa;
  text-align: center;
  transition: all 0.15s;
}

.root-drop.active {
  border-color: #5b9bd5;
  background: #eaf2fb;
  color: #2c6cb0;
}

.tree {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 13px;
  color: #303133;
  cursor: pointer;
  user-select: none;
  border: 1px solid transparent;
}

.row:hover {
  background: #f5f7fa;
}

.row.selected {
  background: #eaf2fb;
  border-color: #5b9bd5;
}

.row.dropping {
  border-color: #5b9bd5;
  box-shadow: 0 0 0 2px rgba(91, 155, 213, 0.25);
}

.count {
  font-size: 11px;
  color: #9aa0aa;
  background: #f0f2f5;
  border-radius: 8px;
  padding: 0 6px;
}
</style>
