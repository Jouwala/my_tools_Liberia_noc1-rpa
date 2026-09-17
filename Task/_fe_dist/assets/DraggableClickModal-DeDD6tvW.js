import{i as e}from"./rolldown-runtime-aKtaBQYM.js";import{dt as t}from"./antd-CNFr3zXA.js";import{S as n}from"./react-vendor-Dxcxxxhu.js";import{g as r}from"./index-BSb1BYxW.js";var i=e(t(),1),a=n(),o=({open:e,title:t,anchor:n,onClose:o,width:s=`92%`,maxWidth:c=`87.5rem`,dark:l,children:u})=>{let{isDark:d}=r(),f=l===void 0?d:l,p=(0,i.useRef)(null),m=(0,i.useRef)({active:!1,dx:0,dy:0});(0,i.useEffect)(()=>{if(document.getElementById(`dcm-style`))return;let e=document.createElement(`style`);e.id=`dcm-style`,e.textContent=`
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
`,document.head.appendChild(e)},[]),(0,i.useLayoutEffect)(()=>{if(!e||!p.current)return;let t=p.current,r=t.offsetWidth,i=t.offsetHeight,a=n?n.x:window.innerWidth/2,o=n?n.y:window.innerHeight/2,s=a-r/2,c=o-i/2;s=Math.max(8,Math.min(s,window.innerWidth-r-8)),c=Math.max(8,Math.min(c,window.innerHeight-i-8)),t.style.left=`${s}px`,t.style.top=`${c}px`,t.style.transform=`none`},[e,n]);let h=(0,i.useCallback)(e=>{if(!m.current.active||!p.current)return;let t=p.current,n=t.offsetWidth,r=t.offsetHeight,i=e.clientX-m.current.dx,a=e.clientY-m.current.dy;i=Math.max(8,Math.min(i,window.innerWidth-n-8)),a=Math.max(8,Math.min(a,window.innerHeight-r-8)),t.style.left=`${i}px`,t.style.top=`${a}px`,t.style.transform=`none`},[]),g=(0,i.useCallback)(()=>{m.current.active=!1,document.removeEventListener(`mousemove`,h),document.removeEventListener(`mouseup`,g)},[h]),_=(0,i.useCallback)(e=>{let t=p.current;if(!t)return;let n=t.querySelector(`.dcm-header`);if(!n||!n.contains(e.target))return;let r=t.querySelector(`.dcm-close`);if(r&&r.contains(e.target))return;m.current.active=!0;let i=t.getBoundingClientRect();m.current.dx=e.clientX-i.left,m.current.dy=e.clientY-i.top,document.addEventListener(`mousemove`,h),document.addEventListener(`mouseup`,g),e.preventDefault()},[h,g]);return(0,i.useEffect)(()=>{if(!e)return;let t=e=>{e.key===`Escape`&&o()};return document.addEventListener(`keydown`,t),()=>document.removeEventListener(`keydown`,t)},[e,o]),(0,i.useEffect)(()=>()=>{document.removeEventListener(`mousemove`,h),document.removeEventListener(`mouseup`,g)},[h,g]),e?(0,a.jsx)(`div`,{className:`dcm-overlay`,children:(0,a.jsxs)(`div`,{ref:p,className:`dcm-modal${f?` dcm-dark`:``}`,style:{width:s,maxWidth:c},onMouseDown:_,children:[(0,a.jsxs)(`div`,{className:`dcm-header`,children:[(0,a.jsx)(`div`,{className:`dcm-title`,children:t}),(0,a.jsx)(`button`,{className:`dcm-close`,onClick:o,"aria-label":`Close`,children:`×`})]}),(0,a.jsx)(`div`,{className:`dcm-body`,children:u})]})}):null};export{o as t};