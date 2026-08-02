<script setup lang="ts">
/**
 * 夜间免打扰横带:一条 0~24 点的轨道,0→nightEnd 段涂深(=不打扰)。
 * 右端手柄可左右拖(吸附整点)调整「到几点」;当前时刻以细竖线标出。
 * 可视化优先:不打扰是「每天重复的一段时间」,一眼看出,不靠读字。
 *
 * 纯受控组件:modelValue = nightEnd(0~23,0=关闭)。改动经 update:modelValue 上抛,
 * 由父组件决定何时落库(本组件不碰网络/设置)。
 */
import { computed, ref } from 'vue'

const props = defineProps<{ modelValue: number }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: number): void
  (e: 'change', v: number): void   // 拖动/按键结束,值已定格,父组件据此落库
}>()

const HOURS = 24
const track = ref<HTMLElement | null>(null)
const dragging = ref(false)

/** 当前时刻(0~24 浮点),用于竖线定位。每次渲染取一次即可,无需秒级响应。 */
const nowHour = new Date().getHours() + new Date().getMinutes() / 60

const fillPct = computed(() => (props.modelValue / HOURS) * 100)
const nowPct = computed(() => (nowHour / HOURS) * 100)

/** 轨道某 clientX 对应的小时数(0~24),吸附整点后上抛。 */
function hourAt(clientX: number): number {
  const el = track.value
  if (!el) return props.modelValue
  const rect = el.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  return Math.round(ratio * HOURS)
}

function onPointerDown(e: PointerEvent) {
  dragging.value = true
  emit('update:modelValue', Math.min(23, hourAt(e.clientX)))
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp, { once: true })
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  emit('update:modelValue', Math.min(23, hourAt(e.clientX)))
}

function onPointerUp() {
  dragging.value = false
  window.removeEventListener('pointermove', onPointerMove)
  emit('change', props.modelValue)      // 松手定格,父组件落库
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowLeft') {
    const v = Math.max(0, props.modelValue - 1)
    emit('update:modelValue', v)
    emit('change', v)
    e.preventDefault()
  } else if (e.key === 'ArrowRight') {
    const v = Math.min(23, props.modelValue + 1)
    emit('update:modelValue', v)
    emit('change', v)
    e.preventDefault()
  }
}

// 刻度:每 3 小时标一个数,避免拥挤
const TICKS = [0, 3, 6, 9, 12, 15, 18, 21, 24]
</script>

<template>
  <div class="night-band">
    <div
      ref="track"
      class="nb-track"
      role="slider"
      :aria-valuenow="modelValue"
      aria-valuemin="0"
      aria-valuemax="23"
      aria-label="夜间免打扰到几点"
      tabindex="0"
      @pointerdown="onPointerDown"
      @keydown="onKey"
    >
      <!-- 不打扰段:0 → nightEnd 涂深 -->
      <div class="nb-fill" :style="{ width: fillPct + '%' }" />
      <!-- 当前时刻竖线 -->
      <div class="nb-now" :style="{ left: nowPct + '%' }" title="现在" />
      <!-- 拖动手柄,吸附整点 -->
      <div
        class="nb-handle"
        :class="{ dragging }"
        :style="{ left: fillPct + '%' }"
      >{{ modelValue }}</div>
    </div>
    <div class="nb-ticks">
      <span v-for="h in TICKS" :key="h" class="nb-tick" :style="{ left: (h / HOURS) * 100 + '%' }">
        {{ h }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.night-band {
  user-select: none;
}
.nb-track {
  position: relative;
  height: 22px;
  background: #eef1f6;
  border-radius: 6px;
  cursor: pointer;
  outline: none;
}
.nb-track:focus-visible {
  box-shadow: 0 0 0 2px #b3d0f0;
}
.nb-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: linear-gradient(90deg, #3d4a63, #55688a);
  border-radius: 6px 0 0 6px;
  transition: width 0.05s linear;
}
.nb-now {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: 2px;
  background: #e8a33d;
  transform: translateX(-1px);
  pointer-events: none;
}
.nb-handle {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  min-width: 26px;
  height: 26px;
  padding: 0 4px;
  box-sizing: border-box;
  background: #fff;
  border: 2px solid #55688a;
  border-radius: 13px;
  color: #3d4a63;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
  pointer-events: none; /* 拖动由轨道统一处理,手柄只作视觉 */
}
.nb-handle.dragging {
  cursor: grabbing;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
}
.nb-ticks {
  position: relative;
  height: 16px;
  margin-top: 2px;
}
.nb-tick {
  position: absolute;
  transform: translateX(-50%);
  font-size: 10px;
  color: #a0a8b5;
}
.nb-tick:first-child {
  transform: translateX(0);
}
.nb-tick:last-child {
  transform: translateX(-100%);
}
</style>
