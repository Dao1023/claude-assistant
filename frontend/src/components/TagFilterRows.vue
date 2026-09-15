<script setup lang="ts">
import type { TagNode } from '@/utils/tags'

interface Props {
  nodes: TagNode[]
  /** 当前层深度,根的孩子=1(决定缩进) */
  depth: number
  /** 父组件注入的选中态计算(自己+可见子孙的全选/半选) */
  stateOf: (name: string) => 'on' | 'half' | 'off'
  /** 折叠中的节点名(默认展开) */
  collapsed: Set<string>
}

defineProps<Props>()
defineEmits<{
  toggle: [name: string]
  'toggle-collapse': [name: string]
}>()
</script>

<template>
  <div class="rows">
    <div class="chip-row" :style="{ paddingLeft: depth * 16 + 'px' }">
      <button
        v-for="node in nodes"
        :key="node.name"
        class="chip"
        :class="stateOf(node.name)"
        @click="$emit('toggle', node.name)"
      >
        <span
          v-if="node.children.length"
          class="arrow"
          @click.stop="$emit('toggle-collapse', node.name)"
        >{{ collapsed.has(node.name) ? '▸' : '▾' }}</span>{{ node.name }}
      </button>
    </div>
    <TagFilterRows
      v-for="node in nodes"
      v-show="node.children.length && !collapsed.has(node.name)"
      :key="'sub-' + node.name"
      :nodes="node.children"
      :depth="depth + 1"
      :state-of="stateOf"
      :collapsed="collapsed"
      @toggle="$emit('toggle', $event)"
      @toggle-collapse="$emit('toggle-collapse', $event)"
    />
  </div>
</template>

<style scoped>
.rows {
  width: 100%;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding-top: 4px;
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

/* 全选:实心浅蓝(隐式继承——整个子树都被这个筛选覆盖) */
.chip.on {
  border-color: #5b9bd5;
  background: #eaf2fb;
  color: #2c6cb0;
}

/* 半选:虚线边,提示子树只覆盖了一部分 */
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
