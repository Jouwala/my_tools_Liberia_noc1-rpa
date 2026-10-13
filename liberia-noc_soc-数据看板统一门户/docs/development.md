# 07 development.md —— 开发方式、命令和回归清单

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\liberia-noc_soc-数据看板统一门户`
> 上级总纲：`D:\01_RPA\development.md`

## 一、环境前置

| 项 | 要求 |
| --- | --- |
| Node.js | 18+ |
| 端口 | **9267**（本项目）；9268（WhatsApp 分析服务）；7038 / 7090 已被 my_app 占用，**不可复用** |
| 网络 | 本地 dev 需能访问 `192.168.100.19`（生产后端） |

### 新机器部署（干净 clone 后）

生产入口 `start.bat` → `npm run start` 跑的是 Express（`server/index.ts`），它从磁盘 `dist/` 直读构建产物。`package.json` 的 `prestart` 钩子已改为自动 `npm run build`，因此**三步缺一不可**：

```powershell
# ① 门户主项目依赖
npm install

# ② WhatsApp 分析服务是**独立子项目**，有自己的 package.json / node_modules，
#    必须单独装一次。漏装不会报错：start-wa-service.mjs 打印
#    "tsx not installed ... Skipping." 后静默跳过，门户页只显示"无法连接本地分析服务"。
cd scripts\whatsapp_analysis
npm install
cd ..\..

# ③ 启动（拉起 9267 门户 + 9268 WhatsApp；prestart 会先构建 dist）
start.bat
#    → http://localhost:9267/uniplam/
```

**首次登录**：`auth-data\` 不入库（含加盐密码哈希）。首次启动自动播种 `admin`，随机初始密码写入 `auth-data\initial-admin-password.txt`，首次登录强制改密（改完删该文件）。

**仓库外依赖（决定了门户"能开"还是"能用"）**：门户只是聚合壳，下列服务由 nginx 直接 `alias`/反代到磁盘或外部系统，**刻意不入库**（`AGENTS.md` 第四节第 6b 条：忽略跟踪 ≠ 可删除）。仅 pull 门户、不部署它们时，页面能开、UI 能渲染、TaskSyncWidget 走静态快照兜底，但**所有 my_app 看板直链与 FineBI 报表链接都会 404**：

| 依赖 | 位置 | 未入库原因 |
| --- | --- | --- |
| my_app 后端（`/api/*` → 7038） | `Task\my_app\` | `db\`（SQLite）未入库，源码在库 |
| my_app 前端产物（`/myapp/` → 7090） | `Task\_fe_dist\` | vite 构建产物，nginx `alias` 直读磁盘 |
| FineBI 决策平台（`/webroot/decision`） | 外部系统 | 不在本仓库 |
| nginx（`:80`） | `D:\01_RPA\nginx-1.28.0\` | 第三方发行包 |

## 二、命令

```powershell
npm install
npm run dev        # http://localhost:9267（predev 会先拉起 wa-service）
npm run build      # 产物输出 dist/；npm run start / start.bat 经 prestart 自动触发
npm run start      # 生产入口（Express server/index.ts），prestart 会先 build
npm run lint       # = tsc --noEmit  —— 改完必跑
npm run preview    # 预览构建产物
npm run clean      # 删除 dist / server.js
```

- 本地 dev 已配置 `/api` 代理到 `http://192.168.100.19`，任务调度部件可直连生产后端。
- 部署到子路径需在 `vite.config.ts` 设 `base` **后重新构建**。

### 仓库整洁度（2026-09-25 起有机器守卫）

背景：AGENTS.md 第四节第 7 条「探针落 `TMP\` 并自清」失效过三次，2026-09-24 审计发现门户 506 个跟踪文件里 347 个是探针/转储/快照。现在由三件东西兜底：

| 机制 | 命令 | 作用 |
| --- | --- | --- |
| 提交前拦截 | `.git\hooks\pre-commit`（工作区根，随 git 生效） | 提交时自动跑 audit，探针/快照/日志入库就拦下 |
| 手工体检 | `npm run check:clean` | 随时自查版本库有没有混入噪声文件 |
| TMP 清理 | `npm run tmp:clean` / `npm run tmp:clean:apply` | 报告 / 真删 `TMP\` 里早于 7 天的积压（脚本加 `--days=N` 可调） |

判断逻辑全在 `scripts\check-cleanliness.mjs`，钩子与手工命令是同一份代码，不会分叉。它管**已跟踪文件**（不该入库却入了库的），`.gitignore` 管**未跟踪文件**（防止新增入库），两者互补。

- 被钩子拦下但确实要提交：`git commit --no-verify`（先确认文件真的是源码）。
- `_*` 前缀的真源码（如 `src\`、`server\` 下的下划线文件）在脚本里有豁免清单，新增类似文件时记得同步该清单。

## 三、代码结构约定

### 状态中枢只有一个

`src\App.tsx` 持有全部状态（看板、分组、鉴权、视图、搜索排序、弹窗开关、持久化）。**没有引入状态库**，组件靠 props 拿数据和回调。

### 新增一个弹窗：必须改三处

以 `DesignGuideModal` / `DocsIndexModal` 为模板：

1. **`src\App.tsx`**
   ```tsx
   const [isXxxModalOpen, setIsXxxModalOpen] = useState(false);
   // …
   <Navbar onOpenXxxModal={() => setIsXxxModalOpen(true)} … />
   // …
   <XxxModal isOpen={isXxxModalOpen} onClose={() => setIsXxxModalOpen(false)} />
   ```
2. **`src\components\Navbar.tsx`**：`NavbarProps` 加 `onOpenXxxModal: () => void`，并在**桌面端与移动端两处**都加入口（漏一处 = 手机上找不到）。
3. **`src\i18n.tsx`**：`zh` 与 `en` **两份**字典都加文案键。

### 组件骨架

```tsx
import React from 'react';
import { useI18n } from '../i18n';

interface XxxModalProps { isOpen: boolean; onClose: () => void; }

export const XxxModal: React.FC<XxxModalProps> = ({ isOpen, onClose }) => {
  const { t } = useI18n();
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="spatial-modal-surface bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden">
        {/* 头部 / 内容 / 底部 */}
      </div>
    </div>
  );
};
```

### 图标

用 `DynamicIcon` 传 lucide 名称字符串：

```tsx
import { DynamicIcon } from './DynamicIcon';
<DynamicIcon name="ListChecks" className="w-5 h-5" />
```

找不到的图标名会**静默回退** `LayoutGrid`——传错名字不会报错，只会显示错图标，改完要肉眼确认。

### 异步请求的竞态

用序号作废模式（见 `fetchQcDrill`）：

```ts
var seq = ++qcDrillSeq;
// …fetch…
.then((data) => { if (seq !== qcDrillSeq) return; /* 过期响应丢弃 */ });
// 关闭弹窗时：qcDrillSeq++;
```

## 四、改代码前的纪律

1. **读 `src\config.ts` 顶部注释**——API 前缀 `/uniplam/api` 的坑，写错直接 405。
2. **文案改两份字典**（`zh` 第 20 行起、`en` 第 516 行起）。
3. **不硬编码 IP**，主机只在 `config.ts`。
4. **不写敏感值**；不提交 `auth-data\`、`portal-default.json`。
5. **中文注释。**
6. **改大文件前建 `_bak_<日期>_<说明>` 快照**：`App.tsx`（43KB）、`i18n.tsx`（117KB）、`MsPortal\index.html`（48KB）。本项目既有习惯，如 `index.html_bak_20260922_QC展示全面改版前`。
7. **探针文件放 `TMP\`**，不要污染根目录（根目录已有大量 `_*.txt` / `_qc*.txt` 历史残留）。
8. **只改样式就只改样式**，别搭车改数据口径。
9. **提交信息带影响面前缀**：`feat(portal): …`、`fix(assets): …`、`chore: …`。

## 五、回归清单

改完逐项验证，**打勾前请真的跑过**。

### 必跑（任何改动）

- [ ] `npm run lint`（`tsc --noEmit`）通过
- [ ] `npm run build` 通过
- [ ] `npm run dev` 后刷新页面，改动**实际可见**
- [ ] `git status --porcelain` 复查：没有 `dist/`、`node_modules/`、`auth-data/`、`portal-default.json`、`*.log`、探针文件混入
- [ ] `npm run check:clean` 通过（探针/快照/日志没被 git 跟踪；pre-commit 钩子也会自动拦）

### 文案 / i18n

- [ ] **中文界面**文案正确
- [ ] **切到英文**，所有新文案正常显示，**没有出现 `xxx.yyy` 形式的 key 原文**
- [ ] 看板业务数据（名称/分类/部门）仍是原值，**没有被误翻译**

### 视觉

- [ ] **深色主题**下正常
- [ ] **浅色主题**下正常（只验一套 = 漏测一半）
- [ ] 新弹窗：遮罩、圆角、阴影、关闭按钮、点击遮罩关闭都正常
- [ ] 窄屏 / 移动端不塌，导航入口在移动端也能找到

### 弹窗接线（新增弹窗时）

- [ ] `App.tsx` 状态、渲染、回调三处都加了
- [ ] `Navbar.tsx` **桌面端与移动端两个入口**都加了
- [ ] 打开 / 关闭 / 反复开关不残留状态

### 接口相关

- [ ] 请求走的是 **`/uniplam/api/*`**，不是 `/api/*`（否则 405）
- [ ] 在浏览器 Network 面板确认请求真的成功（不是靠界面"看起来对"）
- [ ] 请求失败时有降级或错误提示，**不是白屏**
- [ ] 快速连续操作 / 关闭弹窗时，**过期响应没有写回界面**

### 数据相关

- [ ] 改了初值数据时：清掉 `localStorage` 的 `liberia_noc_dashboards_v3`，确认「恢复初始默认看板」后新数据出现
- [ ] 环境切换后所有看板链接都跟着变
- [ ] QC 面板：数字**居中**、标题与副行**左对齐**、取不到显示 `—` 而非 `0`、失败时不留旧数字
- [ ] 时钟 / 倒计时**不抖动**（定宽、补零）

### 大文件改动（`App.tsx` / `i18n.tsx` / `MsPortal\index.html`）

- [ ] 建了 `_bak_<日期>_<说明>` 快照
- [ ] 改动范围最小化，没有误伤相邻代码块
- [ ] 对照 `MsPortal\` 三份专项记录（QC 优化、三列对齐、配色对齐），确认没有回退已定结论

### 手写静态壳（`olbrportal/`、`v1/olbrportal/`）

这两个目录**没有构建步骤**：nginx（`conf\nginx.conf:102/108`）直接 alias 发它们，改完刷新即生效。
`v1` 那份另有类型守卫：

- [ ] `npm run lint:shells`（= `tsc -p v1/olbrportal/tsconfig.json`，`allowJs` + `checkJs`）通过
- [ ] 改了 `v1` 的文案 → `zh` 与 `en` 两份字典都加（都在 `assets\olbr-data.js` 的 `S` 里）
- [ ] `node --check v1\olbrportal\assets\olbr.js` 通过（静态壳没有打包器兜语法错）

**⚠️ 编辑功能的改动必须在真浏览器里验，不能只看代码。**
三处易踩的坑：

1. **编辑的落点与编辑的开关是两件事。** `v1` 曾经把 `#views` 分组面板整块删掉，
   又通过 `setEditing()` 里一行 `state.editing = false` 关掉了编辑态 ——
   结果顶栏按钮点开只剩一条横幅、底下没有可编辑对象。
   改编辑相关代码时，`canEdit()` / `setEditing()` / `syncEditBtn()` /
   渲染卡片的那几个 `renderXxx()` / 事件委托，**这五处要一起看**。
   ⚠️ `v1` 的编辑对象是 **`#views6` 六列的「行条目」**（`renderViews6()` 里渲染成
   `a.card.is-ed`），**不是** `/olbrportal/` 那种 L1 分组页签面板 —— 面板已被刻意去掉，
   不要再"还原"它（那会多出一层与六个入口卡重复的入口）。
2. **`window.confirm()` 会阻塞无头浏览器**：删分组走二次确认，
   用 CDP 驱动时若不先桩掉 `confirm`，渲染进程一阻塞、CDP 就再也收不到回复
   （症状是"进程还在、零输出"，很容易误判成代码死循环）。
3. **分组名 / 看板名的中英文是两个独立字段**（`groups[].zh` 与 `.en`、`titleZh` / `titleEn`），
   而页面语言决定界面读哪一个。探针只改 `zh` 却在英文模式下读标题，会得到
   "保存成功但标题没变"的假故障（真因是漏改了 `en`）。
   验证改名时 **`zh` 与 `en` 一起写、一起还原**。
4. **量 `.card` 上的阴影要等过渡跑完。** `.card` 带 `transition: … box-shadow .16s`，
   刚加上 `.is-in-A` / `.is-in-B` 就读 `getComputedStyle().boxShadow`，
   拿到的是**过渡起始帧**（`rgba(0,0,0,0) 0px 0px 0px 0px inset` —— 透明零宽），
   很容易误判成"高亮没生效"。隔 500ms 再量才是终值。
   断言也要写严：只判 `!== 'none'` 会被那个空阴影蒙过去，
   要同时要求**有非零宽度**且**颜色不全透明**。

**验收探针**（都在 `TMP\`，可复用，不删）：

| 探针 | 覆盖 | 是否写目录 |
| --- | --- | --- |
| `_verify_v1_editgrp2.cjs` | 只读态不动 / 编辑态 `#views6` 行条目全部可编辑 / 看板改名 / 改归属 / 拖拽排序 / 重置顺序 / 分组改名并回显列标题 / 新建分组不多列 / 退出编辑。每步「改 → API 读回 → 复原」，末尾与跑前快照逐字段对账并自动回写 | **会写**（跑前确认没人同时在编辑） |
| `_verify_v1_itemadddel.cjs` | 看板条目的**增 / 删 / 改链接**（50 项）。**起手先按名清理上一轮残留**，再取快照。A 组删：A1 行上两颗删按钮齐全且只读态没有 / A2 唯一分组时「移出本列」被拒 / A3 多分组移出并复原 / A4「删除看板」真落盘且二次确认写清看板名与不可撤销 / A5 `order` 悬挂编号被摘。B 组增：B1 每列一颗「新增看板」/ B2 选模板+搜索过滤+**模板行不横向溢出**（在**全量**列表上量）/ B3 预填副本名、链接留空、标注模板来源 / B4 新 no 唯一、只属本列、clicks=0、图标继承模板、不照抄 `subOf`/`qc` / B5 `javascript:` 被拒 / B6 换模板带回已填值。C 组改链接：C1 表单三字段/预填当前值/`maxlength=512`/按钮文案 / C2 改链接落盘且名字未被改坏 / C3 `javascript:` 被拒 / C4 空链接被拒。**D 组 token 保真**：把探针自己那张卡的链接改成带 token 的形态，只改名字后断言链接**逐字节未变**（防"静默抹掉免登录凭据"，见下方坑表）。**所有靶子都动态取**（不写死编号），末尾与跑前快照逐字段对账并自动回写 | **会写**（末尾自动对账回写） |
| `_diag_myapp_auth.cjs` | 诊断：为什么 `authEnabled=true` 时**本机**不带凭据也能拿到数据 —— 证明后端对**回环来源**自动信任成 `local` 管理员。这是"本机测试骗自己"的根因，排任何鉴权问题先跑它 | 只读 |
| `_diag_myapp_lan_token.cjs` | 诊断：走**局域网地址**（`192.168.100.20`）时 myapp 深链**带 / 不带 `?t=`** 各是什么结果。用来回答"改链接时那串 token 能不能删"。token 运行时从目录 API 读，不落进代码 | 只读 |
| `_find_nur_backup.cjs` | 工具：在 `Task\my_app\backend\data\portal_catalog.json.bak_*` 里按**修改时间倒序**找出仍含某个 `no` 的最新快照，把记录原样打出来。目录**没进 git**，误删/误改只能靠这批手工快照找回来 —— 这是找回来的入口 | 只读 |
| `_restore_nur_and_v1ttwo.cjs` | 工具：**改前先备份**现用目录，再整目录 GET→改→PUT。默认**预览**，加 `--apply` 才写。内置自检：改 `page=` 段时会断言"除该段外逐字节一致"（保住 `&t=`），并回读逐字段核对 | **会写**（`--apply` 时） |
| `_probe_v1_editgeom2.cjs` | 纯只读：量编辑按钮的真实几何 —— 零尺寸、被 `overflow:hidden` 祖先裁剪、按钮互相压盖、标题省略是否仍在、只读态是否回到单行 flex | 不写 |
| `_probe_v1_dragvis.cjs` | 纯只读：拖拽视觉反馈 —— 源卡片压暗、落点高亮有真实的 inset 宽度与可见颜色、跨列不被接受、`dragend` 清干净临时类 | 不写 |
| `_probe_v6_headref.cjs` | 纯只读（除一次改名并复原）：采样「改分组名后列标题何时刷新」，用于排查渲染时机 | **会写**（自带复原） |
| `_shot_v1_editgrp2.cjs` | 只读 + 切一次编辑模式，出两张截图 `_shot_v1_ro.png` / `_shot_v1_ed.png` 供人眼复核 | 不写 |
| `_probe_bf_shot.cjs` | **起一个本地预览服务**（18099 端口，静态发 `/v1/olbrportal/` + 反代 `/api/` 到 7038）。上面 5 个 `_probe_bf_*` 里的 4 个都要先跑它。后台起、用完 kill | 不写 |
| `_probe_bf_vert.cjs` | **Network Benchmark 行六张卡的走势图对齐**（2026-10-01 那次修复的主探针）。量每张卡「图相对卡顶的偏移」并按**栅格行分组**判定（窄断点 `.qc-grid` 折成 3/2 列，跨行比较无意义）。支持 `PROBE_WIN` / `PROBE_LANG` 环境变量遍历视口与语言。✅ 2026-10-07 `#kpi` 两排改成连体卡组（`.qc-group` > `.qc-group-b` > `.qc-card`）后**本探针仍然可用**：它按 `.qc-card--bf` 选卡、按卡片自身 `top` 分行（不是按 DOM 父子关系取行），分组不改变这两件事。同批 `_probe_bf_css / _shot / color / render / spark / line / api` 也都是按 `.qc-card--bf` 或类名选元素的，同样不受影响 | 不写 |
| `_probe_bf_css.cjs` | 上一条的**结构版**：打印每张卡的「卡头 / 数据区 / 图 / 页脚」四段实测高度与卡片 padding。三个 `min-height`（42 / 74 / 82.5px）就是照它填的 —— **改了字号或内边距后必须重跑它重取这三个值** | 不写 |
| `_probe_bf_render.cjs` | 从 `olbr.js` 里 eval 出 `benchSpark` / `metaSpark`，喂真实接口数据，断言双线层数 / 图例 / tooltip 文案 / 降级行为（数据不足返回空串） | 不写（只读接口） |
| `_probe_bf_color.cjs` | Orange 橙线 / MTN 黑线的令牌与 WCAG 对比度（浅色 `#f97316`/`#1a1a1a`、深色 `#fb923c`/`#e8eaf0`），断言无 `--b`、无旧紫 `#7c3aed` 残留 | 不写 |
| `_probe_bf_spark.cjs` | 折线几何：缺测处线**断开**不补 0、两条线共用同一横轴、`viewBox` 与起止点 | 不写 |
| `_probe_bf_line.cjs` | 解析每条 `sp-line` 路径的首末 x，验证六张卡横轴起止一致。顺带记一个事实：Ookla 25 天 vs Meta 24 天，**各自拉伸铺满整宽**，所以"同一天"在两组里的像素列本来就不同 | 不写（只读接口） |
| `_probe_bf_api.cjs` | 检查两个 overview 接口 `daily[]` 的字段名与条数（字段是 `orange_download` 这类全拼，不是 `orange_dl`） | 不写（只读接口） |
| `_verify_v1_defaultzoom.cjs` | **GIS Map 栏两个页签的默认取景档**（2026-10-02「打开就比原来大一号」需求的主验收）。A 组 mwRealTime：打开后**不加任何操作**瓦片级别须为 8（内层全国档 7 +1，网络层证据）、缩放控件在、点一次 `-` 回到 7（证不累加）。B 组 gis：矢量底图与站点要素齐全、控件在、**打开态像素跨度 ÷ 缩小一级后的跨度 ≈2.00**、静置 12s 跨度不变（证不继续放大）。⚠️ 探针内部有「**连续 3 次**读数一致才算落定」的门控，**不要简化掉、也别放宽成 2 次**：gis 是两段式加载（1.1~3.1s 只有 104 个要素/跨度 376，4.0s 才到 948 个/752），第一段本身能稳约 2s，而循环间隔 1.5s —— 只要求连续 2 次一致时，两次采样可能都落在第一段里，表现为同一份探针**时而全绿、时而 B4 假失败**（已实测复现） | 不写 |
| `_probe_v1_zoomclick.cjs` | 上一条的**诊断版**：分别量两页「点一次内层页 `.leaflet-control-zoom-in`」前后的指纹（栅格瓦片级别 / 站点要素像素跨度），打印比值。用来回答「这个页签的 + 控件到底能不能用」以及「一级 = 几倍跨度」。两页证据形态不同：mwRealTime 有栅格瓦片 `src` 级别段，gis 是 PMTiles 矢量瓦片（canvas 渲染，**无** `src` 级别段、也拿不到 map 实例），只能靠像素跨度 | 不写 |
| `_probe_v1_centered.cjs` | **GIS Map 两页在 zoom 8 是否居中**（2026-10-02 用户「只要能做到居中，放大一级是正好，7 有点小」后的验收点）。`mwRealTime` 用 `window.__geoNodes` 的 649 个真实经纬算包围盒中心 vs 国土中心（实测偏差 **1.6% 纬 / 0.2% 经**）；`gis` 无经纬入口，退而量站点像素包围盒中心 vs 容器中心（实测 **9.8% 横 / 1.9% 纵**）。⚠️ `__geoNodes` 是**以站点 id 为键的对象、不是数组**（无 `.length`），当数组用会静默得到"中心 = 0,0"的假失败；探针已两种形状兼容并用显式 `isFinite` 兜底 | 不写 |
| `_shot_v1_defaultzoom.cjs` | 只读出图：依次切到 gis / mwRealTime 并各等 14s（覆盖 `refitLeaflet` 的 12s 观察窗口，确保停在稳定档），存 `_shot_defaultzoom_gis.png` / `_shot_defaultzoom_mwRealTime.png` 供人眼复核「打开就大一号」的观感 | 不写 |
| `_verify_v1_legendcss.cjs` | **门户内嵌 GIS 页时，地图浮层样式必须与直开 `/myapp/?page=gis` 逐项一致**（2026-10-15 用户报「MAINTENANCE ALERTS 图例在门户里背景异常、不匹配」的验收）。浅色 + 深色各一遍，断言 `background` / `z-index` / `position` 三项一致，且浮层没被拉成通高、方位没跑（图例左下 / 排名条右上）。⚠️ 两条关键教训：(1) **必须对比两种入口** —— `MAP_STRIP_CSS` 只在门户侧注入，直开永远是对的，只测一边永远发现不了这类 bug；(2) 探针起手要**分别用各自真实的机制设主题**（门户读 `localStorage['olbr.theme']`、**不认** `?theme=`；直开 my_app 认 `?theme=`），否则会造出"两边主题不同"的假差异，并内置 `C0` 自检先证明两侧主题确实一致 | 不写 |
| `_verify_v1_themeclick.cjs` | 端到端复核**真实用户切主题路径**：点门户顶栏 `#themeBtn` → `setTheme()` → 重建 iframe `src`，断言内层 iframe 的 `data-theme` 跟着变、`src` 带上 `&theme=dark`、排名条由浅底转深色玻璃底且仍居右上。用来兜「门户是深色、地图浮层还是浅色底」这类**只在切换后出现**的观感问题（预置 localStorage 的探针覆盖不到这条路） | 不写 |
| `_verify_v1_panleft.cjs` | **门户内嵌 gis 页「地图内容左移 160px」的验收**（2026-10-15 用户：「把地图向左平移，避免右边的图例遮挡地图」）。8 条断言：地图 pane 拿到 `margin-left:-160px`、站点整体左移、**排名条没被一起平移**且仍贴右边（gap 与直开一致 56px）、图例没被平移、背景/z-index 未被破坏、**用户拖拽后位移仍在**（这是选 margin 而非 transform 的理由 —— Leaflet 只重写 transform）。⚠️ P3/P4 是回归守卫：第一版曾误给排名条加 `translateX(-160px)`，导致它悬在中间、离右边缘 216px | 不写 |
| `_verify_v1_zoomperpage.cjs` | **两个地图页签「打开是否自动放大」的按页验收**（2026-10-16 用户：「alarm 这个地图不要在点一次放大了」）。5 条：MW(mwRealTime) 仍是 zoom 8 且点一次 `-` 回到 7（未累加）；Alarm(gis) 打开态与直开 `/myapp/?page=gis` 的跨度**完全一致**（实测都是 752，ratio 1.000 = 未被放大）；地图左移仍在。⚠️ 页签显示名与 page 值不同名：**Alarm = gis、MW = mwRealTime**（见 `olbr-data.js` 的 `map.gis`/`map.mw`），看代码时别搞混 | 不写 |
| `_diag_v1_pandir.cjs` | 只读诊断：**实测**地图内容左移 vs 右移对「被排名条压住的站点数 / 可见站点数」的影响。结论反直觉 —— 左移 160px 压在排名条上的站点 44→54（更糟）、可见站点 574→193；右移 160px 才是 44→26。用户 2026-10-15 在知悉该结果后仍明确选择「就要左移」，故保留此脚本作为**该决定的事实依据**，避免后人误当 Bug 改回去 | 不写 |
| `_diag_v1_rankgap.cjs` | 只读诊断：拆解「MAINTENANCE ALERTS 为什么没在最右边」。把注入的 `transform` 覆盖为 `none` 前后对比，证明 gap 216px→56px 完全由那次误加的 `translateX(-160px)` 造成，与 index.css 的 `right:196px`（为让开图层开关而设）无关 | 不写 |

> ⚠️ `_verify_v1_editgrp2.cjs` 与 `_verify_v1_itemadddel.cjs` 改的是**服务端全局目录 —— 共享的生产数据**。
> 跑之前确认没有别人在编辑目录，跑完看「收尾核对」那一段是否全绿。
> 用法：`cd TMP` → `node _verify_v1_itemadddel.cjs` / `node _probe_v1_editgeom2.cjs`（都需要 7038 在跑）。
> 探针**复原要用 UI 而不是 API 回写**：页面内存里那份目录是权威的，
> 后续任何一次 `commit()` 都会把它整份 PUT 上去，用 API 改完的文件会被覆盖回去
> （这正是收尾核对曾报"恢复了又出现"的原因）。
>
> ⚠️ **两个验收探针不要同时跑**：它们改的是同一份共享目录，
> 并发的改名/删除会互相覆盖，表现为随机的一条断言失败（实测踩过一次）。

## 六、常见陷阱

| 陷阱 | 后果 | 正确做法 |
| --- | --- | --- |
| API 用 `/api` | 命中 my_app，POST 回 405 | 用 `PORTAL_API`（`/uniplam/api`） |
| 只加中文 i18n 键 | 英文界面显示 key 原文 | `zh` 与 `en` 都加 |
| 只加桌面端入口 | 手机上找不到功能 | `Navbar` 两处都加 |
| 图标名写错 | 静默回退 `LayoutGrid`，不报错 | 改完肉眼确认图标 |
| 硬编码 IP | 换机器要全局搜替换 | 只在 `config.ts` 定义主机 |
| 看板存绝对 URL | 换环境时历史数据失效 | 只存相对路径 `rel` |
| 数字取不到显示 0 | 运维误判为"已清空" | 显示 `—` |
| 整卡加渐变 | "贴纸感"，数据可信度下降 | 纯底 + 细边框 + 柔和阴影 |
| 整卡 `text-center` | 标题与口径被挪走，超范围改动 | 只让数字居中 |
| 用 interval 累加做刷新 | 进页面时机不对要等一整周期 | 墙上时钟对齐网格 |
| 未作废在途请求 | 关掉弹窗后又被写回 | 序号作废模式 |
| 提交 `auth-data/` | 泄露加盐密码哈希 | 已在 `.gitignore`，别绕开 |
| 探针写在根目录 | 历史残留已 76+ 个 | 放 `TMP\` |
| 改静态壳后只跑 `npm run lint` | 那只覆盖 React 侧，**不含 `v1/olbrportal`** | 另跑 `npm run lint:shells` |
| 改编辑功能只看代码不实测 | 开关与落点会脱节（见第五节之三第 1 条的真实事故） | 用 `TMP\_verify_v1_editgrp2.cjs` 跑一遍 |
| 用原生 `confirm()` 做无头验证 | 阻塞渲染进程，CDP 收不到回复（看似死循环） | 先 `window.confirm = () => true` |
| 改名探针只改 `zh` 却读界面标题 | 英文模式下页面读 `en`，得到"存了但没变"的假故障 | `zh`/`en` 一起写、一起还原 |
| 探针用 API 回写来复原 | 页面内存里的目录是权威的，下一次 `commit()` 会整份覆盖回去 | 复原走 UI；末尾按快照对账兜底 |
| 探针无条件点 `#editBtn` 想"进入编辑态" | 它是**开关**不是"进入"按钮：`?edit=1` 已开时再点就**关掉**了，后续 `[data-act]` 查到 0 颗，表现成"按钮点了没反应" | 先判 `documentElement.classList.contains('is-edit')`，没开才点 |
| 探针按编号写死某条看板做测试 | 目录是共享的，别人把它的归属改掉后断言会**假失败**（实测 `no=11` 原挂两组、后来只剩一组） | 按**特征**动态找（如"第一个多分组的条目"） |
| 探针读列标题用 `.v6-t` 的 `firstChild` | 列标题改成可点链接后名字落在 `.v6-t-top > span`，取文本节点会把 `<small>` 说明连起来 | 直接取 `.v6-t-top > span` |
| 把 `offscreen` 计数当按钮被裁 | 那只是**纵向折页**（41 行本来就超出视口），判据应是 `clipped === 0` | 只看 `zero` 与 `clipped` |
| 新增看板时到 `submitForm` 才读目标列 | `openForm()` 里的 `closeGrp()` 会清掉 `tplPick`，读到 `null`，新看板**静默落到第一列** | 目标列在选模板那一步就存进 `state.addGid` |
| 删看板只挪 `items` 不摘 `order` | `order[gid]` 里留下指向不存在看板的**悬挂编号** | 同步把该 `no` 从所有 `order` 数组里过滤掉 |
| 新增看板的 `url` 不做校验 | 该字段直接进 `<a href>`，而目录是所有门户共用的 —— 放行 `javascript:`/`data:` 等于开 XSS 口子 | 过 `^https?://` 白名单 |
| grid/flex 子项只写 `width: 100%` 就以为能收住 | 子项默认 `min-width: auto`，会被内容的**最小内容宽度**撑开（实测选模板的行 439px 塞在 298px 的 grid 里横向溢出，而浮层自身 `scrollWidth == clientWidth`，**页面上看不出报错**） | 给子项补 `min-width: 0`（文本那层再配 `overflow:hidden` + ellipsis） |
| 探针把 fixture 写死（`data-no="1"`、`no === '11'`） | 共享目录随时被人改/删。实测 `no=1(NUR Dashboard)` 被人在页面上删掉后，整片断言变成 `titleZh: undefined` 的连锁假失败，**看着像产品坏了** | 一律 `find(谓词)` 现查（"第一个只属于一个分组的""第一条模板"），断言绑定**读出来的那个值** |
| 断言"继承模板的字段"时比对写死的期望值 | 模板换成别的，断言变成**假绿**（例如写死 `icon === 'dashboard'`，而当前模板的 icon 是 `map`） | 先读模板在目录里的值，再与新建条目比对 |
| 尺寸类断言放在搜索/过滤之后 | 撑破布局的正是名字最长的那几条；过滤后列表只剩 1 行，等于没测 | 尺寸断言放在**全量列表**上，过滤测试另做 |
| 用 PowerShell `.Contains()` / `-match` 查中文 | 编码不稳，**真存在的键会查成 False**（实测 `'edit.title': '编辑'` 报不存在，换 grep 工具立刻找到） | 查中文内容用 grep/read 工具，或 `[System.IO.File]::ReadAllText(<绝对路径>)` |
| **在本机上用 `localhost` 验证鉴权 / 免登录** | myapp 后端对**回环来源自动放行**，认成 `local` 管理员：`/api/auth/me` 从 `127.0.0.1`/`localhost` 返回 `200 {"user":{"username":"local","role":"admin"}}`，从 `192.168.100.20`/`.19` 返回 `401`。于是"去掉 token 也能打开"这类结论**只在服务器本机成立**，真实用户走的是 401 那条路 —— 我据此得出过错误的建议，见 `architecture.md` 第九节 | 验鉴权行为一律用**局域网地址**（`http://192.168.100.20/...`），别用 `localhost`；先跑 `TMP\_diag_myapp_auth.cjs` 确认这件事 |
| 探针中途崩了，没跑收尾对账 | 残留（如 ZZTmp 卡片）留在共享目录里，下一轮 `find(名字)` 命中**旧的那张**，断言开始对错靶子（表现为两三个不相干的断言莫名失败），最后在取表单元素时空指针崩掉 —— 看着像产品坏了，其实全是自己的残留 | 探针**起手先按名清理残留**（连同 `order` 里的悬挂编号）**再**取快照，让它可重复运行 |
| 把**编辑**表单的字段名当成**新增**表单的 | 两处键名不同：编辑是 `zh` / `en` / `itemUrl`，新增是 `itemZh` / `itemEn` / `itemUrl`。写错拿到 `null`，报 `Cannot set properties of null (setting 'value')` | 先读 `FORMS` 定义确认键名；断言里把读到的 `fields` 打出来 |
| **探针用局域网 IP 打页面，然后断言"数据没了"** | 已验证可用的探针都走 `localhost`（`_verify_v1_itemadddel.cjs:33`）。我改用 `192.168.100.20` 后 6 秒只拿到 2 个空 `.v6-row`，`is-edit=false`、卡片名为空 —— 看着像目录被清空，其实是**壳子根本没加载完** | 照抄既有探针的 `URL_PAGE`（`localhost`）与等待时长；断言"某元素不存在"之前，先确认**页面本身**渲染好了 |
| CDP 的 `Runtime.evaluate` 偶发**永不返回**，整个探针挂死 | 有一版核对脚本因此跑了 5 分钟没动静，进程还活着但没进展 | 每次 `send` 都套硬超时（`Promise.race`），再加一个全局兜底超时强杀 Chrome；宁可报错也别挂住 |

## 七、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 本地运行 / 部署（含 nginx 片段） | `README.md` |
| 架构与数据流 | `architecture.md` |
| 视觉规则 | `DESIGN.md` |
| 组件 API | `component-api.md` |
| AI 上手须知 | `AGENTS.md` |
| 全域开发规范 | `D:\01_RPA\development.md` |
| 鉴权开关 | `D:\01_RPA\AUTH_SWITCH.md` |

> **工具负责整理，人与 AI 负责协作执行。**
