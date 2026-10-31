/* qa-assistant.js — v3 门户右下角「问答助手」挂件（2026-10-27）
 * =================================================================
 * 能力来源：Task/whatsapp-kb-bot 的 src/http-server.js（与 WhatsApp 群里同一套
 * 答题引擎与知识库：查表 / 工单统计 / 单号分析 / 站点告警 / VMAX CCA / RAG）。
 *
 * 为什么不在这里直接调模型：浏览器里没有知识库索引，也没有工具链；挂件只负责
 * 「输入 → 同源 /api/portal-qa/ask → 展示」。鉴权、进程拉起、超时都在 my_app 后端
 * （见 backend/routers/portal_qa.py）。
 *
 * 约定：
 *  - 文案走下方 I18N（跟随 <html lang>，与页面语言开关同步 —— 监听 html 的 lang 属性）；
 *  - 登录门（#gate）打开时隐藏挂件，避免未登录也能提问；
 *  - 对话只存在本标签页（sessionStorage），刷新页面不丢、关掉标签页就清；
 *  - 服务端另有一份 5 轮记忆（按 clientId 分桶），用于「那个单子」这类追问。
 */
(function () {
  'use strict';

  var API = '/api/portal-qa';
  var LS_CLIENT = 'olbr.qa.client';
  var SS_MSGS = 'olbr.qa.msgs';
  var MAX_MSGS = 60;
  var MAX_Q = 500;

  var I18N = {
    zh: {
      fab: '问答助手',
      title: '运维问答助手',
      sub: '基于 WhatsApp 知识库 · 中/英',
      placeholder: '问点什么…（Enter 发送，Shift+Enter 换行）',
      send: '发送',
      clear: '清空对话',
      close: '收起',
      dragTip: '拖动标题栏移动 · 双击标题栏复位 · 拖右下角调节窗口大小',
      welcomeTitle: '你好，我是运维问答助手。',
      welcomeBody: '可以问我知识库里的操作步骤、告警码含义、工单与站点情况。答案与 WhatsApp 群里一致。',
      chips: ['告警码 99933 是什么意思？', '今天有多少 TT 还没有闭环？', 'eFlow 里怎么创建用户组？'],
      thinking: '正在思考…',
      elapsed: '已等待',
      sec: '秒',
      slowHint: '本地模型较慢时单次约 30–60 秒，请稍候',
      booting: '正在启动问答服务（首次约 10–30 秒）…',
      booted: '服务就绪 · 知识库 12xx 块',
      ready: '就绪',
      notReady: '问答服务未就绪',
      empty: '问题不能为空',
      failed: '暂时答不上来',
      retry: '重试',
      login: '请先登录 my_app（从门户打开任一 my_app 看板即可）后再提问',
      cleared: '已清空对话',
      confirmClear: '清空当前对话？服务端的追问上下文也会一并清掉。',
      srcKb: '知识库',
      srcLookup: '查表',
      srcStats: '统计',
      srcTt: '工单',
      srcSite: '站点告警',
      srcVmax: 'VMAX',
      viaLocal: '本地兜底',
      chars: '字'
    },
    en: {
      fab: 'Ask assistant',
      title: 'Ops Q&A assistant',
      sub: 'WhatsApp knowledge base · EN/ZH',
      placeholder: 'Ask anything… (Enter to send, Shift+Enter for a new line)',
      send: 'Send',
      clear: 'Clear chat',
      close: 'Collapse',
      dragTip: 'Drag the header to move · double-click it to reset · drag the bottom-right corner to resize',
      welcomeTitle: 'Hi, I am the Ops Q&A assistant.',
      welcomeBody: 'Ask about procedures in the knowledge base, alarm code meanings, tickets and site status. Answers match the WhatsApp group.',
      chips: ['What does alarm 99933 mean?', 'How many TTs are still open today?', 'How to create a user group in eFlow?'],
      thinking: 'Thinking…',
      elapsed: 'elapsed',
      sec: 's',
      slowHint: 'The local model may take 30–60s per answer',
      booting: 'Starting the Q&A service (first run 10–30s)…',
      booted: 'Service ready · KB indexed',
      ready: 'Ready',
      notReady: 'Q&A service is not ready',
      empty: 'Question cannot be empty',
      failed: 'Could not answer',
      retry: 'Retry',
      login: 'Please sign in to my_app first (open any my_app dashboard from the portal), then retry',
      cleared: 'Chat cleared',
      confirmClear: 'Clear this conversation? Server-side follow-up context will be cleared too.',
      srcKb: 'Knowledge base',
      srcLookup: 'Lookup',
      srcStats: 'Stats',
      srcTt: 'Tickets',
      srcSite: 'Site alarms',
      srcVmax: 'VMAX',
      viaLocal: 'local fallback',
      chars: 'chars'
    }
  };

  var CHANNEL_LABEL = {
    kb: 'srcKb', lookup: 'srcLookup', stats: 'srcStats', tt: 'srcTt',
    sitealarm: 'srcSite', vmaxcca: 'srcVmax'
  };

  function lang() {
    var v = document.documentElement.getAttribute('lang') || 'zh';
    return v.indexOf('en') === 0 ? 'en' : 'zh';
  }
  function t(k) {
    var d = I18N[lang()] || I18N.zh;
    return d[k] != null ? d[k] : (I18N.zh[k] != null ? I18N.zh[k] : k);
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function clientId() {
    var id = null;
    try { id = localStorage.getItem(LS_CLIENT); } catch (e) { /* 隐私模式 */ }
    if (!id) {
      id = 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
      try { localStorage.setItem(LS_CLIENT, id); } catch (e) { /* ignore */ }
    }
    return id;
  }

  var msgs = [];
  var busy = false;
  var lastQuestion = '';
  var timer = null;
  var healthDone = false;

  /* ── 面板几何（拖动 + 缩放，2026-10-28 加）─────────────────────────────
   * 为什么不用 left/top：面板 CSS 默认只给了 right/bottom。直接存改动后的
   * right/bottom/width/height，复位（双击）时清掉行内样式即回 CSS 默认。
   * 存 localStorage 跨会话记忆（与 olbr.* 同键前缀习惯），窄屏抽屉不记。 */
  var LS_GEO = 'olbr.qa.geo';
  var GEO_W_MIN = 300, GEO_W_MAX = 720;
  var GEO_H_MIN = 360, GEO_H_MAX = 820;
  var geo = null;
  try {
    var g = JSON.parse(localStorage.getItem(LS_GEO) || 'null');
    if (g && isFinite(g.right) && isFinite(g.bottom) && isFinite(g.width) && isFinite(g.height)) geo = g;
  } catch (e) { geo = null; }
  function saveGeo() {
    try {
      if (geo) localStorage.setItem(LS_GEO, JSON.stringify(geo));
      else localStorage.removeItem(LS_GEO);
    } catch (e) { /* 隐私模式 */ }
  }
  function isNarrow() {
    return window.matchMedia && window.matchMedia('(max-width: 560px)').matches;
  }
  function applyGeo() {
    if (!panel) return;
    if (isNarrow() || !geo) {
      /* 无记忆几何时清行内样式回 CSS 默认。
         窄屏时**必须清**：行内 right/width/height 会盖住媒体查询的
         bottom-sheet 布局（桌面拖过→再缩窗口，会错位成悬空小窗）。 */
      panel.style.right = ''; panel.style.bottom = '';
      panel.style.width = ''; panel.style.height = '';
      return;
    }
    var maxW = Math.max(GEO_W_MIN, Math.min(GEO_W_MAX, window.innerWidth - 24));
    var maxH = Math.max(180, Math.min(GEO_H_MAX, window.innerHeight - 24));
    var minW = Math.min(GEO_W_MIN, maxW);
    var minH = Math.min(GEO_H_MIN, maxH);
    var w = Math.min(maxW, Math.max(minW, geo.width));
    var h = Math.min(maxH, Math.max(minH, geo.height));
    panel.style.width = w + 'px';
    panel.style.height = h + 'px';
    panel.style.right = Math.min(window.innerWidth - w - 12, Math.max(12, geo.right)) + 'px';
    panel.style.bottom = Math.min(window.innerHeight - h - 12, Math.max(12, geo.bottom)) + 'px';
  }
  function resetGeo() {
    geo = null;
    saveGeo();
    applyGeo();
  }

  var fab, panel, body, list, welcome, input, sendBtn, clearBtn, closeBtn, foot;

  function loadMsgs() {
    try {
      var raw = sessionStorage.getItem(SS_MSGS);
      var arr = raw ? JSON.parse(raw) : null;
      if (arr && arr.length) msgs = arr;
    } catch (e) { msgs = []; }
  }
  function saveMsgs() {
    try { sessionStorage.setItem(SS_MSGS, JSON.stringify(msgs.slice(-MAX_MSGS))); } catch (e) { /* ignore */ }
  }

  function metaText(m) {
    var parts = [];
    if (m.channel && CHANNEL_LABEL[m.channel]) parts.push(t(CHANNEL_LABEL[m.channel]));
    if (m.via === 'ollama-fallback') parts.push(t('viaLocal'));
    if (m.ms != null) parts.push((m.ms / 1000).toFixed(1) + t('sec'));
    return parts.join(' · ');
  }

  function render() {
    list.innerHTML = '';
    welcome.hidden = msgs.length > 0;

    msgs.forEach(function (m) {
      var row = el('div', 'qa-msg ' + (m.role === 'me' ? 'me' : (m.role === 'err' ? 'bot err' : 'bot')));
      var bubble = el('div', 'qa-bubble');
      bubble.textContent = m.text;
      row.appendChild(bubble);

      if (m.meta) {
        // meta 存原始字段、渲染时再翻译：切换语言后历史消息的行尾也会跟着变
        var meta = el('div', 'qa-meta',
          typeof m.meta === 'string' ? m.meta : metaText(m.meta));
        row.appendChild(meta);
      }
      if (m.role === 'err') {
        var meta2 = el('div', 'qa-meta');
        var btn = el('button', 'qa-retry', t('retry'));
        btn.type = 'button';
        btn.addEventListener('click', function () {
          if (lastQuestion) ask(lastQuestion, true);
        });
        meta2.appendChild(btn);
        row.appendChild(meta2);
      }
      list.appendChild(row);
    });

    if (busy) {
      var tr = el('div', 'qa-msg bot');
      var bb = el('div', 'qa-bubble qa-typing');
      bb.appendChild(el('span'));
      bb.appendChild(el('span'));
      bb.appendChild(el('span'));
      tr.appendChild(bb);
      list.appendChild(tr);
    }
    body.scrollTop = body.scrollHeight;
  }

  function setBusy(v) {
    busy = v;
    sendBtn.disabled = v;
    input.disabled = v;
    fab.classList.toggle('is-busy', v);
    if (v) {
      var t0 = Date.now();
      foot.textContent = t('thinking') + ' · ' + t('slowHint');
      timer = setInterval(function () {
        var s = Math.round((Date.now() - t0) / 1000);
        foot.textContent = t('thinking') + ' ' + s + t('sec') + ' · ' + t('slowHint');
      }, 1000);
    } else {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
      // 计数停下后必须清掉，否则答完还挂着「正在思考…」（2026-10-27 实测）
      foot.textContent = '';
    }
    render();
  }

  function push(m) {
    msgs.push(m);
    if (msgs.length > MAX_MSGS) msgs = msgs.slice(-MAX_MSGS);
    saveMsgs();
    render();
  }

  function api(path, payload) {
    /* 团队门户（2026-10-30 加）：401 时换一次 my_app 会话再重试一次。
       背景见 scripts/sync_team_assets.py 里本补丁的说明。
       ⚠️ SCOPE/OLBR_SESSION 为 null 时（上游 /v3/olbrportal/）行为与改动前完全一致。 */
    var SESSION = window.OLBR_SESSION || null;
    var raw = function () {
      return fetch(API + path, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload || {})
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          return { status: r.status, body: j };
        });
      });
    };
    if (!SESSION) return raw();
    return raw().then(function (res) {
      /* 只在 401 时自愈；重试**仅一次**，避免把 401 变成死循环。 */
      if (!res || res.status !== 401) return res;
      return SESSION.ensure(true).then(function (r) {
        if (!r.ok) return res;          /* 换不到会话 → 把 401 如实交回调用方 */
        return raw();
      });
    });
  }

  function describeError(res) {
    var b = res.body || {};
    var detail = typeof b.detail === 'string' ? b.detail
      : (b.detail && b.detail.message) || b.error || '';
    if (res.status === 401) return t('login');
    return t('failed') + (detail ? '：' + detail : '（HTTP ' + res.status + '）');
  }

  function ask(text, isRetry) {
    var q = String(text || '').trim();
    if (!q || busy) return;
    if (q.length > MAX_Q) q = q.slice(0, MAX_Q);

    lastQuestion = q;
    if (!isRetry) push({ role: 'me', text: q });
    input.value = '';
    autosize();
    foot.textContent = '';
    setBusy(true);

    api('/ask', { question: q, lang: lang(), clientId: clientId() })
      .then(function (res) {
        setBusy(false);
        if (res.status !== 200 || !res.body || res.body.ok !== true) {
          push({ role: 'err', text: describeError(res) });
          return;
        }
        var d = res.body;
        var answer = String(d.answer || '').trim();
        push({
          role: 'bot',
          text: answer || t('failed'),
          meta: { channel: d.channel, via: d.via, ms: d.ms }
        });
      })
      .catch(function () {
        setBusy(false);
        push({ role: 'err', text: t('failed') + '（网络异常，请检查连接后重试）' });
      });
  }

  function autosize() {
    input.style.height = 'auto';
    input.style.height = Math.min(110, input.scrollHeight) + 'px';
  }

  function openPanel() {
    panel.hidden = false;
    fab.setAttribute('aria-expanded', 'true');
    syncLabels();
    applyGeo();
    render();
    probeHealth();
    input.focus();
  }
  function closePanel() {
    panel.hidden = true;
    fab.setAttribute('aria-expanded', 'false');
  }

  function probeHealth() {
    if (healthDone) return;
    healthDone = true;
    foot.textContent = t('booting');
    /* 团队门户（2026-10-30 加）：探活也要带会话，否则远端用户看到的是
       「服务未就绪」而不是真实状态。401 时换一次会话再试一次。
       ⚠️ 这是 GET，幂等，重试安全。 */
    var SESSION = window.OLBR_SESSION || null;
    var healthRaw = function () {
      return fetch(API + '/health', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    };
    var healthFetch = SESSION
      ? healthRaw().then(function (r) {
          if (r.status !== 401) return r;
          return SESSION.ensure(true).then(function (res) {
            return res.ok ? healthRaw() : r;
          });
        })
      : healthRaw();
    healthFetch
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.healthy && j.detail) {
          var chunks = j.detail.indexChunks;
          foot.textContent = t('booted').replace('12xx', chunks ? String(chunks) : '');
        } else {
          foot.textContent = t('notReady');
        }
      })
      .catch(function () { foot.textContent = t('notReady'); });
  }

  function syncLabels() {
    fab.title = t('fab');
    fab.setAttribute('aria-label', t('fab'));
    var title = document.getElementById('qaTitle');
    var sub = document.getElementById('qaSub');
    if (title) title.textContent = t('title');
    if (sub) sub.textContent = t('sub');
    var headEl = panel ? panel.querySelector('.qa-head') : null;
    if (headEl) headEl.title = t('dragTip');
    if (clearBtn) { clearBtn.title = t('clear'); clearBtn.setAttribute('aria-label', t('clear')); }
    if (closeBtn) { closeBtn.title = t('close'); closeBtn.setAttribute('aria-label', t('close')); }
    if (sendBtn) { sendBtn.title = t('send'); sendBtn.setAttribute('aria-label', t('send')); }
    if (input) input.placeholder = t('placeholder');
    var wt = document.getElementById('qaWelcomeTitle');
    var wb = document.getElementById('qaWelcomeBody');
    if (wt) wt.textContent = t('welcomeTitle');
    if (wb) wb.textContent = t('welcomeBody');
    var chips = document.getElementById('qaChips');
    if (chips) {
      chips.innerHTML = '';
      t('chips').forEach(function (q) {
        var c = el('button', 'qa-chip', q);
        c.type = 'button';
        c.addEventListener('click', function () { ask(q); });
        chips.appendChild(c);
      });
    }
    render();
  }

  function build() {
    fab = el('button', 'qa-fab');
    fab.type = 'button';
    fab.id = 'qaFab';
    fab.hidden = true;
    fab.setAttribute('aria-expanded', 'false');
    fab.setAttribute('aria-controls', 'qaPanel');
    /* 3D 机器人徽章（2026-10-28 换）：素材自带透明 alpha，**不带背景**。
       生成过程见 scripts/make_qa_badge.py（裁掉四周留白 + 预乘 alpha 缩放，
       避免缩到 112px 后边缘出现一圈灰黑描边）。 */
    fab.innerHTML = '<img src="assets/logo-qa-badge-112.png" srcset="assets/logo-qa-badge-112.png 2x, assets/logo-qa-badge-168.png 3x" alt="" draggable="false">';

    panel = el('section', 'qa-panel');
    panel.id = 'qaPanel';
    panel.hidden = true;
    panel.setAttribute('aria-live', 'polite');
    panel.innerHTML =
      '<header class="qa-head">' +
        '<span class="qa-avatar"><img src="assets/logo-qa-badge-112.png" srcset="assets/logo-qa-badge-112.png 2x, assets/logo-qa-badge-168.png 3x" alt="" draggable="false"></span>' +
        '<div class="qa-head-txt"><strong id="qaTitle"></strong><small id="qaSub"></small></div>' +
        '<button type="button" class="qa-icon-btn" id="qaClear"><i class="ph ph-trash" aria-hidden="true"></i></button>' +
        '<button type="button" class="qa-icon-btn" id="qaClose"><i class="ph ph-x" aria-hidden="true"></i></button>' +
      '</header>' +
      '<div class="qa-body">' +
        '<div class="qa-welcome" id="qaWelcome">' +
          '<b id="qaWelcomeTitle"></b>' +
          '<div id="qaWelcomeBody" style="margin-top:4px"></div>' +
          '<div class="qa-chips" id="qaChips"></div>' +
        '</div>' +
        '<div id="qaMsgs"></div>' +
      '</div>' +
      '<form class="qa-form">' +
        '<textarea class="qa-input" id="qaInput" rows="1" maxlength="' + MAX_Q + '"></textarea>' +
        '<button type="submit" class="qa-send" id="qaSend"><i class="ph ph-paper-plane-tilt" aria-hidden="true"></i></button>' +
      '</form>' +
      '<div class="qa-foot" id="qaFoot"></div>';

    document.body.appendChild(panel);
    document.body.appendChild(fab);

    body = panel.querySelector('.qa-body');
    list = document.getElementById('qaMsgs');
    welcome = document.getElementById('qaWelcome');
    input = document.getElementById('qaInput');
    sendBtn = document.getElementById('qaSend');
    clearBtn = document.getElementById('qaClear');
    closeBtn = document.getElementById('qaClose');
    foot = document.getElementById('qaFoot');

    fab.addEventListener('click', function () {
      if (panel.hidden) openPanel(); else closePanel();
    });
    closeBtn.addEventListener('click', closePanel);

    clearBtn.addEventListener('click', function () {
      if (!msgs.length) return;
      if (!window.confirm(t('confirmClear'))) return;
      msgs = [];
      saveMsgs();
      render();
      foot.textContent = t('cleared');
      api('/session/clear', { clientId: clientId() }).catch(function () { /* 清空失败不打扰 */ });
    });

    panel.querySelector('.qa-form').addEventListener('submit', function (e) {
      e.preventDefault();
      ask(input.value);
    });
    input.addEventListener('input', autosize);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        ask(input.value);
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !panel.hidden) closePanel();
    });

    wireDragResize();
    syncLabels();
  }

  /* ── 标题栏拖动 + 右下角缩放 ──────────────────────────────────────────
   * 拖动：按住 .qa-head（按钮除外）→ 按 right/bottom 改位置，面板贴着
   *   视口走，松手落盘。FAB 保持在右下原处不动。
   * 缩放：按住 .qa-resize → 按 width/height 改尺寸，有最小最大值。
   * 统一用 Pointer Events + setPointerCapture：指针滑出面板仍能收到
   *   move/up，触屏也可用；窄屏抽屉模式直接不绑。 */
  function wireDragResize() {
    var head = panel.querySelector('.qa-head');
    var grip = el('span', 'qa-resize');
    grip.setAttribute('aria-hidden', 'true');
    panel.appendChild(grip);

    var act = null; /* { kind:'move'|'size', pointerId, x, y, left, top, w, h } */

    function start(e, kind) {
      if (isNarrow() || panel.hidden) return;
      var r = panel.getBoundingClientRect();
      act = {
        kind: kind, pointerId: e.pointerId, x: e.clientX, y: e.clientY,
        left: r.left, top: r.top,
        w: r.width, h: r.height
      };
      panel.classList.add('is-drag');
      if (kind === 'move') head.classList.add('is-drag');
      e.currentTarget.setPointerCapture(e.pointerId);
      e.preventDefault();
    }
    function onMove(e) {
      if (!act || act.pointerId !== e.pointerId) return;
      if (act.kind === 'move') {
        var r = panel.getBoundingClientRect();
        var left = Math.min(window.innerWidth - r.width - 12, Math.max(12, act.left + e.clientX - act.x));
        var top = Math.min(window.innerHeight - r.height - 12, Math.max(12, act.top + e.clientY - act.y));
        panel.style.right = (window.innerWidth - left - r.width) + 'px';
        panel.style.bottom = (window.innerHeight - top - r.height) + 'px';
      } else {
        var maxW = Math.max(GEO_W_MIN, Math.min(GEO_W_MAX, window.innerWidth - act.left - 12));
        var maxH = Math.max(180, Math.min(GEO_H_MAX, window.innerHeight - act.top - 12));
        var minW = Math.min(GEO_W_MIN, maxW);
        var minH = Math.min(GEO_H_MIN, maxH);
        var nw = Math.min(maxW, Math.max(minW, act.w + e.clientX - act.x));
        var nh = Math.min(maxH, Math.max(minH, act.h + e.clientY - act.y));
        panel.style.width = nw + 'px';
        panel.style.height = nh + 'px';
        panel.style.right = (window.innerWidth - act.left - nw) + 'px';
        panel.style.bottom = (window.innerHeight - act.top - nh) + 'px';
      }
    }
    function onUp(e) {
      if (!act || (e && act.pointerId !== e.pointerId)) return;
      act = null;
      panel.classList.remove('is-drag');
      head.classList.remove('is-drag');
      var r = panel.getBoundingClientRect();
      geo = {
        right: Math.round(window.innerWidth - r.right),
        bottom: Math.round(window.innerHeight - r.bottom),
        width: Math.round(r.width),
        height: Math.round(r.height)
      };
      saveGeo();
    }

    /* 点按钮/链接不算拖动：e.target 在 .qa-icon-btn 里就放行给点击 */
    head.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      if (e.target.closest && e.target.closest('.qa-icon-btn')) return;
      start(e, 'move');
    });
    grip.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      start(e, 'size');
    });
    head.addEventListener('pointermove', onMove);
    grip.addEventListener('pointermove', onMove);
    head.addEventListener('pointerup', onUp);
    grip.addEventListener('pointerup', onUp);
    head.addEventListener('pointercancel', onUp);
    grip.addEventListener('pointercancel', onUp);
    /* 双击标题栏空白复位（按钮上双击不触发） */
    head.addEventListener('dblclick', function (e) {
      if (e.target.closest && e.target.closest('.qa-icon-btn')) return;
      resetGeo();
    });
    window.addEventListener('resize', function () {
      if (act) onUp();
      applyGeo();
    });
  }

  /* 登录门打开时隐藏挂件：未登录的访客不该能问内部工单/站点数据 */
  function syncVisibility() {
    var gate = document.getElementById('gate');
    var gateOpen = !!(gate && !gate.hasAttribute('hidden'));
    /* 团队门户作用域（2026-10-29 加）：Excel 的 Knowledge Q&A 域里「Quick Q&A」
       这一行决定右下角这个挂件要不要出现。
       ⚠️ SCOPE 为 null 时（上游 /v3/olbrportal/ 那份共用文件）行为与改动前完全一致。 */
    var scope = window.OLBR_SCOPE || null;
    var allowed = !scope || scope.ok('qa', 'assistant');
    fab.hidden = gateOpen || !allowed;
    if (gateOpen || !allowed) closePanel();
  }

  function observe() {
    var gate = document.getElementById('gate');
    if (gate && window.MutationObserver) {
      new MutationObserver(syncVisibility).observe(gate, { attributes: true, attributeFilter: ['hidden'] });
    }
    if (window.MutationObserver) {
      new MutationObserver(syncLabels).observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    }
    syncVisibility();
  }

  function start() {
    build();
    loadMsgs();
    render();
    observe();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();

