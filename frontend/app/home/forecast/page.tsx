import Link from 'next/link'

export default function ForecastHomePage() {
  return (
    <main style={{ minHeight: '100vh', padding: '24px' }}>
      <section
        className="card"
        style={{
          maxWidth: '960px',
          margin: '0 auto',
          padding: '24px',
          borderRadius: '16px',
        }}
      >
        <h2 style={{ marginTop: 0 }}>产销预测模块</h2>
        <p style={{ color: 'var(--jy-muted)' }}>点击下方按钮进入仪表盘。</p>
        <Link
          href="/home/forecast/dashboard"
          style={{
            display: 'inline-block',
            padding: '10px 16px',
            borderRadius: 10,
            background: 'var(--jy-primary)',
            color: '#fff',
            fontWeight: 700,
          }}
        >
          打开仪表盘
        </Link>
      </section>
    </main>
  )
}
