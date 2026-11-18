<template>
  <section class="page" data-module="fieldcheck">
    <header class="page-head">
      <div>
        <h2>表结构字段数据集</h2>
        <p class="page-desc">每张表只保留一份可追溯的当前字段定义；版本按 待确认 → 已确认 → 已发布 顺序推进，已发布版本只归档不回退。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="showCurrent = !showCurrent; void reload()">
          {{ showCurrent ? '查看全部版本' : '只看当前版本' }}
        </button>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>表名称</span>
        <input v-model="tableFilter" placeholder="按表名称检索" />
      </label>
      <label class="filter-item">
        <span>版本状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="s in statusOrder" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="tableFilter = ''; statusFilter = ''; void reload()">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>数据集编号</th><th>表名称</th><th>版本</th><th>来源</th>
          <th>分区字段</th><th>主键字段</th><th>排序字段</th><th>版本保留</th>
          <th>版本状态</th><th>当前</th><th style="width: 200px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="ds in rows" :key="String(ds.id)">
          <td>{{ ds.数据集编号 }}</td>
          <td>{{ ds.表名称 }}</td>
          <td>v{{ ds.版本号 }}</td>
          <td>{{ ds.来源 }}</td>
          <td>{{ ds.分区字段 || '—' }}</td>
          <td>{{ ds.主键字段 || '—' }}</td>
          <td>{{ ds.排序字段 || '—' }}</td>
          <td>{{ ds.版本保留 || '—' }}</td>
          <td><span class="badge" :class="datasetBadge(ds.版本状态)">{{ ds.版本状态 }}</span></td>
          <td>{{ ds.是否当前 ? '是' : '否' }}</td>
          <td class="row-actions">
            <button class="link" type="button" :disabled="ds.版本状态 !== '待确认'" @click="act(ds, '确认版本')">确认版本</button>
            <button class="link" type="button" :disabled="ds.版本状态 !== '已确认'" @click="act(ds, '发布版本')">发布版本</button>
            <button class="link" type="button" @click="openDetail(ds)">字段详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="11" class="empty-state">暂无表结构字段数据集，创建湖表格式配置后自动生成</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 个数据集版本</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="okMessage" class="ok-text">{{ okMessage }}</span>
    </footer>

    <!-- 字段详情：字段清单 + 同一批字段核对清单 -->
    <div v-if="detailVisible" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <div class="modal-head">
          <h3>字段详情 · {{ detail?.dataset.数据集编号 }}（{{ detail?.dataset.表名称 }} v{{ detail?.dataset.版本号 }}）</h3>
          <button class="btn ghost small" type="button" @click="closeDetail">关闭</button>
        </div>
        <div class="modal-body">
          <h4 class="sub-title">字段清单</h4>
          <table class="data-table">
            <thead><tr><th>字段名</th><th>字段类型</th><th>字段角色</th></tr></thead>
            <tbody>
              <tr v-for="f in detail?.dataset.字段清单 ?? []" :key="f.字段名">
                <td>{{ f.字段名 }}</td><td>{{ f.字段类型 }}</td>
                <td><span class="tag-role" :class="f.字段角色">{{ f.字段角色 }}</span></td>
              </tr>
            </tbody>
          </table>
          <p v-if="detail?.dataset.冲突说明" class="hint" style="margin-top: 8px">
            冲突说明：{{ detail.dataset.冲突说明 }}
          </p>

          <h4 class="sub-title">字段核对清单（与配置详情入口同一批结果）</h4>
          <table class="data-table">
            <thead>
              <tr><th>核对编号</th><th>来源模块</th><th>核对项</th><th>线上分区</th><th>数据集分区</th><th>核对结果</th><th>明细</th><th>处理时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="chk in detail?.checklist ?? []" :key="chk.id">
                <td>{{ chk.核对编号 }}</td><td>{{ chk.来源模块 }}</td><td>{{ chk.核对项 }}</td>
                <td>{{ chk.线上分区 || '—' }}</td><td>{{ chk.数据集分区 || '—' }}</td>
                <td><span class="badge" :class="checkBadge(chk.核对结果)">{{ chk.核对结果 }}</span></td>
                <td>{{ chk.明细 }}</td><td>{{ chk.处理时间 }}</td>
              </tr>
              <tr v-if="!(detail?.checklist ?? []).length"><td colspan="8" class="empty-state">暂无核对记录</td></tr>
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

type Row = Record<string, any>

const statusOrder = ['待确认', '已确认', '已发布', '已归档']
const rows = ref<Row[]>([])
const total = ref(0)
const tableFilter = ref('')
const statusFilter = ref('')
const showCurrent = ref(false)
const errorMessage = ref('')
const okMessage = ref('')

const detailVisible = ref(false)
const detail = ref<{ dataset: Row; checklist: Row[] } | null>(null)

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

async function act(ds: Row, action: '确认版本' | '发布版本') {
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
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版本流转失败'
  }
}

async function openDetail(ds: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`/api/fieldcheck/datasets/${ds.id}`)
    if (!response.ok) throw new Error('字段详情读取失败')
    detail.value = await response.json()
    detailVisible.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '字段详情读取失败'
  }
}

function closeDetail() {
  detailVisible.value = false
  detail.value = null
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (tableFilter.value) params.set('table', tableFilter.value)
  if (statusFilter.value) params.set('status', statusFilter.value)
  if (showCurrent.value) params.set('current_only', 'true')
  try {
    const response = await request(`/api/fieldcheck/datasets?${params.toString()}`)
    if (!response.ok) throw new Error('数据集读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据集读取失败'
  }
}

onMounted(reload)
</script>
