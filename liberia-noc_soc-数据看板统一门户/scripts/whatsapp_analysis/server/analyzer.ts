// 分析器：把扩展抓取的 ScanResult 变成结构化任务。
// 两条路径：①配置了 AI -> LLM 提取；②未配置/失败 -> 本地规则降级提取（NOC 关键词）。
// 合并去重：同群 + 同站点（24h 内、未完成）的消息合并为一条任务，见 storage.upsertTask。
import type {
  AiTask,
  ContextImage,
  ContextMessage,
  MentionContext,
  ScanResult,
} from "./ai/types";
import { SYSTEM_PROMPT, buildUserPrompt, formatContextBlock } from "./ai/prompts";
import {
  messageKey,
  storeRawMessages,
  upsertTask,
  type Task,
  type TaskInput,
} from "./storage";

const MERGE_WINDOW_HOURS = 24;

const NOC_KEYWORDS = [
  "Site Down", "Power", "Transmission", "2G", "3G", "4G",
  "PM", "LBR", "UPBG", "Board Fail", "domain", "Third Party",
];

const URGENT_RE = /(site\s*down|down\s*due|urgent|asap|emergency|power\s*off|critical|中断|紧急|立即)/i;
const FOLLOWUP_RE = /(check|confirm|update|please|feedback|verify|follow|确认|检查|跟进|反馈)/i;

function extractSiteId(text: string): string {
  const m =
    text.match(/(?:site|station|站点)\s*[:：(（]?\s*(\d{2,5})/i) ||
    text.match(/\((\d{2,5})\)/) ||
    text.match(/\b(\d{3,5})\b/);
  return m ? m[1] : "";
}

function extractSiteName(text: string): string {
  const m = text.match(/([A-Za-z][A-Za-z0-9 ._-]{2,40}?)\s*[(（](\d{2,5})[)）]/);
  return m ? m[1].trim() : "";
}

// TT 工单号：TT1234567 / TT-1234567 / TT 1234567（规则降级路的兜底提取）
function extractTtId(text: string): string {
  const m = text.match(/\bTT[-_ ]?(\d{4,12})\b/i);
  return m ? `TT${m[1]}` : "";
}

// 告警名称：NOC 常见告警短语命中即返回（规则降级路的兜底提取）
const ALARM_PATTERNS = [
  /\bSite\s*Down\b/i,
  /\bBTS\s*Down\b/i,
  /\bCell\s*Down\b/i,
  /\bPower\s*(?:OFF|Failure|Fail)\b/i,
  /\bBoard\s*Fail(?:ure)?\b/i,
  /\bTransmission\s*Alarm/i,
  /\bRectifier\s*Fail/i,
  /\bSite\s*Outage\b/i,
  /\bVSWR\s*Alarm/i,
];

function extractAlarmName(text: string): string {
  for (const re of ALARM_PATTERNS) {
    const m = text.match(re);
    if (m) return m[0].trim();
  }
  return "";
}

function classify(text: string): "urgent" | "followup" | "fyi" {
  if (URGENT_RE.test(text)) return "urgent";
  if (FOLLOWUP_RE.test(text)) return "followup";
  return "fyi";
}

// 归一化：小写 + 去掉所有空白/标点/符号。AI 对同一消息两次改写（加句号、换大小写、
// 中英标点）时合并键保持一致，防止同一条事项生成重复任务
function normKey(s: string): string {
  return s.toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
}

function mergeKeyFor(siteId: string, siteName: string, issue: string): string {
  if (siteId) return `site:${normKey(siteId)}`;
  if (siteName) return `name:${normKey(siteName).slice(0, 60)}`;
  if (issue) return `issue:${normKey(issue).slice(0, 60)}`;
  return "";
}

// @我 消息没有时间戳时（频道/公告类消息没有 pre-plain-text），
// 用上下文里最近一条带时间戳的消息近似回填，保证 MessageTime 不空
function contextTime(ctx: MentionContext): string {
  const ms = ctx.messages;
  for (let i = ctx.mentionIndex; i >= 0; i--) {
    if (ms[i]?.timestamp) return ms[i].timestamp;
  }
  for (let i = ctx.mentionIndex + 1; i < ms.length; i++) {
    if (ms[i]?.timestamp) return ms[i].timestamp;
  }
  return "";
}

function heuristicTasks(
  groupName: string,
  selfName: string,
  contexts: MentionContext[]
): TaskInput[] {
  const out: TaskInput[] = [];
  for (const ctx of contexts) {
    const mentionMsg = ctx.messages[ctx.mentionIndex];
    if (!mentionMsg) continue;
    const allText = ctx.messages.map((m) => m.text).join(" \n ");
    const siteId = extractSiteId(allText);
    const siteName = extractSiteName(allText);
    const issueKw = NOC_KEYWORDS.filter((k) => allText.includes(k));
    out.push({
      merge_key: mergeKeyFor(siteId, siteName, issueKw.join(",")),
      group_name: groupName,
      requester: mentionMsg.sender,
      message_time: mentionMsg.timestamp || contextTime(ctx),
      site_name: siteName || null,
      site_id: siteId || null,
      tt_id: extractTtId(allText) || null,
      alarm_name: extractAlarmName(allText) || null,
      issue: issueKw.length ? issueKw.join(" / ") : null,
      action_required: mentionMsg.text,
      deadline: null,
      priority: classify(allText),
      source: "rules",
      raw_message_keys: ctx.messages.map((m) => messageKey(groupName, m)),
    });
  }
  void selfName;
  return out;
}

// AI 偶尔编造占位名（Unknown/未知/Anonymous…）：一律视为没有可靠请求人
const FAKE_REQUESTERS = /^(unknown|未知|匿名|anonymous|n\/?a|系统|system)$/i;

function aiTaskToInput(
  groupName: string,
  t: AiTask,
  requester: string,
  messageTime: string,
  rawKeys: string[]
): TaskInput {
  const aiRequester = (t.requester || "").trim();
  const safeRequester =
    aiRequester && !FAKE_REQUESTERS.test(aiRequester) ? aiRequester : requester || "";
  return {
    merge_key: mergeKeyFor(t.site_id || "", t.site_name || "", t.issue || ""),
    group_name: groupName,
    // Requester 只信服务器端片段里的 @我 消息发送人；AI 值仅在非占位词时作参考
    requester: safeRequester,
    // MessageTime 不信任 AI 抄写：优先用服务器端已知片段里 @我 消息的时间戳
    message_time: messageTime || t.message_time || null,
    site_name: t.site_name || null,
    site_id: t.site_id || null,
    tt_id: t.tt_id || null,
    alarm_name: t.alarm_name || null,
    issue: t.issue || null,
    action_required: t.action || null,
    deadline: t.deadline || null,
    priority: t.priority,
    source: "ai",
    raw_message_keys: rawKeys,
  };
}

export interface AnalyzeOutput {
  degraded: boolean;
  reason?: string;
  tasks: Task[];
  scanResult?: ScanResult;
}

export async function analyze(
  scan: ScanResult,
  ai: {
    configured: boolean;
    analyze: (
      s: string,
      u: string,
      images?: ContextImage[]
    ) => Promise<{ tasks: AiTask[] }>;
  }
): Promise<AnalyzeOutput> {
  const selfName = scan.selfName || process.env.SELF_NAME || "";
  const blocks: {
    groupName: string;
    block: string;
    rawKeys: string[];
    requester: string;
    messageTime: string;
    images: ContextImage[];
  }[] = [];
  const degradedInputs: TaskInput[] = [];
  let imageNo = 0; // 截图全局编号：与请求体里图片的拼接顺序一致，AI 才能对得上号

  for (const conv of scan.conversations) {
    storeRawMessages(
      conv.groupName,
      (conv.allMessages || []).map((m) => ({
        group_name: conv.groupName,
        sender: m.sender,
        timestamp: m.timestamp,
        text: m.text,
        is_from_me: !!m.isFromMe,
        mentioned_me: false,
      }))
    );
    for (const ctx of conv.mentionContexts) {
      const mentionMsg = ctx.messages[ctx.mentionIndex];
      const rawKeys = ctx.messages.map((m) => messageKey(conv.groupName, m));
      const images = (ctx.images || []).filter(
        (img) => img && typeof img.dataBase64 === "string" && img.dataBase64.length > 64
      );
      // 文本块里标记随附截图（全局连续编号），与请求体里的图片按序对应
      const blockText = formatContextBlock(
        conv.groupName,
        ctx.messages,
        ctx.mentionIndex
      );
      const startNo = imageNo + 1;
      imageNo += images.length;
      const marker = images.length
        ? images.length === 1
          ? `\n【截图 ${startNo}】`
          : `\n【截图 ${startNo}-${imageNo}】`
        : "";
      blocks.push({
        groupName: conv.groupName,
        block: blockText + marker,
        rawKeys,
        requester: mentionMsg ? mentionMsg.sender : "",
        messageTime:
          (mentionMsg ? mentionMsg.timestamp || "" : "") || contextTime(ctx),
        images,
      });
      degradedInputs.push(
        ...heuristicTasks(conv.groupName, selfName, [ctx])
      );
    }
  }

  if (!blocks.length) {
    return { degraded: !ai.configured, tasks: [], scanResult: undefined };
  }

  if (ai.configured) {
    try {
      const userPrompt = buildUserPrompt(
        selfName || "(未设置，@开头的提及视为@我)",
        blocks.map((b) => b.block)
      );
      const allImages = blocks.flatMap((b) => b.images);
      const result = await ai.analyze(SYSTEM_PROMPT, userPrompt, allImages);
      // 归属：AI 标了 block（"片段 2"）就用它；否则按站点/请求人匹配；再兜底第一个片段
      const blockFor = (t: AiTask) => {
        const m = (t.block || "").match(/片段\s*(\d+)/);
        if (m) {
          const idx = Number(m[1]) - 1;
          if (blocks[idx]) return blocks[idx];
        }
        return (
          blocks.find(
            (b) =>
              (t.site_id && b.block.includes(t.site_id)) ||
              (t.requester && b.block.includes(t.requester))
          ) || blocks[0]
        );
      };
      // 多个 AI 任务合并进同一个存储任务时，响应里只保留一条（最新合并结果），
      // 否则侧边栏会出现同 ID 的重复卡片
      const byId = new Map<number, Task>();
      for (const t of result.tasks) {
        const match = blockFor(t);
        const task = upsertTask(
          aiTaskToInput(
            match.groupName,
            t,
            match.requester,
            match.messageTime,
            match.rawKeys
          ),
          MERGE_WINDOW_HOURS
        );
        byId.set(task.id, task);
      }
      return { degraded: false, tasks: [...byId.values()] };
    } catch (e) {
      // AI 失败不阻塞：降级为规则提取
      const byId = new Map<number, Task>();
      for (const input of degradedInputs) {
        const task = upsertTask(input, MERGE_WINDOW_HOURS);
        byId.set(task.id, task);
      }
      return {
        degraded: true,
        reason: `AI 分析失败，已降级为规则提取：${e instanceof Error ? e.message : String(e)}`,
        tasks: [...byId.values()],
      };
    }
  }

  const byId = new Map<number, Task>();
  for (const input of degradedInputs) {
    const task = upsertTask(input, MERGE_WINDOW_HOURS);
    byId.set(task.id, task);
  }
  return {
    degraded: true,
    reason: "未配置 AI API（.env 中 AI_API_TYPE / AI_API_KEY），已使用本地规则提取。",
    tasks: [...byId.values()],
  };
}
