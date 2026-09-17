// 临时自检（跑完即删）：上线版本的最终验收 —— 布局/遮挡/右上角统计/坐标轴/版本
const fs = require('fs');
const src = process.argv[2];
const dst = process.argv[3];
let html = fs.readFileSync(src, 'utf8');
const boot = '<script>try{localStorage.setItem("myapp_auto_refresh_effective","900")}catch(e){}</script>';
const probe = '<script>setTimeout(function(){var o=[];' +
  'var mb=document.getElementById("cardsBusiness").getBoundingClientRect();' +
  'var mq=document.getElementById("cardsQuality").getBoundingClientRect();' +
  'o.push("同排: business.top="+Math.round(mb.top)+" quality.top="+Math.round(mq.top)+" 同高="+(Math.round(mb.height)===Math.round(mq.height)));' +
  'var fixed=[];document.querySelectorAll("*").forEach(function(e){if(getComputedStyle(e).position==="fixed"&&e.offsetHeight>0)fixed.push(e.className||e.id)});' +
  'o.push("fixed 元素: "+(fixed.length?fixed.join(","):"无"));' +
  'var st=document.querySelector(".panel-stats");o.push("右上角统计: "+(st?st.textContent.replace(/\\s+/g," "):"无"));' +
  'o.push("版本: "+document.getElementById("verLabel").textContent+" | "+document.getElementById("arLabel").textContent);' +
  'o.push("状态: "+document.getElementById("status").textContent+" | 数据截至: "+document.getElementById("asof").textContent);' +
  'var t=[];try{echarts.getInstanceByDom(document.getElementById("ch_traffic_gb")).getZr().storage.getDisplayList()' +
  '.forEach(function(el){var s=el.style&&el.style.text;if(typeof s==="string"&&s&&/^\\d\\d-\\d\\d$/.test(s))t.push(s)})}catch(e){t.push("ERR")}' +
  'o.push("X 轴刻度("+t.length+"): "+t.join(" "));' +
  'var w=window.innerWidth,h=window.innerHeight,b=document.querySelector(".status").getBoundingClientRect();' +
  'o.push("页面高="+document.documentElement.scrollHeight+" 视口="+h+" 状态条 top="+Math.round(b.top)+"(文档流内)");' +
  'var d=document.createElement("pre");d.id="fin";d.textContent=o.join("\\n");document.body.appendChild(d)},8000);</script>';
html = html.replace('<body>', '<body>' + boot + probe);
fs.writeFileSync(dst, html);
console.log('final probe ->', dst);
