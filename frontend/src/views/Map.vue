<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
const data = ref<any>(null)
const noPlan = ref(false)
const candidates = ref<any[]>([])
async function refresh() {
  try {
    data.value = await api('/seating/current?hall_id=1')
    noPlan.value = false
  } catch {
    data.value = null
    noPlan.value = true
  }
}
async function run() {
  data.value = await api('/seating/run?hall_id=1', { method: 'POST' })
  noPlan.value = false
}
onMounted(async () => {
  candidates.value = await api('/candidates')
  await refresh()
})
const gridStyle = computed(() => data.value ? ({ gridTemplateColumns: `repeat(${data.value.cols}, 72px)` }) : {})
const cells = computed(() => {
  if (!data.value) return []
  const map = new Map<string, any>()
  for (const a of data.value.assignments || []) map.set(a.row + ',' + a.col, a)
  const out: any[] = []
  for (let r = 0; r < data.value.rows; r++) {
    for (let c = 0; c < data.value.cols; c++) {
      out.push(map.get(r + ',' + c) || { empty: true, row: r, col: c })
    }
  }
  return out
})
// 违规高亮与网格出自同一份响应,天然同一代
const violKeys = computed(() => {
  const keys = new Set<string>()
  for (const x of data.value?.violations || []) {
    if (x.a_id != null) keys.add(String(x.a_id))
    if (x.b_id != null) keys.add(String(x.b_id))
  }
  return keys
})
function isViol(cell: any) {
  if (cell.empty) return false
  const id = cell.candidate_id ?? cell.id
  return id != null && violKeys.value.has(String(id))
}
function paperClass(pid: number) {
  return pid % 2 === 0 ? 'b' : 'a'
}
</script>
<template>
  <h1>考场课桌网格</h1>
  <p class="sub">课桌网格为主视图 · 左侧考生名册夹板 · 违规课桌高亮</p>
  <button class="btn" @click="run">重新排座</button>
  <span v-if="data" class="muted" style="margin-left:0.75rem">当前第 {{ data.generation }} 代</span>
  <p v-if="noPlan" class="muted" style="margin-top:0.85rem">尚未排座,点击「重新排座」生成第一代。</p>
  <div class="hs-classroom" style="margin-top:0.85rem" v-if="data">
    <aside class="hs-clipboard">
      <h2>考生名册</h2>
      <div v-for="c in candidates" :key="c.id" class="hs-roster-row">
        <div>
          <div>{{ c.name }}</div>
          <div class="hs-ticket">{{ c.ticket_no }}</div>
        </div>
        <div>卷{{ c.paper_id }}</div>
      </div>
    </aside>
    <div class="hs-desk-stage">
      <div class="hs-grid-board" :style="gridStyle">
        <div
          v-for="(cell,i) in cells" :key="i"
          class="hs-desk"
          :class="{ empty: cell.empty, 'hs-viol': isViol(cell) }"
        >
          <template v-if="!cell.empty">
            <span class="hs-paper-tag" :class="paperClass(cell.paper_id)">卷{{ cell.paper_id }}</span>
            <div>{{ cell.name }}</div>
          </template>
          <template v-else>·</template>
        </div>
      </div>
    </div>
  </div>
</template>
