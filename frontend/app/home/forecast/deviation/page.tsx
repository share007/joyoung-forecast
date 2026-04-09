'use client'

import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ChangeEvent } from 'react'
import Link from 'next/link'
import { ArrowLeft, Calculator, Loader2, Upload } from 'lucide-react'

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
  const [forecastRunText, setForecastRunText] = useState('')

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
      const run = body.forecast_run || {}
      setForecastRunText(`预测运行: ${run.run_date || '-'} ${run.created_at || ''}`.trim())
    } catch (err) {
      const msg = err instanceof Error ? err.message : '偏差计算失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main style={{ minHeight: '100vh', padding: 20 }}>
      <section className="card" style={{ maxWidth: 1200, margin: '0 auto', borderRadius: 16, padding: 20 }}>
        <Link href="/home/forecast" style={{ color: 'var(--jy-muted, #7f6a4a)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <ArrowLeft size={16} /> 返回
        </Link>

        <h1 style={{ marginBottom: 8 }}>预测偏差核对</h1>
        <p style={{ marginTop: 0, color: 'var(--jy-muted, #7f6a4a)' }}>
          导入 2026 年 1-3 月真实销售数据，点击“偏差计算”后生成各月真实值与预测值的差异量、差异率。
        </p>

        {error && (
          <div className="card" style={{ marginTop: 12, borderRadius: 12, padding: 12, color: 'var(--jy-danger, #d9480f)' }}>
            {error}
          </div>
        )}

        <section style={{ marginTop: 14, display: 'grid', gap: 12, gridTemplateColumns: '1fr auto auto' }}>
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
            style={primaryButton}
            disabled={loading}
            onClick={() => fileInputRef.current?.click()}
            title={loading ? '操作进行中，请稍候' : '导入真实销量文件'}
          >
            {uploading ? <Loader2 size={16} /> : <Upload size={16} />} 导入真实销量
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
              style={accentButton}
              disabled={loading}
              onClick={calculateDeviation}
              title={loading ? '操作进行中，请稍候' : '根据最新预测与最新真实数据计算偏差'}
            >
              {loading ? <Loader2 size={16} /> : <Calculator size={16} />} 偏差计算
            </button>
          </div>
        </section>

        <section className="card" style={{ marginTop: 14, borderRadius: 12, padding: 12 }}>
          <h3 style={{ marginTop: 0 }}>月度偏差结果</h3>
          {forecastRunText && <p style={{ marginTop: 0, color: 'var(--jy-muted, #7f6a4a)' }}>{forecastRunText}</p>}
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
                {monthRows.map((row) => (
                  <tr key={row.month} style={{ borderTop: '1px solid var(--jy-border, #efd8b0)' }}>
                    <td style={tdStyle}>{row.month}</td>
                    <td style={tdStyle}>{row.actual_sales}</td>
                    <td style={tdStyle}>{row.forecast_sales}</td>
                    <td style={tdStyle}>{row.difference}</td>
                    <td style={tdStyle}>{formatRate(row.difference_rate)}</td>
                  </tr>
                ))}
                {!monthRows.length && (
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
                  <th style={thStyle}>产品编码</th>
                  <th style={thStyle}>月份</th>
                  <th style={thStyle}>真实销量</th>
                  <th style={thStyle}>预测销量</th>
                  <th style={thStyle}>差异量</th>
                  <th style={thStyle}>差异率</th>
                </tr>
              </thead>
              <tbody>
                {detailRows.map((row, idx) => (
                  <tr key={`${row.product_code}-${row.month}-${idx}`} style={{ borderTop: '1px solid var(--jy-border, #efd8b0)' }}>
                    <td style={tdStyle}>{row.product_code}</td>
                    <td style={tdStyle}>{row.month}</td>
                    <td style={tdStyle}>{row.actual_sales}</td>
                    <td style={tdStyle}>{row.forecast_sales}</td>
                    <td style={tdStyle}>{row.difference}</td>
                    <td style={tdStyle}>{formatRate(row.difference_rate)}</td>
                  </tr>
                ))}
                {!detailRows.length && (
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

const tdStyle: CSSProperties = {
  padding: '10px 12px',
}
