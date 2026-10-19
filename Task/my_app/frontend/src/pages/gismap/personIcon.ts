/* 人员图层共用的小工具（2026-10-19 从 PersonnelLayer.tsx 抽出）
 *
 * **为什么抽出来**：GIS 页的人员图层（`gismap/PersonnelLayer.tsx`）与新的
 * 人员位置地图（`?page=person`，`pages/personmap/PersonMapView.tsx`）都要
 * 画同一套小人地图针，并且都需要「姓名归一化」来做人员比对。
 * 复制两份的话，任何一次造型调整都会让两个页面的图标长得不一样，
 * 而姓名归一化一旦分叉就会出现「GIS 页能看到的人、Person 页看不到」
 * （AGENTS.md 第三节 1b：同一语义不得有两套实现）。
 *
 * 只放**纯函数**，不依赖 React、Leaflet 与 i18n —— 这样两个调用方都能直接 import。
 */

/** 姓名归一化 —— 人员比对**唯一实现**。
 *  规则：去括号后缀、去 P:/G: 前缀、折叠空白、去首尾逗号、小写。
 *  （person.name 实测有 `Ernest Feikai  Sherman,` 这种双空格 + 尾逗号的脏值。） */
export function normName(v: unknown): string {
  return String(v ?? '')
    .replace(/\([^)]*\)/g, '')
    .replace(/^\s*[PGpg]\s*[:]\s*/, '')
    .replace(/\s+/g, ' ')
    .replace(/^[\s,]+|[\s,]+$/g, '')
    .toLowerCase()
}

/** HTML 转义 —— 姓名/电话来自数据库，直接拼进 divIcon 的 html 字符串里，
 *  若含 `<` `&` `"` 会破坏结构甚至注入。**所有拼进 html 的动态值都必须过这里**
 *  （AGENTS.md 三.4：外部输入一律视为不可信）。 */
export function escapeHtml(v: unknown): string {
  return String(v ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** 人员「地图针」图标：内联 SVG（项目原则是不引图片资源，见 LeafletMap.tsx 文件头）。
 *
 * 造型参照用户给的参考图（2026-10-16）：水滴形地图针（上圆下尖）+
 * 正上方一个白色圆底 + 圆底内的人形剪影；针尖带一小段白色高光点。
 *  - `color` 由外部按主题/选中态给（深色主题浅蓝、浅色主题蓝、选中态红）；
 *  - 尺寸用 viewBox 等比缩放（`width`/`height` = s，viewBox 固定 24×36），
 *    这样换尺寸不会把造型拉变形。
 *  - 选中态：下方再描一圈半透明白色外发光，让人一眼看到「当前选中的人」。
 */
export function personIconSvg(color: string, size: number, selected: boolean): string {
  const s = size
  const glow = selected
    ? `<path d="M12 0.5 C5.1 0.5 0.2 5.4 0.2 12.2 C0.2 17.6 4.9 23.2 10.2 30.6 C10.7 31.3 11.3 32.5 12 34 C12.7 32.5 13.3 31.3 13.8 30.6 C19.1 23.2 23.8 17.6 23.8 12.2 C23.8 5.4 18.9 0.5 12 0.5 Z" fill="#fff" opacity="0.55"/>`
    : ''
  return `
<svg width="${s}" height="${s * 1.5}" viewBox="0 0 24 36" xmlns="http://www.w3.org/2000/svg">
  ${glow}
  <!-- 水滴形针身 -->
  <path d="M12 1.5 C6 1.5 1.2 6.3 1.2 12.3 C1.2 17.5 6.2 23.4 12 32.5 C17.8 23.4 22.8 17.5 22.8 12.3 C22.8 6.3 18 1.5 12 1.5 Z"
        fill="${color}" stroke="#fff" stroke-width="1.2"/>
  <!-- 白色圆底 -->
  <circle cx="12" cy="12.2" r="6.1" fill="#fff"/>
  <!-- 人形剪影：头 + 肩 -->
  <circle cx="12" cy="10.2" r="2.5" fill="${color}"/>
  <path d="M7.4 17.2 C7.4 13.9 9.4 12.6 12 12.6 C14.6 12.6 16.6 13.9 16.6 17.2 Z"
        fill="${color}"/>
</svg>`
}
