import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { Manrope, Noto_Sans_SC } from 'next/font/google'
import './globals.css'

const manrope = Manrope({ subsets: ['latin'], variable: '--font-manrope' })
const notoSansSc = Noto_Sans_SC({ subsets: ['latin'], variable: '--font-noto-sc' })

export const metadata: Metadata = {
  title: '九阳产销预测系统',
  description: '基于销量数据的预测与产销协同平台',
}

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body
        className={`${manrope.variable} ${notoSansSc.variable}`}
        style={{
          fontFamily:
            'var(--font-noto-sc), var(--font-manrope), "PingFang SC", "Microsoft YaHei", sans-serif',
        }}
      >
        {children}
      </body>
    </html>
  )
}
