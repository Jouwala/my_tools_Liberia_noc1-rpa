# my_app 新增「VMAX 用户查询」页

## 背景与结论

VMAX CCA 投诉页（10.123.255.12:26180，`/vmax/cca/view/userinfo/query_imsimdn` 等 3 个接口）按用户号码查询用户/终端信息。my_app 已有成熟的 VMAX 对接底座可复用（门户登录、RSA `encryptedStr` 加密信封、`verify=False` 会话，见 `backend/services/vmax_multi_data/vmax_report_client.py`），但这 3 个接口的**明文参数格式与响应结构全库零记录**，需先从 VMAX 前端 JS 反推 + 实测（本仓库对 vReport 即此套路）。

关键决策（用户未答复提问，按推荐项执行）：
- **凭据**：新建 `vmax_cca` 凭据组，不复用 `vmax_cxo`（ZeeshanM）——VMAX 门户同一账号单会话互踢，ZeeshanM 被 8790 看板代理长期占用，复用会造成双方会话互踢抖动。密码由用户在「设置→凭据管理」录入，未配置时接口返回明确指引。
- **范围**：页面展示用户信息（query_imsimdn）+ 终端信息（query_terminal）两张卡片；getcause 只探测并记录协议到 README，不进页面。

## 阶段 0：协议探测（一次性，借 8790 代理会话，不新增登录）

1. 写一次性探测脚本放 `Task/my_app/TMP/`（任务结束自清）：优先经本机 8790 代理（`http://127.0.0.1:8790/proxy?url=`，ZeeshanM 会话）拉取 `https://10.123.255.12:26180/rdk/app/vmax_s_data_cca/complaint/web/` 的 HTML 与 JS bundle，grep 三个接口名，定位明文参数构造代码；确认 CCA 应用是否需要额外上下文激活调用（类似看板的 dbCommonConfig.js）。
2. 用探明的参数格式实测 query_imsimdn / query_terminal（测试号码），记录响应 JSON 结构；Referer 必须为 `https://10.123.255.12:26180/rdk/app/vmax_s_data_cca/complaint/web/`（nginx 侧实测 Referer 不符即 403）。
3. 探测结论全部落 `backend/services/vmax_cca/README.md`（参数构造、响应结构、实测样本，脱敏）。

## 阶段 1：后端

| 文件 | 内容 |
| --- | --- |
| `backend/services/vmax_cca/vmax_cca_client.py`（新建，<500 行） | `VmaxCcaClient`：复用 `vmax_multi_data.vmax_report_client` 的 `encrypt_param` / `RSA_HEADER` / `_loads_tolerant` / `VMAX_HOST`；requests.Session + trust_env=False + verify=False + Referer 指向 complaint/web/；门户登录（loginAuthenticate→RSA 密码→web-common/login，凭据 key=`vmax_cca`，凭据为空时报错并指引去设置页）；惰性会话 + 失效（401/403/404/407）自动重登重试一次；threading.Lock 串行化（门户单会话）；`query_user(msisdn)` / `query_terminal(msisdn)` 归一化响应为 dict；号码归一化（去空格、+231/231 前缀，以探明格式为准）；模块级单例 |
| `backend/services/vmax_cca/README.md`（新建） | 协议记录（阶段 0 产物） |
| `backend/services/vmax_cca/__init__.py`（新建） | 包初始化 |
| `backend/routers/vmax_cca_query.py`（新建） | `GET /api/vmax-cca-query?msisdn=...`（Query 校验 6-20 位数字，风格参照 `eflow_qa.py`；错误走 HTTPException 中文 detail）；返回 `{msisdn, user, terminal}`；不落库；日志中 msisdn 掩码，不打响应敏感内容 |
| `backend/main.py`（修改） | include_router（与 vmax_cxo 系列路由同段） |
| `backend/services/credential_store.py`（修改） | CREDENTIAL_GROUPS 新增 `vmax_cca` 组（test_kind 复用现有 `vmax_portal`，无需改 credential_tester） |
| `tests/test_vmax_cca.py`（新建） | 离线单测：号码归一化、参数构造、响应解析（参照 `test_vmax_multi_data.py`） |

## 阶段 2：前端

| 文件 | 内容 |
| --- | --- |
| `frontend/src/pages/VmaxUserQuery.tsx`（新建） | 从 `_TemplatePage.tsx` 骨架起步：输入框（回车/按钮）+ 用户信息卡 + 终端信息卡；加载 Spin / 错误+重试 / 空态三态（写法抄 `EflowQa.tsx:883-897,1772-1810`，含请求序号 useRef 守卫）；字段用 Descriptions 渲染——已知字段 i18n 标签、未知字段原样键值兜底；不进 AR_BOARD_PAGES（工具页不自动刷新） |
| `frontend/src/api.ts`（修改） | 加 `vmaxCcaQuery(msisdn)` 导出函数 |
| `frontend/src/App.tsx`（修改，五处） | PageKey `vmax_user_query` / VALID_PAGES / PAGE_META（MobileOutlined）/ DEFAULT_GROUPS 挂 `grp_network`（ip_trace 之后）/ renderPage case |
| `frontend/src/i18n.tsx`（修改） | zh/en 双份：`nav.vmaxUserQuery` + `vmaxq.*` 文案与字段标签映射 |
| `frontend/src/pages/helpContent.ts`（修改） | PAGE_DOCS zh/en + PAGE_LIST + NAV_KEY_MAP + CATEGORIES 三件套 |
| 生成帮助文档 | `node scripts/generate-help-doc.mjs` 重新生成 `15-user-help*.md` |

## 阶段 3：文档同步

- `docs/manual/11-feature-guide.md`：按导航顺序插「VMAX 用户查询」一节
- `docs/manual/14-integrations.md`：VMAX 链路表加一行（CCA 投诉查询）
- `docs/manual/05-security-and-credentials.md`：加 `vmax_cca` 凭据组说明
- 全部中文，不写口令/账号；内网 IP 沿用既有写法

## 阶段 4：验证与收尾

1. `cd Task/my_app/frontend` → `npm run check:i18n` → `npx tsc --noEmit`
2. `pytest tests/test_vmax_cca.py`；service 层直连实测一次查询（凭据已配置时）
3. `git status --porcelain` 复查；删除 TMP 探测脚本
4. **发布动作单独确认**：`npm run build`（产物直接写线上目录 `Task/_fe_dist`）与后端 7038 重启属生产变更，完成上述验证后先征求意见再执行

## 非目标

查询历史/审计落库、getcause 进页面、Excel 导出、批量号码查询。

## 风险与对策

- `vmax_cca` 凭据未录入 → 接口返回「请先在设置→凭据管理配置」的明确错误
- ZeeshanM 可能无 CCA 投诉权限 → 阶段 0 借 8790 会话实测即可发现，结论记入 README（届时必须用专用账号）
- 响应结构未知 → 前端通用键值渲染兜底，探明后补标签映射
- 探测全程借 8790 代理既有会话，不新增登录，不影响看板代理