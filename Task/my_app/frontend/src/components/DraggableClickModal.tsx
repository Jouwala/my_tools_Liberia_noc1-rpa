// DraggableClickModal
// 通用下钻弹窗组件：
//  - 以"点击位置"为中心弹出（点击点落在弹窗中心，越界自动 clamp 到视口内）
//  - 按住标题栏可自由拖动（限制在视口内）
//  - 仅通过右上角 × 与 Esc 关闭，点遮罩不关闭（避免误触）
// 行为与 Warehouse 看板的明细弹窗保持一致。
import React, { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import { useTheme } from '../theme'

export interface DraggableClickModalProps {
  open: boolean
  title: React.ReactNode
  /** 触发打开时的鼠标坐标；为空则居中于屏幕 */
  anchor?: { x: number; y: number } | null
  onClose: () => void
  width?: number | string
  maxWidth?: number
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
  maxWidth = 1400,
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
  display: flex; align-items: center; justify-content: center;
}
.dcm-modal {
  position: fixed;
  background: #fff; border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.18);
  display: flex; flex-direction: column;
  max-height: 88vh; overflow: hidden;
  z-index: 1001;
}
.dcm-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; cursor: move; user-select: none;
  border-bottom: 1px solid #f0f0f0; background: #fafafa;
  border-radius: 10px 10px 0 0;
}
.dcm-title { font-size: 15px; font-weight: 600; color: #1f1f1f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dcm-close {
  border: none; background: transparent; cursor: pointer;
  font-size: 20px; line-height: 1; color: #999; padding: 0 4px; margin-left: 12px;
}
.dcm-close:hover { color: #ff4d4f; }
.dcm-body { padding: 16px 18px; overflow: auto; }

/* ---- 暗色主题（Warehouse 深空蓝） ---- */
.dcm-modal.dcm-dark {
  background: linear-gradient(145deg, #141f33 0%, #112540 100%);
  box-shadow: 0 12px 40px rgba(0,0,0,0.5);
  border: 1px solid rgba(100,255,218,0.22);
}
.dcm-modal.dcm-dark .dcm-header {
  background: rgba(10,25,41,0.6);
  border-bottom: 1px solid rgba(100,255,218,0.22);
}
.dcm-modal.dcm-dark .dcm-title { color: #e6f4ff; }
.dcm-modal.dcm-dark .dcm-close { color: #94a3b8; }
.dcm-modal.dcm-dark .dcm-close:hover { color: #ff6b6b; }
.dcm-modal.dcm-dark .dcm-body { background: transparent; }

/* antd 组件在暗色弹窗内的适配 */
.dcm-dark .ant-table, .dcm-dark .ant-table table { background: transparent; color: #e6f4ff; }
.dcm-dark .ant-table-thead > tr > th { background: rgba(100,255,218,0.10) !important; color: #b3e5fc !important; border-bottom: 1px solid rgba(100,255,218,0.18) !important; }
.dcm-dark .ant-table-tbody > tr > td { border-bottom: 1px solid rgba(255,255,255,0.06) !important; color: #e6f4ff; }
.dcm-dark .ant-table-tbody > tr:hover > td { background: rgba(100,255,218,0.08) !important; }
.dcm-dark .ant-table-tbody > tr > td .ant-tag { color: #e6f4ff; }
.dcm-dark .ant-input { background: rgba(10,25,41,0.6); border-color: rgba(100,255,218,0.25); color: #e6f4ff; }
.dcm-dark .ant-input::placeholder { color: #64748b; }
.dcm-dark .ant-pagination { color: #94a3b8; }
.dcm-dark .ant-pagination .ant-pagination-total-text { color: #94a3b8; }
.dcm-dark .ant-empty-description { color: #94a3b8; }
.dcm-dark .ant-spin-text { color: #94a3b8; }
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
    left = Math.max(pad, Math.min(left, window.innerWidth - w - pad))
    top = Math.max(pad, Math.min(top, window.innerHeight - h - pad))
    el.style.left = `${left}px`
    el.style.top = `${top}px`
    el.style.transform = 'none'
  }, [open, anchor])

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

  return (
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
    </div>
  )
}

export default DraggableClickModal
