<script setup lang="ts">
interface Props {
  /** 全部可选标签 */
  tags: string[]
  /** 当前选中的标签(v-model) */
  modelValue: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

function toggle(tag: string) {
  const next = props.modelValue.includes(tag)
    ? props.modelValue.filter((t) => t !== tag)
    : [...props.modelValue, tag]
  emit('update:modelValue', next)
}

function clear() {
  emit('update:modelValue', [])
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <span class="text-sm font-medium text-gray-500">标签筛选</span>

    <el-check-tag
      v-for="tag in tags"
      :key="tag"
      :checked="modelValue.includes(tag)"
      @change="toggle(tag)"
    >
      #{{ tag }}
    </el-check-tag>

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
</template>

<style scoped>
/* Element Plus 的 el-check-tag 默认偏大(14px/7-15/加粗),收小。
   它是第三方组件,scoped :deep 的选择器特异性高于 .el-check-tag 默认,稳定覆盖。 */
:deep(.el-check-tag) {
  font-size: 11px;
  padding: 3px 8px;
  font-weight: 400;
}
</style>
