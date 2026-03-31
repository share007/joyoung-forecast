import Link from 'next/link'

export default function HomePage() {
  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
      }}
    >
      <section
        className="card"
        style={{
          width: '100%',
          maxWidth: '760px',
          borderRadius: '20px',
          padding: '36px',
          background:
            'linear-gradient(135deg, rgba(243,152,0,0.14) 0%, rgba(255,255,255,1) 40%, rgba(255,90,31,0.08) 100%)',
        }}
      >
        <p style={{ margin: 0, color: 'var(--jy-muted)', fontWeight: 700, letterSpacing: 1.2 }}>JOYOUNG FORECAST</p>
        <h1 style={{ marginTop: 10, marginBottom: 14, fontSize: '36px', lineHeight: 1.15 }}>九阳产销协同决策驾驶舱</h1>
        <p style={{ marginTop: 0, color: 'var(--jy-muted)', lineHeight: 1.7 }}>
          支持 Excel 导入、销量预测、生产补货建议与库存风险评估。
        </p>
        <Link
          href="/home/forecast/dashboard"
          style={{
            display: 'inline-flex',
            marginTop: 12,
            padding: '12px 20px',
            borderRadius: 999,
            fontWeight: 700,
            color: '#fff',
            background: 'linear-gradient(135deg, var(--jy-primary), var(--jy-accent))',
            boxShadow: '0 12px 24px rgba(243,152,0,0.26)',
          }}
        >
          进入预测系统
        </Link>
      </section>
    </main>
  )
}
