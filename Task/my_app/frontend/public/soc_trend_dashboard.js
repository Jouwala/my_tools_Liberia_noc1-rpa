/* SOC 多维趋势组合看板 —— 页面逻辑
 * 数据：/api/soc-trend/{meta,series,alarms,dict}（只读，落盘库由任务 soc_trend_sync 维护）
 * 协议：跟随 my_app 外壳（myapp-theme / myapp-locale / MyAppRefresh），与 vmax_cxo_dashboard_daily 同款。
 */
(function(){
'use strict';

/* ============ i18n（跟随外壳：localStorage['app-locale'] + postMessage） ============ */
var I18N = {
 zh: {
  'app.title':'SOC 多维趋势组合看板','app.sub':'一个入口 · 三日对比 · 多选定位',
  'scope.data':'数据','scope.voice':'语音',
  'cat.flow':'流量','cat.video':'视频','cat.web':'网页','cat.game':'游戏',
  'cat.ottvoice':'OTT语音','cat.ottvideo':'OTT视频','cat.tcp':'TCP指标','cat.control':'控制面',
  'dim.total':'全网','dim.area':'全部区域','dim.ne':'网元 (SGW)','dim.app':'业务APP (Top20)',
  'lbl.day':'分析日 D','lbl.dim':'维度','lbl.metric':'指标','btn.reset':'清除本页下钻',
  'alarm.title':'重大告警分析','alarm.none':'本窗口无双基线越限告警','alarm.expand':'展开其余 {n} 项',
  'alarm.collapse':'收起','alarm.notready':'基线未就绪（D-1 / D-7 尚无同窗口数据，暂不出告警）',
  'alarm.foot':'红色 Critical · 橙色 Major；均需 D-1 与 D-7 双基线越限。仅全网及一级范围触发，不受下钻筛选影响。',
  'contrib.main':'主要统计贡献来自 {name}（{pct}%）','contrib.more':' 等 {n} 个成员',
  'trend.title':'当前业务趋势','trend.ref':'全网参考','trend.chip':'{label} {val} {pct}',
  'radar.title':'局部异常雷达','radar.none':'本窗口无局部异常组','radar.items':'{n} 项',
  'radar.base':'基准规模 {gb} GB','radar.hint':'点击卡片定位到趋势图',
  'dict.title':'指标字典','dict.metric':'指标','dict.unit':'单位','dict.source':'来源计数器',
  'dict.cats':'适用类目','dict.rules':'口径与告警规则','dict.close':'关闭',
  'ph.control':'控制面：数仓对应表族（aggr_base_control_* / 2b2c 信令族）暂无数据，此页签先占位。',
  'ph.control.sub':'待上游采集接入后自动出数（soc_trend_sync 每小时补采）。',
  'ph.voice':'语音页签（VoLTE/VoNR KQI）：数仓表族暂无数据，先占位。',
  'ph.voice.sub':'OTT语音（VoIP）业务流量与 TCP 体验在「数据 → OTT语音」类目下查看。',
  'st.loading':'加载中…','st.live':'实时数据 · 更新 {ts}','st.empty':'暂无数据：等 soc_trend_sync 首次落盘',
  'st.fail':'数据加载失败：{msg}','st.noecharts':'ECharts 未加载',
  'win.hour':'告警窗口 00:00–{h}:00 · 与 D-1 / D-7 同时段对比','win.day':'同时段 00:00–{h}:00 汇总 · 与 D-1 / D-7 同窗口对比',
  'dir.drop':'下降','dir.rise':'上升','lvl.critical':'Critical','lvl.major':'Major',
  'member.all':'全网','member.unknown':'未归类','unit.hour':'时','legend.d':'day (D)','legend.d1':'day-1','legend.d7':'day-7',
 },
 en: {
  'app.title':'SOC Multi-Dim Trend Dashboard','app.sub':'One entry · 3-day compare · drill-down',
  'scope.data':'Data','scope.voice':'Voice',
  'cat.flow':'Traffic','cat.video':'Video','cat.web':'Web','cat.game':'Game',
  'cat.ottvoice':'OTT Voice','cat.ottvideo':'OTT Video','cat.tcp':'TCP KPI','cat.control':'Control Plane',
  'dim.total':'Whole Network','dim.area':'All Areas','dim.ne':'NE (SGW)','dim.app':'Apps (Top 20)',
  'lbl.day':'Analysis Day D','lbl.dim':'Dimension','lbl.metric':'Metric','btn.reset':'Reset drill-down',
  'alarm.title':'Major Alarm Analysis','alarm.none':'No dual-baseline breach in this window',
  'alarm.expand':'Show {n} more','alarm.collapse':'Collapse',
  'alarm.notready':'Baselines not ready (D-1 / D-7 missing for the same window)',
  'alarm.foot':'Red Critical · Orange Major; both D-1 and D-7 baselines must breach. Whole network and top-level scope only.',
  'contrib.main':'Main contribution from {name} ({pct}%)','contrib.more':' +{n} members',
  'trend.title':'Current Traffic Trend','trend.ref':'Whole-network reference',
  'trend.chip':'{label} {val} {pct}',
  'radar.title':'Local Anomaly Radar','radar.none':'No local anomaly group','radar.items':'{n} items',
  'radar.base':'Base scale {gb} GB','radar.hint':'Click a card to locate in the chart',
  'dict.title':'Metric Dictionary','dict.metric':'Metric','dict.unit':'Unit','dict.source':'Source counters',
  'dict.cats':'Categories','dict.rules':'Caliber & alarm rules','dict.close':'Close',
  'ph.control':'Control plane: the corresponding warehouse tables are empty — placeholder for now.',
  'ph.control.sub':'Will light up automatically once upstream ingestion starts (soc_trend_sync hourly).',
  'ph.voice':'Voice tab (VoLTE/VoNR KQI): warehouse tables empty — placeholder for now.',
  'ph.voice.sub':'OTT voice (VoIP) traffic and TCP experience live under Data → OTT Voice.',
  'st.loading':'Loading…','st.live':'Live · updated {ts}','st.empty':'No data yet — waiting for soc_trend_sync',
  'st.fail':'Failed to load: {msg}','st.noecharts':'ECharts unavailable',
  'win.hour':'Alarm window 00:00–{h}:00 vs D-1 / D-7 same span','win.day':'Same-span 00:00–{h}:00 totals vs D-1 / D-7 same window',
  'dir.drop':'drop','dir.rise':'rise','lvl.critical':'Critical','lvl.major':'Major',
  'member.all':'Whole Network','member.unknown':'Unclassified','unit.hour':':00','legend.d':'day (D)','legend.d1':'day-1','legend.d7':'day-7',
 },
};
var LOCALE = 'zh';
function t(key, params){
  var s = (I18N[LOCALE] && I18N[LOCALE][key]) || I18N.zh[key] || key;
  if (params) { Object.keys(params).forEach(function(k){ s = s.split('{'+k+'}').join(params[k]); }); }
  return s;
}

var API = '/api/soc-trend';
var CATS = ['flow','video','web','game','ottvoice','ottvideo','tcp','control'];
var state = {gran:'hour', scope:'data', cat:'flow', dim:'total', metric:'total_gb',
             day:null, member:null, alLimit:3, radarSel:null};
var meta=null, dict=null, series=null, alarms=null, charts={}, sparkCache={};

/* ---- 工具 ---- */
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function fmt(v,digits){if(v==null)return '—';var n=Number(v);return Number.isFinite(n)?n.toLocaleString('en-US',{maximumFractionDigits:digits==null?1:digits}):'—'}
function pct(v){return v==null?'—':((v>0?'+':'')+Number(v).toFixed(1)+'%')}
function setStatus(txt,ok){var e=document.getElementById('status');e.textContent=txt;e.className='status '+(ok?'':'bad')}
function metricName(id){var d=dict&&dict.metrics?dict.metrics.filter(function(m){return m.id===id})[0]:null;return d?(LOCALE==='en'?d.en:d.zh):id}
/* 后端成员名不随外壳语言变化，这里对特殊成员做本地化（area=0 未归类） */
function memberDisp(member,name){return member==='0'?t('member.unknown'):(name||member)}
function metricUnit(id){var d=dict&&dict.metrics?dict.metrics.filter(function(m){return m.id===id})[0]:null;return d?d.unit:''}
function metricDigits(id){var d=dict&&dict.metrics?dict.metrics.filter(function(m){return m.id===id})[0]:null;return d?d.digits:1}
function chart(id){if(charts[id])charts[id].dispose();charts[id]=echarts.init(document.getElementById(id),null,{renderer:'canvas'});return charts[id]}
function resizeAll(){Object.keys(charts).forEach(function(k){try{charts[k].resize()}catch(e){}})}
function txtCol(){return document.documentElement.dataset.theme==='light'?'#29485d':'#ffffff'}
function mutCol(){return document.documentElement.dataset.theme==='light'?'#587184':'#dce7ff'}

/* ---- 主题 / 语言（与外壳联动） ---- */
function initialTheme(){var q=new URLSearchParams(location.search).get('theme');if(q==='dark'||q==='light')return q;try{var s=localStorage.getItem('myapp-theme');if(s==='dark'||s==='light')return s}catch(e){}return 'dark'}
document.documentElement.dataset.theme=initialTheme();
function applyTheme(mode){if(mode!=='dark'&&mode!=='light')return;document.documentElement.dataset.theme=mode;
 try{localStorage.setItem('myapp-theme',mode)}catch(e){}
 if(series&&window.echarts)drawMain();renderRadar(true);}
function applyLocale(locale){LOCALE=(locale==='en')?'en':'zh';try{localStorage.setItem('app-locale',LOCALE)}catch(e){}
 try{document.documentElement.lang=(LOCALE==='zh'?'zh-CN':'en')}catch(e){}
 document.getElementById('appTitle').textContent=t('app.title');
 document.getElementById('appSub').textContent=t('app.sub');
 document.getElementById('dictBtn').textContent=t('dict.title');
 document.getElementById('lblDay').textContent=t('lbl.day');
 document.getElementById('lblDim').textContent=t('lbl.dim');
 document.getElementById('lblMetric').textContent=t('lbl.metric');
 document.getElementById('resetBtn').textContent=t('btn.reset');
 renderAll();}

/* ---- API ---- */
function getJSON(url){return fetch(url,{cache:'no-store'}).then(function(r){
  return r.json().then(function(d){ if(!r.ok) throw new Error(d&&d.error?('HTTP '+r.status+': '+d.error):('HTTP '+r.status)); return d; });})}

function loadDict(){
  return getJSON(API+'/dict').then(function(d){dict=d;}).catch(function(){dict=null;});
}
function loadMeta(){
  return getJSON(API+'/meta').then(function(d){
    meta=d;
    if(!state.day){
      state.day = state.gran==='hour' ? (meta.latest_hour_day||meta.latest_day) : (meta.latest_day||meta.latest_hour_day);
    }
    if(!state.day) throw new Error(t('st.empty'));
    renderNotice();renderCatBar();renderMetricSel();renderDimSel();
  });
}
function loadSeries(){
  var url=API+'/series?gran='+state.gran+'&day='+state.day+'&cat='+state.cat+'&dim='+state.dim;
  return getJSON(url).then(function(d){series=d;ensureMember();renderMain();});
}
function loadAlarms(){
  var url=API+'/alarms?gran='+state.gran+'&day='+state.day;
  return getJSON(url).then(function(d){alarms=d;renderAlarms();renderRadar();});
}
function loadAll(){
  if(!window.echarts){setStatus(t('st.noecharts'),false);return}
  setStatus(t('st.loading'),true);
  var boot=dict?Promise.resolve():loadDict();
  boot.then(loadMeta).then(function(){
    if(state.scope==='voice'){renderVoice();setStatus(t('st.live',{ts:meta.updated_at||'—'}),true);return}
    renderVoice();
    return Promise.all([loadSeries(),loadAlarms()]).then(function(){
      setStatus(t('st.live',{ts:meta.updated_at||'—'}),true);});
  }).catch(function(e){setStatus(t('st.fail',{msg:e.message}),false);
    document.getElementById('alarmList').innerHTML='<div class="empty">'+esc(e.message)+'</div>';});
}

/* ---- 状态联动 ---- */
function setGran(g){if(state.gran===g)return;state.gran=g;
  document.querySelectorAll('#granSeg button').forEach(function(b){b.classList.toggle('on',b.getAttribute('data-g')===g)});
  var days=state.gran==='hour'?meta.hour_days:meta.day_days;
  var latest=days&&days.length?days[days.length-1]:null;
  if(latest)state.day=latest;
  document.getElementById('dayInput').value=state.day||'';
  state.member=null;state.radarSel=null;loadAll();}
function setScope(s){state.scope=s;
  document.querySelectorAll('#scopeTabs button').forEach(function(b){
    b.setAttribute('aria-selected',b.getAttribute('data-scope')===s);
    b.classList.toggle('active',b.getAttribute('data-scope')===s)});
  document.getElementById('dataArea').hidden=(s!=='data');
  document.getElementById('voiceArea').hidden=(s!=='voice');
  if(s==='voice'){renderVoice();return}
  loadAll();}
function setCat(c){state.cat=c;state.member=null;state.radarSel=null;state.alLimit=3;
  renderCatBar();
  state.metric=(meta.cats[c].metrics||[])[0]||'total_gb';renderMetricSel();
  var dims=meta.cats[c].dims||[];
  state.dim=dims[0]||'total';renderDimSel();
  if(!meta.cats[c].ready){renderPlaceholder();renderAlarms();renderRadar();return}
  loadSeries();loadAlarms();}
function setDim(d){state.dim=d;state.member=null;state.radarSel=null;
  var opts=meta.cats[state.cat].dims||[];
  if(opts.indexOf(d)<0)return;
  loadSeries();}
function setMetric(m){state.metric=m;renderMain();}
function setDay(v){if(!v)return;state.day=v;state.member=null;state.radarSel=null;loadAll();}
function ensureMember(){
  var members=(series&&series.members)||[];
  var ids=members.map(function(m){return m.member});
  if(!state.member||ids.indexOf(state.member)<0)state.member=ids[0]||'all';
  renderMemberBar();}
function resetDrill(){state.dim='total';state.member=null;state.radarSel=null;state.alLimit=3;
  document.getElementById('dimSel').value='total';
  if(meta.cats[state.cat].ready)loadSeries();else{renderPlaceholder();}}
function focusMember(dim,member){
  // 雷达分组全部来自 flow/tcp（ciservice 族才有区域/网元维度），点击定位前先切回流量类目
  if(state.cat!=='flow'&&state.cat!=='tcp'){state.cat='flow';renderCatBar();
    state.metric=(meta.cats.flow.metrics||[])[0]||'total_gb';renderMetricSel();}
  state.dim=dim;state.member=member;state.radarSel=member;
  document.getElementById('dimSel').value=dim;
  var p=document.getElementById('trendPanel');
  if(meta.cats[state.cat].ready){
    loadSeries().then(function(){renderRadar();       // 刷新选中高亮
      if(p&&p.scrollIntoView)p.scrollIntoView({behavior:'smooth',block:'start'});});
  }}

/* ---- 渲染：通知条 / 类目 / 指标 / 成员 ---- */
function renderNotice(){
  var el=document.getElementById('notice');if(!meta)return;
  var cats=meta.cats||{};
  var html=['<span>'+esc((dict&&dict.rules&&'')||'')+'VMAX 数仓 GBase 只读直连 · 任务 soc_trend_sync</span>',
            '<span>'+esc(t('st.live',{ts:meta.updated_at||'—'}))+'</span>',
            '<span>'+esc(t('alarm.foot'))+'</span>'];
  if(cats.control&&!cats.control.ready)html.push('<span class="warn">'+esc(t('ph.control'))+'</span>');
  el.innerHTML=html.join('');
}
function renderCatBar(){
  var bar=document.getElementById('catBar');
  bar.innerHTML=CATS.map(function(c){
    var ready=!meta||!meta.cats[c]||meta.cats[c].ready;
    return '<button data-cat="'+c+'" class="'+(state.cat===c?'on':'')+'"'+(ready?'':' disabled')+
      ' title="'+esc(ready?'':t('ph.control'))+'">'+esc(t('cat.'+c))+'</button>';
  }).join('');
}
function renderMetricSel(){
  var sel=document.getElementById('metricSel');
  var mids=(meta&&meta.cats[state.cat]&&meta.cats[state.cat].metrics)||[];
  sel.innerHTML=mids.map(function(m){
    return '<option value="'+esc(m)+'"'+(m===state.metric?' selected':'')+'>'+esc(metricName(m))+'</option>';
  }).join('');
  sel.style.display=mids.length?'':'none';
}
function renderDimSel(){
  var sel=document.getElementById('dimSel');
  var dims=(meta&&meta.cats[state.cat]&&meta.cats[state.cat].dims)||['total'];
  sel.innerHTML=dims.map(function(d){
    return '<option value="'+esc(d)+'"'+(d===state.dim?' selected':'')+'>'+esc(t('dim.'+d))+'</option>';
  }).join('');
  sel.style.display=dims.length>1?'':'none';
}
function renderMemberBar(){
  var bar=document.getElementById('memberBar');
  var members=(series&&series.members)||[];
  if(state.dim==='total'||members.length<2){bar.innerHTML='';return}
  bar.innerHTML=members.map(function(m){
    return '<span class="'+(m.member===state.member?'up':'')+'" style="cursor:pointer" data-member="'+
      esc(m.member)+'"><b>'+esc(memberDisp(m.member,m.name))+'</b></span>';
  }).join('');
}

/* ---- 渲染：主趋势图 + 大数字 ---- */
function drawMain(){
  if(!series||!window.echarts)return;
  var c=chart('mainChart');
  var digit=metricDigits(state.metric), unit=metricUnit(state.metric);
  var focused=series.members.filter(function(m){return m.member===state.member})[0];
  if(!focused)return;
  var opt={animation:false,tooltip:{trigger:'axis',confine:true},
    legend:{top:2,textStyle:{color:mutCol(),fontSize:10}},
    grid:{left:56,right:18,top:34,bottom:24}};
  if(state.gran==='hour'){
    var x=[],i;for(i=0;i<24;i++)x.push((i<10?'0':'')+i+t('unit.hour'));
    var line=function(day,label,color,dash){
      return {name:label,type:'line',smooth:true,connectNulls:true,showSymbol:false,
        lineStyle:{width:day===series.day?2.4:1.6,type:dash},
        itemStyle:{color:color},
        data:focused.points[day].map(function(p){return p?p.values[state.metric]:null})};};
    opt.xAxis={type:'category',data:x,axisLabel:{color:txtCol(),fontSize:10},axisLine:{lineStyle:{color:mutCol()}}};
    opt.yAxis={type:'value',name:unit,nameTextStyle:{color:txtCol(),fontSize:9},scale:true,
      axisLabel:{color:txtCol(),fontSize:9},splitLine:{show:false}};
    opt.series=[line(series.day,t('legend.d'),'#2b8cff','solid'),
                line(series.d1,t('legend.d1'),'#08bd83','dashed'),
                line(series.d7,t('legend.d7'),'#f4ce00','dotted')];
  }else{
    var days=series.days||[];
    opt.xAxis={type:'category',data:days.map(function(d){return d.slice(5)}),
      axisLabel:{color:txtCol(),fontSize:10},axisLine:{lineStyle:{color:mutCol()}}};
    opt.yAxis={type:'value',name:unit,nameTextStyle:{color:txtCol(),fontSize:9},scale:true,
      axisLabel:{color:txtCol(),fontSize:9},splitLine:{show:false}};
    opt.series=[{name:t('legend.d'),type:'line',smooth:true,showSymbol:true,symbolSize:5,
      lineStyle:{width:2.2},itemStyle:{color:'#2b8cff'},
      data:days.map(function(d){var v=focused.values[d];return v?v[state.metric]:null}),
      markPoint:{data:[{coord:[days.indexOf(series.day),null],symbol:'circle',symbolSize:9,
        itemStyle:{color:'#2b8cff'}},
        {coord:[days.indexOf(series.d1),null],symbol:'circle',symbolSize:8,itemStyle:{color:'#08bd83'}},
        {coord:[days.indexOf(series.d7),null],symbol:'circle',symbolSize:8,itemStyle:{color:'#f4ce00'}}]}}];
  }
  c.setOption(opt,true);
}
function renderMain(){
  if(!meta||!meta.cats[state.cat].ready){renderPlaceholder();return}
  document.getElementById('mainChart').style.height='';           // 恢复占位时压低的高度
  document.getElementById('trendTitle').textContent=t('cat.'+state.cat)+' · '+t('trend.title');
  document.getElementById('trendHint').textContent=
    metricName(state.metric)+' ('+metricUnit(state.metric)+') · '+
    (state.dim==='total'?t('dim.total'):(focusedName()||state.member));
  renderDimSel();renderMemberBar();drawMain();renderBig();
}
function focusedName(){
  var m=(series&&series.members||[]).filter(function(x){return x.member===state.member})[0];
  return m?memberDisp(m.member,m.name):null;
}
function renderBig(){
  var elVal=document.getElementById('bigVal'),elUnit=document.getElementById('bigUnit'),
      chips=document.getElementById('trendChips');
  if(!series){elVal.textContent='—';elUnit.textContent='';chips.innerHTML='';return}
  var digit=metricDigits(state.metric),unit=metricUnit(state.metric);
  var focused=series.members.filter(function(m){return m.member===state.member})[0];
  var cur=null,b1=null,b7=null;
  if(state.gran==='hour'&&focused){
    var h=Math.max(0,series.window_end_hour);
    var pD=focused.points[series.day][h],p1=focused.points[series.d1][h],p7=focused.points[series.d7][h];
    cur=pD?pD.values[state.metric]:null;b1=p1?p1.values[state.metric]:null;b7=p7?p7.values[state.metric]:null;
  }else if(focused){
    cur=(focused.values[series.day]||{})[state.metric];
    b1=(focused.values[series.d1]||{})[state.metric];
    b7=(focused.values[series.d7]||{})[state.metric];
  }
  elVal.textContent=fmt(cur,digit);elUnit.textContent=unit+' · '+
    (state.gran==='hour'?((series.window_end_hour<10?'0':'')+series.window_end_hour+t('unit.hour')):series.day);
  function chip(label,v,base){
    var p=(v!=null&&base)?((v-base)/base*100):null;
    var cls=p==null?'':(p<0?'down':'up');
    return '<span class="'+cls+'">'+esc(label)+' <b>'+fmt(v,digit)+'</b> '+esc(pct(p))+'</span>';
  }
  chips.innerHTML=chip('D-1',b1,cur)+chip('D-7',b7,cur);
}

/* ---- 渲染：告警列表 ---- */
function renderAlarms(){
  var list=document.getElementById('alarmList'),count=document.getElementById('alCount'),
      foot=document.getElementById('alFoot'),btnArea=document.getElementById('alTime');
  if(!meta||!meta.cats[state.cat].ready){
    count.setAttribute('hidden','');foot.textContent='';
    list.innerHTML='<div class="empty"><div class="big">'+esc(t('ph.control'))+'</div>'+esc(t('ph.control.sub'))+'</div>';
    btnArea.textContent='';return;
  }
  if(!alarms){list.innerHTML='';return}
  document.getElementById('winInfo').textContent=state.gran==='hour'
    ?t('win.hour',{h:alarms.window_end_hour}):t('win.day',{h:alarms.window_end_hour});
  btnArea.textContent=state.gran==='hour'
    ?(String(alarms.window_end_hour).padStart(2,'0')+':00'):'';
  if(!alarms.baselines_ready){
    list.innerHTML='<div class="empty">'+esc(t('alarm.notready'))+'</div>';
    count.setAttribute('hidden','');foot.textContent=esc(t('alarm.foot'));return;
  }
  var all=alarms.alarms||[];
  var shown=all.slice(0,state.alLimit),rest=all.length-shown.length;
  count.removeAttribute('hidden');count.textContent=String(all.length);
  if(!all.length){
    list.innerHTML='<div class="empty">'+esc(t('alarm.none'))+'</div>';
  }else{
    list.innerHTML=shown.map(alarmHtml).join('')+
      (rest>0?'<button class="ghost-btn al-toggle" id="alMore">'+esc(t('alarm.expand',{n:rest}))+'</button>':
       (all.length>3?'<button class="ghost-btn al-toggle" id="alMore">'+esc(t('alarm.collapse'))+'</button>':''));
    var more=document.getElementById('alMore');
    if(more)more.addEventListener('click',function(){
      state.alLimit=state.alLimit>3?3:catAll.length;renderAlarms();});
  }
  foot.textContent=t('alarm.foot')+' '+((dict&&dict.rules&&dict.rules.min_scale)||'');
}
function alarmHtml(a){
  var dir=t('dir.'+a.direction), lvl=t('lvl.'+a.level);
  var main='<span class="tag">'+esc(lvl)+'</span><b>'+esc(memberDisp(a.member,a.name))+'</b> / '+esc(metricName(a.metric))+
    ' '+esc(dir)+' <b>'+esc(Math.abs(a.d1_pct).toFixed(1)+'%')+'</b>'+
    '<span class="why">（较D-1；较D-7 '+esc(Math.abs(a.d7_pct).toFixed(1))+'%）</span>';
  var contrib='';
  var cs=(a.contributions||[]);
  if(cs.length){
    var tail=cs.length>1?t('contrib.more',{n:cs.length-1}):'';
    contrib='<div class="contrib">'+esc(t('contrib.main',{name:cs[0].name,pct:cs[0].share_pct}))+esc(tail)+'</div>';
  }
  var scale=a.base_gb?'<span class="why"> · '+esc(t('radar.base',{gb:a.base_gb}))+'</span>':'';
  return '<div class="al-item '+a.level+'">'+main+scale+contrib+'</div>';
}

/* ---- 渲染：异常雷达 ---- */
function renderRadar(keep){
  var list=document.getElementById('radarList'),badge=document.getElementById('radarCount');
  if(!meta||!meta.cats[state.cat].ready){badge.setAttribute('hidden','');document.getElementById('radarHint').textContent='';
    list.innerHTML='<div class="empty">—</div>';return;}
  if(!alarms){return}
  var groups=(alarms.radar||[]);
  document.getElementById('radarHint').textContent=t('radar.hint');
  if(!groups.length){badge.setAttribute('hidden','');list.innerHTML='<div class="empty">'+esc(t('radar.none'))+'</div>';return}
  badge.removeAttribute('hidden');badge.textContent=String(groups.length);
  list.innerHTML=groups.map(function(g,i){
    var worst=g.worst?(metricName(g.worst.metric)+' D-1 '+pct(g.worst.d1_pct)+' · D-7 '+pct(g.worst.d7_pct)):'';
    return '<div class="radar-item'+(state.radarSel===g.member?' sel':'')+'" data-dim="'+g.dim+'" data-member="'+esc(g.member)+'">'+
      '<div class="r-head"><span class="dot '+g.level+'"></span><b>'+esc(memberDisp(g.member,g.name))+'</b>'+
      '<span style="color:#9fb6d8">'+esc(t('radar.items',{n:g.count}))+'</span></div>'+
      '<div class="r-meta">'+esc(worst)+' · '+esc(t('radar.base',{gb:g.base_gb}))+'</div>'+
      '<div id="spark_'+i+'" class="chart-sm"></div></div>';
  }).join('');
  Array.prototype.forEach.call(list.querySelectorAll('.radar-item'),function(el){
    el.addEventListener('click',function(){
      focusMember(el.getAttribute('data-dim'),el.getAttribute('data-member'));});
  });
  drawSparks(groups);
}
function drawSparks(groups){
  groups.forEach(function(g,i){
    var el=document.getElementById('spark_'+i);if(!el||!window.echarts)return;
    var dim=g.dim;
    var done=function(vals){
      var days=Object.keys(vals).sort();
      try{
        chart('spark_'+i).setOption({animation:false,grid:{left:4,right:4,top:4,bottom:4},
          xAxis:{type:'category',show:false,data:days},yAxis:{type:'value',show:false,scale:true},
          series:[{type:'line',showSymbol:false,smooth:true,
            lineStyle:{width:1.4,color:g.level==='critical'?'#ff5c6c':'#ffa640'},
            areaStyle:{opacity:.15,color:g.level==='critical'?'#ff5c6c':'#ffa640'},
            data:days.map(function(d){return vals[d]})}]},true);
      }catch(e){}
    };
    if(state.gran!=='day'&&sparkCache[dim]){done(sparkCache[dim][g.member]||{});return}
    getJSON(API+'/series?gran=day&cat=flow&dim='+dim).then(function(d){
      var byMember={};(d.members||[]).forEach(function(m){
        var vals={};Object.keys(m.values||{}).forEach(function(day){
          var v=m.values[day];vals[day]=v?(v.total_gb||0):0;});
        byMember[m.member]=vals;});
      sparkCache[dim]=byMember;done(byMember[g.member]||{});
    }).catch(function(){});
  });
}

/* ---- 渲染：占位（控制面 / 语音） ---- */
function renderPlaceholder(){
  document.getElementById('alarmList').innerHTML=
    '<div class="empty"><div class="big">'+esc(t('ph.control'))+'</div>'+esc(t('ph.control.sub'))+'</div>';
  document.getElementById('radarList').innerHTML='<div class="empty">—</div>';
  document.getElementById('radarCount').setAttribute('hidden','');
  document.getElementById('trendTitle').textContent=t('cat.'+state.cat)+' · '+t('trend.title');
  document.getElementById('bigVal').textContent='—';document.getElementById('bigUnit').textContent='';
  document.getElementById('trendChips').innerHTML='';
  document.getElementById('mainChart').style.height='120px';
  if(window.echarts){try{chart('mainChart').clear()}catch(e){}}
  document.getElementById('winInfo').textContent='';
}
function renderVoice(){
  var on=state.scope==='voice';
  document.getElementById('voiceArea').hidden=!on;
  document.getElementById('dataArea').hidden=on;
  if(on)document.getElementById('voiceEmpty').innerHTML=
    '<div class="big">'+esc(t('ph.voice'))+'</div>'+esc(t('ph.voice.sub'));
}

/* ---- 指标字典弹窗 ---- */
function renderDict(){
  if(!dict)return;
  document.getElementById('dictTitle').textContent=t('dict.title');
  var r=dict.rules||{};
  document.getElementById('dictRules').innerHTML=
    ['alarm','contribution','min_scale','granularity'].map(function(k){
      return r[k]?'<div>· '+esc(r[k])+'</div>':'';}).join('');
  var head='<thead><tr><th>'+esc(t('dict.metric'))+'</th><th>'+esc(t('dict.unit'))+'</th>'+
    '<th>'+esc(t('dict.source'))+'</th><th>'+esc(t('dict.cats'))+'</th></tr></thead>';
  var rows=(dict.metrics||[]).map(function(m){
    return '<tr><td>'+esc(LOCALE==='en'?m.en:m.zh)+'</td><td>'+esc(m.unit)+'</td><td>'+
      esc(m.source)+'</td><td>'+esc((m.cats||[]).map(function(c){return t('cat.'+c)}).join(', '))+'</td></tr>';
  }).join('');
  document.getElementById('dictTable').innerHTML=head+'<tbody>'+rows+'</tbody>';
  document.getElementById('dictModal').removeAttribute('hidden');
}

/* ---- 全量重渲染（切语言 / 主题后调用；boot 前调用是安全的，静态骨架已够） ---- */
function renderAll(){
  if(!meta){ return; }
  renderNotice();renderCatBar();renderMetricSel();renderDimSel();
  if(state.scope==='voice'){renderVoice();return}
  if(!meta.cats[state.cat].ready){renderPlaceholder();return}
  renderMain();
  if(alarms){renderAlarms();renderRadar();}
}

/* ---- 事件绑定 ---- */
document.getElementById('granSeg').addEventListener('click',function(e){
  var b=e.target.closest('[data-g]');if(b)setGran(b.getAttribute('data-g'));});
document.getElementById('scopeTabs').addEventListener('click',function(e){
  var b=e.target.closest('[data-scope]');if(b)setScope(b.getAttribute('data-scope'));});
document.getElementById('catBar').addEventListener('click',function(e){
  var b=e.target.closest('[data-cat]');if(b&&!b.disabled)setCat(b.getAttribute('data-cat'));});
document.getElementById('dimSel').addEventListener('change',function(e){setDim(e.target.value)});
document.getElementById('metricSel').addEventListener('change',function(e){setMetric(e.target.value)});
document.getElementById('dayInput').addEventListener('change',function(e){setDay(e.target.value)});
document.getElementById('resetBtn').addEventListener('click',resetDrill);
document.getElementById('memberBar').addEventListener('click',function(e){
  var b=e.target.closest('[data-member]');if(b){state.member=b.getAttribute('data-member');
    renderMemberBar();renderMain();}});
document.getElementById('dictBtn').addEventListener('click',renderDict);
document.getElementById('dictClose').addEventListener('click',function(){
  document.getElementById('dictModal').setAttribute('hidden','');});
document.getElementById('dictModal').addEventListener('click',function(e){
  if(e.target===this)this.setAttribute('hidden','');});
window.addEventListener('resize',resizeAll);
window.addEventListener('message',function(e){
  if(!e.data)return;
  if(e.data.__type==='myapp-theme')applyTheme(e.data.mode);
  else if(e.data.__type==='myapp-locale')applyLocale(e.data.locale);
});
(function(){try{var _l=localStorage.getItem('app-locale');
  LOCALE=(_l==='en'||_l==='zh')?_l:((((navigator.language||'zh')+'').toLowerCase().indexOf('zh')===0)?'zh':'en');}catch(e){}})();
/* 全局错误可见化：必须先于 applyLocale 挂载（启动路径上的任何异常都要能浮出来） */
window.addEventListener('error', function(e){
  setStatus('JS: ' + (e && e.message ? e.message : 'unknown') +
    (e && e.filename ? ' @' + String(e.filename).split('/').pop() + ':' + e.lineno : ''), false);});
window.addEventListener('unhandledrejection', function(e){
  var r = e && e.reason; setStatus('PROMISE: ' + (r && r.message ? r.message : String(r)), false);});
applyLocale(LOCALE);
if(window.echarts){
  loadAll();
  /* 加载兜底：15s 仍无结果时显式报错，避免永久停在 loading */
  setTimeout(function(){
    var s = document.getElementById('status');
    if (s && s.textContent === t('st.loading')) setStatus(t('st.fail', {msg: 'timeout (15s) — API 无响应或脚本异常'}), false);
  }, 15000);
  try{MyAppRefresh.install({defaultSec:600,onRefresh:function(){loadAll();}});}catch(e){}
}else{setStatus(t('st.noecharts'),false)}
})();
