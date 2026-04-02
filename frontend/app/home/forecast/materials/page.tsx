'use client'

import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ChangeEvent } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2, Upload } from 'lucide-react'

interface MaterialItem {
  id: number
  product_code: string
  listing_date: string
  delisting_date: string
  created_at?: string
}

function resolveApiBase() {
  if (process.env.NEXT_PUBLIC_API_BASE) return process.env.NEXT_PUBLIC_API_BASE
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:8000`
  }
  return 'http://localhost:8000'
}

export default function MaterialsPage() {
  const [apiBase, setApiBase] = useState(resolveApiBase())
  const [materials, setMaterials] = useState<MaterialItem[]>([])
  const [productCodeKeyword, setProductCodeKeyword] = useState('')
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem('jy_api_base') : ''
    const base = stored || resolveApiBase()
    setApiBase(base)
    void fetchMaterials(base)
  }, [])

  const fetchMaterials = async (base?: string, keyword?: string) => {
    const target = (base || apiBase || resolveApiBase()).replace(/\/$/, '')
    const query = (keyword ?? productCodeKeyword).trim()
    const url = query ? `${target}/materials?product_code=${encodeURIComponent(query)}` : `${target}/materials`
    const res = await fetch(url)
    if (!res.ok) {
      setMaterials([])
      setSelectedIds([])
      return
    }
    const body = await res.json()
    setMaterials((body.items || []) as MaterialItem[])
    setSelectedIds([])
  }

  const uploadMaterials = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    setLoading(true)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)

      const res = await fetch(`${apiBase.replace(/\/$/, '')}/materials/upload`, {
        method: 'POST',
        body: form,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || '上传商品基础数据失败')
      }
      await fetchMaterials(apiBase, productCodeKeyword)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '上传商品基础数据失败'
      setError(msg)
    } finally {
      setLoading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const toggleSelectAll = (checked: boolean) => {
    if (!checked) {
      setSelectedIds([])
      return
    }
    setSelectedIds(materials.map((item) => item.id))
  }

  const toggleOne = (id: number, checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => (prev.includes(id) ? prev : [...prev, id]))
      return
    }
    setSelectedIds((prev) => prev.filter((item) => item !== id))
  }

  const deleteSelected = async () => {
    if (!selectedIds.length) return
    const ok = typeof window !== 'undefined' ? window.confirm(`确认删除已勾选的 ${selectedIds.length} 条商品基础数据吗？`) : true
    if (!ok) return

    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${apiBase.replace(/\/$/, '')}/materials/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: selectedIds }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || '删除商品基础数据失败')
      }
      await fetchMaterials(apiBase, productCodeKeyword)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '删除商品基础数据失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const allSelected = materials.length > 0 && selectedIds.length === materials.length

  return (
    <main style={{ minHeight: '100vh', padding: 20 }}>
      <section className="card" style={{ maxWidth: 1100, margin: '0 auto', borderRadius: 16, padding: 20 }}>
        <Link href="/home/forecast" style={{ color: 'var(--jy-muted, #7f6a4a)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <ArrowLeft size={16} /> 返回
        </Link>

        <h1 style={{ marginBottom: 8 }}>商品基础数据管理</h1>
        <p style={{ marginTop: 0, color: 'var(--jy-muted, #7f6a4a)' }}>
          导入商品编码及生命周期日期（上市日期、下市日期），月度预测将按生命周期过滤输出。
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
            onClick={() => {
              if (typeof window !== 'undefined') window.localStorage.setItem('jy_api_base', apiBase)
              void fetchMaterials(apiBase, productCodeKeyword)
            }}
            style={ghostButton}
          >
            刷新列表
          </button>
          <button
            style={primaryButton}
            onClick={() => fileInputRef.current?.click()}
            disabled={loading}
            title={loading ? '上传进行中，请稍候' : '上传商品基础数据文件'}
          >
            {loading ? <Loader2 size={16} /> : <Upload size={16} />} 上传商品基础数据
          </button>
          <button
            style={ghostButton}
            disabled={loading || !selectedIds.length}
            onClick={deleteSelected}
            title={selectedIds.length ? `删除已勾选 ${selectedIds.length} 条数据` : '请先勾选要删除的行'}
          >
            删除已勾选
          </button>
        </section>

        <section style={{ marginTop: 12, display: 'grid', gap: 12, gridTemplateColumns: '1fr auto' }}>
          <input
            value={productCodeKeyword}
            onChange={(e) => setProductCodeKeyword(e.target.value)}
            placeholder="按物料编码查询，例如 P001"
            style={inputStyle}
          />
          <button style={ghostButton} disabled={loading} onClick={() => void fetchMaterials(apiBase, productCodeKeyword)}>
            查询
          </button>
        </section>

        <input ref={fileInputRef} type="file" accept=".csv,.xls,.xlsx" onChange={uploadMaterials} style={{ display: 'none' }} />

        <section className="card" style={{ marginTop: 14, borderRadius: 12, padding: 12 }}>
          <h3 style={{ marginTop: 0 }}>当前商品生命周期数据</h3>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--jy-surface-soft, #fff6ea)' }}>
                  <th style={thStyle}>
                    <input type="checkbox" checked={allSelected} onChange={(e) => toggleSelectAll(e.target.checked)} />
                  </th>
                  <th style={thStyle}>商品编码</th>
                  <th style={thStyle}>上市日期</th>
                  <th style={thStyle}>下市日期</th>
                </tr>
              </thead>
              <tbody>
                {materials.map((item, idx) => (
                  <tr key={`${item.product_code}-${idx}`} style={{ borderTop: '1px solid var(--jy-border, #efd8b0)' }}>
                    <td style={tdStyle}>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(item.id)}
                        onChange={(e) => toggleOne(item.id, e.target.checked)}
                      />
                    </td>
                    <td style={tdStyle}>{item.product_code}</td>
                    <td style={tdStyle}>{item.listing_date || '-'}</td>
                    <td style={tdStyle}>{item.delisting_date || '-'}</td>
                  </tr>
                ))}
                {!materials.length && (
                  <tr>
                    <td style={tdStyle} colSpan={4}>暂无商品基础数据</td>
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
