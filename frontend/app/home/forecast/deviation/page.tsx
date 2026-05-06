'use client'

import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ChangeEvent } from 'react'
import { Calculator, Download, Loader2, Upload } from 'lucide-react'
import * as XLSX from 'xlsx'
import ForecastTabs from '../components/ForecastTabs'

interface DeviationMonthRow {
  month: string
  actual_sales: number
  forecast_sales: number
  difference: number
  difference_rate: number | null
}

interface DeviationDetailRow {
  product_code: string
  month: string
  actual_sales: number
  forecast_sales: number
  difference: number
  difference_rate: number | null
}

interface ActualFileSummary {
  id: number
  file_name: string
  row_count: number
  created_at: string
  months: string[]
}

function resolveApiBase() {
  if (process.env.NEXT_PUBLIC_API_BASE) return process.env.NEXT_PUBLIC_API_BASE
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:8000`
  }
  return 'http://localhost:8000'
}

function formatRate(value: number | null) {
  if (value === null || Number.isNaN(value)) return '-'
  const pct = value * 100
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
}

export default function DeviationPage() {
  const [apiBase, setApiBase] = useState(resolveApiBase())
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [actualFile, setActualFile] = useState<ActualFileSummary | null>(null)
  const [monthRows, setMonthRows] = useState<DeviationMonthRow[]>([])
  const [detailRows, setDetailRows] = useState<DeviationDetailRow[]>([])
  const [cnyMonthRows, setCnyMonthRows] = useState<DeviationMonthRow[]>([])
  const [cnyDetailRows, setCnyDetailRows] = useState<DeviationDetailRow[]>([])
  const [forecastRunText, setForecastRunText] = useState('')
  const [monthSort, setMonthSort] = useState<{ key: keyof DeviationMonthRow; direction: 'asc' | 'desc' }>({
    key: 'month',
    direction: 'asc',
  })
  const [detailSort, setDetailSort] = useState<{ key: keyof DeviationDetailRow; direction: 'asc' | 'desc' }>({
    key: 'product_code',
    direction: 'asc',
  })

  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem('jy_api_base') : ''
    const base = stored || resolveApiBase()
    setApiBase(base)
    void fetchLatestActual(base)
  }, [])

  const fetchLatestActual = async (base?: string) => {
    const target = (base || apiBase || resolveApiBase()).replace(/\/$/, '')
    const res = await fetch(`${target}/actuals/latest`)
    if (!res.ok) {
      setActualFile(null)
      return
    }
    const body = await res.json()
    if (!body.exists || !body.file) {
      setActualFile(null)
      return
    }
    setActualFile(body.file as ActualFileSummary)
  }

  const uploadActualFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    setLoading(true)
    setUploading(true)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)

      const res = await fetch(`${apiBase.replace(/\/$/, '')}/actuals/upload`, {
        method: 'POST',
        body: form,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || '导入真实销量失败')
      }

      await fetchLatestActual(apiBase)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '导入真实销量失败'
      setError(msg)
    } finally {
      setLoading(false)
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const calculateDeviation = async () => {
    if (!actualFile) {
      setError('请先导入真实销量数据，再进行偏差计算')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${apiBase.replace(/\/$/, '')}/forecast/monthly/deviation/calculate`, {
        method: 'POST',
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || '偏差计算失败')
      }

      const body = await res.json()
      setMonthRows((body.months || []) as DeviationMonthRow[])
      setDetailRows((body.details || []) as DeviationDetailRow[])
      setCnyMonthRows((body.cny_months || []) as DeviationMonthRow[])
      setCnyDetailRows((body.cny_details || []) as DeviationDetailRow[])
      const run = body.forecast_run || {}
      setForecastRunText(`最新预测版本: ${run.run_date || '-'} ${run.created_at || ''}`.trim())
    } catch (err) {
      const msg = err instanceof Error ? err.message : '偏差计算失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const deleteActualFile = async () => {
    const ok = typeof window !== 'undefined' ? window.confirm('确认删除当前真实销量数据吗？') : true
    if (!ok) return

    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${apiBase.replace(/\/$/, '')}/actuals/latest`, { method: 'DELETE' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || '删除真实销量失败')
      }
      setActualFile(null)
      setMonthRows([])
      setDetailRows([])
      setCnyMonthRows([])
      setCnyDetailRows([])
      setForecastRunText('')
    } catch (err) {
      const msg = err instanceof Error ? err.message : '删除真实销量失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const sortMonthBy = (key: keyof DeviationMonthRow) => {
    setMonthSort((prev) => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc',
    }))
  }

  const sortDetailBy = (key: keyof DeviationDetailRow) => {
    setDetailSort((prev) => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc',
    }))
  }

  const sortedMonthRows = [...monthRows].sort((a, b) => {
    const av = a[monthSort.key]
    const bv = b[monthSort.key]
    const dir = monthSort.direction === 'asc' ? 1 : -1

    if (monthSort.key === 'month') {
      return String(av).localeCompare(String(bv)) * dir
    }
    const an = av === null ? Number.NEGATIVE_INFINITY : Number(av)
    const bn = bv === null ? Number.NEGATIVE_INFINITY : Number(bv)
    return (an - bn) * dir
  })

  const sortedDetailRows = [...detailRows].sort((a, b) => {
    const av = a[detailSort.key]
    const bv = b[detailSort.key]
    const dir = detailSort.direction === 'asc' ? 1 : -1

    if (detailSort.key === 'product_code' || detailSort.key === 'month') {
      return String(av).localeCompare(String(bv)) * dir
    }
    const an = av === null ? Number.NEGATIVE_INFINITY : Number(av)
    const bn = bv === null ? Number.NEGATIVE_INFINITY : Number(bv)
    return (an - bn) * dir
  })

  const exportDeviationExcel = () => {
    if (!sortedMonthRows.length && !sortedDetailRows.length) return

    const wb = XLSX.utils.book_new()
    const monthSheetRows = sortedMonthRows.map((row) => ({
      月份: row.month,
      真实销量: row.actual_sales,
      预测销量: row.forecast_sales,
      差异量_预测减真实: row.difference,
      差异率: row.difference_rate === null ? '' : `${(row.difference_rate * 100).toFixed(2)}%`,
    }))
    const detailSheetRows = sortedDetailRows.map((row) => ({
      产品编码: row.product_code,
      月份: row.month,
      真实销量: row.actual_sales,
      预测销量: row.forecast_sales,
      差异量_预测减真实: row.difference,
      差异率: row.difference_rate === null ? '' : `${(row.difference_rate * 100).toFixed(2)}%`,
    }))

    const wsMonth = XLSX.utils.json_to_sheet(monthSheetRows)
    const wsDetail = XLSX.utils.json_to_sheet(detailSheetRows)
    XLSX.utils.book_append_sheet(wb, wsMonth, '月度偏差结果')
    XLSX.utils.book_append_sheet(wb, wsDetail, '产品明细偏差')

    const now = new Date()
    const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(
      now.getHours(),
    ).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`
    XLSX.writeFile(wb, `forecast_deviation_${stamp}.xlsx`)
  }

  return (
    <main style={{ minHeight: '100vh', padding: 20 }}>
      <section className="card" style={{ maxWidth: 1200, margin: '0 auto', borderRadius: 16, padding: 20 }}>
        <ForecastTabs />

        <h1 style={{ marginBottom: 8 }}>预测偏差核对</h1>
        <p style={{ marginTop: 0, color: 'var(--jy-muted, #7f6a4a)' }}>
          导入 2026 年 1-3 月真实销售数据，点击“偏差计算”后生成各月真实值与预测值的差异量、差异率。
        </p>

        {error && (
          <div className="card" style={{ marginTop: 12, borderRadius: 12, padding: 12, color: 'var(--jy-danger, #d9480f)' }}>
            {error}
          </div>
        )}

        <section style={{ marginTop: 14, display: 'grid', gap: 12, gridTemplateColumns: '1fr auto auto auto' }}>
          <input
            value={apiBase}
            onChange={(e) => setApiBase(e.target.value)}
            placeholder="后端地址，例如 http://localhost:8000"
            style={inputStyle}
          />
          <button
            style={ghostButton}
            onClick={() => {
              if (typeof window !== 'undefined') window.localStorage.setItem('jy_api_base', apiBase)
              void fetchLatestActual(apiBase)
            }}
          >
            刷新
          </button>
          <button
            style={loading ? { ...primaryButton, ...disabledButtonStyle } : primaryButton}
            disabled={loading}
            onClick={() => fileInputRef.current?.click()}
            title={loading ? '操作进行中，请稍候' : '导入真实销量文件'}
          >
            {uploading ? <Loader2 size={16} /> : <Upload size={16} />} 导入真实销量
          </button>
          <button
            style={loading || !actualFile ? { ...ghostButton, ...disabledButtonStyle } : ghostButton}
            disabled={loading || !actualFile}
            onClick={deleteActualFile}
            title={actualFile ? '删除当前真实销量数据' : '暂无可删除的真实销量数据'}
          >
            删除真实销量
          </button>
        </section>

        <input ref={fileInputRef} type="file" accept=".csv,.xls,.xlsx" onChange={uploadActualFile} style={{ display: 'none' }} />

        <section className="card" style={{ marginTop: 14, borderRadius: 12, padding: 12 }}>
          <div style={{ color: 'var(--jy-muted, #7f6a4a)', fontSize: 14, display: 'grid', gap: 6 }}>
            <div>当前真实数据文件: {actualFile?.file_name || '未导入'}</div>
            <div>记录数: {actualFile?.row_count ?? 0}</div>
            <div>覆盖月份: {actualFile?.months?.length ? actualFile.months.join('、') : '-'}</div>
            <div>导入时间: {actualFile?.created_at || '-'}</div>
          </div>

          <div style={{ marginTop: 12 }}>
            <button
              style={loading || !actualFile ? { ...accentButton, ...disabledButtonStyle } : accentButton}
              disabled={loading || !actualFile}
              onClick={calculateDeviation}
              title={
                loading
                  ? '操作进行中，请稍候'
                  : actualFile
                    ? '根据最新预测与最新真实数据计算偏差'
                    : '请先导入真实销量数据'
              }
            >
              {loading ? <Loader2 size={16} /> : <Calculator size={16} />} 偏差计算
            </button>
            {!actualFile && <p style={{ margin: '8px 0 0', color: 'var(--jy-muted, #7f6a4a)', fontSize: 13 }}>请先导入真实销量数据。</p>}
          </div>
        </section>

        <section className="card" style={{ marginTop: 14, borderRadius: 12, padding: 12 }}>
          <h3 style={{ marginTop: 0 }}>春节窗口单独误差</h3>
          <p style={{ marginTop: 0, color: 'var(--jy-muted, #7f6a4a)', fontSize: 13 }}>
            统计春节窗口(月份由节日日期自动识别，通常为 1-2 月)的误差，便于单独校验春节影响。
          </p>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--jy-surface-soft, #fff6ea)' }}>
                  <th style={thStyle}>月份</th>
                  <th style={thStyle}>真实销量</th>
                  <th style={thStyle}>预测销量</th>
                  <th style={thStyle}>差异量(预测-真实)</th>
                  <th style={thStyle}>差异率</th>
                </tr>
              </thead>
              <tbody>
                {cnyMonthRows.map((row) => (
                  <tr key={`cny-${row.month}`} style={{ borderTop: '1px solid var(--jy-border, #efd8b0)' }}>
                    <td style={tdStyle}>{row.month}</td>
                    <td style={tdStyle}>{row.actual_sales}</td>
                    <td style={tdStyle}>{row.forecast_sales}</td>
                    <td style={tdStyle}>{row.difference}</td>
                    <td style={tdStyle}>{formatRate(row.difference_rate)}</td>
                  </tr>
                ))}
                {!cnyMonthRows.length && (
                  <tr>
                    <td style={tdStyle} colSpan={5}>暂无春节窗口偏差结果</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: 10, color: 'var(--jy-muted, #7f6a4a)', fontSize: 13 }}>
            春节窗口明细条数: {cnyDetailRows.length}
          </div>
        </section>

        <section className="card" style={{ marginTop: 14, borderRadius: 12, padding: 12 }}>
          <h3 style={{ marginTop: 0 }}>月度偏差结果</h3>
          {forecastRunText && <p style={{ marginTop: 0, color: 'var(--jy-muted, #7f6a4a)' }}>{forecastRunText}</p>}
          <div style={{ marginBottom: 10 }}>
            <button
              style={loading || (!sortedMonthRows.length && !sortedDetailRows.length) ? { ...ghostButton, ...disabledButtonStyle } : ghostButton}
              disabled={loading || (!sortedMonthRows.length && !sortedDetailRows.length)}
              onClick={exportDeviationExcel}
              title={sortedMonthRows.length || sortedDetailRows.length ? '导出月度偏差和产品明细偏差到同一个Excel文件' : '暂无可导出数据'}
            >
              <Download size={16} /> 导出偏差结果
            </button>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--jy-surface-soft, #fff6ea)' }}>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortMonthBy('month')}>月份 {monthSort.key === 'month' ? (monthSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortMonthBy('actual_sales')}>真实销量 {monthSort.key === 'actual_sales' ? (monthSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortMonthBy('forecast_sales')}>预测销量 {monthSort.key === 'forecast_sales' ? (monthSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortMonthBy('difference')}>差异量(预测-真实) {monthSort.key === 'difference' ? (monthSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortMonthBy('difference_rate')}>差异率 {monthSort.key === 'difference_rate' ? (monthSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                </tr>
              </thead>
              <tbody>
                {sortedMonthRows.map((row) => (
                  <tr key={row.month} style={{ borderTop: '1px solid var(--jy-border, #efd8b0)' }}>
                    <td style={tdStyle}>{row.month}</td>
                    <td style={tdStyle}>{row.actual_sales}</td>
                    <td style={tdStyle}>{row.forecast_sales}</td>
                    <td style={tdStyle}>{row.difference}</td>
                    <td style={tdStyle}>{formatRate(row.difference_rate)}</td>
                  </tr>
                ))}
                {!sortedMonthRows.length && (
                  <tr>
                    <td style={tdStyle} colSpan={5}>暂无偏差结果</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card" style={{ marginTop: 14, borderRadius: 12, padding: 12 }}>
          <h3 style={{ marginTop: 0 }}>产品明细偏差（可选核查）</h3>
          <div style={{ maxHeight: 320, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--jy-surface-soft, #fff6ea)' }}>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortDetailBy('product_code')}>产品编码 {detailSort.key === 'product_code' ? (detailSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortDetailBy('month')}>月份 {detailSort.key === 'month' ? (detailSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortDetailBy('actual_sales')}>真实销量 {detailSort.key === 'actual_sales' ? (detailSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortDetailBy('forecast_sales')}>预测销量 {detailSort.key === 'forecast_sales' ? (detailSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortDetailBy('difference')}>差异量 {detailSort.key === 'difference' ? (detailSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                  <th style={thStyle}><button style={sortButton} onClick={() => sortDetailBy('difference_rate')}>差异率 {detailSort.key === 'difference_rate' ? (detailSort.direction === 'asc' ? '↑' : '↓') : '↕'}</button></th>
                </tr>
              </thead>
              <tbody>
                {sortedDetailRows.map((row, idx) => (
                  <tr key={`${row.product_code}-${row.month}-${idx}`} style={{ borderTop: '1px solid var(--jy-border, #efd8b0)' }}>
                    <td style={tdStyle}>{row.product_code}</td>
                    <td style={tdStyle}>{row.month}</td>
                    <td style={tdStyle}>{row.actual_sales}</td>
                    <td style={tdStyle}>{row.forecast_sales}</td>
                    <td style={tdStyle}>{row.difference}</td>
                    <td style={tdStyle}>{formatRate(row.difference_rate)}</td>
                  </tr>
                ))}
                {!sortedDetailRows.length && (
                  <tr>
                    <td style={tdStyle} colSpan={6}>暂无明细偏差</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </main>
  )
}

const inputStyle: CSSProperties = {
  border: '1px solid var(--jy-border, #efd8b0)',
  borderRadius: 10,
  padding: '10px 12px',
}

const primaryButton: CSSProperties = {
  border: 'none',
  borderRadius: 10,
  padding: '10px 14px',
  color: '#fff',
  background: 'linear-gradient(135deg, var(--jy-primary, #f39800), var(--jy-accent, #ff5a1f))',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 8,
  cursor: 'pointer',
  fontWeight: 700,
}

const accentButton: CSSProperties = {
  ...primaryButton,
  background: 'linear-gradient(135deg, #dc7f00, #f39800)',
}

const disabledButtonStyle: CSSProperties = {
  opacity: 0.55,
  cursor: 'not-allowed',
}

const ghostButton: CSSProperties = {
  border: '1px solid var(--jy-border, #efd8b0)',
  borderRadius: 10,
  padding: '10px 14px',
  color: 'var(--jy-muted, #7f6a4a)',
  background: '#fff',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 8,
  cursor: 'pointer',
  fontWeight: 700,
}

const thStyle: CSSProperties = {
  textAlign: 'left',
  padding: '10px 12px',
  color: 'var(--jy-muted, #7f6a4a)',
}

const sortButton: CSSProperties = {
  border: 'none',
  background: 'transparent',
  padding: 0,
  margin: 0,
  color: 'inherit',
  fontWeight: 700,
  cursor: 'pointer',
}

const tdStyle: CSSProperties = {
  padding: '10px 12px',
}
