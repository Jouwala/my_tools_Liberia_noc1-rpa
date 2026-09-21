const fs = require('fs');
const raw = fs.readFileSync('src/data/initialDashboards.ts','utf8');
const re = /id:\s*'([^']+)'[\s\S]*?platform:\s*'finebi'[\s\S]*?url:\s*`([^`]+)`/g;
let m, n=0;
while ((m = re.exec(raw))) { n++; console.log(m[1].padEnd(42)+' | '+m[2]); }
console.log('count: '+n);
