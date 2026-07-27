<script setup lang="ts" generic="T extends { id: string; title: string; importance: number; tags: string[] }">
import TaskCard from './TaskCard.vue'

interface Props {
  /** 栏目标题,如 "START · 越久越重要" */
  heading: string
  /** 主题色 */
  accent: string
  tasks: T[]
  /** 由任务生成底部信息文案 */
  footerOf: (task: T) => string
}

defineProps<Props>()

const emit = defineEmits<{
  select: [id: string]
}>()
</script>

<template>
  <section class="column">
    <header class="column-header" :style="{ color: accent }">
      <span class="column-dot" :style="{ backgroundColor: accent }"></span>
      <h2 class="column-heading">{{ heading }}</h2>
      <span class="column-count">{{ tasks.length }}</span>
    </header>

    <el-scrollbar class="column-scroll" wrap-class="column-wrap">
      <div v-if="tasks.length" class="flex flex-col gap-2.5 px-1 py-1">
        <TaskCard
          v-for="task in tasks"
          :key="task.id"
          :title="task.title"
          :importance="task.importance"
          :footer="footerOf(task)"
          :tags="task.tags"
          :accent="accent"
          @select="emit('select', task.id)"
        />
      </div>
      <el-empty v-else description="暂无任务" :image-size="80" />
    </el-scrollbar>
  </section>
</template>

<style scoped>
.column {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  background: #ffffff;
  border-radius: 14px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
  overflow: hidden;
}

.column-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px 10px;
  border-bottom: 1px solid #f0f1f5;
}
.column-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.column-heading {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.column-count {
  margin-left: auto;
  font-size: 12px;
  font-weight: 600;
  color: #909399;
  background: #f0f1f5;
  border-radius: 999px;
  padding: 1px 9px;
}

.column-scroll {
  flex: 1;
  min-height: 0;
}
:deep(.column-wrap) {
  padding: 4px 8px 12px;
}
</style>
