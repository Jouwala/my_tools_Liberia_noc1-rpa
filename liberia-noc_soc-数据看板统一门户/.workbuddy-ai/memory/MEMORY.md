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

## 布局陷阱

- `.qarow` 的行高靠 `#emailSlot` 的 `.canvas { min-height: var(--qarow-h) }` 撑起来；
  团队矩阵把 Auto Report 整块隐藏后这一行没有确定高度，任何 `flex:1` +
  `min-height:0` 的 `.canvas` 都会塌成 0（absolute iframe 随之看不见）。
  排查「iframe 加载不出来」时先量容器高度，再看网络日志。
- 全局 `[hidden] { display:none !important }` 已存在，矩阵隐藏是可靠的；
  布局编辑器的隐藏用 `[data-tl-off]` / 空容器用 `:empty`，CSS 判据三者都要认。
