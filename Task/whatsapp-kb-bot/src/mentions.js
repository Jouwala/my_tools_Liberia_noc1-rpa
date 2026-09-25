/**
 * @提及识别与消息解析 —— 纯函数，无外部依赖，可独立测试。
 *
 * 单独成模块的原因：这是路由的核心，出错会导致机器人「听不见」或「乱插话」，
 * 但真实 WhatsApp 连接无法在测试里复现，所以必须能脱离网络单测。
 */
import { jidNormalizedUser } from 'baileys';

/**
 * 收集机器人自身的多种标识形式。
 * WhatsApp 群里的提及可能是手机号 JID（xxx@s.whatsapp.net），
 * 也可能是 LID（xxx@lid），且自身 id 可能带设备后缀（xxx:5@s.whatsapp.net），
 * 所以必须把两种形式都收进来再比对。
 *
 * @param sock      Baileys socket
 * @param credsMe   state.creds.me —— 凭据里的自身信息
 *
 * 为什么两个来源都要：实测换号后 `sock.user.lid` 为空，但 `creds.me.lid`
 * 有值（如 `91019685171349:1@lid`）。只读 sock.user 会导致群里用 LID 形式
 * @机器人时完全识别不到，且日志只显示「未匹配」，极难定位。
 * 凭据比 socket 上的字段更可靠，必须一并收集。
 */
export function selfIdentifiers(sock, credsMe = null) {
  const ids = new Set();
  for (const jid of [sock?.user?.id, sock?.user?.lid, credsMe?.id, credsMe?.lid]) {
    if (!jid) continue;
    ids.add(jidNormalizedUser(jid));
    ids.add(String(jid).split('@')[0].split(':')[0]);
  }
  return ids;
}

/** 归一化任意 JID 为两种可比对形式：[完整JID, 纯号码] */
export function jidForms(jid) {
  const s = String(jid || '');
  return [jidNormalizedUser(s), s.split('@')[0].split(':')[0]];
}

/** 从各类消息结构中抽取纯文本 */
export function extractText(message) {
  if (!message) return '';
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    message.documentMessage?.caption ||
    message.buttonsResponseMessage?.selectedDisplayText ||
    message.listResponseMessage?.title ||
    message.templateButtonReplyMessage?.selectedDisplayText ||
    ''
  );
}

/**
 * 判断该消息是否应触发机器人。
 * @param message    msg.message
 * @param selfIds    selfIdentifiers() 的结果
 * @param botMessageIds 机器人已发出消息的 id 集合（用于识别"引用回复机器人"）
 * @returns {{triggered: boolean, via: 'mention'|'reply'|null}}
 */
export function detectTrigger(message, selfIds, botMessageIds = new Set()) {
  const ctx = message?.extendedTextMessage?.contextInfo || message?.imageMessage?.contextInfo;

  const mentioned = ctx?.mentionedJid || [];
  if (mentioned.some((j) => jidForms(j).some((f) => selfIds.has(f)))) {
    return { triggered: true, via: 'mention' };
  }

  const quotedId = ctx?.stanzaId;
  if (quotedId && botMessageIds.has(quotedId)) {
    return { triggered: true, via: 'reply' };
  }

  return { triggered: false, via: null };
}

/**
 * 去掉正文里的 @标记，得到真正的问题。
 * WhatsApp 正文里的提及通常写成 @手机号，但也可能出现完整 JID 或 LID 形式，
 * 例如 @8613800138000@c.us、@99887766@lid，需要一并清掉，否则会污染问题文本。
 */
export function stripMentions(text) {
  return String(text || '')
    .replace(/@\d{5,}(?:@[a-z.]+)?/gi, '') // @手机号 / @手机号@域名
    .replace(/@[a-z0-9.\-_]+@(?:lid|c\.us|s\.whatsapp\.net|g\.us)/gi, '') // @标识@lid 等
    .replace(/\s+/g, ' ')
    .trim();
}

/** 该会话是否允许响应 */
export function isAllowedChat({ chatJid, isGroup, allowGroups, replyMode }) {
  if (!isGroup && replyMode === 'group') return false;
  if (isGroup && !allowGroups.includes('*') && !allowGroups.includes(chatJid)) return false;
  return true;
}
