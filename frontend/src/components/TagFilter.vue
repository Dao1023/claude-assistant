<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TagInfo } from '@/types'
import { buildTree, descendantsMap } from '@/utils/tags'
import TagFilterRows from './TagFilterRows.vue'

interface Props {
  /** 全部可选标签(平铺带父指针) */
  tags: TagInfo[]
  /** 当前选中的标签(v-model) */
  modelValue: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

const tree = computed(() => buildTree(props.tags))
const descMap = computed(() => descendantsMap(props.tags))

/** 折叠中的节点名(默认全展开) */
const collapsed = ref<Set<string>>(new Set())

function toggleCollapse(name: string) {
  const next = new Set(collapsed.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  collapsed.value = next
}

/** 该标签的显示子树是否已被选中完全覆盖(自己选中,或可见子孙全覆盖) */
function covered(name: string): boolean {
  if (props.modelValue.includes(name)) return true
  const kids = descMap.value.get(name) ?? []
  return kids.length > 0 && kids.every(covered)
}

/** 显示子树里是否有任意选中(半选判定用) */
function anySelected(name: string): boolean {
  return props.modelValue.includes(name) || (descMap.value.get(name) ?? []).some(anySelected)
}

function stateOf(name: string): 'on' | 'half' | 'off' {
  if (covered(name)) return 'on'
  return anySelected(name) ? 'half' : 'off'
}

/** 点 chip = 整个显示子树一起选/取消(隐式继承的交互面) */
function toggle(name: string) {
  const all = [name, ...(descMap.value.get(name) ?? [])]
  const sel = new Set(props.modelValue)
  if (covered(name)) all.forEach((n) => sel.delete(n))
  else all.forEach((n) => sel.add(n))
  emit('update:modelValue', [...sel])
}

function clear() {
  emit('update:modelValue', [])
}
</script>

<template>
  <div class="tag-filter">
    <div class="roots">
      <span class="label">标签筛选</span>
      <button
        v-for="node in tree"
        :key="node.name"
        class="chip"
        :class="stateOf(node.name)"
        @click="toggle(node.name)"
      >
        <span
          v-if="node.children.length"
          class="arrow"
          @click.stop="toggleCollapse(node.name)"
        >{{ collapsed.has(node.name) ? '▸' : '▾' }}</span>{{ node.name }}
      </button>
      <el-button
        v-if="modelValue.length"
        link
        type="primary"
        size="small"
        @click="clear"
      >
        清空筛选
      </el-button>
    </div>
    <TagFilterRows
      v-for="node in tree"
      v-show="node.children.length && !collapsed.has(node.name)"
      :key="'rows-' + node.name"
      :nodes="node.children"
      :depth="1"
      :state-of="stateOf"
      :collapsed="collapsed"
      @toggle="toggle"
      @toggle-collapse="toggleCollapse"
    />
  </div>
</template>

<style scoped>
.tag-filter {
  display: flex;
  flex-direction: column;
}

.roots {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.label {
  font-size: 12px;
  font-weight: 500;
  color: #6b7280;
  margin-right: 2px;
}

.chip {
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 400;
  line-height: 1.4;
  color: #606266;
  background: #fff;
  cursor: pointer;
}

.chip:hover {
  border-color: #5b9bd5;
}

.chip.on {
  border-color: #5b9bd5;
  background: #eaf2fb;
  color: #2c6cb0;
}

.chip.half {
  border-style: dashed;
  border-color: #5b9bd5;
  color: #2c6cb0;
}

.arrow {
  margin-right: 2px;
  color: #9aa0aa;
  font-size: 10px;
}
</style>
