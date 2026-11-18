<template>
  <section class="page" data-module="tablefmt">
    <header class="page-head">
      <div>
        <h2>湖表格式管理管理</h2>
        <p class="page-desc">维护湖仓表格式的类型选择、分区定义与版本策略；登记字段完整保留，创建表后生成同版本表结构字段数据集。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记表格式配置</button>
        <button class="btn" type="button" @click="exportRows">导出湖表格式管理清单</button>
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
        <span>配置编号 / 表名称</span>
        <input v-model="keyword" placeholder="按配置编号或表名称检索" />
      </label>
      <label class="filter-item">
        <span>配置状态</span>
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
          <th style="width: 260px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">配置详情</button>
            <button class="link" type="button" @click="openEdit(row)" :disabled="row.status !== '草稿'">编辑</button>
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openRefresh(row)" :disabled="row.status === '草稿'">刷新字段清单</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无湖表格式管理数据，可先登记表格式配置</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条湖表格式管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="okMessage" class="ok-text">{{ okMessage }}</span>
    </footer>

    <!-- 登记 / 编辑弹窗 -->
    <div v-if="formVisible" class="modal-mask" @click.self="closeForm">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ formMode === 'create' ? '登记表格式配置' : `编辑配置 ${form.配置编号}` }}</h3>
          <button class="btn ghost small" type="button" @click="closeForm">关闭</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <label v-for="field in baseFields" :key="field.name" class="form-item" :class="{ full: field.full }">
              <span>{{ field.label }}<em v-if="field.required"> *</em></span>
              <input v-model="form[field.name]" :placeholder="field.placeholder" />
            </label>
            <label v-for="field in structFields" :key="field.name" class="form-item" :class="{ full: field.full }">
              <span>{{ field.label }}</span>
              <input v-model="form[field.name]" :placeholder="field.placeholder" />
              <span class="hint">{{ field.hint }}</span>
            </label>
          </div>
          <p class="hint" style="margin-top: 12px">
            分区字段、主键字段、版本留存在创建表前必须齐全；多字段用英文逗号分隔，如 <code>dt,region</code>。
          </p>
        </div>
        <div class="modal-foot">
          <button class="btn" type="button" @click="closeForm">取消</button>
          <button class="btn primary" type="button" :disabled="saving" @click="saveForm">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- 刷新字段清单弹窗 -->
    <div v-if="refreshVisible" class="modal-mask" @click.self="closeRefresh">
      <div class="modal">
        <div class="modal-head">
          <h3>刷新字段清单 · {{ refreshRow?.表名称 }}</h3>
          <button class="btn ghost small" type="button" @click="closeRefresh">关闭</button>
        </div>
        <div class="modal-body">
          <p class="hint">提交线上表最新结构；与显式配置冲突时会生成新数据集版本，下游字段目录只保留一份当前定义。</p>
          <div class="form-grid">
            <label class="form-item"><span>线上分区字段</span><input v-model="refreshForm.分区字段" placeholder="如 dt,region" /></label>
            <label class="form-item"><span>线上主键字段</span><input v-model="refreshForm.主键字段" placeholder="如 order_id" /></label>
            <label class="form-item"><span>线上排序字段</span><input v-model="refreshForm.排序字段" placeholder="如 updated_at" /></label>
            <label class="form-item"><span>补充字段</span><input v-model="refreshForm.补充字段" placeholder="额外普通字段，逗号分隔" /></label>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" type="button" @click="closeRefresh">取消</button>
          <button class="btn primary" type="button" :disabled="saving" @click="submitRefresh">执行刷新</button>
        </div>
      </div>
    </div>

    <!-- 配置详情弹窗：配置明细 + 数据集版本 + 字段核对清单，三个区块同源 -->
    <div v-if="detailVisible" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <div class="modal-head">
          <h3>配置详情 · {{ detailRow?.表名称 }}</h3>
          <button class="btn ghost small" type="button" @click="closeDetail">关闭</button>
        </div>
        <div class="modal-body">
          <h4 class="sub-title">表格式配置明细</h4>
          <div class="detail-grid">
            <div v-for="field in detailFields" :key="field" class="item">
              <span class="k">{{ field }}</span><span>{{ detailRow?.[field] ?? '—' }}</span>
            </div>
            <div class="item"><span class="k">当前数据集</span><span>{{ detailData?.当前数据集编号 || '—' }}</span></div>
          </div>

          <h4 class="sub-title">表结构字段数据集（同表仅一份当前定义）</h4>
          <table class="data-table">
            <thead>
              <tr>
                <th>数据集编号</th><th>版本</th><th>来源</th><th>分区字段</th><th>主键字段</th><th>排序字段</th><th>版本保留</th><th>版本状态</th><th>当前</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ds in detailData?.datasets ?? []" :key="String(ds.id)">
                <td>{{ ds.数据集编号 }}</td>
                <td>v{{ ds.版本号 }}</td>
                <td>{{ ds.来源 }}</td>
                <td>{{ ds.分区字段 || '—' }}</td>
                <td>{{ ds.主键字段 || '—' }}</td>
                <td>{{ ds.排序字段 || '—' }}</td>
                <td>{{ ds.版本保留 || '—' }}</td>
                <td><span class="badge" :class="datasetBadge(String(ds.版本状态))">{{ ds.版本状态 }}</span></td>
                <td>{{ ds.是否当前 ? '是' : '否' }}</td>
                <td class="row-actions">
                  <button class="link" type="button" :disabled="!canConfirm(ds)" @click="datasetAction(ds, '确认版本')">确认版本</button>
                  <button class="link" type="button" :disabled="!canPublish(ds)" @click="datasetAction(ds, '发布版本')">发布版本</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="(detailData?.datasets ?? []).some((d: Row) => d.冲突说明)" class="hint" style="margin-top: 6px">
            冲突说明：{{ detailData?.datasets.find((d: Row) => d.冲突说明)?.冲突说明 }}
          </p>

          <h4 class="sub-title">字段清单（当前数据集）</h4>
          <table class="data-table">
            <thead><tr><th>字段名</th><th>字段类型</th><th>字段角色</th></tr></thead>
            <tbody>
              <tr v-for="f in currentFields" :key="f.字段名">
                <td>{{ f.字段名 }}</td><td>{{ f.字段类型 }}</td>
                <td><span class="tag-role" :class="f.字段角色">{{ f.字段角色 }}</span></td>
              </tr>
              <tr v-if="!currentFields.length"><td colspan="3" class="empty-state">暂无字段清单</td></tr>
            </tbody>
          </table>

          <h4 class="sub-title">字段核对清单（与字段详情入口同一批结果）</h4>
          <table class="data-table">
            <thead>
              <tr><th>核对编号</th><th>来源模块</th><th>核对项</th><th>线上分区</th><th>数据集分区</th><th>核对结果</th><th>明细</th><th>处理时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="chk in detailData?.checklist ?? []" :key="String(chk.id)">
                <td>{{ chk.核对编号 }}</td><td>{{ chk.来源模块 }}</td><td>{{ chk.核对项 }}</td>
                <td>{{ chk.线上分区 || '—' }}</td><td>{{ chk.数据集分区 || '—' }}</td>
                <td><span class="badge" :class="checkBadge(String(chk.核对结果))">{{ chk.核对结果 }}</span></td>
                <td>{{ chk.明细 }}</td><td>{{ chk.处理时间 }}</td>
              </tr>
              <tr v-if="!(detailData?.checklist ?? []).length"><td colspan="8" class="empty-state">暂无核对记录</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type FieldRow = { 字段名: string; 字段类型: string; 字段角色: string }
type FormField = { name: string; label: string; required?: boolean; placeholder: string; hint?: string; full?: boolean }

const ENDPOINT = '/api/tablefmt'
const columns = ['配置编号', '表名称', '格式类型', '分区字段', '主键字段', '排序字段', '版本保留', '配置状态']
const statuses = ['草稿', '已创建', '已优化', '已废弃']
const stats = ref([
  { label: '表格式配置总数', value: 0 },
  { label: '已创建表', value: 0 },
  { label: '已优化表', value: 0 },
])

const baseFields: FormField[] = [
  { name: '配置编号', label: '配置编号', required: true, placeholder: '如 TABL-0010' },
  { name: '表名称', label: '表名称', required: true, placeholder: '如 lake.orders' },
  { name: '格式类型', label: '格式类型', required: true, placeholder: 'iceberg / hudi / paimon' },
]
const structFields: FormField[] = [
  { name: '分区字段', label: '分区字段', placeholder: '如 dt', hint: '多字段逗号分隔，如 dt,region' },
  { name: '主键字段', label: '主键字段', placeholder: '如 order_id', hint: '创建表前必填' },
  { name: '排序字段', label: '排序字段', placeholder: '如 updated_at' },
  { name: '版本保留', label: '版本保留', placeholder: '如 30天', hint: '创建表前必填' },
]
const detailFields = ['配置编号', '表名称', '格式类型', '分区字段', '主键字段', '排序字段', '版本保留', '配置状态']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const okMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const saving = ref(false)

// 弹窗状态
const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | null>(null)
const form = ref<Record<string, string>>({})
const refreshVisible = ref(false)
const refreshRow = ref<Row | null>(null)
const refreshForm = ref<Record<string, string>>({})
const detailVisible = ref(false)
const detailRow = ref<Row | null>(null)
const detailData = ref<{ 当前数据集编号: string; datasets: Row[]; checklist: Row[] } | null>(null)

const currentFields = computed<FieldRow[]>(() => {
  const ds = (detailData.value?.datasets ?? []).find((item) => item.是否当前)
  return (ds?.字段清单 as FieldRow[] | undefined) ?? []
})

function availableActions(row: Row): string[] {
  switch (row.status) {
    case '草稿':
      return ['创建表']
    case '已创建':
      return ['优化表']
    case '已优化':
      return ['废弃表']
    default:
      return []
  }
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
  formMode.value = 'create'
  form.value = { 配置编号: '', 表名称: '', 格式类型: '', 分区字段: '', 主键字段: '', 排序字段: '', 版本保留: '' }
  formVisible.value = true
}

function openEdit(row: Row) {
  if (row.status !== '草稿') {
    errorMessage.value = '仅草稿状态的配置可以编辑'
    return
  }
  formMode.value = 'edit'
  editingId.value = Number(row.id)
  form.value = {
    配置编号: String(row.配置编号 ?? ''),
    表名称: String(row.表名称 ?? ''),
    格式类型: String(row.格式类型 ?? ''),
    分区字段: String(row.分区字段 ?? ''),
    主键字段: String(row.主键字段 ?? ''),
    排序字段: String(row.排序字段 ?? ''),
    版本保留: String(row.版本保留 ?? ''),
  }
  formVisible.value = true
}

function closeForm() {
  formVisible.value = false
  editingId.value = null
}

async function saveForm() {
  errorMessage.value = ''
  okMessage.value = ''
  saving.value = true
  try {
    const url = formMode.value === 'create' ? ENDPOINT : `${ENDPOINT}/${editingId.value}`
    const method = formMode.value === 'create' ? 'POST' : 'PUT'
    const response = await request(url, { method, body: JSON.stringify({ values: form.value }) })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '保存失败')
    }
    okMessage.value = payload.message
    formVisible.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}

function openRefresh(row: Row) {
  if (row.status === '草稿') {
    errorMessage.value = '草稿尚未创建表，没有可刷新的线上字段清单'
    return
  }
  refreshRow.value = row
  refreshForm.value = { 分区字段: '', 主键字段: '', 排序字段: '', 补充字段: '' }
  refreshVisible.value = true
}

function closeRefresh() {
  refreshVisible.value = false
  refreshRow.value = null
}

async function submitRefresh() {
  if (!refreshRow.value) return
  errorMessage.value = ''
  okMessage.value = ''
  saving.value = true
  try {
    const response = await request(`${ENDPOINT}/${refreshRow.value.id}/refresh`, {
      method: 'POST',
      body: JSON.stringify({ values: refreshForm.value }),
    })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '刷新失败')
    okMessage.value = payload.message
    refreshVisible.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '刷新失败'
  } finally {
    saving.value = false
  }
}

async function openDetail(row: Row) {
  detailRow.value = row
  detailVisible.value = true
  detailData.value = null
  try {
    const response = await request(`${ENDPOINT}/${row.id}/datasets`)
    if (!response.ok) throw new Error('配置详情读取失败')
    detailData.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '配置详情读取失败'
  }
}

function closeDetail() {
  detailVisible.value = false
  detailRow.value = null
  detailData.value = null
}

function canConfirm(ds: Row): boolean {
  return ds.版本状态 === '待确认'
}

function canPublish(ds: Row): boolean {
  return ds.版本状态 === '已确认'
}

async function datasetAction(ds: Row, action: '确认版本' | '发布版本') {
  errorMessage.value = ''
  okMessage.value = ''
  try {
    const response = await request(`/api/fieldcheck/datasets/${ds.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '版本流转失败')
    okMessage.value = payload.message
    if (detailRow.value) await openDetail(detailRow.value)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版本流转失败'
  }
}

function datasetBadge(status: string): string {
  if (status === '已发布') return 'success'
  if (status === '已归档') return 'warn'
  if (status === '待确认') return 'danger'
  return 'primary'
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
    errorMessage.value = error instanceof Error ? error.message : '湖表格式管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('表格式配置列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value[0].value = rows.value.length
    stats.value[1].value = rows.value.filter((r) => r.status === '已创建' || r.status === '已优化' || r.status === '已废弃').length
    stats.value[2].value = rows.value.filter((r) => r.status === '已优化' || r.status === '已废弃').length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '湖表格式管理列表读取失败'
  }
}

onMounted(reload)
</script>
