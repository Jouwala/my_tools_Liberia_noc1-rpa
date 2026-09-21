const fs=require('fs');
const s=fs.readFileSync('MsPortal/index.html','utf8').split(/\r?\n/);
for(let i=300;i<=330;i++) console.log((i+1)+'|'+s[i]);
