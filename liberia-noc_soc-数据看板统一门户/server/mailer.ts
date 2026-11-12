import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { IncomingMessage } from 'node:http';
import dotenv from 'dotenv';
import nodemailer from 'nodemailer';
import type { Transporter } from 'nodemailer';
import { APP_BASE } from './portalDefault';

// ============================================================================
// 门户邮件通道（自助找回密码用）—— SMTP 配置与发送
// ----------------------------------------------------------------------------
// 为什么门户要自己有一份发信实现，而不复用 my_app 的 email_notifier.py：
//   那是 Python（smtplib），门户后端是 Node；且工作区约定「my_app 的引用不外放」。
//   跨语言 subprocess 调它会把门户耦合到 my_app 的运行环境，故这里用 Node 生态
//   成熟的 nodemailer 独立实现，凭据走门户自己的 .env（与 my_app 互不依赖）。
//
// 安全边界（务必遵守）：
//   · SMTP 账号/授权码只放 .env / .env.local（已 .gitignore），**绝不硬编码、绝不入库**；
//   · 重置 token 与重置链接**绝不写日志**（下面 catch 只打印通用失败原因，不带 URL）；
//   · 未配置 SMTP 时 isMailConfigured()=false，找回密码端点回统一提示「联系管理员」，
//     功能默认关闭，配好凭据后无需改代码即自动启用。
//
// 配置项（键名可公开，值敏感）：
//   PORTAL_SMTP_HOST / PORTAL_SMTP_PORT / PORTAL_SMTP_SECURE
//   PORTAL_SMTP_USER / PORTAL_SMTP_PASS / PORTAL_SMTP_FROM（可选，默认同 USER）
//   PORTAL_PUBLIC_URL —— 门户对外完整基址（含 /uniplam），用于拼重置链接；
//                        缺省时回退按请求 Host 头推导（经 nginx 时通常可用）。
// ============================================================================

// 加载门户自己的 .env.local / .env（前者优先）。dev（vite）与 prod（tsx server/index.ts）
// 都经 routes.ts 引入本模块，故两侧都能拿到 SMTP 配置；文件不存在时 dotenv 静默跳过。
const PORTAL_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
dotenv.config({ path: [path.join(PORTAL_ROOT, '.env.local'), path.join(PORTAL_ROOT, '.env')] });

function env(key: string): string {
  return String(process.env[key] ?? '').trim();
}

/** SMTP 是否已配置（HOST + USER + PASS 三者齐全才算可用） */
export function isMailConfigured(): boolean {
  return !!(env('PORTAL_SMTP_HOST') && env('PORTAL_SMTP_USER') && env('PORTAL_SMTP_PASS'));
}

/**
 * 拼重置链接。token 走 URL **fragment**（#reset=…）而非查询串：
 * fragment 不随请求发到服务端，也不进 Referer，因此 nginx/门户访问日志里不会留下 token。
 *
 * APP_BASE 只在函数体内（请求时）读取 —— 本模块与 portalDefault 经 auth 形成引用环，
 * 但环上都是「函数体内使用」，模块求值阶段不触碰该绑定，故无 TDZ 风险（已核启动顺序）。
 */
export function buildResetUrl(req: IncomingMessage, token: string): string {
  const configured = env('PORTAL_PUBLIC_URL').replace(/\/+$/, '');
  let base: string;
  if (configured) {
    base = configured;
  } else {
    const proto = String(req.headers['x-forwarded-proto'] || 'http').split(',')[0].trim() || 'http';
    const host = String(req.headers.host || 'localhost').trim();
    base = `${proto}://${host}${APP_BASE.replace(/\/+$/, '')}`;
  }
  return `${base}/#reset=${encodeURIComponent(token)}`;
}

let transporter: Transporter | null = null;

function getTransporter(): Transporter {
  if (transporter) return transporter;
  const port = Number(env('PORTAL_SMTP_PORT') || 465);
  // 465 默认implicit TLS；显式 PORTAL_SMTP_SECURE 可覆盖（如 587 STARTTLS 填 false）
  const secureRaw = env('PORTAL_SMTP_SECURE').toLowerCase();
  const secure = secureRaw ? ['1', 'true', 'yes', 'on'].includes(secureRaw) : port === 465;
  transporter = nodemailer.createTransport({
    host: env('PORTAL_SMTP_HOST'),
    port,
    secure,
    auth: { user: env('PORTAL_SMTP_USER'), pass: env('PORTAL_SMTP_PASS') },
  });
  return transporter;
}

/**
 * 发送找回密码邮件。失败时抛错（调用方捕获并记日志，但对用户仍回统一响应，不泄露发送成败）。
 * ⚠️ 日志/异常里绝不带 resetUrl 或 token。
 */
export async function sendPasswordResetEmail(
  to: string,
  resetUrl: string,
  username: string
): Promise<void> {
  const from = env('PORTAL_SMTP_FROM') || env('PORTAL_SMTP_USER');
  const subject = '统一门户 · 找回密码';
  const text = [
    `您好，${username}：`,
    '',
    '我们收到了找回您统一门户账号密码的请求。',
    '请在 30 分钟内打开下面的链接设置新密码（链接一次性有效，用过或过期即失效）：',
    '',
    resetUrl,
    '',
    '如果这不是您本人的操作，请忽略本邮件，您的密码不会改变。',
    '',
    '—— Liberia NOC/SOC 数据看板统一门户',
  ].join('\n');
  await getTransporter().sendMail({ from, to, subject, text });
}