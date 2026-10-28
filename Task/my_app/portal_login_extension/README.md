# my_app Portal Login Chrome 扩展

为 eFlow 等「直连 + 服务端可程序化拿到会话」的门户提供“本浏览器”模式登录。扩展不会保存门户账号或密码：用户点击 my_app 卡片后，前端申请 45 秒、仅可消费一次的票据；扩展消费票据，服务端完成既有的 RSA/OAuth2 鉴权，再由扩展把结果种进**当前用户自己的 Chrome profile**。

> **RAIS 不在扩展范围内（2026-10-26 起）**：上游把登录改成 RSA 公钥加密 + **服务端强制一次性图形验证码**，服务端拿不到会话，也就没有东西可交给扩展种。`/api/portals/client-login/ticket` 对验证码门户直接回 400，前端会自动跳过扩展、改为打开上游登录页。

## 运行方式

1. 确认客户端能直接打开 `https://10.100.20.8:28001` 与 `https://10.100.20.9:8766`，且 Windows/Chrome 已通过企业根证书信任它们的 HTTPS 证书。扩展不能绕过 Chrome 的证书错误页。
2. 确认 my_app 的客户端访问地址是 `http://192.168.100.20/myapp/` 或 HTTPS 同地址。若实际地址不同，先同步修改 `manifest.json` 中的 `host_permissions`、my_app bridge 的 `matches`，以及 `background.js` 的 `MYAPP_ORIGINS`；不要用 `*://*/*` 放宽权限。
3. 测试期：Chrome 打开 `chrome://extensions`，开启开发者模式，选择“加载已解压的扩展程序”，目录选本目录。
4. 回到 `/myapp/?page=portalLogin`，选择“本浏览器”，点击 eFlow（RAIS 已不走扩展，见上文说明）。成功后新标签页在当前 Chrome profile 中打开，关闭 my_app 不会清除门户会话。

## 企业部署

生产环境建议由 AD/Intune/Chrome Enterprise 强制安装，不让用户手工操作：

1. 在受控发布主机执行 Chrome 的 `--pack-extension`，保存生成的 `.pem` 私钥到受限的运维密钥库，绝不提交或分发该私钥。
2. 在内网 HTTPS 地址托管 `.crx` 和 Chrome update manifest（XML）。
3. 获取打包后的扩展 ID，在 Chrome `ExtensionSettings` 中设置该 ID 的 `installation_mode: force_installed` 与内部 `update_url`。Windows 设备应已加入 AD/Azure AD 或 Chrome Enterprise 管理。
4. 用组策略下发门户 HTTPS 根证书，然后在客户端访问 `chrome://policy` 验证策略已生效。

扩展权限有意收敛到：my_app 服务器、eFlow、RAIS；以及 `cookies`（仅为这两个门户写登录会话）和临时 `storage.session`。不要把账号密码放入 manifest、脚本、注册表策略或 URL。

## 验收与故障定位

- my_app 卡片立即显示“正在登录”，成功后扩展打开一个新标签页；eFlow/RAIS Cookie 应出现在**用户本机**的 Chrome DevTools Application 面板中。
- 若提示证书错误，先修复 Windows 根证书部署；若页面打开但未登录，检查扩展的 service worker 控制台以及 my_app 日志中的 `[PORTAL]` 信息。
- 若提示扩展未部署，页面会保持原行为：直接打开门户登录页并提示手工登录。
- 票据过期、重复点击或网络中断后重新点击卡片即可；票据不能重复使用。
