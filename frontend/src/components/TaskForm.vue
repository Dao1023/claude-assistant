<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { addTask, updateTask } from '@/api/client'
import type { TagInfo, TaskDetail } from '@/types'
import { buildTree, depthMap } from '@/utils/tags'

interface Props {
  /** 对话框是否可见(v-model) */
  modelValue: boolean
  /** 编辑时传入现有任务(预填);新增时为 null */
  task: TaskDetail | null
  /** 全部已有标签(平铺带父指针,全量) */
  allTags: TagInfo[]
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  /** 提交成功(新增/编辑),通知父组件刷新列表 */
  saved: []
}>()

/** 标签层级深度(选项缩进用),根=0 */
const depths = computed(() => depthMap(props.allTags))

function tagLabel(name: string): string {
  return '　'.repeat(depths.value.get(name) ?? 0) + name
}

/** 选项顺序 = 树前序(父标签后紧跟子树)。
    后端 flat 按活跃数全局降序,平铺出来会"根部一层、子级一层",不像树 */
const orderedTags = computed<TagInfo[]>(() => {
  const out: TagInfo[] = []
  const walk = (nodes: ReturnType<typeof buildTree>) => {
    for (const n of nodes) {
      out.push({ name: n.name, parent: n.parent })
      walk(n.children)
    }
  }
  walk(buildTree(props.allTags))
  return out
})

const isEdit = computed(() => props.task !== null)
const title = computed(() => (isEdit.value ? '编辑任务' : '新增任务'))

/** 表单数据(本地副本,不直接改 props) */
const form = reactive({
  title: '',
  drive: 'start' as 'start' | 'end',
  priority: 3,
  tags: [] as string[],
  // start:预期间隔(天)+ 完成后是否重置(独立)
  expected_days: 15 as number | null,
  is_cyclic: false,
  // end:重复间隔(天),空=非周期
  recurring: false,
  recurrence_days: 1 as number | null,
  anchor: '',
  deadline: '',
  note: '',
})

const saving = ref(false)

/** 打开时:编辑预填 / 新增重置 */
watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    const t = props.task
    form.title = t?.title ?? ''
    form.drive = t?.drive ?? 'start'
    form.priority = t?.priority ?? 3
    form.tags = t ? [...t.tags] : []
    form.expected_days = t?.expected_days ?? 15
    form.is_cyclic = t ? Boolean(t.is_cyclic) : false
    form.recurring = t?.recurrence_days != null
    form.recurrence_days = t?.recurrence_days ?? 1
    form.anchor = t?.anchor ?? ''
    form.deadline = t?.deadline ?? ''
    form.note = t?.note ?? ''
  },
)

const isStart = computed(() => form.drive === 'start')

async function submit() {
  if (!form.title.trim()) {
    ElMessage.warning('标题不能为空')
    return
  }
  saving.value = true
  try {
    // 按 drive 只带对应字段:start=expected_days+is_cyclic,end=recurrence_days
    const driveFields = isStart.value
      ? {
          expected_days: form.expected_days || null,
          is_cyclic: form.is_cyclic ? 1 : 0,
          anchor: form.anchor || null,
        }
      : {
          recurrence_days: form.recurring ? form.recurrence_days || null : null,
          deadline: form.deadline || null,
        }
    if (isEdit.value && props.task) {
      await updateTask(props.task.id, {
        title: form.title.trim(),
        priority: form.priority,
        tags: form.tags,
        note: form.note || null,
        ...driveFields,
      })
      ElMessage.success('已保存')
    } else {
      await addTask({
        title: form.title.trim(),
        drive: form.drive,
        priority: form.priority,
        tags: form.tags,
        note: form.note || null,
        ...driveFields,
      })
      ElMessage.success('已新增任务')
    }
    emit('update:modelValue', false)
    emit('saved')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '提交失败')
  } finally {
    saving.value = false
  }
}

function handleUpdate(value: boolean) {
  emit('update:modelValue', value)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="480px"
    @update:model-value="handleUpdate"
  >
    <el-form label-width="72px" label-position="left">
      <el-form-item label="标题" required>
        <el-input v-model="form.title" placeholder="要做的事" maxlength="50" />
      </el-form-item>

      <el-form-item label="类型">
        <!-- 新增可选;编辑只读(drive 创建后不可改,避免脏数据) -->
        <el-radio-group v-model="form.drive" :disabled="isEdit">
          <el-radio value="start">START · 越久越重要</el-radio>
          <el-radio value="end">DDL · 越近越急</el-radio>
        </el-radio-group>
      </el-form-item>

      <!-- 按 drive 显隐对应字段 -->
      <template v-if="isStart">
        <el-form-item label="锚点">
          <el-date-picker
            v-model="form.anchor"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="上次做是哪天(缺省今天)"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="预期">
          <div class="cycle-row">
            <span class="cycle-text">约</span>
            <el-input-number v-model="form.expected_days" :min="1" :max="365" size="small" />
            <span class="cycle-text">天完成</span>
          </div>
        </el-form-item>
        <el-form-item label="完成后">
          <el-switch v-model="form.is_cyclic" />
          <span class="cycle-text" style="margin-left: 8px">重置一个(周期任务)</span>
        </el-form-item>
      </template>
      <template v-else>
        <el-form-item label="截止">
          <el-date-picker
            v-model="form.deadline"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm"
            placeholder="截止时间"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="重复">
          <div class="cycle-row">
            <el-switch v-model="form.recurring" />
            <template v-if="form.recurring">
              <span class="cycle-text">每</span>
              <el-input-number v-model="form.recurrence_days" :min="1" :max="365" size="small" />
              <span class="cycle-text">天重复</span>
            </template>
          </div>
        </el-form-item>
      </template>

      <el-form-item label="优先级">
        <el-input-number v-model="form.priority" :min="1" :max="5" />
      </el-form-item>

      <el-form-item label="标签">
        <el-select
          v-model="form.tags"
          multiple
          filterable
          allow-create
          default-first-option
          placeholder="选已有标签,或输入新建"
          style="width: 100%"
        >
          <el-option v-for="t in orderedTags" :key="t.name" :label="tagLabel(t.name)" :value="t.name" />
        </el-select>
      </el-form-item>

      <el-form-item label="备注">
        <el-input v-model="form.note" type="textarea" :rows="2" maxlength="200" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="handleUpdate(false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">
        {{ isEdit ? '保存' : '新增' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.cycle-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cycle-text {
  font-size: 13px;
  color: #606266;
}
</style>
