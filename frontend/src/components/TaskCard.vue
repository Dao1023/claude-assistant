<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  title: string
  importance: number
  /** START: "X 天没做了";DDL: "还剩 X 天" 倒计时(文案由父组件算好传入) */
  footer: string
  tags: string[]
  /** 主题色,用于左侧竖条 */
  accent: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  select: []
}>()

/** 按 importance 高低着色:>=1.0 红 / >=0.3 橙 / >=0 蓝 / 负 灰 */
const importanceClass = computed(() => {
  const v = props.importance
  if (v >= 1.0) return 'imp-red'
  if (v >= 0.3) return 'imp-orange'
  if (v >= 0) return 'imp-blue'
  return 'imp-gray'
})

const importanceText = computed(() => props.importance.toFixed(2))
</script>

<template>
  <div class="task-card" :style="{ borderLeftColor: accent }" @click="emit('select')">
    <h3 class="task-title">{{ title }}</h3>

    <div class="task-meta">
      <span class="task-footer">{{ footer }}</span>
      <span class="imp-badge" :class="importanceClass">{{ importanceText }}</span>
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

/* 手机:卡片高度收紧,不浪费纵向空间(桌面不变) */
@media (max-width: 767px) {
  .task-card {
    padding: 8px 12px;
  }
  .task-title {
    line-height: 1.3;
  }
}

.task-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
  color: #2c3e50;
  word-break: break-word;
}

/* 元信息统一沉底:时间文案(左) + 重要性(中) + 标签(右) */
.task-meta {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
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
  margin-right: auto; /* 时间文案靠左,重要性+标签挤右边 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
