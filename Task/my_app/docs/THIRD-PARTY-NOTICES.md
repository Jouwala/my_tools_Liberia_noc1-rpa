# 第三方组件许可与归属声明（THIRD-PARTY NOTICES）

> 生成日期：2026-09-27　|　核查范围：`Task\my_app` 前端 + 后端
> 核查方式：解析 `frontend/package-lock.json` 全部生产包 + `importlib.metadata`
> 读取全部已安装 Python 发行版的许可元数据，并用 AST 扫描 `backend/` 下 260 个
> `.py` 得出**真实 import 集**（而非仅读清单）。
>
> **本文档的用途**：履行 Apache-2.0 / MIT / BSD 等许可要求的「版权与许可声明保留」义务。
> Apache-2.0 第 4(d) 条与 SheetJS 官方文档均明确要求分发方提供 open source disclosure。

---

## 一、必须履行的归属义务（Apache-2.0）

本项目的**前端产物**（`Task\_fe_dist\assets\vendor-*.js`）中**实际打包**了下列
Apache-2.0 组件。Apache-2.0 允许商用，但**要求保留版权与许可声明**：

### 1. SheetJS Community Edition (`xlsx@0.20.3`)

打包位置：`_fe_dist\assets\vendor-*.js`（已实测命中 `SheetJS` 特征串）
代码引用：`frontend\src\pages\EflowQa.tsx:39`、`frontend\src\pages\TableBrowser.tsx:5`

```
SheetJS Community Edition -- https://sheetjs.com/
Copyright (C) 2012-present   SheetJS LLC
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
      http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

> **安装来源特殊说明**：`frontend\package.json` 的 `xlsx` 依赖安装的是 **CDN tarball** 而非 npm 包：
> `"xlsx": "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz"`
> SheetJS 已停止向 npm registry 发布新版本，新版仅从自有 CDN 分发。
> 供应链含义：**没有 registry 签名与 provenance 背书**，升级前须人工核验 tarball 完整性。
> 不要改成 `npm install xlsx` —— npm 上的 `xlsx` 停留在 0.18.5（且带已知 CVE）。

### 2. 其他 Apache-2.0 前端组件

| 组件 | 版本 | 用途 |
| --- | --- | --- |
| `echarts` | 6.1.0 | 图表渲染（全站看板） |
| `crc-32` | 1.2.2 | xlsx 的传递依赖 |

---

## 二、已处置的非标准许可项（**非 OSI 开源**）

### 1. `react-leaflet` —— Hippocratic License 2.1 —— ✅ **已于 2026-09-27 移除**

**这不是开源许可。** Hippocratic-2.1 是 Ethical Source 许可，未被 OSI 认可。
（`@react-leaflet/core` 同样是 Hippocratic-2.1。）

- 关键条款：第 1(a)/2 条要求使用须符合「联合国人权原则与人权法」，**违约则授权自动终止**；
  Indemnity 条要求 Licensee 对 Licensor 作出**赔偿承诺**（标准 MIT/BSD 无此条）；
  争议依《海牙商业与人权仲裁规则》解决。属企业采购规范常见禁用项。

**处置方式**：自研 `frontend\src\components\LeafletMap.tsx`（原生 leaflet 封装）
取代 react-leaflet，保持原有声明式写法使页面 JSX 几乎不改、地图行为不变。
`react-leaflet` 依赖已从 `package.json` 移除。

- 受影响页面（已改指向自研封装）：
  - `frontend\src\pages\GISMap.tsx:9`
  - `frontend\src\pages\PacketLossDashboard.tsx:18`
  - `frontend\src\components\MapWheelZoomOnClick.tsx`
  - `frontend\src\pages\gismap\MapController.tsx`
- 设计要点与踩坑记录见 `components\LeafletMap.tsx` 头部注释。

> **⚠ 重要更正 —— 不存在「回退到 v4」的干净路径。**
> 曾误以为 4.x 仍是 MIT。实测 npm registry 元数据：
> `react-leaflet@3.2.5` / `@4.2.1` / `@5.0.0` **全部声明 `license = Hippocratic-2.1`**。
> 唯一的干净路径就是现在这条：**直接用底层 leaflet**。
> `leaflet@1.9.4` 本身是 **BSD-2-Clause，无此问题**。

### 2. `pyjab==1.1.7` —— GPLv2（后端，**强传染**）—— ⚠️ **待决策**

- 使用位置：`backend\services\cn_ems\cs_ems_jab.py:27`、`cs_em_jab_probe.py:4`
  （`from pyjab.jabdriver import JABDriver, Service, JABException`）
- 元数据：`License: GPLv2`，classifier `GNU General Public License v2 (GPLv2)`
- 来源：`https://github.com/gaozhao1989/pyjab`（Java Access Bridge 的 Python 封装，基于 JNA）

**影响判定取决于分发方式**：
- **仅内网自用**（不向客户分发该脚本）→ GPL 的「分发」未触发，**风险可控**；
- **随产品交付客户** → `cs_ems_jab.py` 作为衍生作品须以 GPL 开源，
  与本项目闭源定位冲突，须替换或隔离。

> 补充事实：`cn_ems\` 下这套 U31 EMS 桌面客户端 GUI 自动化脚本
> （`cs_ems_jab.py` / `cs_ems_login.py` / `cs_ems_kpi_code*.py`）经全仓库检索，
> **没有任何 router 或 `task_registry.py` 入口 import 它们** —— 目前是半隔离的
> 手动/探针脚本，不在定时任务链路上，因此**传染面有限**。

---

## 三、合规但需记录（弱传染 / 双许可 / 未使用）

| 组件 | 许可 | 判定 |
| --- | --- | --- |
| `paramiko==5.0.0` | LGPL-2.1 | 动态链接、未修改源码 → **合规**。`get_sp_table.py:29`、`sp_report_gen\gernarate_sp_report.py:15` |
| `psycopg2-binary==2.9.12` | LGPL with exceptions | **合规**（许可含明确链接例外） |
| `jszip@3.10.2` | `MIT OR GPL-3.0-or-later` | **双许可，本项目选 MIT**（exceljs 传递依赖） |
| `lightningcss@1.32.0` | MPL-2.0 | 文件级弱传染，**仅构建期使用，不进产物** |
| `buffers@0.1.1` | lock 中**无声明**（实为 MIT） | 经 `unzipper` → `exceljs` 传递引入。自动化扫描会报 `unknown`，属老包（2014 年，已无维护），有供应链陈旧风险 |

> **注**：此前列入本表的 `jsts` / `@turf/jsts`（`EDL-1.0 OR EPL-1.0`）与
> `splaytree-ts`（`BDS-3-Clause`）**已随 `@turf/*` 依赖一并移除**（见下方「近期变更」），
> 当前前端依赖树中**不再存在**，无需再跟踪。
> 同样地，`react-leaflet` / `@react-leaflet/core` 的 Hippocratic-2.1 也已消失。

### 已安装但**代码零引用** —— 建议卸载以降低扫描噪声

| 组件 | 许可 | 说明 |
| --- | --- | --- |
| `PyMuPDF==1.28.2` | **AGPL-3.0 或商业授权** | 全仓库 `import fitz` **零命中**。AGPL 是最强传染性许可，若将来真要用必须走 Artifex 商业授权，**建议直接卸载** |
| `MouseInfo==0.1.3` | GPLv3+ | `pyautogui` 的传递依赖，代码中从未 import |
| `PyMsgBox==2.0.1` | GPLv3+ | 同上，从未 import |

> `pyautogui` 自身是 BSD，其 GPL 传递依赖未被调用，**不构成分发义务**，
> 但会污染依赖树扫描结果，建议在目标环境按需裁剪。

---

## 四、未登记进 lock 的包（**无归属问题，仅可复现性**）

> 2026-09-27 已补齐 8 个此前缺失的运行时依赖（见第六节变更记录）。
> **下列 2 个仍故意未登记**，原因各异：

| 包 | 代码引用 | 说明 |
| --- | --- | --- |
| `twilio` | `backend\services\incident_overview_service.py:667`、`:709` | **未在任何 requirements 中登记**。代码走 `try/except` 兜底，缺失时返回「库未安装」，属**静默降级** —— 虚拟助手的电话/短信功能实际不可用。若启用需安装并配置 `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_PHONE_NUMBER`。之所以不列入必需依赖：缺失不影响启动，按需安装更合适 |
| `python-calamine` | `backend\services\ipran_ume_kpi_service.py:686`（`engine='calamine'`） | **未登记且无兜底** —— pandas 的 calamine 引擎需要此独立包，缺失会**直接抛错**。⚠️ 若该任务在目标环境启用，必须补装并登记进 lock；当前未锁是待确认该任务的启用范围 |

---

## 五、维护约定

1. **新增依赖前先查本表**，避免重复引入同类库（`AGENTS.md` 第三节第 7 条）。
2. **新增 Apache-2.0 / BSD / MIT 组件时**，把版权行追加到本文档第一节。
3. **引入任何 GPL / AGPL / Hippocratic / SSPL 等非宽松许可前必须评估**，
   并在此处记录结论与豁免依据。
4. **不要写入敏感值**（`AGENTS.md` 第四节第 2 条）—— 本表只登记包名、版本、许可。
5. **重新生成方式**（无需安装额外工具）：
   ```powershell
   # 前端：列出全部生产包及其许可
   cd Task\my_app\frontend
   node -e "const l=require('./package-lock.json');for(const k of Object.keys(l.packages)){const v=l.packages[k];if(!k||v.dev)continue;if(k.split('node_modules/').length>2)continue;console.log((v.license||'(none)')+'  '+k.replace(/^node_modules\//,'')+'@'+v.version)}"
   # 后端：列出已安装发行版的许可
   cd Task\my_app
   python -c "import importlib.metadata as m;[print((d.metadata.get('License-Expression') or d.metadata.get('License') or '(unknown)')+'  '+d.metadata['Name']+'=='+d.version) for d in m.distributions()]"
   ```

---

## 六、本次核查的结论摘要

- **前端依赖树已无非宽松许可项**：`react-leaflet`(Hippocratic-2.1)、`@turf/*`(EDL/EPL)、
  `splaytree-ts`(BDS-3-Clause) 均已移除；**无 GPL/AGPL 组件进入前端产物**，可安全分发。
- **后端 `pyjab` 是唯一 GPLv2 强传染项**，风险取决于 `cn_ems\` 是否随产品交付。
- **`xlsx`（SheetJS）的 Apache-2.0 允许商用**，但需履行本文档第一节的归属声明；
  其 CDN 分发方式带来供应链可追溯性缺口，升级时须人工核验。
- **`requirements.lock.txt` 已补齐**此前的 8 个缺失包（见下）。

### 近期变更记录

| 日期 | 变更 | 缘由 |
| --- | --- | --- |
| 2026-09-27 | 移除 `react-leaflet` / `@react-leaflet/core`，改自研 `components\LeafletMap.tsx` | Hippocratic-2.1 非 OSI 开源，含人权条款 / 仲裁 / 赔偿义务 |
| 2026-09-27 | 移除 `@turf/bezier-spline`、`@turf/buffer`、`@turf/helpers`、`@turf/intersect`、`tslib` | 连带移除 EDL/EPL 与 BDS-3-Clause 项；`tslib` 为传递依赖无需显式声明 |
| 2026-09-27 | `requirements.lock.txt` 补入 `alembic`/`requests`/`playwright`/`geoip2`/`shapely`/`psycopg2-binary`/`pymysql`/`exchangelib` 及其传递依赖 | 此前 lock 自称可复现，但按它装出的环境缺 `psycopg2` 导致 `MY_APP_DB_MODE=pg` **直接连不上主库**；缺 `playwright` 则三条截图链路全断 |
| 2026-09-27 | 建立本文档 | 履行 Apache-2.0 第 4(d) 条与 SheetJS 官方要求的 open source disclosure 义务 |

> **仍未处置（待决策）**：后端 `pyjab`(GPLv2) 的分发边界；
> 未登记的 `twilio`（静默降级）与 `python-calamine`（无兜底，缺失即抛错）；
> 建议卸载零引用的 `PyMuPDF`(AGPL) 以降低扫描噪声。
