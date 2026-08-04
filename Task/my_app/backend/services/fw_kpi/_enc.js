// _enc.js — 在 Node 中复用服务器原始 e.js (strEnc) 与内置 SM3，计算登录加密字段。
// 用法: node _enc.js <uname> <pwd> <cn> <cp> <c_form>
// 输出: JSON {"q","w","smvalidate"}
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const crypto = require('crypto');

const ejsPath = path.join(__dirname, 'e.js');
const ejs = fs.readFileSync(ejsPath, 'utf-8');
const sandbox = { parseInt, Math, Array, String };
vm.createContext(sandbox);
vm.runInContext(ejs, sandbox);

if (typeof sandbox.strEnc !== 'function') {
    console.error('strEnc not found in e.js');
    process.exit(1);
}

const [uname, pwd, cn, cp, c] = process.argv.slice(2);
const q = sandbox.strEnc(uname, cn, cp, c);
const w = sandbox.strEnc(pwd, cp, cn, c);
const smvalidate = crypto.createHash('SM3').update(uname + pwd + cp + cn, 'utf-8').digest('hex');
console.log(JSON.stringify({ q, w, smvalidate }));
