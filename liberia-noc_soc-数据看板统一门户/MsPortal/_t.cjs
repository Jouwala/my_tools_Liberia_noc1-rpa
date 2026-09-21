const http = require('http');
function req(method, path, cookie, body) {
  return new Promise((res, rej) => {
    const data = body ? Buffer.from(body) : null;
    const headers = cookie ? { Cookie: cookie } : {};
    if (data) { headers['Content-Type'] = 'application/x-www-form-urlencoded'; headers['Content-Length'] = data.length; }
    const r = http.request({ host: '127.0.0.1', port: 80, method, path, headers }, (resp) => {
      let b = '';
      resp.on('data', (d) => (b += d));
      resp.on('end', () => res({ s: resp.statusCode, b, ck: resp.headers['set-cookie'] }));
    });
    r.on('error', rej);
    if (data) r.write(data);
    r.end();
  });
}
(async () => {
  for (const u of [['admin', 'Liberia@2026'], ['operator', 'Liberia@2026'], ['admin', 'wrong']]) {
    const r = await req('POST', '/MsPortal/api/auth/login.php', null, 'username=' + u[0] + '&password=' + u[1]);
    console.log(u[0].padEnd(9), r.s, (r.b || '').slice(0, 200).replace(/\s+/g, ' '));
  }
})();
