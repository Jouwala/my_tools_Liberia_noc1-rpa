/**
 * TT 单分析 —— 调用 my_app 的工单库做实时级别核查。
 *
 * 与 RAG 的分工很明确：
 *   知识库（RAG）回答「规则是什么」——静态知识，向量检索就够；
 *   这里回答「这一单现在什么情况」——必须实时查库，所以走独立通道。
 *
 * 实现方式：Node 起子进程跑 scripts/tt-analyze.py。
 * 之所以不用 my_app 的 HTTP 接口：那要求 my_app 服务在跑，
 * 而子进程方式只依赖「工单库文件可读」，机器人独立可用。
 */
import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { ROOT } from './config.js';

const SCRIPT = resolve(ROOT, 'scripts', 'tt-analyze.py');

// my_app 的后端运行环境（含 sqlite3 + openpyxl）
const PYTHON =
  process.env.TT_PYTHON ||
  'C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe';

// 超时按**最坏情况**给，不是按常规查询。
// 常规查询走本地索引约 1.3 秒；但索引失效时（工单库被整体重排）要整表重建，
// 而全表扫描在 Y 盘上波动极大 —— 实测同一台机器上从 11 秒到 **100 秒**都出现过
// （`SELECT count(*) FROM eflow_tt` 实测 100.0s）。
// 原先的 90 秒会正好卡在这个区间里，让「重建」变成「超时」。
const TIMEOUT_MS = Number(process.env.TT_TIMEOUT_MS || 180000);

/** TT 单号形态：TT + 至少 6 位数字（实测形如 TT202609150073） */
const TT_RE = /\bTT\d{6,}\b/i;

/** 从问题里抽出 TT 单号；没有则返回 null */
export function extractTtNo(text) {
  const m = String(text || '').match(TT_RE);
  return m ? m[0].toUpperCase() : null;
}

/** 环境是否具备 TT 分析条件（脚本 + Python 解释器都在） */
export function ttAvailable() {
  return existsSync(SCRIPT) && existsSync(PYTHON);
}

/**
 * 失败文案（超时 / 出错 / 空结果）。
 *
 * TT 通道不过模型，这几句是脚本之外、由 Node 侧直接发出的兜底 ——
 * 写死中文的话，英文提问遇到超时或异常会收到一句中文报错。
 * 之所以不放进脚本：这些情况发生在**脚本没能正常返回**的时候，
 * 此时只能由调用方兜底。
 */
const FAIL_TEXT = {
  zh: {
    timeout: (tt, s) =>
      `分析 ${tt} 超时（${s}s）。工单库在 Y 盘（网络盘），首次查询要建本地单号索引，` +
      `可能偏慢；稍后再试通常会快很多。`,
    error: (tt, detail) => `分析 ${tt} 时出错了：${detail}`,
    empty: (tt) => `分析 ${tt} 没有返回结果。`,
    unknown: '未知错误',
  },
  en: {
    timeout: (tt, s) =>
      `Analyzing ${tt} timed out (${s}s). The ticket DB sits on a network drive (Y:); ` +
      `the first query builds a local index and can be slow — retrying usually works much faster.`,
    error: (tt, detail) => `Something went wrong while analyzing ${tt}: ${detail}`,
    empty: (tt) => `Analyzing ${tt} returned no result.`,
    unknown: 'unknown error',
  },
};

/**
 * 分析一个 TT 单。
 *
 * 刻意**永不抛异常** —— 这是在群里回复用户，
 * 子进程失败也必须给出一句人话，不能静默或抛栈。
 *
 * @param {string} ttNo
 * @param {{lang?: 'zh'|'en'}} [opts] 回复语言（按提问语言判定，见 lang.js）
 */
export function analyzeTt(ttNo, { lang = 'zh' } = {}) {
  // 只放行脚本认得的取值，避免上游传错让 argparse 直接退出（exit 2）
  const replyLang = lang === 'en' ? 'en' : 'zh';
  const F = FAIL_TEXT[replyLang];
  return new Promise((resolvePromise) => {
    execFile(
      PYTHON,
      [SCRIPT, ttNo, '--lang', replyLang],
      {
        timeout: TIMEOUT_MS,
        encoding: 'utf8',
        windowsHide: true,
        maxBuffer: 4 * 1024 * 1024,
        // 必须显式指定，不能靠继承环境。
        // 机器人是从 Windows 启动的，环境里没有 LANG，于是 Python 的 stdout
        // 退化成系统代码页（本机实测 cp1252），脚本一 print 中文就抛
        //   UnicodeEncodeError: 'charmap' codec can't encode characters ...
        // 在 Git Bash 里手跑却没事（有 LANG）—— 这正是当初没发现的原因。
        // 配合脚本里的 reconfigure 双保险。
        env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
      },
      (err, stdout, stderr) => {
        const out = (stdout || '').trim();

        if (err) {
          const timedOut = err.killed || /timed out/i.test(err.message || '');
          if (timedOut) {
            resolvePromise({ ok: false, text: F.timeout(ttNo, TIMEOUT_MS / 1000) });
            return;
          }

          // 「查无此单」不是程序故障：脚本按约定以退出码 1 表示未找到，
          // 但 stdout 里已经写好了一句给用户看的话，直接用，别报「命令失败」。
          // 只有 stdout 为空（退出码 2/3）才是真出错。
          if (out) {
            resolvePromise({ ok: false, text: out });
            return;
          }

          const raw = (stderr || err.message || '').trim();
          const lines = raw.split('\n').map((s) => s.trim()).filter(Boolean);
          // Python 的 traceback 第一行永远是 "Traceback (most recent call last):"，
          // 照抄下来等于没信息。真正有用的异常类型和消息在**最后一行**。
          const detail = lines[lines.length - 1] || F.unknown;
          resolvePromise({ ok: false, text: F.error(ttNo, detail) });
          return;
        }

        if (!out) {
          resolvePromise({ ok: false, text: F.empty(ttNo) });
          return;
        }
        resolvePromise({ ok: true, text: out });
      }
    );
  });
}
