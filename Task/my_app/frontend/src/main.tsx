import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { runAuthBootstrap } from './api'

/* 鉴权引导必须先于 React 渲染完成。
 * 原因：门户深链 ?t=<门户token> 换 myapp 会话 Cookie 是异步请求，若与页面挂载并行，
 * 业务页面会在 Cookie 落地前抢跑数据接口 → 首屏必现「Failed to load data / 401」，
 * 刷新即好（那时 Cookie 已存在）。放在渲染前 await，从结构上消除抢跑。
 * 另加 8 秒上限兜底：门户/后端异常时不至于白屏过久，超时也照常渲染，
 * 由页面上的「请通过统一门户登录」引导兜住。 */
const boot = Promise.race([
  runAuthBootstrap(),
  new Promise<boolean>((resolve) => { window.setTimeout(() => resolve(false), 8000) }),
])

boot
  .catch(() => false)
  .finally(() => {
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    )
  })
