<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, api } from '../api'
const s = ref<any>({})
const noGeneration = ref(false)
const failed = ref(false)
onMounted(async () => {
  try {
    s.value = await api('/seating/stats?hall_id=1')
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) noGeneration.value = true
    else failed.value = true
  }
})
</script>
<template>
  <h1>统计</h1>
  <p class="sub">排座占用与违规汇总 · 与排座图、违规列表同属指针世代<template v-if="s.generation != null"> #{{ s.generation }}</template></p>
  <div class="card" v-if="noGeneration">尚无已落代的排座，请先在排座图页执行排座。</div>
  <div class="card" v-else-if="failed">读模型对不齐，整场失败（不回算、不展示半套数字）。</div>
  <div v-else class="card" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem">
    <div><div class="muted">已排座</div><div class="stat">{{ s.seated }}</div></div>
    <div><div class="muted">未排上</div><div class="stat">{{ s.unplaced }}</div></div>
    <div><div class="muted">违规数</div><div class="stat">{{ s.violations }}</div></div>
    <div><div class="muted">座位容量</div><div class="stat">{{ s.capacity }}</div></div>
  </div>
</template>
