import crypto from 'node:crypto';

// ============================================================================
// 密码哈希与校验（scrypt 加盐）
// ----------------------------------------------------------------------------
// 存储格式：`scrypt$<salt-hex>$<hash-hex>`，**永不存明文**。
// 参数 N=16384, r=8, p=1 —— 与历史数据一致，改动会导致所有老账号无法登录，
// 除非同时提供多参数回退校验；当前无此需求，保持不动。
// 校验用 timingSafeEqual 防时序侧信道。
// ============================================================================

const SCRYPT_PARAMS = { N: 16384, r: 8, p: 1 } as const;
const KEY_LEN = 32;

export function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16);
  const hash = crypto.scryptSync(password, salt, KEY_LEN, SCRYPT_PARAMS);
  return `scrypt$${salt.toString('hex')}$${hash.toString('hex')}`;
}

export function verifyPassword(password: string, stored: string): boolean {
  const [scheme, saltHex, hashHex] = stored.split('$');
  if (scheme !== 'scrypt' || !saltHex || !hashHex) return false;
  try {
    const expected = Buffer.from(hashHex, 'hex');
    const actual = crypto.scryptSync(password, Buffer.from(saltHex, 'hex'), expected.length, {
      ...SCRYPT_PARAMS,
    });
    return actual.length === expected.length && crypto.timingSafeEqual(actual, expected);
  } catch {
    return false;
  }
}

/** 生成账号 id（8 字节随机 hex） */
export function newId(): string {
  return crypto.randomBytes(8).toString('hex');
}

/** 生成会话 token（32 字节随机 hex） */
export function newSessionToken(): string {
  return crypto.randomBytes(32).toString('hex');
}
