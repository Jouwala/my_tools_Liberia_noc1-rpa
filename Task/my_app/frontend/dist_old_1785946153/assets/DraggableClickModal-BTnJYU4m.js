import{r as e}from"./rolldown-runtime-QTnfLwEv.js";import{et as t}from"./antd-Btc7GeOB.js";import{t as n}from"./react-vendor-By8HlURe.js";var r=e(t(),1),i=n(),a=({open:e,title:t,anchor:n,onClose:a,width:o=`92%`,maxWidth:s=1400,dark:c=!1,children:l})=>{let u=(0,r.useRef)(null),d=(0,r.useRef)({active:!1,dx:0,dy:0});(0,r.useEffect)(()=>{if(document.getElementById(`dcm-style`))return;let e=document.createElement(`style`);e.id=`dcm-style`,e.textContent=`
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
`,document.head.appendChild(e)},[]),(0,r.useLayoutEffect)(()=>{if(!e||!u.current)return;let t=u.current,r=t.offsetWidth,i=t.offsetHeight,a=n?n.x:window.innerWidth/2,o=n?n.y:window.innerHeight/2,s=a-r/2,c=o-i/2;s=Math.max(8,Math.min(s,window.innerWidth-r-8)),c=Math.max(8,Math.min(c,window.innerHeight-i-8)),t.style.left=`${s}px`,t.style.top=`${c}px`,t.style.transform=`none`},[e,n]);let f=(0,r.useCallback)(e=>{if(!d.current.active||!u.current)return;let t=u.current,n=t.offsetWidth,r=t.offsetHeight,i=e.clientX-d.current.dx,a=e.clientY-d.current.dy;i=Math.max(8,Math.min(i,window.innerWidth-n-8)),a=Math.max(8,Math.min(a,window.innerHeight-r-8)),t.style.left=`${i}px`,t.style.top=`${a}px`,t.style.transform=`none`},[]),p=(0,r.useCallback)(()=>{d.current.active=!1,document.removeEventListener(`mousemove`,f),document.removeEventListener(`mouseup`,p)},[f]),m=(0,r.useCallback)(e=>{let t=u.current;if(!t)return;let n=t.querySelector(`.dcm-header`);if(!n||!n.contains(e.target))return;let r=t.querySelector(`.dcm-close`);if(r&&r.contains(e.target))return;d.current.active=!0;let i=t.getBoundingClientRect();d.current.dx=e.clientX-i.left,d.current.dy=e.clientY-i.top,document.addEventListener(`mousemove`,f),document.addEventListener(`mouseup`,p),e.preventDefault()},[f,p]);return(0,r.useEffect)(()=>{if(!e)return;let t=e=>{e.key===`Escape`&&a()};return document.addEventListener(`keydown`,t),()=>document.removeEventListener(`keydown`,t)},[e,a]),(0,r.useEffect)(()=>()=>{document.removeEventListener(`mousemove`,f),document.removeEventListener(`mouseup`,p)},[f,p]),e?(0,i.jsx)(`div`,{className:`dcm-overlay`,children:(0,i.jsxs)(`div`,{ref:u,className:`dcm-modal${c?` dcm-dark`:``}`,style:{width:o,maxWidth:s},onMouseDown:m,children:[(0,i.jsxs)(`div`,{className:`dcm-header`,children:[(0,i.jsx)(`div`,{className:`dcm-title`,children:t}),(0,i.jsx)(`button`,{className:`dcm-close`,onClick:a,"aria-label":`Close`,children:`×`})]}),(0,i.jsx)(`div`,{className:`dcm-body`,children:l})]})}):null};export{a as t};