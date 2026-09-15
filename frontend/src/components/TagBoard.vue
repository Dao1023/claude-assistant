<script setup lang="ts">
import { computed } from 'vue'

import type { EndTask, StartTask, TagInfo } from '@/types'
import { buildGroups, UNTAGGED, type BoardTask } from '@/utils/taskGroups'
import TaskCard from './TaskCard.vue'

interface Props {
  starts: StartTask[]
  ends: EndTask[]
  /** 全部标签(平铺带父指针),决定分组结构 */
  tags: TagInfo[]
  /** 侧边栏勾选的标签;空 = 全部 */
  selected: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  select: [id: string]
}>()

// 卡片底部文案(数据归后端,文案归前端)——从旧 App 两栏视图原样迁来
function startFooter(task: StartTask): string {
  if (task.days_since === null || task.days_since === undefined) return '还没做过'
  if (task.days_since <= 0) return '今天做过'
  return `${task.days_since.toFixed(1)} 天`
}

function endFooter(task: EndTask): string {
  if (!task.deadline) return '无截止时间'
  const secs = Math.floor((new Date(task.deadline.replace(' ', 'T')).getTime() - Date.now()) / 1000)
  if (secs <= 0) return '已过期'
  const days = Math.floor(secs / 86400)
  if (days >= 1) return `还剩 ${days} 天`
  const h = Math.floor(secs / 3600)
  if (h >= 1) return `还剩 ${h} 小时`
  return `还剩 ${Math.floor(secs / 60)} 分钟`
}

/** 两种驱动合并成统一看板任务;左边条颜色区分驱动(蓝=start,红=ddl) */
const tasks = computed<BoardTask[]>(() => [
  ...props.starts.map((t) => ({
    id: t.id,
    title: t.title,
    importance: t.importance,
    drive: 'start' as const,
    tags: t.tags,
    footer: startFooter(t),
  })),
  ...props.ends.map((t) => ({
    id: t.id,
    title: t.title,
    importance: t.importance,
    drive: 'end' as const,
    tags: t.tags,
    footer: endFooter(t),
  })),
])

const groups = computed(() => buildGroups(tasks.value, props.tags, props.selected))

function accentOf(t: BoardTask): string {
  return t.drive === 'start' ? '#5b9bd5' : '#e05252'
}
</script>

<template>
  <div class="tag-board">
    <section
      v-for="g in groups"
      :key="g.name"
      class="group"
      :class="{ untagged: g.name === UNTAGGED, indented: g.depth > 0 }"
      :style="g.depth > 0 ? { marginLeft: g.depth * 20 + 'px' } : undefined"
    >
      <header class="group-head">
        <span class="group-name">{{ g.name }}</span>
        <span class="group-count">{{ g.tasks.length }}</span>
      </header>
      <div class="group-body">
        <TaskCard
          v-for="t in g.tasks"
          :key="t.id"
          :title="t.title"
          :importance="t.importance"
          :footer="t.footer"
          :tags="t.tags"
          :accent="accentOf(t)"
          @select="emit('select', t.id)"
        />
      </div>
    </section>

    <el-empty v-if="!groups.length" description="没有匹配的任务" :image-size="100" />
  </div>
</template>

<style scoped>
.tag-board {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: #f5f6f8;
}

/* 分层:子组整体右缩进 + 左侧导向竖线,层级一眼可见 */
.group {
  background: #ffffff;
  border-radius: 10px;
  padding: 10px 14px 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.group.indented {
  border-left: 2px solid #e8eef5;
}

.group-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.group-name {
  font-size: 13px;
  font-weight: 700;
  color: #2c3e50;
}

.group.untagged .group-name {
  color: #909399;
}

.group-count {
  font-size: 11px;
  font-weight: 400;
  color: #9aa0aa;
  background: #eef0f3;
  border-radius: 8px;
  padding: 0 6px;
}

/* 卡片栅格:窄屏一列,随宽度自动加列 */
.group-body {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
}

@media (max-width: 767px) {
  .tag-board {
    padding: 10px 12px;
  }

  .group {
    padding: 8px 10px 10px;
  }

  .group.indented {
    margin-left: 12px !important;
  }

  .group-body {
    grid-template-columns: 1fr;
  }
}
</style>
