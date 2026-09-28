import { useEffect, useState } from 'react'
import './App.css'
import ExcelPreview from './ExcelPreview'

function App() {
  const [message, setMessage] = useState('正在连接后端……')

  useEffect(() => {
    const controller = new AbortController()

    async function checkBackend() {
      try {
        const response = await fetch('/api/v1/health', {
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error('接口请求失败')
        }

        const data = await response.json()

        if (
          data.status !== 'ok' ||
          data.service !== 'paperassist-system'
        ) {
          throw new Error('接口返回内容不符合预期')
        }

        if (!controller.signal.aborted) {
          setMessage('后端连接成功')
        }
      } catch {
        if (!controller.signal.aborted) {
          setMessage('连接失败，请确认后端正在运行，然后刷新页面。')
        }
      }
    }

    void checkBackend()

    return () => controller.abort()
  }, [])

  return (
    <main className="workspace">
      <h1>PaperAssist System</h1>
      <p>科研论文辅助系统</p>
      <p className="connection-status" role="status">{message}</p>
      <ExcelPreview />
    </main>
  )
}

export default App
