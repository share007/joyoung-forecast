'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { CSSProperties } from 'react'

const tabs = [
  { href: '/home/forecast/dashboard', label: '打开仪表盘' },
  { href: '/home/forecast/materials', label: '商品基础数据导入' },
  { href: '/home/forecast/deviation', label: '预测偏差核对' },
]

export default function ForecastTabs() {
  const pathname = usePathname()

  return (
    <section style={wrapperStyle}>
      {tabs.map((tab) => {
        const active = pathname === tab.href || pathname === `${tab.href}/`
        return (
          <Link key={tab.href} href={tab.href} style={active ? activeTabStyle : tabStyle}>
            {tab.label}
          </Link>
        )
      })}
    </section>
  )
}

const wrapperStyle: CSSProperties = {
  display: 'flex',
  gap: 12,
  flexWrap: 'wrap',
  marginBottom: 12,
}

const tabStyle: CSSProperties = {
  display: 'inline-block',
  padding: '10px 16px',
  borderRadius: 14,
  border: '1px solid var(--jy-border, #efd8b0)',
  color: 'var(--jy-muted, #7f6a4a)',
  fontWeight: 700,
  background: '#fff',
}

const activeTabStyle: CSSProperties = {
  ...tabStyle,
  color: '#fff',
  border: 'none',
  background: 'linear-gradient(135deg, var(--jy-primary, #f39800), var(--jy-accent, #ff5a1f))',
}
