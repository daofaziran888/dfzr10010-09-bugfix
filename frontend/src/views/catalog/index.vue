<template>
  <section class="page" data-module="catalog">
    <header class="page-head">
      <div>
        <h2>数据目录同步管理</h2>
        <p class="page-desc">下游字段目录只沿用当前表结构字段数据集；先兼容历史记录，再核对版本边界，用分区信息校验线上表，结果同步字段核对清单。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记同步作业</button>
        <button class="btn" type="button" @click="exportRows">导出数据目录同步清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>作业编号 / 表名称</span>
        <input v-model="keyword" placeholder="按作业编号或关联表检索" />
      </label>
      <label class="filter-item">
        <span>作业状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th style="width: 240px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openChecklist(row)">核对清单</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无数据目录同步数据，可先登记同步作业</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据目录同步记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="okMessage" class="ok-text">{{ okMessage }}</span>
    </footer>

    <!-- 登记同步作业 -->
    <div v-if="formVisible" class="modal-mask" @click.self="closeForm">
      <div class="modal">
        <div class="modal-head">
          <h3>登记同步作业</h3>
          <button class="btn ghost small" type="button" @click="closeForm">关闭</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <label v-for="field in formFields" :key="field.name" class="form-item">
              <span>{{ field.label }}<em v-if="field.required"> *</em></span>
              <input v-model="form[field.name]" :placeholder="field.placeholder" />
              <span v-if="field.hint" class="hint">{{ field.hint }}</span>
            </label>
          </div>
          <p class="hint" style="margin-top: 12px">
            绑定数据集编号时会校验版本边界：已归档或非当前版本会被拒绝，目录模块禁止回退已发布版本。
          </p>
        </div>
        <div class="modal-foot">
          <button class="btn" type="button" @click="closeForm">取消</button>
          <button class="btn primary" type="button" :disabled="saving" @click="saveForm">保存</button>
        </div>
      </div>
    </div>

    <!-- 核对清单弹窗 -->
    <div v-if="checklistVisible" class="modal-mask" @click.self="closeChecklist">
      <div class="modal">
        <div class="modal-head">
          <h3>字段核对清单 · {{ checklistRow?.表名称 || checklistRow?.作业编号 }}</h3>
          <button class="btn ghost small" type="button" @click="closeChecklist">关闭</button>
        </div>
        <div class="modal-body">
          <div class="detail-grid" v-if="checklistRow">
            <div class="item"><span class="k">关联湖表</span><span>{{ checklistRow.表名称 || '—' }}</span></div>
            <div class="item"><span class="k">绑定数据集</span><span>{{ checklistRow.数据集编号 || '—' }}</span></div>
            <div class="item"><span class="k">线上分区</span><span>{{ checklistRow.线上分区 || '—' }}</span></div>
            <div class="item"><span class="k">当前数据集</span><span>{{ checklistRow.当前数据集编号 || '—' }}</span></div>
          </div>
          <table class="data-table" style="margin-top: 12px">
            <thead>
              <tr><th>核对编号</th><th>数据集</th><th>核对项</th><th>线上分区</th><th>数据集分区</th><th>核对结果</th><th>明细</th><th>处理时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="chk in checklistItems" :key="String(chk.id)">
                <td>{{ chk.核对编号 }}</td><td>{{ chk.数据集编号 || '—' }}</td><td>{{ chk.核对项 }}</td>
                <td>{{ chk.线上分区 || '—' }}</td><td>{{ chk.数据集分区 || '—' }}</td>
                <td><span class="badge" :class="checkBadge(String(chk.核对结果))">{{ chk.核对结果 }}</span></td>
                <td>{{ chk.明细 }}</td><td>{{ chk.处理时间 }}</td>
              </tr>
              <tr v-if="!checklistItems.length"><td colspan="8" class="empty-state">该作业关联表暂无核对记录</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/catalog'
const columns = ['作业编号', '表名称', '源路径', '目标目录', '同步模式', '数据集编号', '线上分区', '同步频率', '作业状态']
const statuses = ['草稿', '同步中', '已完成', '已暂停']
const stats = ref([
  { label: '同步作业总数', value: 0 },
  { label: '同步中作业', value: 0 },
  { label: '核对不一致', value: 0 },
])

const formFields = [
  { name: '作业编号', label: '作业编号', required: true, placeholder: '如 CATA-0010' },
  { name: '表名称', label: '关联湖表', required: false, placeholder: '如 lake.orders，用于分区核对' },
  { name: '源路径', label: '源路径', required: true, placeholder: 's3://lake/warehouse/orders' },
  { name: '目标目录', label: '目标目录', required: true, placeholder: 'lake_catalog.db.orders' },
  { name: '同步模式', label: '同步模式', placeholder: '全量 / 增量' },
  { name: '增量字段', label: '增量字段', placeholder: '如 updated_at' },
  { name: '过滤规则', label: '过滤规则', placeholder: '如 dt >= 2026-11-01' },
  { name: '同步频率', label: '同步频率', placeholder: '如 每日01:00' },
  { name: '数据集编号', label: '绑定数据集编号', placeholder: '如 FD-0002，须为当前版本', hint: '非当前/已归档版本会被拒绝' },
  { name: '线上分区', label: '线上分区', placeholder: '如 dt,region' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const okMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const saving = ref(false)

const formVisible = ref(false)
const form = ref<Record<string, string>>({})
const checklistVisible = ref(false)
const checklistRow = ref<Row | null>(null)
const checklistItems = ref<Row[]>([])

function availableActions(row: Row): string[] {
  const base = []
  if (row.表名称) base.push('分区核对')
  switch (row.status) {
    case '草稿':
      base.push('启动同步')
      break
    case '同步中':
      base.push('暂停同步')
      break
    case '已完成':
      base.push('归档作业')
      break
    default:
      break
  }
  return base
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  form.value = Object.fromEntries(formFields.map((f) => [f.name, '']))
  formVisible.value = true
}

function closeForm() {
  formVisible.value = false
}

async function saveForm() {
  errorMessage.value = ''
  okMessage.value = ''
  saving.value = true
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values: form.value }) })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '登记失败')
    okMessage.value = payload.message
    formVisible.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    saving.value = false
  }
}

async function openChecklist(row: Row) {
  checklistRow.value = row
  checklistVisible.value = true
  checklistItems.value = []
  try {
    const table = String(row.表名称 || '')
    if (!table) {
      errorMessage.value = '该作业未关联湖表，没有核对清单'
      return
    }
    const response = await request(`/api/fieldcheck/checklist?table=${encodeURIComponent(table)}`)
    if (!response.ok) throw new Error('字段核对清单读取失败')
    const payload = await response.json()
    checklistItems.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '字段核对清单读取失败'
  }
}

function closeChecklist() {
  checklistVisible.value = false
  checklistRow.value = null
  checklistItems.value = []
}

function checkBadge(result: string): string {
  if (result === '一致' || result === '通过') return 'success'
  if (result === '不一致' || result === '异常') return 'danger'
  return 'warn'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  okMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '动作未生效')
    okMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据目录同步操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('同步作业列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value[0].value = rows.value.length
    stats.value[1].value = rows.value.filter((r) => r.status === '同步中').length
    stats.value[2].value = rows.value.filter((r) => r.abnormal).length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据目录同步列表读取失败'
  }
}

onMounted(reload)
</script>
