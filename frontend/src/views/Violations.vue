<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, api } from '../api'
const viols = ref<any[]>([])
const unplaced = ref<any[]>([])
const noGeneration = ref(false)
const failed = ref(false)
const generation = ref<number | null>(null)
onMounted(async () => {
  try {
    const res = await api('/seating/violations?hall_id=1')
    viols.value = res.violations; unplaced.value = res.unplaced
    generation.value = res.generation
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) noGeneration.value = true
    else failed.value = true
  }
})
</script>
<template>
  <h1>违规</h1>
  <p class="sub">间距不足或同试卷四邻相邻 · 仅来自当前指针世代<template v-if="generation != null"> #{{ generation }}</template></p>
  <div class="card" v-if="noGeneration">尚无已落代的排座，请先在排座图页执行排座。</div>
  <div class="card" v-else-if="failed">读模型对不齐，整场失败（不回算、不展示半套数字）。</div>
  <template v-else>
  <div class="card">
    <table>
      <thead><tr><th>类型</th><th>考生A</th><th>考生B</th><th>说明</th></tr></thead>
      <tbody>
        <tr v-for="(v,i) in viols" :key="i">
          <td>{{ v.kind }}</td><td>{{ v.a_id }}</td><td>{{ v.b_id }}</td><td>{{ v.detail }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!viols.length" class="muted">无违规</p>
  </div>
  <div class="card" v-if="unplaced.length">
    <h3>未排上</h3>
    <div v-for="u in unplaced" :key="u.id">{{ u.name }}（{{ u.ticket_no }}）</div>
  </div>
  </template>
</template>
