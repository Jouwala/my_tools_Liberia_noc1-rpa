// DraggableClickModal
// 通用下钻弹窗组件：
//  - 以"点击位置"为中心弹出（点击点落在弹窗中心，越界自动 clamp 到视口内）
//  - 按住标题栏可自由拖动（限制在视口内）
//  - 仅通过右上角 × 与 Esc 关闭，点遮罩不关闭（避免误触）
// 行为与 Warehouse 看板的明细弹窗保持一致。
//
// 【必须用 Portal 挂到 body】——踩过的坑，别再删：
// 本组件可能被渲染在任意卡片内部（如 VmaxDiagnosisCard 的评分卡下钻）。
// 全站卡片样式会给 .ant-card / .wh-card 挂 backdrop-filter（index.css 的玻璃态），
// 而 backdrop-filter（同 filter / transform / will-change / contain）会让该元素成为
// position:fixed 子元素的**包含块**。于是弹窗的 fixed 变成「相对卡片固定」，
// JS 写的 top 会再叠加一段卡片的文档偏移：实测 top:522px 渲染成 882.5px，
// 弹窗整个被推出视口下沿（1328 > vh 1100）。
// 挂到 body 后包含块恒为视口，与卡片样式完全解耦。
import React, { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useTheme } from '../theme'

export interface DraggableClickModalProps {
  open: boolean
  title: React.ReactNode
  /** 触发打开时的鼠标坐标；为空则居中于屏幕 */
  anchor?: { x: number; y: number } | null
  onClose: () => void
  width?: number | string
  maxWidth?: number | string
  /** 暗色主题（Warehouse 深空蓝风格）；缺省跟随全局主题 */
  dark?: boolean
  children?: React.ReactNode
}

const DraggableClickModal: React.FC<DraggableClickModalProps> = ({
  open,
  title,
  anchor,
  onClose,
  width = '92%',
  maxWidth = '87.5rem',
  dark: darkProp,
  children,
}) => {
  const { isDark } = useTheme()
  // 未显式指定时跟随全局主题（暗色→dcm-dark 样式；浅色→默认白底）
  const dark = darkProp !== undefined ? darkProp : isDark
  const modalRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ active: boolean; dx: number; dy: number }>({ active: false, dx: 0, dy: 0 })

  // 注入一次样式（同时提供 light / dark 两套）
  useEffect(() => {
    if (document.getElementById('dcm-style')) return
    const style = document.createElement('style')
    style.id = 'dcm-style'
    style.textContent = `
.dcm-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.45);
  /* 刻意不用 flex 居中：.dcm-modal 由 JS 写 top/left 精确定位，
   * 若 overlay 是 flex 容器，modal 作为 flex item 会先被 align-items 居中，
   * JS 写的 top 再叠加在该偏移之上。JS 定位的场景下 overlay 只当遮罩层。 */
  display: block;
}
.dcm-modal {
  position: fixed;
  background: #fff; border-radius: var(--wh-radius-md);
  box-shadow: 0 8px 32px rgba(0,0,0,0.18);
  display: flex; flex-direction: column;
  max-height: 88vh; overflow: hidden;
  z-index: 1001;
  /* 首帧兜底：JS 还没写 top/left 时先钉在视口左上（避免闪现到默认位置）。
   * 真正的居中/贴合点击点由 useLayoutEffect 计算后覆盖。
   * 注：靠 createPortal 挂到 body 才能保证这里的 fixed 就是「相对视口」——
   * 具体原因见本文件顶部注释（祖先的 backdrop-filter 会改写 fixed 的包含块）。 */
  top: 0; left: 0; margin: 0;
  align-self: auto;
}
.dcm-header {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;
  gap: var(--wh-space-sm);
  padding: var(--wh-space-md); cursor: move; user-select: none;
  border-bottom: 1px solid #f0f0f0; background: #fafafa;
  border-radius: var(--wh-radius-md) var(--wh-radius-md) 0 0;
  /* 头栏永远占位，不允许被 flex 压缩：内容再长也只让 body 滚动 */
  flex: 0 0 auto;
}
.dcm-title { font-size: 0.9375rem; font-weight: 600; color: #1f1f1f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dcm-close {
  border: none; background: transparent; cursor: pointer;
  font-size: 1.25rem; line-height: 1; color: #999; padding: 0 var(--wh-space-xs);
}
.dcm-close:hover { color: #ff4d4f; }
/* body 必须在「头栏之外」的剩余高度里自己滚。
 * 只有 .dcm-modal 的 max-height 是不够的：body 是 flex 子项，默认 min-height:auto
 * 会让内容把弹窗整体撑高（max-height 失效），于是定位时 h > 视口高，
 * clamp 公式 window.innerHeight - h - pad 变负数 → 弹窗上下同时被裁。
 * 三件套缺一不可：min-height:0 允许收缩 + flex:1 吃掉剩余高度 + overflow:auto 内部滚动。 */
.dcm-body {
  padding: var(--wh-space-md);
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
}

/* ---- 暗色主题（Warehouse 深空蓝） ---- */
.dcm-modal.dcm-dark {
  background: linear-gradient(145deg, #08122c 0%, #050d22 100%);
  box-shadow: 0 12px 40px rgba(0,0,0,0.5);
  border: 1px solid rgba(0, 217, 255,0.22);
}
.dcm-modal.dcm-dark .dcm-header {
  background: rgba(8, 18, 44,0.6);
  border-bottom: 1px solid rgba(0, 217, 255,0.22);
}
.dcm-modal.dcm-dark .dcm-title { color: #f5f7ff; }
.dcm-modal.dcm-dark .dcm-close { color: #aebbd4; }
.dcm-modal.dcm-dark .dcm-close:hover { color: #ff5c6c; }
.dcm-modal.dcm-dark .dcm-body { background: transparent; }

/* antd 组件在暗色弹窗内的适配 */
.dcm-dark .ant-table, .dcm-dark .ant-table table { background: transparent; color: #f5f7ff; }
.dcm-dark .ant-table-thead > tr > th { background: rgba(0, 217, 255,0.10) !important; color: #7fd2ee !important; border-bottom: 1px solid rgba(0, 217, 255,0.18) !important; }
.dcm-dark .ant-table-tbody > tr > td { border-bottom: 1px solid rgba(255,255,255,0.06) !important; color: #f5f7ff; }
.dcm-dark .ant-table-tbody > tr:hover > td { background: rgba(0, 217, 255,0.08) !important; }
.dcm-dark .ant-table-tbody > tr > td .ant-tag { color: #f5f7ff; }
.dcm-dark .ant-input { background: rgba(8, 18, 44,0.6); border-color: rgba(0, 217, 255,0.25); color: #f5f7ff; }
.dcm-dark .ant-input::placeholder { color: #6f8cb4; }
.dcm-dark .ant-pagination { color: #aebbd4; }
.dcm-dark .ant-pagination .ant-pagination-total-text { color: #aebbd4; }
.dcm-dark .ant-empty-description { color: #aebbd4; }
.dcm-dark .ant-spin-text { color: #aebbd4; }
`
    document.head.appendChild(style)
  }, [])

  // 打开时定位：以点击点为中心，越界 clamp 到视口
  useLayoutEffect(() => {
    if (!open || !modalRef.current) return
    const el = modalRef.current
    const w = el.offsetWidth
    const h = el.offsetHeight
    const cx = anchor ? anchor.x : window.innerWidth / 2
    const cy = anchor ? anchor.y : window.innerHeight / 2
    const pad = 8
    let left = cx - w / 2
    let top = cy - h / 2
    // Math.max(pad, ...) 兜底：当 h 仍大于视口（极端小窗）时，宁可从顶部开始也把
    // 标题栏留在屏幕内，剩余内容由 .dcm-body 内部滚动，不让整个弹窗被推到屏幕外。
    left = Math.max(pad, Math.min(left, window.innerWidth - w - pad))
    top = Math.max(pad, Math.min(top, window.innerHeight - h - pad))
    el.style.left = `${left}px`
    el.style.top = `${top}px`
    el.style.transform = 'none'
  }, [open, anchor])

  // 视口尺寸变化时重新 clamp（否则窗口缩小后弹窗会停在屏幕外）
  useEffect(() => {
    if (!open) return
    const onResize = () => {
      const el = modalRef.current
      if (!el) return
      const w = el.offsetWidth
      const h = el.offsetHeight
      const pad = 8
      const left = parseFloat(el.style.left || '0')
      const top = parseFloat(el.style.top || '0')
      el.style.left = `${Math.max(pad, Math.min(left, window.innerWidth - w - pad))}px`
      el.style.top = `${Math.max(pad, Math.min(top, window.innerHeight - h - pad))}px`
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [open])

  const onMouseMove = useCallback((e: MouseEvent) => {
    if (!drag.current.active || !modalRef.current) return
    const el = modalRef.current
    const w = el.offsetWidth
    const h = el.offsetHeight
    const pad = 8
    let left = e.clientX - drag.current.dx
    let top = e.clientY - drag.current.dy
    left = Math.max(pad, Math.min(left, window.innerWidth - w - pad))
    top = Math.max(pad, Math.min(top, window.innerHeight - h - pad))
    el.style.left = `${left}px`
    el.style.top = `${top}px`
    el.style.transform = 'none'
  }, [])

  const onMouseUp = useCallback(() => {
    drag.current.active = false
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
  }, [onMouseMove])

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    const el = modalRef.current
    if (!el) return
    const header = el.querySelector('.dcm-header') as HTMLElement | null
    if (!header || !header.contains(e.target as Node)) return
    const closeBtn = el.querySelector('.dcm-close')
    if (closeBtn && closeBtn.contains(e.target as Node)) return
    drag.current.active = true
    const rect = el.getBoundingClientRect()
    drag.current.dx = e.clientX - rect.left
    drag.current.dy = e.clientY - rect.top
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    e.preventDefault()
  }, [onMouseMove, onMouseUp])

  // Esc 关闭
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // 卸载时清理拖拽监听
  useEffect(() => () => {
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
  }, [onMouseMove, onMouseUp])

  if (!open) return null

  return createPortal(
    <div className="dcm-overlay">
      <div
        ref={modalRef}
        className={`dcm-modal${dark ? ' dcm-dark' : ''}`}
        style={{ width, maxWidth }}
        onMouseDown={onMouseDown}
      >
        <div className="dcm-header">
          <div className="dcm-title">{title}</div>
          <button className="dcm-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="dcm-body">{children}</div>
      </div>
    </div>,
    document.body,
  )
}

export default DraggableClickModal
