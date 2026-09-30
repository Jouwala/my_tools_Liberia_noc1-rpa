/* ============================================================================
 * OoklaLogo —— Speedtest by Ookla 品牌标识（仪表盘标记 + SPEEDTEST 字标 + by OOKLA）
 * ----------------------------------------------------------------------------
 * 用途：标出"这张卡的数据来自 Speedtest by Ookla"。当前唯一调用点是
 *   pages/BmSpeedtest.tsx 的「关键指标对比」4 张卡（下载/上传/时延/抖动）——
 *   四张卡同源（speedtest_data），所以标识作为"数据来源"对四张都成立。
 *
 * ⚠️ **这是按参考图比例手工复刻的字体版近似，不是 Ookla 的官方矢量资产。**
 *   对外分发/商用前应换成官方 SVG，并按 Ookla 的品牌规范使用。
 *   换法：只替换下面的 <svg> 内容，组件接口不变；几何数值的来源见下。
 *
 * 几何取自参考图的**逐像素实测**（坐标按"标记外缘左上角 = (0,0)"定）：
 *   标记外缘 38×32 → 外半径 19、描边 4.5；标记右缘 → 字标左缘 间距 11；
 *   SPEEDTEST 宽 124、大写高 15（基线 y=22）；by OOKLA 宽 61、左缩进 13（x=62）、基线 y=41。
 *   字标用 textLength 锁死宽度、lengthAdjust="spacing" 只调字距不拉伸字形，
 *   这样即使落到 Segoe UI / Roboto 这类与 Ookla 自有字体不同的字体上，
 *   整块的**外框比例**也不变形。
 *   viewBox 用负原点 -0.5：标记外缘正好压在 x=0/y=0 上，不留边距的话
 *   抗锯齿会把最左/最上各削掉半像素。
 *
 * 为什么用内联 SVG 而不是 PNG：
 *   · 深浅两套主题：本组件用 currentColor，颜色交给 --wh-ookla-ink 令牌
 *     （见 theme.ts 的 WH.ooklaInk 与 index.css），随 data-theme 自动切换、
 *     且**不需要重渲染**；PNG 会把某一种底色烤进图里。
 *   · 根 .gitignore 忽略 *.png，新增的图进不了版本库，换台机器拉下来就没有了。
 *
 * 为什么不和门户那份共用：门户的 v1/olbrportal 是**手写静态壳**（纯 JS + nginx alias，
 * 无构建步骤），本文件是 Vite + React 的模块。两者没有共享的包边界，
 * 复制一份是当前结构下唯一可行的做法；改动其一时请同步另一处
 * （门户侧在 v1/olbrportal/assets/olbr-data.js 的 OOKLA_LOGO）。
 *
 * 刻意**不**画 ® 上标：参考图里那两个 ® 只有 1~2px，在本页卡片这个渲染尺寸下
 * 会退化成看不清的灰点、像渲染瑕疵。归属改由 hover 提示给出。
 * ========================================================================== */

import type { CSSProperties } from 'react'
import { Tooltip } from 'antd'
import { WH } from '../theme'
import { useI18n } from '../i18n'

/** viewBox 尺寸（含 -0.5 四周留白），用于按高度反推宽度 */
const VIEW_W = 174
const VIEW_H = 45

interface OoklaLogoProps {
  /** 渲染高度（px）。宽度按 viewBox 固有比例自动算出，永远不变形。 */
  height?: number
  style?: CSSProperties
}

export default function OoklaLogo({ height = 24, style }: OoklaLogoProps) {
  const { t } = useI18n()
  const label = t('bms.kpi.ooklaTip')
  // 宽度显式算出来而不是交给 width:auto：SVG 只有 viewBox 没有固有尺寸，
  // 各浏览器对"只给 height、宽度自适应"的处理并不一致，
  // 显式给宽高是唯一稳的做法（比例已经锁在常量里，不会写歪）。
  const width = Math.round((height * VIEW_W) / VIEW_H * 100) / 100

  return (
    <Tooltip title={label}>
      <span
        role="img"
        aria-label={label}
        style={{
          display: 'inline-flex', alignItems: 'center', lineHeight: 0,
          color: WH.ooklaInk, cursor: 'help',
          ...style,
        }}
      >
        {/* svg 自身不带 aria：无障碍名称由外层 span 的 role/aria-label 提供，
            两处都写会让"这个标识叫什么"变成两个真相源 */}
        <svg width={width} height={height} viewBox="-0.5 -0.5 174 45"
          focusable="false" aria-hidden="true" style={{ display: 'block' }}>
          {/* 圆弧：起点在左下 135°，弧半径 16.75 = 外半径 19 − 半个描边 2.25；
              large-arc=1 + sweep=1 → 走 270° 的"长边"（经过正上方），
              缺口留在正下方 90° */}
          <g fill="none" stroke="currentColor" strokeLinecap="round">
            <path d="M7.16 30.84A16.75 16.75 0 1 1 30.84 30.84" strokeWidth={4.5} />
            {/* 指针：自圆心指向右上 45°，长度 10（参考图实测针尖距圆心 11.67
                减去圆头半径 1.8），描边比圆环略细（实测 3.5 vs 4） */}
            <path d="M19 19L26.07 11.93" strokeWidth={3.6} />
          </g>
          <g fill="currentColor" stroke="none">
            <text x={49} y={22} fontSize={20.8} fontWeight={800}
              textLength={124} lengthAdjust="spacing">SPEEDTEST</text>
            {/* 副行字号 13 是"不与 textLength 打架"的上限：参考图那行的大写高折合字号约 17，
                但 Segoe UI 在该字号下自然宽 80 > 目标 61，被 textLength 压回去会让字母粘连。
                取 13 时自然宽 61.5 ≈ 目标，字距几乎不用调 —— 宁可副行略小，也不要字母粘连。 */}
            <text x={62} y={41} fontSize={13} textLength={61} lengthAdjust="spacing">
              <tspan fontWeight={500}>by </tspan><tspan fontWeight={700}>OOKLA</tspan>
            </text>
          </g>
        </svg>
      </span>
    </Tooltip>
  )
}
