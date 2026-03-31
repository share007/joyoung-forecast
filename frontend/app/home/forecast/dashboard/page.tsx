'use client'

import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ChangeEvent } from 'react'
import Link from 'next/link'
import { AlertCircle, ArrowLeft, Download, Loader2, Upload } from 'lucide-react'

interface MonthlyForecastRow {
  product_code: string
  month: string
  sales: number
  lower_bound?: number
  upper_bound?: number
}

function resolveApiBase() {
  if (process.env.NEXT_PUBLIC_API_BASE) return process.env.NEXT_PUBLIC_API_BASE
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:8000`
  }
  return 'http://localhost:8000'
}

export default function DashboardPage() {
  const [apiBase, setApiBase] = useState('')
  const [apiStatus, setApiStatus] = useState<'unknown' | 'ok' | 'error'>('unknown')
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError] = useState('')
  const [importFileName, setImportFileName] = useState('')
  const [importColumns, setImportColumns] = useState<string[]>([])
  const [detected, setDetected] = useState<Record<string, string>>({})
  const [columnMapping, setColumnMapping] = useState({ product_code: '', date: '', sales: '' })
  const [forecastRows, setForecastRows] = useState<MonthlyForecastRow[]>([])
  const [algorithmSummary, setAlgorithmSummary] = useState('')

  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem('jy_api_base') : ''
    const base = stored || resolveApiBase()
    setApiBase(base)
    void testConnection(base)
  }, [])

  const testConnection = async (base?: string) => {
    const target = (base || apiBase || resolveApiBase()).replace(/\/$/, '')
    try {
      const res = await fetch(`${target}/`)
      if (!res.ok) throw new Error('bad status')
      setApiStatus('ok')
      return true
    } catch {
      setApiStatus('error')
      return false
    }
  }

  const uploadFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const connected = await testConnection(apiBase)
    if (!connected) {
      setError(`后端不可达：${apiBase}`)
      return
    }

    setLoading(true)
    setUploading(true)
    setUploadProgress(0)
    setError('')
    setForecastRows([])

    try {
      const form = new FormData()
      form.append('file', file)

      const payload = await new Promise<any>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${apiBase.replace(/\/$/, '')}/upload`)

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            setUploadProgress(Math.min(99, Math.round((e.loaded / e.total) * 100)))
          }
        }

        xhr.onerror = () => reject(new Error('Failed to fetch'))
        xhr.onload = () => {
          try {
            const body = JSON.parse(xhr.responseText || '{}')
            if (xhr.status >= 200 && xhr.status < 300) {
              setUploadProgress(100)
              resolve(body)
              return
            }
            reject(new Error(body.detail || `上传失败（${xhr.status}）`))
          } catch {
            reject(new Error('上传响应解析失败'))
          }
        }

        xhr.send(form)
      })

      setImportFileName(file.name)
      setImportColumns(payload.summary?.columns || [])
      setDetected(payload.detected_columns || {})
      setColumnMapping({
        product_code: payload.detected_columns?.product_code || '',
        date: payload.detected_columns?.date || '',
        sales: payload.detected_columns?.sales || '',
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : '上传失败'
      setError(`${msg}。若看到 Failed to fetch，请确认后端地址可达：${apiBase}`)
    } finally {
      setLoading(false)
      setUploading(false)
    }
  }

  const runForecast = async () => {
    const connected = await testConnection(apiBase)
    if (!connected) {
      setError(`后端不可达：${apiBase}`)
      return
    }

    setLoading(true)
    setError('')
    try {
      const mappingPayload =
        columnMapping.product_code && columnMapping.date && columnMapping.sales
          ? columnMapping
          : undefined

      const res = await fetch(`${apiBase.replace(/\/$/, '')}/forecast/monthly`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          forecast_months: 3,
          column_mapping: mappingPayload,
        }),
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || '预测失败')
      }

      const body = await res.json()
      setForecastRows(body.data || [])
      setAlgorithmSummary(
        `${body.algorithm?.strategy || ''} | 已选模型: ${body.algorithm?.selected_method || '-'} | 评估指标: ${body.algorithm?.selection_metric || '-'}`,
      )
      if (!importFileName && body.source_file) setImportFileName(body.source_file)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '预测失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const exportCsv = () => {
    if (!forecastRows.length) return
    const content = [
      ['产品编码', '月份', '销量'].join(','),
      ...forecastRows.map((row) => [row.product_code, row.month, row.sales].join(',')),
    ].join('\n')

    const blob = new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `monthly_forecast_${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
  }

  return (
    <main style={{ minHeight: '100vh', padding: 20 }}>
      <section className="card" style={{ maxWidth: 1200, margin: '0 auto', borderRadius: 16, padding: 20 }}>
        <Link href="/home/forecast" style={{ color: 'var(--jy-muted)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <ArrowLeft size={16} /> 返回
        </Link>
        <h1 style={{ marginBottom: 8 }}>九阳月度销量预测</h1>
        <p style={{ marginTop: 0, color: 'var(--jy-muted)' }}>上传历史日销量数据，系统将输出当前月起未来3个月各产品编码销量。</p>

        <section className="card" style={{ borderRadius: 12, padding: 12, display: 'grid', gap: 10, gridTemplateColumns: '1fr auto auto' }}>
          <input value={apiBase} onChange={(e) => setApiBase(e.target.value)} placeholder="后端地址，例如 http://localhost:8000" style={inputStyle} />
          <button
            onClick={async () => {
              if (typeof window !== 'undefined') window.localStorage.setItem('jy_api_base', apiBase)
              await testConnection(apiBase)
            }}
            style={ghostButton}
          >
            测试连接
          </button>
          <div style={{ alignSelf: 'center', fontSize: 13, color: apiStatus === 'ok' ? '#2f9e44' : apiStatus === 'error' ? '#d9480f' : 'var(--jy-muted)' }}>
            {apiStatus === 'ok' ? '后端已连接' : apiStatus === 'error' ? '后端连接失败' : '未检测'}
          </div>
        </section>

        {error && (
          <div className="card" style={{ marginTop: 12, borderRadius: 12, padding: 12, color: 'var(--jy-danger)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertCircle size={16} /> {error}
          </div>
        )}

        {uploading && (
          <div className="card" style={{ marginTop: 12, borderRadius: 12, padding: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--jy-muted)', fontSize: 13 }}>
              <span>上传进度</span>
              <span>{uploadProgress}%</span>
            </div>
            <div style={{ height: 10, borderRadius: 999, background: '#fde9cb', marginTop: 8 }}>
              <div style={{ width: `${uploadProgress}%`, height: '100%', background: 'linear-gradient(90deg,#f39800,#ff5a1f)', borderRadius: 999 }} />
            </div>
          </div>
        )}

        <section style={{ marginTop: 14, display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <button style={primaryButton} onClick={() => fileInputRef.current?.click()} disabled={loading}>
            {loading ? <Loader2 size={16} /> : <Upload size={16} />} 上传历史销量文件
          </button>
          <button style={accentButton} onClick={runForecast} disabled={loading}>运行月度预测</button>
          <button style={ghostButton} onClick={exportCsv} disabled={!forecastRows.length}><Download size={16} /> 导出结果</button>
        </section>

        <input ref={fileInputRef} type="file" accept=".csv,.xls,.xlsx" onChange={uploadFile} style={{ display: 'none' }} />

        <section className="card" style={{ marginTop: 14, borderRadius: 12, padding: 12 }}>
          <div style={{ color: 'var(--jy-muted)', fontSize: 14, display: 'grid', gap: 6 }}>
            <div>最近导入文件: {importFileName || '未导入'}</div>
            <div>导入列: {importColumns.length ? importColumns.join('、') : '-'}</div>
            <div>自动映射: 产品编码={detected.product_code || '-'}，日期={detected.date || '-'}，销量={detected.sales || '-'}</div>
          </div>

          {importColumns.length > 0 && (
            <div style={{ marginTop: 12, display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
              <select value={columnMapping.product_code} onChange={(e) => setColumnMapping((s) => ({ ...s, product_code: e.target.value }))} style={inputStyle}>
                <option value="">产品编码列（自动）</option>
                {importColumns.map((col) => <option key={`p-${col}`} value={col}>{col}</option>)}
              </select>
              <select value={columnMapping.date} onChange={(e) => setColumnMapping((s) => ({ ...s, date: e.target.value }))} style={inputStyle}>
                <option value="">日期列（自动）</option>
                {importColumns.map((col) => <option key={`d-${col}`} value={col}>{col}</option>)}
              </select>
              <select value={columnMapping.sales} onChange={(e) => setColumnMapping((s) => ({ ...s, sales: e.target.value }))} style={inputStyle}>
                <option value="">销量列（自动）</option>
                {importColumns.map((col) => <option key={`s-${col}`} value={col}>{col}</option>)}
              </select>
            </div>
          )}

          {algorithmSummary && <p style={{ marginTop: 10, color: 'var(--jy-muted)', fontSize: 13 }}>{algorithmSummary}</p>}
        </section>

        <section className="card" style={{ marginTop: 14, borderRadius: 12, padding: 12 }}>
          <h3 style={{ marginTop: 0 }}>预测结果（产品编码、月份、销量）</h3>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--jy-surface-soft)' }}>
                  <th style={thStyle}>产品编码</th>
                  <th style={thStyle}>月份</th>
                  <th style={thStyle}>销量</th>
                  <th style={thStyle}>下限</th>
                  <th style={thStyle}>上限</th>
                </tr>
              </thead>
              <tbody>
                {forecastRows.map((row, idx) => (
                  <tr key={`${row.product_code}-${row.month}-${idx}`} style={{ borderTop: '1px solid var(--jy-border)' }}>
                    <td style={tdStyle}>{row.product_code}</td>
                    <td style={tdStyle}>{row.month}</td>
                    <td style={tdStyle}>{row.sales}</td>
                    <td style={tdStyle}>{row.lower_bound ?? '-'}</td>
                    <td style={tdStyle}>{row.upper_bound ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </main>
  )
}

const inputStyle: CSSProperties = {
  border: '1px solid var(--jy-border)',
  borderRadius: 10,
  padding: '10px 12px',
}

const primaryButton: CSSProperties = {
  border: 'none',
  borderRadius: 10,
  padding: '10px 14px',
  color: '#fff',
  background: 'linear-gradient(135deg, var(--jy-primary), var(--jy-accent))',
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
  border: '1px solid var(--jy-border)',
  borderRadius: 10,
  padding: '10px 14px',
  color: 'var(--jy-muted)',
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
  color: 'var(--jy-muted)',
}

const tdStyle: CSSProperties = {
  padding: '10px 12px',
}
