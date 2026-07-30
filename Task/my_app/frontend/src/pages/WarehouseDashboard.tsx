import { useEffect, useRef, useState } from 'react';

/**
 * 仓库看板（Warehouse Dashboard）
 *
 * 该页面完整复用 Unified_Tools/WareHouseDashBoard/templates/index.html 的参考实现，
 * 以保证与原始看板「完全一样」。参考 HTML 通过 /api/data、/api/warehouses、/api/details
 * 三个接口获取数据（计算逻辑见 backend/services/sp_dashboard.py，对齐 app_sp_optimized.py）。
 *
 * 这里用 <iframe> 直接加载 public/warehouse-dashboard.html（同源，开发期由 Vite 提供，
 * 生产期由后端 dist 提供），从而 100% 保留原始布局 / 配色 / 图表 / 交互。
 */
export default function WarehouseDashboard() {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(1600);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    let timer: number | undefined;

    const measure = () => {
      try {
        const doc = iframe.contentDocument;
        if (doc && doc.body) {
          const h = Math.max(
            doc.body.scrollHeight,
            doc.documentElement.scrollHeight,
            doc.body.offsetHeight,
          );
          setHeight(h + 40);
        }
      } catch {
        /* cross-origin 时无法测量，保持当前高度 */
      }
    };

    const onLoad = () => {
      measure();
      timer = window.setInterval(measure, 600);
      // 数据 / 图表异步加载，预留一段时间持续测量
      window.setTimeout(() => {
        if (timer) window.clearInterval(timer);
      }, 15000);
    };

    iframe.addEventListener('load', onLoad);
    return () => {
      iframe.removeEventListener('load', onLoad);
      if (timer) window.clearInterval(timer);
    };
  }, []);

  return (
    <div style={{ width: '100%' }}>
      <iframe
        ref={iframeRef}
        src={`${import.meta.env.BASE_URL}warehouse-dashboard.html`}
        title="Warehouse Dashboard"
        style={{
          width: '100%',
          height: `${height}px`,
          border: 'none',
          display: 'block',
          background: '#0a1929',
        }}
      />
    </div>
  );
}
