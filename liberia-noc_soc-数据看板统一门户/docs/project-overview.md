# 04 project-overview.md —— 项目整体说明

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\liberia-noc_soc-数据看板统一门户`
> 上级总纲：`D:\01_RPA\project-overview.md`；功能概览正文见本项目 `README.md`

## 一、项目定位

**Liberia NOC/SOC 数据看板统一门户**是一个**聚合入口**，解决的问题是：看板散落在两套系统里（FineBI 决策报表中心 + 自研 my_app），用户每天要在两个入口之间来回找表。

门户本身**不生产业务数据**，它做三件事：

1. **聚合**——把 my_app 的真实页面直链与 FineBI 报表条目收进一个目录；
2. **组织**——分类、标签、部门、收藏、置顶、热度排序，让不同角色快速找到自己那张表；
3. **呈现**——三种视图、深浅双模、中英双语、二维码、内嵌预览。

## 二、能力清单

| 能力 | 说明 |
| --- | --- |
| 看板聚合 | my_app 真实页面直链（`?page=` 查询参数格式）+ FineBI 报表分类条目 |
| 实时任务调度 | 顶部 `TaskSyncWidget` 每 60 秒拉取任务状态，展示 my_app 后端定时任务运行情况；**接口离线自动降级为静态快照** |
| 三种视图 | 卡片网格 / 高密清单 / 业务分类矩阵（MS 综合运维、告警监控、工单流程、网络性能、资源供应链等） |
| 环境切换 | 一键批量替换所有看板链接的 IP/域名（预设：生产 nginx、vite 7090 直连、本机调试） |
| 深浅双模 | 默认深色 NOC 值班主题，可切浅色日间模式 |
| 中英文国际化 | 顶栏切换，选择持久化到 localStorage（键 `liberia_noc_lang`）；**看板业务数据保持原值不翻译** |
| 收藏与置顶 | 星标收藏、置顶、访问热度排序、JSON 导入导出备份 |
| 移动端 | 每张看板二维码扫码（需同网段 WiFi）+ iframe 内嵌预览 |
| 鉴权与用户管理 | 登录、改密、用户管理、鉴权开关（见 `AUTH_SWITCH.md`） |
| 分组管理 | 自定义分组 |
| QC 质量指标面板 | 质量指标卡片 + 点开下钻明细，两档刷新节奏 |
| 文档索引 | 站内「文档索引」弹窗，导航本 8 份体系文档 |

## 三、数据从哪来

门户**不复制**业务数据，只用两种数据：

| 数据 | 来源 | 说明 |
| --- | --- | --- |
| 看板目录 | 内置初始数据 `src\data\initialDashboards.ts` + 门户后端 `/uniplam/api/portal-default` + 本地 `localStorage` 覆盖 | **本地优先** |
| 实时任务状态 | my_app 后端 `/api/tasks`（同源部署时经 nginx） | 60s 轮询，离线降级 |
| QC 指标 | 门户后端 `/uniplam/api/portal-qc/*` | 两档节奏刷新 |

> **看板数据持久化在浏览器 `localStorage`（键 `liberia_noc_dashboards_v3`）。初值改了但用户没清缓存时"看不到新数据"——需点顶栏「恢复初始默认看板」。**

## 四、技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | React 19、TypeScript、Vite 6、Tailwind CSS v4、lucide-react、motion |
| 后端 | Express（`server\`：`auth.ts`、`authDb.ts`、`authSwitch.ts`），构建经 `vite.config.ts` |
| 静态页 | `MsPortal\index.html`（复刻版）、`viewer.html`（查看器） |

## 五、部署拓扑

```
192.168.100.19:80 (nginx)
 ├── /myapp/   → 127.0.0.1:7090   my_app 前端
 ├── /api/     → 7090 → 127.0.0.1:7038   my_app 后端
 ├── /webroot/decision            FineBI 决策平台
 └── /uniplam/ → 9267             本门户（前端 + /uniplam/api/* 门户后端）
```

开发端口 **9267**（7038/7090 已被 my_app 占用，不可复用）。细节见 `architecture.md`。

## 六、角色与关注点

| 角色 | 关心 | 用哪个视图 |
| --- | --- | --- |
| NOC/SOC 值班 | 实时告警、任务是否在跑 | 卡片网格 + 顶部任务部件 |
| 网优工程师 | 具体 KPI 报表 | 搜索 + 高密清单 |
| 管理层 | 达标率、宏观俯瞰 | 业务分类矩阵 |

## 七、已知限制

1. **FineBI 具体报表链接仍是目录占位**（标签"链接待更新"、状态 beta），需在门户内"编辑看板配置"逐条替换为实际 URL。
2. **二维码要求手机与门户同网段 WiFi**，跨网段不可用。
3. **看板配置本地优先**，改了代码里的初始数据不等于用户立刻看到。
4. **环境切换改的是本地配置**，不改变服务端。
5. `MsPortal\` 目录下大量 `_*.txt` / `_qc*.txt` 是历史过程产物，不是功能代码。

## 八、目录结构

```
src\
 ├── config.ts               # 全局环境配置（API/主机/入口 URL）— 单一真相源
 ├── i18n.tsx                # 中英双字典 + useI18n()
 ├── App.tsx                 # 状态管理与 localStorage 持久化
 ├── auth\                   # 鉴权上下文与分组
 ├── components\             # 21 个组件（见 component-api.md）
 ├── data\initialDashboards.ts
 └── types\dashboard.ts
server\                      # 门户后端（鉴权、用户库、鉴权开关）
docs\                        # 本 8 份体系文档
MsPortal\                    # 复刻版单页与查看器（含历史备份与过程产物）
scripts\                     # 迁移与启动脚本
```

## 九、相关文档

| 内容 | 去哪里 |
| --- | --- |
| AI 上手须知 | `AGENTS.md` |
| 功能概览正文 | `README.md` |
| 架构与数据流 | `architecture.md` |
| 使用说明 | `user-guide.md` |
| 开发与回归 | `development.md` |
| 视觉规则 | `DESIGN.md` |
| 组件 API | `component-api.md` |
| 当前任务 | `TODO.md` |

> **工具负责整理，人与 AI 负责协作执行。**
