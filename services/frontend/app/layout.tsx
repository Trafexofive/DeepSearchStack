import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'DeepSearch - AI-Powered Search',
  description: 'Self-hosted AI search engine with RAG and synthesis',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
