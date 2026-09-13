import fs from 'node:fs';
import path from 'node:path';

// ============================================================================
// 共享鉴权总开关（uniplam 门户侧）
// ----------------------------------------------------------------------------
// 目标：日常开发时让 /uniplam/ 与 /myapp/ 都跳过用户登录，且两个应用读的是
// **同一个开关**，不会出现「门户免登录、myapp 还要求登录」的错配。
//
// 真相源优先级（高 → 低）：
//   1. 环境变量 AUTH_ENABLED（1/true/on/yes = 开启鉴权；0/false/off/no = 关闭鉴权）
//   2. 共享开关文件 <仓库根>/auth-switch.json 的 authEnabled 字段
//   3. 缺省 = true（保持原有行为，安全默认）
//
// 生产保护：当 AUTH_SWITCH_ENV / NODE_ENV / APP_ENV 任一为 production/prod 时，
// 即使配了关闭也会被强制回「开启鉴权」并打印醒目告警，且**拒绝写入关闭状态**。
//
// 热生效：结论带 TTL 缓存（RELOAD_TTL_MS），页面上点开关后无需重启进程，
// 两侧都会在数秒内自动跟上。setAuthEnabled() 由门户接口调用（见 server/auth.ts）。
//
// 与 my_app 侧 backend/auth_switch.py 保持**完全一致的语义**，改一处请同步另一处。
//
// 安全边界：本模块只读写 auth-switch.json（外加一份滚动备份 .prev），
// 绝不触碰 auth-data/ 下的用户库（users / requests / sessions）。
// ============================================================================

/** 鉴权模式：enforced = 正常校验登录；bypass = 跳过登录（仅日常开发） */
export type AuthMode = 'enforced' | 'bypass';

export interface AuthSwitchState {
  /** 是否要求用户登录 */
  authEnabled: boolean;
  mode: AuthMode;
  /** 结论来源，便于排查「为什么现在是免登录」 */
  source: 'env' | 'file' | 'default' | 'guard';
  /** 共享开关文件路径 */
  flagFile: string;
  /** 生效的运行环境标识 */
  env: string;
  /** 生产保护触发时的说明 */
  reason?: string;
  /** 环境变量 AUTH_ENABLED 是否已接管（此时改文件不生效） */
  envOverride?: boolean;
  /** 最近一次改动时间（来自开关文件，便于追溯） */
  updatedAt?: string;
  /** 最近一次改动的操作者 */
  updatedBy?: string;
}

const TRUTHY = new Set(['1', 'true', 'yes', 'on', 'y', 't']);
const FALSY = new Set(['0', 'false', 'no', 'off', 'n', 'f']);
const PROD_ENVS = new Set(['production', 'prod']);

/** 结论缓存时长：页面上切换后，最迟这么多毫秒后两侧都会跟上 */
const RELOAD_TTL_MS = 3000;

/** 共享开关文件默认位置：<仓库根>/auth-switch.json（本文件位于 <门户>/server/） */
function defaultFlagFile(): string {
  const fromEnv = (process.env.AUTH_SWITCH_FILE || '').trim();
  if (fromEnv) return path.resolve(fromEnv);
  try {
    // vite 的配置加载器会注入 __dirname（vite.config.ts 已在用同一写法）
    return path.resolve(__dirname, '..', '..', 'auth-switch.json');
  } catch {
    // 纯 ESM 环境下 __dirname 不存在：退化为「门户目录的上一级」
    return path.resolve(process.cwd(), '..', 'auth-switch.json');
  }
}

/** 解析布尔配置；无法识别时返回 null（交给下一优先级） */
function parseBool(raw: string | undefined): boolean | null {
  const value = String(raw ?? '').trim().toLowerCase();
  if (!value) return null;
  if (TRUTHY.has(value)) return true;
  if (FALSY.has(value)) return false;
  return null;
}

function currentEnv(): string {
  const raw = process.env.AUTH_SWITCH_ENV || process.env.NODE_ENV || process.env.APP_ENV || '';
  return String(raw).trim().toLowerCase() || 'development';
}

interface FlagFileContent {
  enabled: boolean | null;
  updatedAt?: string;
  updatedBy?: string;
}

/** 读共享开关文件；不存在/损坏时 enabled 为 null（按缺省处理，不抛错打断启动） */
function readFlagFile(flagFile: string): FlagFileContent {
  try {
    if (!fs.existsSync(flagFile)) return { enabled: null };
    const parsed = JSON.parse(fs.readFileSync(flagFile, 'utf-8')) as {
      authEnabled?: unknown;
      updatedAt?: unknown;
      updatedBy?: unknown;
    };
    let enabled: boolean | null = null;
    if (typeof parsed?.authEnabled === 'boolean') enabled = parsed.authEnabled;
    else if (typeof parsed?.authEnabled === 'string') enabled = parseBool(parsed.authEnabled);
    return {
      enabled,
      updatedAt: typeof parsed?.updatedAt === 'string' ? parsed.updatedAt : undefined,
      updatedBy: typeof parsed?.updatedBy === 'string' ? parsed.updatedBy : undefined,
    };
  } catch (e) {
    console.warn(`[auth-switch] 开关文件解析失败，按「开启鉴权」处理: ${flagFile} (${String(e)})`);
    return { enabled: null };
  }
}

interface Cache {
  state: AuthSwitchState;
  at: number;
}

let cache: Cache | null = null;
/** 上一次已打印过的结论，用于避免每个请求都刷日志 */
let lastLogged: string | null = null;

/** 解析鉴权开关状态（带 TTL 缓存，切换后最迟 RELOAD_TTL_MS 生效） */
export function getAuthSwitch(): AuthSwitchState {
  const now = Date.now();
  if (cache && now - cache.at < RELOAD_TTL_MS) return cache.state;

  const flagFile = defaultFlagFile();
  const env = currentEnv();

  let authEnabled: boolean;
  let source: AuthSwitchState['source'];
  let updatedAt: string | undefined;
  let updatedBy: string | undefined;

  const fromEnv = parseBool(process.env.AUTH_ENABLED);
  if (fromEnv !== null) {
    authEnabled = fromEnv;
    source = 'env';
  } else {
    const fromFile = readFlagFile(flagFile);
    if (fromFile.enabled !== null) {
      authEnabled = fromFile.enabled;
      source = 'file';
    } else {
      authEnabled = true;
      source = 'default';
    }
    updatedAt = fromFile.updatedAt;
    updatedBy = fromFile.updatedBy;
  }

  let reason: string | undefined;
  if (!authEnabled && PROD_ENVS.has(env)) {
    authEnabled = true;
    source = 'guard';
    reason = `运行环境为 ${env}，已忽略「关闭鉴权」配置并强制开启`;
  }

  const state: AuthSwitchState = {
    authEnabled,
    mode: authEnabled ? 'enforced' : 'bypass',
    source,
    flagFile,
    env,
    reason,
    envOverride: fromEnv !== null,
    updatedAt,
    updatedBy,
  };

  cache = { state, at: now };

  // 结论变化时才打日志（正常请求不再刷屏）
  const fingerprint = `${authEnabled}|${env}|${source}`;
  if (fingerprint !== lastLogged) {
    lastLogged = fingerprint;
    const line = `[auth-switch] 鉴权${authEnabled ? '已开启' : '已关闭(免登录)'} | 环境=${env} 来源=${source} 开关文件=${flagFile}`;
    if (authEnabled) {
      console.warn(line);
    } else {
      console.warn(
        `${line}\n[auth-switch] 注意：当前 /uniplam/ 与 /myapp/ 均跳过用户登录，仅限日常开发使用。`
      );
    }
    if (reason) {
      console.error(`[auth-switch] 严重告警：${reason}。请检查 AUTH_ENABLED / ${flagFile}。`);
    }
  }

  return state;
}

/** 当前是否跳过用户登录（仅日常开发为 true） */
export function isAuthBypass(): boolean {
  return !getAuthSwitch().authEnabled;
}

export interface SetAuthEnabledResult {
  ok: boolean;
  state?: AuthSwitchState;
  /** 未生效/被拒的原因（给页面直接展示） */
  detail?: string;
}

/**
 * 写入开关文件（仅门户接口调用）。成功后会立刻刷新本进程缓存。
 *
 * 只做一件事：把 authEnabled 写进 auth-switch.json。
 * 写前把旧内容滚动备份为 auth-switch.json.prev，采用「临时文件 + 改名」原子写，
 * 因此**不会**影响 auth-data/ 里的用户、申请与登录会话。
 */
export function setAuthEnabled(enabled: boolean, operator?: string): SetAuthEnabledResult {
  const current = getAuthSwitch();
  const flagFile = current.flagFile;
  const env = currentEnv();

  // 生产保护：拒绝把生产环境切成免登录
  if (!enabled && PROD_ENVS.has(env)) {
    return { ok: false, detail: `运行环境为 ${env}，禁止关闭鉴权` };
  }
  // 环境变量接管时改文件没有意义：直接说明原因，避免「点了没反应」
  if (current.envOverride) {
    return {
      ok: false,
      detail: '环境变量 AUTH_ENABLED 已接管开关，改配置文件不生效；请移除该环境变量后重启进程',
    };
  }

  try {
    const dir = path.dirname(flagFile);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

    let payload: Record<string, unknown> = {};
    try {
      if (fs.existsSync(flagFile)) {
        const parsed = JSON.parse(fs.readFileSync(flagFile, 'utf-8')) as unknown;
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          payload = parsed as Record<string, unknown>;
        }
      }
    } catch {
      // 旧文件损坏：保留一份现场，然后用干净内容重建
      try {
        fs.copyFileSync(flagFile, `${flagFile}.broken_${Date.now()}`);
      } catch {
        /* 备份失败不阻断写入 */
      }
    }

    // 滚动备份上一版（只留一份，不堆积）
    try {
      if (fs.existsSync(flagFile)) fs.copyFileSync(flagFile, `${flagFile}.prev`);
    } catch {
      /* 备份失败不阻断写入 */
    }

    payload.authEnabled = enabled;
    payload.updatedAt = new Date().toISOString();
    // 留痕：谁在什么时候改的（便于事后审计「鉴权为什么是关的」）
    payload.updatedBy = operator || 'unknown';
    payload.note =
      '共享鉴权总开关（uniplam 门户 + myapp 共用）。authEnabled=false 时两边都跳过用户登录，仅限日常开发。';

    const tmp = `${flagFile}.tmp_${process.pid}`;
    fs.writeFileSync(tmp, `${JSON.stringify(payload, null, 2)}\n`, 'utf-8');
    fs.renameSync(tmp, flagFile);

    // 立刻刷新本进程缓存，页面点完马上看到结果
    cache = null;
    lastLogged = null;
    const state = getAuthSwitch();
    return { ok: true, state };
  } catch (e) {
    return { ok: false, detail: `写入开关文件失败: ${String(e)}` };
  }
}

/** 清缓存（仅测试/热重载使用） */
export function resetAuthSwitchCache(): void {
  cache = null;
  lastLogged = null;
}
