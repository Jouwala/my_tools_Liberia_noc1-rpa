/**
 * 索引新鲜度检测 —— 回答「磁盘上的 knowledge/ 与进程内存里的索引一致吗」。
 *
 * ## 为什么必须有
 *
 * 索引是**进程启动时一次性读进内存**的（`src/index.js` 的 `loadIndex()`），
 * 之后无论 `data/index.json` 怎么更新，跑着的进程都还在用旧快照。
 * 2026-09-15 踩过这个坑：索引 15:22 就重建好了，但进程是 14:42 起的，
 * 群里提问一直按旧的占位内容检索，表现是「资料明明放进去了，机器人还说没有依据」。
 *
 * 更近的一次：`knowledge/08_级别缺失与排查.md` 已经在磁盘上，
 * 但索引 `meta.sources` 里**没有它** —— 于是现场高频问「为什么没有级别」
 * 仍答「资料没有」。README 已写：检索调参救不了没有的内容。
 *
 * ## 为什么不 exit(1)
 *
 * 与 Ollama 自检同一取舍（2026-10-01 停机 29 小时事故的教训）：
 * 「索引过期」只影响**问答质量**，不影响收发消息与 ping/help。
 * 一个旁路问题不该让整条链路起不来 —— 只打警告，交给 ping 暴露。
 *
 * ## 判据为什么用 size+mtime 而不是正文哈希
 *
 * 目标是发现「加了文件 / 重导出了规则」，size+mtime 足够且廉价
 * （816 块语料的正文哈希没必要每次都算）。
 *
 * 本模块不读 CONFIG、不写盘（只读文件系统），便于离线单测。
 */
import { readdirSync, statSync, existsSync, readFileSync } from 'node:fs';
import { join, extname, relative } from 'node:path';
import { createHash } from 'node:crypto';

/** 与 ingest.js 保持一致的扩展名白名单。 */
const EXTS = new Set(['.md', '.markdown', '.txt', '.text']);

/**
 * 扫描知识库目录，返回每个文件的相对路径 + size + mtime（毫秒）。
 *
 * @param {string} dir 知识库根目录绝对路径
 * @param {string} root 用于计算相对路径的项目根（默认与 dir 相同）
 * @returns {Array<{rel:string,size:number,mtimeMs:number}>}
 */
export function scanKnowledge(dir, root = dir) {
  const out = [];
  if (!existsSync(dir)) return out;
  const walk = (d) => {
    for (const name of readdirSync(d)) {
      if (name.startsWith('.')) continue;
      const full = join(d, name);
      const st = statSync(full);
      if (st.isDirectory()) walk(full);
      else if (EXTS.has(extname(name).toLowerCase())) {
        out.push({
          rel: relative(root, full).replace(/\\/g, '/'),
          size: st.size,
          mtimeMs: st.mtimeMs,
        });
      }
    }
  };
  walk(dir);
  return out;
}

/**
 * 对比索引 meta 与磁盘实际文件集合。
 *
 * meta 兼容两种历史形态：
 *   · 新：`meta.knowledgeFiles = [{rel,size,mtimeMs}]`（本轮 ingest 写入）
 *   · 旧：只有 `meta.sources = [rel,...]`（没有 size/mtime）——
 *         此时只能比较**集合**，无法判断「同文件被改过」。
 *
 * @param {object} meta   index.meta（可能为 undefined）
 * @param {Array<{rel,size,mtimeMs}>} scan scanKnowledge() 的结果
 * @returns {{ok:boolean, missingInIndex:string[], extraInIndex:string[],
 *            newerOnDisk:string[], unknownMtime:boolean}}
 *   - `missingInIndex` 磁盘有、索引没有（**最常见**：新加的 08_）
 *   - `extraInIndex`   索引有、磁盘没有（文件被删/改名）
 *   - `newerOnDisk`    同名但磁盘 mtime 比索引记录的更新（文件被改过）
 *   - `unknownMtime`   meta 里没有 mtime 信息，无法判断内容是否变过
 */
export function diffIndex(meta, scan) {
  const indexed = Array.isArray(meta?.knowledgeFiles) ? meta.knowledgeFiles : [];
  const indexedByRel = new Map(indexed.map((f) => [f.rel, f]));
  // scan 允许为 null/undefined（扫盘失败时调用方会传 null）——
  // 本身不抛异常是硬要求：索引过期是质量问题，不能连累调用方。
  const files = Array.isArray(scan) ? scan : [];

  // 旧索引只有 sources 数组 —— 退化到「只比集合」
  const fallbackRels = Array.isArray(meta?.sources) ? meta.sources : null;
  const indexedRels = fallbackRels || indexed.map((f) => f.rel);
  const indexedRelSet = new Set(indexedRels);
  const unknownMtime = !meta?.knowledgeFiles;

  const missingInIndex = files.filter((f) => !indexedRelSet.has(f.rel)).map((f) => f.rel);
  const scanRelSet = new Set(files.map((f) => f.rel));
  const extraInIndex = indexedRels.filter((rel) => !scanRelSet.has(rel));

  const newerOnDisk = [];
  if (!unknownMtime) {
    for (const f of files) {
      const idx = indexedByRel.get(f.rel);
      // mtime 比索引记录晚 → 这个文件在索引构建之后被改过
      if (idx && Number.isFinite(idx.mtimeMs) && f.mtimeMs > idx.mtimeMs + 1) {
        newerOnDisk.push(f.rel);
      }
    }
  }

  const ok = missingInIndex.length === 0 && extraInIndex.length === 0 && newerOnDisk.length === 0;
  return { ok, missingInIndex, extraInIndex, newerOnDisk, unknownMtime };
}

/**
 * 知识库**正文**指纹：按相对路径排序后，把每个文件的 sha256 串起来再哈希。
 *
 * 用途与「size+mtime」的区别（2026-11-16 复盘）：
 * `sync-kb.mjs` 过去把「四份规则 xlsx 的 size+mtime」当指纹，可规则采集**每天
 * 04:20 都会重写** `eflow_TT_rules.xlsx`，mtime 必变 —— 于是每天都被判成
 * 「规则更新了」，白算 6001 条向量（约 4 分钟）并重启一次 bot。实测
 * 2026-11-15→11-16 的 5 份导出文档里有 4 份 size 完全相同、正文也没变。
 * 正文哈希只认内容：mtime 变了但正文没变 → 指纹不变 → 跳过重建。
 *
 * 目录里有文件读不了时**抛异常**（不静默跳过）：拿不到完整正文就不能断言
 * 「没变化」，宁可让调用方报错、下一轮重试。
 *
 * @param {Array<{rel:string}>} files scanKnowledge() 的结果
 * @param {string} root 读取文件用的根目录
 * @returns {string} 64 位十六进制摘要
 */
export function hashKnowledge(files, root) {
  const h = createHash('sha256');
  for (const f of [...(files || [])].sort((a, b) => a.rel.localeCompare(b.rel))) {
    const buf = readFileSync(join(root, f.rel));
    h.update(f.rel);
    h.update('\0');
    h.update(createHash('sha256').update(buf).digest('hex'));
    h.update('\0');
  }
  return h.digest('hex');
}

/**
 * 生成给人看的一行/多行警告（ping 与启动日志共用）。
 * 索引新鲜（ok=true）时返回 null —— 调用方据此决定要不要打这一段。
 *
 * @param {{ok,missingInIndex,extraInIndex,newerOnDisk,unknownMtime}} diff
 * @returns {string|null}
 */
export function freshnessWarning(diff) {
  if (!diff || diff.ok) return null;
  const bits = [];
  if (diff.missingInIndex.length) {
    bits.push(`未入库 ${diff.missingInIndex.join('、')}`);
  }
  if (diff.extraInIndex.length) {
    bits.push(`索引里有但磁盘已无 ${diff.extraInIndex.join('、')}`);
  }
  if (diff.newerOnDisk.length) {
    bits.push(`内容比索引新 ${diff.newerOnDisk.join('、')}`);
  }
  return `⚠️ 磁盘知识比索引新：${bits.join('；')} —— 请 npm run ingest 后重启进程`;
}
