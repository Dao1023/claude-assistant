<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type Node from 'element-plus/es/components/tree/src/model/node'
import { Plus, Edit, Delete } from '@element-plus/icons-vue'

import { createTag, deleteTag, fetchTags, updateTag } from '@/api/client'
import type { TagTreeNode } from '@/types'

interface Props {
  /** 当前选中的标签名(v-model,空=全显示) */
  modelValue: string[]
}
const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: string[]]
  /** 树结构/名字变了,父组件刷新看板数据 */
  changed: []
}>()

const tree = ref<TagTreeNode[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    tree.value = (await fetchTags()).tree
    syncChecked()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载标签失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ---------- 勾选(筛选) ----------

const treeRef = ref()
/** id ↔ name 互查(勾选态用 id 存,对外暴露名字) */
const byId = computed(() => {
  const m = new Map<number, TagTreeNode>()
  const walk = (nodes: TagTreeNode[]) => {
    for (const n of nodes) {
      m.set(n.id, n)
      walk(n.children)
    }
  }
  walk(tree.value)
  return m
})

const nameToId = computed(() => {
  const m = new Map<string, number>()
  for (const [id, n] of byId.value) m.set(n.name, id)
  return m
})

function syncChecked() {
  const ids = props.modelValue
    .map((n) => nameToId.value.get(n))
    .filter((v): v is number => v !== undefined)
  treeRef.value?.setCheckedKeys(ids, false)
}

watch(
  () => [props.modelValue, tree.value],
  () => syncChecked(),
)

/** 勾选变化 → 对外发名字集合(或语义:任一选中/祖先命中由父组件做) */
function onCheck(_node: TagTreeNode, { checkedNodes }: { checkedNodes: TagTreeNode[] }) {
  emit(
    'update:modelValue',
    checkedNodes.map((n) => n.name),
  )
}

function clear() {
  emit('update:modelValue', [])
}

// ---------- 管理:新建 / 改名 / 删除 ----------

const nameDialog = ref(false)
const nameMode = ref<'create-root' | 'create-child' | 'rename'>('create-root')
const nameInput = ref('')
const nameSaving = ref(false)
/** 改名的同时若被勾选,选中集合同步换成新名(否则勾选会丢) */
let renameOldName: string | null = null
let createParent: TagTreeNode | null = null

const nameTitle = computed(() =>
  nameMode.value === 'rename' ? '改名' : nameMode.value === 'create-child' ? '新建子标签' : '新建标签',
)

function openCreateRoot() {
  nameMode.value = 'create-root'
  createParent = null
  nameInput.value = ''
  nameDialog.value = true
}

function openCreateChild(node: TagTreeNode) {
  nameMode.value = 'create-child'
  createParent = node
  nameInput.value = ''
  nameDialog.value = true
}

function openRename(node: TagTreeNode) {
  nameMode.value = 'rename'
  renameOldName = node.name
  nameInput.value = node.name
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
    if (nameMode.value === 'rename' && renameOldName) {
      const id = nameToId.value.get(renameOldName)
      if (id !== undefined) {
        await updateTag(id, { name })
        if (props.modelValue.includes(renameOldName)) {
          emit(
            'update:modelValue',
            props.modelValue.map((n) => (n === renameOldName ? name : n)),
          )
        }
      }
    } else if (nameMode.value === 'create-child' && createParent) {
      await createTag(name, createParent.id)
    } else {
      await createTag(name)
    }
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

async function doDelete(node: TagTreeNode) {
  try {
    await ElMessageBox.confirm(
      `删除「${node.name}」?它的子标签会提升到原父级,任务会断开此标签。`,
      '删除标签',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteTag(node.id)
    if (props.modelValue.includes(node.name)) {
      emit(
        'update:modelValue',
        props.modelValue.filter((n) => n !== node.name),
      )
    }
    ElMessage.success('已删除')
    await load()
    emit('changed')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '删除失败')
  }
}

// ---------- 拖拽调层次 ----------

function subtreeIds(n: TagTreeNode): Set<number> {
  return new Set([n.id, ...n.children.flatMap((c) => [...subtreeIds(c)])])
}

/** inner=成为子标签;before/after=成为该节点的兄弟(挂在同一父级,根兄弟=回根级) */
function allowDrop(dragNode: Node, dropNode: Node, type: 'prev' | 'inner' | 'next') {
  if (subtreeIds(dragNode.data as TagTreeNode).has((dropNode.data as TagTreeNode).id)) {
    return false // 自己/子孙禁放(防环)
  }
  return true
}

async function onDrop(dragNode: Node, dropNode: Node, dropType: 'prev' | 'inner' | 'next') {
  const drag = dragNode.data as TagTreeNode
  const drop = dropNode.data as TagTreeNode
  const newParent = dropType === 'inner' ? drop.id : drop.parent_id
  try {
    await updateTag(drag.id, { parent_id: newParent })
    await load()
    emit('changed')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '移动失败')
    await load() // 失败,回滚视图
  }
}
</script>

<template>
  <aside class="tag-sidebar" v-loading="loading">
    <div class="side-header">
      <span class="side-title">标签</span>
      <el-button link type="primary" size="small" :icon="Plus" @click="openCreateRoot">
        新建
      </el-button>
      <el-button
        v-if="modelValue.length"
        link
        type="info"
        size="small"
        @click="clear"
      >
        清空筛选
      </el-button>
    </div>

    <el-tree
      ref="treeRef"
      :data="tree"
      node-key="id"
      show-checkbox
      draggable
      default-expand-all
      :props="{ label: 'name', children: 'children' }"
      :allow-drop="allowDrop"
      @check="onCheck"
      @node-drop="onDrop"
    >
      <template #default="{ data }">
        <span class="row">
          <span class="label">{{ data.name }}</span>
          <span v-if="data.count" class="count">{{ data.count }}</span>
          <span class="ops" @click.stop>
            <el-button
              class="op"
              link
              size="small"
              :icon="Plus"
              title="新建子标签"
              @click="openCreateChild(data)"
            />
            <el-button
              class="op"
              link
              size="small"
              :icon="Edit"
              title="改名"
              @click="openRename(data)"
            />
            <el-button
              class="op danger"
              link
              size="small"
              :icon="Delete"
              title="删除"
              @click="doDelete(data)"
            />
          </span>
        </span>
      </template>
    </el-tree>

    <p class="side-hint">勾选筛选(父含全部子标签)· 拖到目标上=成为其子标签</p>

    <!-- 名字对话框 -->
    <el-dialog v-model="nameDialog" :title="nameTitle" width="340px">
      <el-input v-model="nameInput" placeholder="标签名" maxlength="20" @keyup.enter="submitName" />
      <template #footer>
        <el-button @click="nameDialog = false">取消</el-button>
        <el-button type="primary" :loading="nameSaving" @click="submitName">确定</el-button>
      </template>
    </el-dialog>
  </aside>
</template>

<style scoped>
.tag-sidebar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  background: #fafbfc;
  border-right: 1px solid #eceef3;
  overflow: auto;
}

.side-header {
  display: flex;
  align-items: center;
  gap: 4px;
}

.side-title {
  font-size: 13px;
  font-weight: 600;
  color: #2c3e50;
  margin-right: auto;
}

.side-hint {
  font-size: 11px;
  color: #9aa0aa;
  margin: 4px 0 0;
}

/* 树整体收小,行距收紧 */
.tag-sidebar :deep(.el-tree-node__content) {
  height: 30px;
  border-radius: 6px;
}

.tag-sidebar :deep(.el-tree-node__label) {
  flex: 1;
  min-width: 0;
}

.tag-sidebar :deep(.el-checkbox) {
  margin-right: 4px;
}

.row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  font-size: 12px;
  color: #303133;
}

.label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count {
  font-size: 10px;
  color: #9aa0aa;
  background: #eef0f3;
  border-radius: 8px;
  padding: 0 5px;
  flex-shrink: 0;
}

/* 悬停才显示操作钮,不干扰平时浏览 */
.ops {
  display: none;
  flex-shrink: 0;
  margin-left: auto;
}

.tag-sidebar :deep(.el-tree-node__content:hover) .ops {
  display: inline-flex;
}

.op {
  padding: 2px;
  color: #9aa0aa;
}

.op:hover {
  color: #5b9bd5;
}

.op.danger:hover {
  color: #e05252;
}
</style>
