'use client'

import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ChangeEvent } from 'react'
import Link from 'next/link'
import { AlertCircle, ArrowLeft, Download, Loader2, Trash2, Upload } from 'lucide-react'

interface MonthlyForecastRow {
  product_code: string
  month: string
  sales: number
  lower_bound?: number
  upper_bound?: number
}

interface ImportFileRecord {
  id: number
  file_name: string
  created_at: string
  row_count: number
  columns: string[]
  detected_columns: Record<string, string>
}

interface ForecastRun {
  id: number
  run_date: string
  created_at: string
  source_file_count: number
  source_row_count: number
  data: MonthlyForecastRow[]
}

function resolveApiBase() {
  if (process.env.NEXT_PUBLIC_API_BASE) return process.env.NEXT_PUBLIC_API_BASE
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:8000`
  }
  return 'http://localhost:8000'
}

export default function DashboardPage() {
  const [apiBase, setApiBase] = useState(resolveApiBase())
  const [apiStatus, setApiStatus] = useState<'unknown' | 'ok' | 'error'>('unknown')
  const [loading, setLoading] = useState(false)
  const [forecasting, setForecasting] = useState(false)
  const [forecastProgress, setForecastProgress] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError] = useState('')
  const [importFileName, setImportFileName] = useState('')
  const [importColumns, setImportColumns] = useState<string[]>([])
  const [detected, setDetected] = useState<Record<string, string>>({})
  const [columnMapping, setColumnMapping] = useState({ product_code: '', date: '', sales: '' })
  const [startMonth, setStartMonth] = useState('2026-01')
  const [importFiles, setImportFiles] = useState<ImportFileRecord[]>([])
  const [forecastRuns, setForecastRuns] = useState<ForecastRun[]>([])
  const [algorithmSummary, setAlgorithmSummary] = useState('')

  const fileInputRef = useRef<HTMLInputElement>(null)

  const syncImportStates = (files: ImportFileRecord[]) => {
    setImportFiles(files)
    const unionColumns = Array.from(new Set(files.flatMap((item) => item.columns || [])))
    setImportColumns(unionColumns)

    const newest = files[0]
    if (newest) {
      setImportFileName(newest.file_name)
      setDetected(newest.detected_columns || {})
      setColumnMapping((prev) => ({
        product_code: prev.product_code || newest.detected_columns?.product_code || '',
        date: prev.date || newest.detected_columns?.date || '',
        sales: prev.sales || newest.detected_columns?.sales || '',
      }))
    } else {
      setImportFileName('')
      setDetected({})
      setColumnMapping({ product_code: '', date: '', sales: '' })
    }
  }

  useEffect(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem('jy_api_base') : ''
    const base = stored || resolveApiBase()
    setApiBase(base)
    void initialize(base)
  }, [])

  const initialize = async (base: string) => {
    await testConnection(base)
    await Promise.all([fetchImports(base), fetchForecastRuns(base)])
  }

  const fetchImports = async (base?: string) => {
    const target = (base || apiBase || resolveApiBase()).replace(/\/$/, '')
    const res = await fetch(`${target}/imports`)
    if (!res.ok) {
      syncImportStates([])
      return
    }
    const body = await res.json()
    const files = (body.files || []) as ImportFileRecord[]
    syncImportStates(files)
  }

  const fetchForecastRuns = async (base?: string) => {
    const target = (base || apiBase || resolveApiBase()).replace(/\/$/, '')
    const res = await fetch(`${target}/forecast/monthly/runs`)
    if (!res.ok) {
      setForecastRuns([])
      return
    }
    const body = await res.json()
    setForecastRuns((body.runs || []) as ForecastRun[])
  }

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
      setDetected(payload.detected_columns || {})
      setColumnMapping({
        product_code: payload.detected_columns?.product_code || '',
        date: payload.detected_columns?.date || '',
        sales: payload.detected_columns?.sales || '',
      })
      await fetchImports(apiBase)
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

    let progressTimer: ReturnType<typeof setInterval> | null = null
    setLoading(true)
    setForecasting(true)
    setForecastProgress(1)
    setError('')
    try {
      progressTimer = setInterval(() => {
        setForecastProgress((prev) => (prev >= 95 ? prev : prev + Math.max(1, Math.round((95 - prev) * 0.12))))
      }, 350)

      const mappingPayload =
        columnMapping.product_code && columnMapping.date && columnMapping.sales
          ? columnMapping
          : undefined

      const res = await fetch(`${apiBase.replace(/\/$/, '')}/forecast/monthly`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          forecast_months: 3,
          start_month: startMonth,
          column_mapping: mappingPayload,
        }),
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || '预测失败')
      }

      const body = await res.json()
      setForecastProgress(100)
      setAlgorithmSummary(
        `${body.algorithm?.strategy || ''} | 已选模型: ${body.algorithm?.selected_method || '-'} | 评估指标: ${body.algorithm?.selection_metric || '-'}`,
      )
      await fetchForecastRuns(apiBase)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '预测失败'
      setError(msg)
    } finally {
      if (progressTimer) clearInterval(progressTimer)
      setTimeout(() => setForecastProgress(0), 300)
      setForecasting(false)
      setLoading(false)
    }
  }

  const exportCsv = () => {
    if (!orderedRuns.length || !rowKeys.length) return

    const headerTop = ['产品编码']
    orderedRuns.forEach((run, index) => {
      headerTop.push(`预测运行日期 ${run.run_date}`, '', '', '', '')
      if (index < orderedRuns.length - 1) headerTop.push('')
    })
    headerTop.push('预警', '偏差百分比')

    const headerSecond = ['-']
    orderedRuns.forEach((run, index) => {
      headerSecond.push('月份', '销量', '下限', '上限', '运行时间')
      if (index < orderedRuns.length - 1) headerSecond.push('')
    })
    headerSecond.push('-', '-')

    const dataRows = rowKeys.map((key) => {
      const [productCode, monthKey] = key.split('||')
      const row = [productCode]
      orderedRuns.forEach((run, index) => {
        const current = runRowLookup.get(`${run.id}||${productCode}||${monthKey}`)
        row.push(
          current?.month ?? '-',
          String(current?.sales ?? '-'),
          String(current?.lower_bound ?? '-'),
          String(current?.upper_bound ?? '-'),
          formatRunTime(run.created_at),
        )
        if (index < orderedRuns.length - 1) row.push('')
      })
      row.push(resolveWarning(key), formatDeviation(key))
      return row
    })

    const content = [headerTop, headerSecond, ...dataRows].map((line) => line.join(',')).join('\n')

    const blob = new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    const firstDate = orderedRuns[0]?.run_date?.replace(/\//g, '-') || 'na'
    const lastDate = orderedRuns[orderedRuns.length - 1]?.run_date?.replace(/\//g, '-') || 'na'
    link.download = `monthly_forecast_${firstDate}_to_${lastDate}.csv`
    link.click()
  }

  const clearForecastRuns = async () => {
    const ok = typeof window !== 'undefined' ? window.confirm('确认清空预测结果数据吗？此操作不可恢复。') : true
    if (!ok) return

    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${apiBase.replace(/\/$/, '')}/forecast/monthly/runs`, { method: 'DELETE' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || '清空预测结果失败')
      }
      setForecastRuns([])
      setAlgorithmSummary('')
    } catch (err) {
      const msg = err instanceof Error ? err.message : '清空预测结果失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const removeImportFile = async (id: number) => {
    setLoading(true)
    setError('')
    const previousFiles = importFiles
    const nextFiles = previousFiles.filter((item) => item.id !== id)
    syncImportStates(nextFiles)
    try {
      const res = await fetch(`${apiBase.replace(/\/$/, '')}/imports/${id}`, { method: 'DELETE' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || '删除导入记录失败')
      }
      await fetchImports(apiBase)
    } catch (err) {
      syncImportStates(previousFiles)
      const msg = err instanceof Error ? err.message : '删除导入记录失败'
      setError(msg)
    } finally {
      await testConnection(apiBase)
      setLoading(false)
    }
  }

  const orderedRuns = [...forecastRuns].sort((a, b) => a.run_date.localeCompare(b.run_date))
  const firstRun = orderedRuns[0]
  const lastRun = orderedRuns[orderedRuns.length - 1]
  const rowKeys = Array.from(
    new Set(orderedRuns.flatMap((run) => run.data.map((row) => `${row.product_code}||${row.month}`))),
  )
  const runRowLookup = new Map<string, MonthlyForecastRow>()
  orderedRuns.forEach((run) => {
    run.data.forEach((row) => {
      runRowLookup.set(`${run.id}||${row.product_code}||${row.month}`, row)
    })
  })

  const formatRunTime = (value: string) => {
    if (!value) return '-'
    const d = new Date(value.replace(' ', 'T'))
    if (Number.isNaN(d.getTime())) return value
    const yyyy = d.getFullYear()
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const mi = String(d.getMinutes()).padStart(2, '0')
    const ss = String(d.getSeconds()).padStart(2, '0')
    return `${yyyy}/${mm}/${dd} ${hh}:${mi}:${ss}`
  }

  const resolveWarning = (key: string) => {
    if (!firstRun || !lastRun || firstRun.id === lastRun.id) return '-'
    const [productCode, monthKey] = key.split('||')
    const first = runRowLookup.get(`${firstRun.id}||${productCode}||${monthKey}`)?.sales
    const last = runRowLookup.get(`${lastRun.id}||${productCode}||${monthKey}`)?.sales
    if (first === undefined || last === undefined || first === 0) return '-'
    const diffRatio = (last - first) / Math.abs(first)
    if (diffRatio > 0.1) return '销量上涨，注意备货'
    if (diffRatio < -0.1) return '销量下滑，注意备货'
    return '-'
  }

  const resolveDeviationPercent = (key: string) => {
    if (!firstRun || !lastRun || firstRun.id === lastRun.id) return null
    const [productCode, monthKey] = key.split('||')
    const first = runRowLookup.get(`${firstRun.id}||${productCode}||${monthKey}`)?.sales
    const last = runRowLookup.get(`${lastRun.id}||${productCode}||${monthKey}`)?.sales
    if (first === undefined || last === undefined || first === 0) return null
    return ((last - first) / Math.abs(first)) * 100
  }

  const formatDeviation = (key: string) => {
    const value = resolveDeviationPercent(key)
    if (value === null) return '-'
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
  }

  const separatorCount = Math.max(0, orderedRuns.length - 1)
  const totalColumns = 1 + orderedRuns.length * 5 + separatorCount + 2

  return (
    <main style={{ minHeight: '100vh', padding: 20 }}>
      <section className="card" style={{ maxWidth: 1200, margin: '0 auto', borderRadius: 16, padding: 20 }}>
        <Link href="/home/forecast" style={{ color: 'var(--jy-muted, #7f6a4a)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <ArrowLeft size={16} /> 返回
        </Link>
        <div style={{ marginTop: 8 }}>
          <Link href="/home/forecast/materials" style={{ color: 'var(--jy-muted, #7f6a4a)', fontSize: 13 }}>
            前往商品基础数据导入
          </Link>
        </div>
        <h1 style={{ marginBottom: 8 }}>九阳月度销量预测</h1>
        <p style={{ marginTop: 0, color: 'var(--jy-muted, #7f6a4a)' }}>上传历史日销量数据，系统将输出当前月起未来3个月各产品编码销量。</p>

        <section className="card" style={{ borderRadius: 12, padding: 12, display: 'grid', gap: 10, gridTemplateColumns: '1fr auto auto' }}>
          <input value={apiBase} onChange={(e) => setApiBase(e.target.value)} placeholder="后端地址，例如 http://localhost:8000" style={inputStyle} />
          <button
            onClick={async () => {
              if (typeof window !== 'undefined') window.localStorage.setItem('jy_api_base', apiBase)
              const ok = await testConnection(apiBase)
              if (ok) await Promise.all([fetchImports(apiBase), fetchForecastRuns(apiBase)])
            }}
            style={ghostButton}
          >
            测试连接
          </button>
          <div style={{ alignSelf: 'center', fontSize: 13, color: apiStatus === 'ok' ? '#2f9e44' : apiStatus === 'error' ? '#d9480f' : 'var(--jy-muted, #7f6a4a)' }}>
            {apiStatus === 'ok' ? '后端已连接' : apiStatus === 'error' ? '后端连接失败' : '未检测'}
          </div>
        </section>

        {error && (
          <div className="card" style={{ marginTop: 12, borderRadius: 12, padding: 12, color: 'var(--jy-danger, #d9480f)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertCircle size={16} /> {error}
          </div>
        )}

        {uploading && (
          <div className="card" style={{ marginTop: 12, borderRadius: 12, padding: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--jy-muted, #7f6a4a)', fontSize: 13 }}>
              <span>上传进度</span>
              <span>{uploadProgress}%</span>
            </div>
            <div style={{ height: 10, borderRadius: 999, background: '#fde9cb', marginTop: 8 }}>
              <div style={{ width: `${uploadProgress}%`, height: '100%', background: 'linear-gradient(90deg,#f39800,#ff5a1f)', borderRadius: 999 }} />
            </div>
          </div>
        )}

        {forecasting && (
          <div className="card" style={{ marginTop: 12, borderRadius: 12, padding: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--jy-muted, #7f6a4a)', fontSize: 13 }}>
              <span>月度预测进度</span>
              <span>{forecastProgress}%</span>
            </div>
            <div style={{ height: 10, borderRadius: 999, background: '#fde9cb', marginTop: 8 }}>
              <div style={{ width: `${forecastProgress}%`, height: '100%', background: 'linear-gradient(90deg,#dc7f00,#f39800)', borderRadius: 999 }} />
            </div>
          </div>
        )}

        <section style={{ marginTop: 14, display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <input
            type="month"
            value={startMonth}
            onChange={(e) => setStartMonth(e.target.value)}
            style={inputStyle}
            title="预测起始月份（默认 2026-01）"
          />
          <button
            style={primaryButton}
            onClick={() => fileInputRef.current?.click()}
            disabled={loading}
            title={loading ? '上一次操作未结束，请稍候' : '上传历史销量文件'}
          >
            {loading ? <Loader2 size={16} /> : <Upload size={16} />} 上传历史销量文件
          </button>
          <button
            style={accentButton}
            onClick={runForecast}
            disabled={loading}
            title={loading ? '上一次操作未结束，请稍候' : '运行月度预测'}
          >
            运行月度预测
          </button>
          <button style={ghostButton} onClick={exportCsv} disabled={!forecastRuns.length}><Download size={16} /> 导出结果</button>
          <button
            style={ghostButton}
            onClick={clearForecastRuns}
            disabled={loading || !forecastRuns.length}
            title={loading ? '上一次操作未结束，请稍候' : '清空当前预测结果数据'}
          >
            <Trash2 size={16} /> 清空预测结果
          </button>
          <Link href="/home/forecast/materials" style={{ ...ghostButton, textDecoration: 'none' }}>
            商品基础数据管理
          </Link>
        </section>

        <input ref={fileInputRef} type="file" accept=".csv,.xls,.xlsx" onChange={uploadFile} style={{ display: 'none' }} />

        <section className="card" style={{ marginTop: 14, borderRadius: 12, padding: 12 }}>
          <div style={{ color: 'var(--jy-muted, #7f6a4a)', fontSize: 14, display: 'grid', gap: 6 }}>
            <div>最近导入文件: {importFileName || '未导入'}</div>
            <div>导入文件数: {importFiles.length}</div>
            <div>导入列: {importColumns.length ? importColumns.join('、') : '-'}</div>
            <div>自动映射: 产品编码={detected.product_code || '-'}，日期={detected.date || '-'}，销量={detected.sales || '-'}</div>
          </div>

          {importFiles.length > 0 && (
            <div style={{ marginTop: 12, overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--jy-surface-soft, #fff6ea)' }}>
                    <th style={thStyle}>文件名</th>
                    <th style={thStyle}>上传时间</th>
                    <th style={thStyle}>记录数</th>
                    <th style={thStyle}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {importFiles.map((file) => (
                    <tr key={file.id} style={{ borderTop: '1px solid var(--jy-border, #efd8b0)' }}>
                      <td style={tdStyle}>{file.file_name}</td>
                      <td style={tdStyle}>{file.created_at}</td>
                      <td style={tdStyle}>{file.row_count}</td>
                      <td style={tdStyle}>
                        <button
                          style={{ ...ghostButton, padding: '6px 10px', cursor: loading ? 'not-allowed' : 'pointer' }}
                          disabled={loading}
                          onClick={() => void removeImportFile(file.id)}
                        >
                          <Trash2 size={14} /> 删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

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

          {algorithmSummary && <p style={{ marginTop: 10, color: 'var(--jy-muted, #7f6a4a)', fontSize: 13 }}>{algorithmSummary}</p>}
        </section>

        <section className="card" style={{ marginTop: 14, borderRadius: 12, padding: 12 }}>
          <h3 style={{ marginTop: 0 }}>预测结果（按预测运行日期展示）</h3>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--jy-surface-soft, #fff6ea)' }}>
                  <th style={thStyle}>产品编码</th>
                  {orderedRuns.flatMap((run, index) => {
                    const nodes = [<th key={`run-${run.id}`} style={thStyle} colSpan={5}>预测运行日期 {run.run_date}</th>]
                    if (index < orderedRuns.length - 1) {
                      nodes.push(<th key={`sep-head-${run.id}`} style={separatorHeadStyle}><input value="" readOnly style={separatorInputStyle} /></th>)
                    }
                    return nodes
                  })}
                  <th style={thStyle} rowSpan={2}>预警</th>
                  <th style={thStyle} rowSpan={2}>偏差百分比</th>
                </tr>
                <tr style={{ background: 'var(--jy-surface-soft, #fff6ea)' }}>
                  <th style={thStyle}>-</th>
                  {orderedRuns.flatMap((run, index) => {
                    const nodes = [
                      <th key={`month-${run.id}`} style={thStyle}>月份</th>,
                      <th key={`sales-${run.id}`} style={thStyle}>销量</th>,
                      <th key={`lower-${run.id}`} style={thStyle}>下限</th>,
                      <th key={`upper-${run.id}`} style={thStyle}>上限</th>,
                      <th key={`time-${run.id}`} style={thStyle}>运行时间</th>,
                    ]
                    if (index < orderedRuns.length - 1) {
                      nodes.push(<th key={`sep-sub-${run.id}`} style={separatorHeadStyle}><input value="" readOnly style={separatorInputStyle} /></th>)
                    }
                    return nodes
                  })}
                </tr>
              </thead>
              <tbody>
                {rowKeys.map((key) => {
                  const [productCode, monthKey] = key.split('||')
                  return (
                    <tr key={key} style={{ borderTop: '1px solid var(--jy-border, #efd8b0)' }}>
                      <td style={tdStyle}>{productCode}</td>
                      {orderedRuns.flatMap((run, index) => {
                        const row = runRowLookup.get(`${run.id}||${productCode}||${monthKey}`)
                        const nodes = [
                          <td key={`m-${run.id}-${key}`} style={tdStyle}>{row?.month ?? '-'}</td>,
                          <td key={`s-${run.id}-${key}`} style={tdStyle}>{row?.sales ?? '-'}</td>,
                          <td key={`l-${run.id}-${key}`} style={tdStyle}>{row?.lower_bound ?? '-'}</td>,
                          <td key={`u-${run.id}-${key}`} style={tdStyle}>{row?.upper_bound ?? '-'}</td>,
                          <td key={`t-${run.id}-${key}`} style={tdStyle}>{formatRunTime(run.created_at)}</td>,
                        ]
                        if (index < orderedRuns.length - 1) {
                          nodes.push(<td key={`sep-body-${run.id}-${key}`} style={separatorCellStyle}><input value="" readOnly style={separatorInputStyle} /></td>)
                        }
                        return nodes
                      })}
                      <td style={tdStyle}>{resolveWarning(key)}</td>
                      <td style={tdStyle}>{formatDeviation(key)}</td>
                    </tr>
                  )
                })}
                {!rowKeys.length && (
                  <tr>
                    <td style={tdStyle} colSpan={Math.max(3, totalColumns)}>暂无预测结果</td>
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

const separatorHeadStyle: CSSProperties = {
  width: 30,
  minWidth: 30,
  padding: '10px 6px',
}

const separatorCellStyle: CSSProperties = {
  width: 30,
  minWidth: 30,
  padding: '8px 6px',
}

const separatorInputStyle: CSSProperties = {
  width: 18,
  border: '1px solid var(--jy-border, #efd8b0)',
  borderRadius: 6,
  padding: '8px 0',
  background: '#fff',
}
