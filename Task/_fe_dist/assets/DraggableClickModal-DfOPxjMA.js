import{a as e,n as t}from"./rolldown-runtime-DaJ6WEGw.js";import{_n as n}from"./antd-dhko3Sy8.js";import{H as r}from"./react-vendor-DJS8GeoD.js";import{m as i,v as a}from"./index-I-CzcFs6.js";var o,s,c,l=t((()=>{o=e(n(),1),i(),s=r(),c=({open:e,title:t,anchor:n,onClose:r,width:i=`92%`,maxWidth:c=`87.5rem`,dark:l,children:u})=>{let{isDark:d}=a(),f=l===void 0?d:l,p=(0,o.useRef)(null),m=(0,o.useRef)({active:!1,dx:0,dy:0});(0,o.useEffect)(()=>{if(document.getElementById(`dcm-style`))return;let e=document.createElement(`style`);e.id=`dcm-style`,e.textContent=`
.dcm-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.45);
  display: flex; align-items: center; justify-content: center;
}
.dcm-modal {
  position: fixed;
  background: #fff; border-radius: var(--wh-radius-md);
  box-shadow: 0 8px 32px rgba(0,0,0,0.18);
  display: flex; flex-direction: column;
  max-height: 88vh; overflow: hidden;
  z-index: 1001;
}
.dcm-header {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;
  gap: var(--wh-space-sm);
  padding: var(--wh-space-md); cursor: move; user-select: none;
  border-bottom: 1px solid #f0f0f0; background: #fafafa;
  border-radius: var(--wh-radius-md) var(--wh-radius-md) 0 0;
}
.dcm-title { font-size: 0.9375rem; font-weight: 600; color: #1f1f1f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dcm-close {
  border: none; background: transparent; cursor: pointer;
  font-size: 1.25rem; line-height: 1; color: #999; padding: 0 var(--wh-space-xs);
}
.dcm-close:hover { color: #ff4d4f; }
.dcm-body { padding: var(--wh-space-md); overflow: auto; }

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
`,document.head.appendChild(e)},[]),(0,o.useLayoutEffect)(()=>{if(!e||!p.current)return;let t=p.current,r=t.offsetWidth,i=t.offsetHeight,a=n?n.x:window.innerWidth/2,o=n?n.y:window.innerHeight/2,s=a-r/2,c=o-i/2;s=Math.max(8,Math.min(s,window.innerWidth-r-8)),c=Math.max(8,Math.min(c,window.innerHeight-i-8)),t.style.left=`${s}px`,t.style.top=`${c}px`,t.style.transform=`none`},[e,n]);let h=(0,o.useCallback)(e=>{if(!m.current.active||!p.current)return;let t=p.current,n=t.offsetWidth,r=t.offsetHeight,i=e.clientX-m.current.dx,a=e.clientY-m.current.dy;i=Math.max(8,Math.min(i,window.innerWidth-n-8)),a=Math.max(8,Math.min(a,window.innerHeight-r-8)),t.style.left=`${i}px`,t.style.top=`${a}px`,t.style.transform=`none`},[]),g=(0,o.useCallback)(()=>{m.current.active=!1,document.removeEventListener(`mousemove`,h),document.removeEventListener(`mouseup`,g)},[h]),_=(0,o.useCallback)(e=>{let t=p.current;if(!t)return;let n=t.querySelector(`.dcm-header`);if(!n||!n.contains(e.target))return;let r=t.querySelector(`.dcm-close`);if(r&&r.contains(e.target))return;m.current.active=!0;let i=t.getBoundingClientRect();m.current.dx=e.clientX-i.left,m.current.dy=e.clientY-i.top,document.addEventListener(`mousemove`,h),document.addEventListener(`mouseup`,g),e.preventDefault()},[h,g]);return(0,o.useEffect)(()=>{if(!e)return;let t=e=>{e.key===`Escape`&&r()};return document.addEventListener(`keydown`,t),()=>document.removeEventListener(`keydown`,t)},[e,r]),(0,o.useEffect)(()=>()=>{document.removeEventListener(`mousemove`,h),document.removeEventListener(`mouseup`,g)},[h,g]),e?(0,s.jsx)(`div`,{className:`dcm-overlay`,children:(0,s.jsxs)(`div`,{ref:p,className:`dcm-modal${f?` dcm-dark`:``}`,style:{width:i,maxWidth:c},onMouseDown:_,children:[(0,s.jsxs)(`div`,{className:`dcm-header`,children:[(0,s.jsx)(`div`,{className:`dcm-title`,children:t}),(0,s.jsx)(`button`,{className:`dcm-close`,onClick:r,"aria-label":`Close`,children:`×`})]}),(0,s.jsx)(`div`,{className:`dcm-body`,children:u})]})}):null}}));export{l as n,c as t};