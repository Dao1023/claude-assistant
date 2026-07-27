<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  title: string
  importance: number
  /** START: "X 天没做了";DDL: countdown 字符串 */
  footer: string
  tags: string[]
  /** 主题色,用于左侧竖条 */
  accent: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  select: []
}>()

/** 过期哨兵值(engine.OVERDUE = 1e9)。超过即视为"已逾期",不显示原始大数。 */
const OVERDUE = 1e6

/** 按 importance 高低着色:逾期/>=1.0 红 / >=0.3 橙 / >=0 蓝 / 负 灰 */
const importanceClass = computed(() => {
  const v = props.importance
  if (v >= OVERDUE || v >= 1.0) return 'imp-red'
  if (v >= 0.3) return 'imp-orange'
  if (v >= 0) return 'imp-blue'
  return 'imp-gray'
})

const importanceText = computed(() =>
  props.importance >= OVERDUE ? '逾期' : props.importance.toFixed(2)
)
</script>

<template>
  <div class="task-card" :style="{ borderLeftColor: accent }" @click="emit('select')">
    <div class="flex items-start justify-between gap-3">
      <h3 class="task-title">{{ title }}</h3>
      <span class="imp-badge" :class="importanceClass">{{ importanceText }}</span>
    </div>

    <div class="mt-2 flex items-center justify-between gap-2">
      <span class="task-footer">{{ footer }}</span>
      <div v-if="tags.length" class="flex flex-wrap justify-end gap-1">
        <span v-for="t in tags" :key="t" class="tag-chip">#{{ t }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-card {
  background: #ffffff;
  border-radius: 10px;
  border-left: 3px solid transparent;
  padding: 12px 14px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition:
    box-shadow 0.15s ease,
    transform 0.15s ease;
}
.task-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transform: translateY(-1px);
}

.task-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
  color: #2c3e50;
  word-break: break-word;
}

.imp-badge {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  padding: 1px 7px;
  border-radius: 6px;
  line-height: 1.5;
}
.imp-red {
  color: #e05252;
  background: rgba(224, 82, 82, 0.1);
}
.imp-orange {
  color: #e6a23c;
  background: rgba(230, 162, 60, 0.12);
}
.imp-blue {
  color: #5b9bd5;
  background: rgba(91, 155, 213, 0.12);
}
.imp-gray {
  color: #909399;
  background: rgba(144, 147, 153, 0.12);
}

.task-footer {
  font-size: 12px;
  color: #909399;
}

.tag-chip {
  font-size: 11px;
  color: #5b9bd5;
  background: rgba(91, 155, 213, 0.1);
  border-radius: 5px;
  padding: 0 5px;
  line-height: 1.6;
  white-space: nowrap;
}
</style>
