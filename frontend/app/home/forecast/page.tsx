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
        <p style={{ color: 'var(--jy-muted)' }}>请选择要进入的功能页面。</p>
        <section style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
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
            运行预测
          </Link>
          <Link
            href="/home/forecast/deviation"
            style={{
              display: 'inline-block',
              padding: '10px 16px',
              borderRadius: 10,
              border: '1px solid var(--jy-border, #efd8b0)',
              color: 'var(--jy-muted, #7f6a4a)',
              fontWeight: 700,
            }}
          >
            预测偏差核对
          </Link>
          <Link
            href="/home/forecast/materials"
            style={{
              display: 'inline-block',
              padding: '10px 16px',
              borderRadius: 10,
              border: '1px solid var(--jy-border, #efd8b0)',
              color: 'var(--jy-muted, #7f6a4a)',
              fontWeight: 700,
            }}
          >
            基础数据
          </Link>
        </section>
      </section>
    </main>
  )
}
