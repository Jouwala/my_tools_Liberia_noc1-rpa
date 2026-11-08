# 项目长期约定（liberia-noc_soc-数据看板统一门户）

## v3 团队门户资产的唯一真相源

- `v3/team_portal/assets/olbr.css` 是**生成物**：由 `scripts/sync_team_assets.py`
  从 `v3/olbrportal/assets/olbr.css` + 脚本里的 `CSS_TEAM_SUFFIX` 拼出。
  改团队专有样式要改 `sync_team_assets.py` 的 `CSS_TEAM_SUFFIX`，再跑
  `python scripts/sync_team_assets.py` 重新生成；直接改生成文件会被下次同步覆盖。
  `olbr.js` 的团队补丁同理，由 `scripts/patch_team_portal.py` 生成。
- 改完固定跑三件套：`sync_team_assets.py --check`、
  `patch_team_portal.py --check`、`check_scope_coverage.py`。
- 五个团队门户 `/v3/{fo,bo,flm,smc,cxo}_portal/` 在 nginx 里全部 alias 到
  `v3/team_portal/` 同一目录；上游主门户是 `/v3/olbrportal/`，两者有意不同，
  不要互相「顺手同步」。
- 线上地址 `https://192.168.100.20/`，nginx 配置在 `D:/01_RPA/nginx-1.28.0/conf/nginx.conf`；
  团队门户带 `auth_request` 门禁，未带会话时 curl 任何路径都返回 team-login.html(7626B)，
  不能用它判断静态资源内容。

## CCH 面板的显示名（2026-11-08 起）

- `#cchSlot` 那块面板的**显示名**是「客户投诉查询 / Customer Complaint Query」，
  取自 `olbr-data.js` 的 `cch.title`（zh/en 两份字典）与 `scope-map.json` 的
  `cch` 域 zh/en；它内嵌 my_app 的 `?page=vmax_user_query`（VMAX CCA 投诉系统）。
- 「CCH」从此**只是内部标识**：域键 `cch` / 槽位 `#cchSlot` / CSS `.cch-slot` /
  `SCOPE.hasCch()` / `excelDomain` 占位 / 历史注释里仍会看到，不要再当成界面文案
  改回去，也不要拿它当界面文案去翻译。
- 已下线的 `complaint` 域显示名带「（已下线）/ (legacy)」后缀，专门用来与
  cch 的新中文名消歧；两者指向同一个 my_app 页面，但一个隐藏一个生效。
- 改 `scope-map.json` 的显示名后，服务端 `teamScopeDb.getTemplate()` 有缓存，
  **管理界面需重启 dev(9267)**；静态门户只需浏览器强刷。

## Knowledge Q&A 的 Master Site 页签（2026-11-08 起）

- 第三页签 `key='master_site'`，内嵌 `/myapp/?page=tables&table=master_site_db`
  （同源相对路径，qaSrc 自动补 `embed=1` / `lang` / `theme`）。默认表靠
  **my_app 的 `?table=` 深链**实现：`Task/my_app/frontend/src/pages/TableBrowser.tsx`
  用 `urlState.ts` 读写该参数；门户不摆第二份表选择器，切表用页内下拉。
- ⚠️ my_app 前端是 `vite preview` 服务 `D:/01_RPA/Task/_fe_dist` 的**构建产物**，
  改 `TableBrowser.tsx` 后必须 `npm run build`（在 my_app/frontend 下）才生效。
  镜像地，门户静态资产是 nginx 直出磁盘文件，用户浏览器要 Ctrl+F5 强刷。
- `qa-reload` 按 iframe 当前地址重载（外域 RAG 走 try/catch 回落），不要在
  刷新时重算 qaSrc()，否则会把用户切过的 `table` 冲回默认值。
- 该页签**只在上游主门户显示**：团队副本由 `patch_team_portal.py` 的 qa-filter
  按矩阵 `qa/master_site` 判据过滤，矩阵未勾则置 null；将来要开放给某团队，
  在矩阵里勾这一项即可。
- 门户内嵌 `/myapp/` 的**首屏可能慢十几秒**：`/api/tables` 要遍历全库统计行数，
  单独就 1.6~2.8s，而门户同屏有多路 my_app iframe 抢后端。排查「表体空白」
  先按 CDP 时间线看 `/api/tables` 是否已返回，别急着改业务逻辑；
  `TableBrowser` 的 `loading` 初值必须是 true、加载中显示 `common.loading`，
  否则 antd 会把「该表暂无数据」当事实显示（取不到 ≠ 0）。
- QA 页签点击分支**只重画一次** `el.innerHTML = qaSectionHtml()`；
  不要再在重画前给即将被丢弃的旧 iframe 单独赋 src，那会重复加载并
  产生 `net::ERR_ABORTED`，加重后端排队。

## 布局陷阱

- `.qarow` 的行高靠 `#emailSlot` 的 `.canvas { min-height: var(--qarow-h) }` 撑起来；
  团队矩阵把 Auto Report 整块隐藏后这一行没有确定高度，任何 `flex:1` +
  `min-height:0` 的 `.canvas` 都会塌成 0（absolute iframe 随之看不见）。
  排查「iframe 加载不出来」时先量容器高度，再看网络日志。
- 全局 `[hidden] { display:none !important }` 已存在，矩阵隐藏是可靠的；
  布局编辑器的隐藏用 `[data-tl-off]` / 空容器用 `:empty`，CSS 判据三者都要认。

## 页签选中态（2026-11-08 用户拍板，别「顺手修可读性」）

- `olbr.css` 的 `--tab-sel` = `#40cdc8`（用户截图逐像素取色），
  `--tab-sel-ink` = `#ffffff`，深浅主题同色；作用于 `.tab[aria-selected=true]`、
  `.v6-sub[aria-pressed=true]`、`.subv[aria-pressed=true]`。
- 白字压该色只有 **1.95:1**，低于 AA。用户看过「浅蓝底 + 深青字 4.62:1」
  方案后仍明确要白字 + 截图色，属观感优先的**有意取舍**（同 --title 那条）。
  别以无障碍为由自动改回去；真要改先问，最小改动是 --tab-sel 换 #177a77。
- 布局（2026-11-08 用户二次改口）：**GIS Map 与 Knowledge Q&A 两栏页签都靠左**。
  `olbr.css` 里两条规则并列 `#l0Map` / `#qaSlot`：
  `#l0Map .p-head, #qaSlot .p-head { flex-wrap:nowrap }` 与
  `#l0Map .p-head > .p-hd, #qaSlot .p-head > .p-hd { flex:0 1 auto }`；
  全局 `.p-hd` 仍是 `1 1 auto`，其它面板继续居中，**别把这条并进全局**。
  用户先要 GIS Map 靠左，随后要 QA「参考 GIS Map」也靠左；此前
  「QA 保持居中」的约定已作废，注释（CSS + 两处 JS）已同步改写。
