#!/usr/bin/env node
// ============================================================================
// verify-readiness.mjs —— 商用就绪度回归脚本（零依赖，Node 22 原生 fetch）
// ----------------------------------------------------------------------------
// 把《MsPortal 商用就绪度检测》里那套手工 curl 固化成一个命令，
// 整改后（以及以后每次发布前）跑一遍，逐条 PASS/FAIL。
//
// 用法：
//   node scripts/verify-readiness.mjs
//   node scripts/verify-readiness.mjs --host 192.168.100.20
//   node scripts/verify-readiness.mjs --host 192.168.100.20 --json
//
// 退出码：全 PASS = 0；有 FAIL = 1（可用于 CI / 计划任务门禁）。
//
// 检查项（对应 B1–B5）：
//   B1 门户 9267 不再泄漏 vite dev 资产
//   B2 80 跳 https、443 返回 200
//   B3 匿名读 /portal-default 被挡（非 200）
//   B4 my_app 7090 匿名出口已关闭（连不上或非 200）
//   B5 备份/归档文件不可下载（404/403）
// ============================================================================

const args = process.argv.slice(2);
function arg(name, fallback) {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
}
const HOST = arg('--host', '127.0.0.1');
const JSON_OUT = args.includes('--json');
const TIMEOUT_MS = 6000;

/** 发一个不跟随重定向的请求，返回状态码（连不上返回 0） */
async function status(url, { followRedirect = false, method = 'GET' } = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method,
      redirect: followRedirect ? 'follow' : 'manual',
      signal: ctrl.signal,
    });
    return res.status;
  } catch {
    return 0; // 连接失败 / 超时
  } finally {
    clearTimeout(t);
  }
}

/** 取回响应体文本（失败返回空串） */
async function body(url) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    return await res.text();
  } catch {
    return '';
  } finally {
    clearTimeout(t);
  }
}

const results = [];
function record(id, desc, ok, detail) {
  results.push({ id, desc, ok, detail });
}

async function main() {
  // —— B1：门户生产服务不再泄漏 dev 资产 ——
  {
    const html = await body(`http://${HOST}/uniplam/`);
    const leaked = /@vite\/client|react-refresh/.test(html);
    record('B1', '门户不再泄漏 vite dev 资产（@vite/client / react-refresh）', !leaked,
      leaked ? '响应含 dev 资产' : '未发现 dev 资产');
  }

  // —— B2：TLS ——
  {
    const httpStatus = await status(`http://${HOST}/`);
    const httpsStatus = await status(`https://${HOST}/`, { followRedirect: true });
    record('B2', '80 → https 跳转（期望 301/302/308）', [301, 302, 308].includes(httpStatus),
      `http=${httpStatus}`);
    record('B2', 'https 可访问（期望 200）', httpsStatus === 200, `https=${httpsStatus}`);
  }

  // —— B3：匿名读目录被挡（未登录） ——
  {
    const s = await status(`http://${HOST}/uniplam/api/portal-default`, { followRedirect: true });
    record('B3', '匿名读 /portal-default 被挡（期望非 200，应为 401）', s !== 200 && s !== 0,
      `status=${s}`);
  }

  // —— B4：my_app 7090 匿名出口关闭 ——
  {
    const creds = await status(`http://${HOST}:7090/api/credentials`);
    const whoami = await status(`http://${HOST}:7090/api/auth/me`);
    record('B4', '7090 /api/credentials 不再匿名可读（期望 0 或 401/403）',
      creds === 0 || creds === 401 || creds === 403, `status=${creds}`);
    record('B4', '7090 /api/auth/me 不再匿名回管理员（期望 0 或 401/403）',
      whoami === 0 || whoami === 401 || whoami === 403, `status=${whoami}`);
  }

  // —— B5：备份/归档不可下载 ——
  {
    const probes = [
      '/MsPortal/assets/portal.js.fixed',
      '/MsPortal/index_bak_20260917_direct_login.html',
      '/MsPortal/tailwind.config.v3.js.archived',
    ];
    for (const p of probes) {
      const s = await status(`http://${HOST}${p}`, { followRedirect: true });
      record('B5', `备份/归档不可下载 ${p}（期望 403/404）`,
        s === 403 || s === 404, `status=${s}`);
    }
  }

  // —— 输出 ——
  const failed = results.filter((r) => !r.ok);
  if (JSON_OUT) {
    console.log(JSON.stringify({ host: HOST, passed: results.length - failed.length, failed: failed.length, results }, null, 2));
  } else {
    console.log(`\n=== 商用就绪度回归 @ ${HOST} ===\n`);
    for (const r of results) {
      console.log(`${r.ok ? 'PASS' : 'FAIL'}  [${r.id}] ${r.desc}  (${r.detail})`);
    }
    console.log(`\n合计：${results.length - failed.length}/${results.length} 通过` +
      (failed.length ? `，${failed.length} 项未过 ❌` : ' ✅'));
  }
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => {
  console.error('脚本异常：', e);
  process.exit(2);
});
