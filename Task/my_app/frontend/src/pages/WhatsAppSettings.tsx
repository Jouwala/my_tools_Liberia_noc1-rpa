import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Tag, message, Spin, Alert, Space } from 'antd'
import { QrcodeOutlined, ReloadOutlined, MobileOutlined, CheckCircleOutlined, CloseCircleOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import QRCode from 'qrcode'
import api from '../api'
import { useI18n } from '../i18n'
import { WH } from '../theme'
import { CardBase } from '../components/cards'

/**
 * 两个「已关联设备」——**同一个 WhatsApp 号码**，两个设备槽：
 * notify = P1 告警推送（notify.js, data/auth-notify）
 * bot    = 知识库问答（index.js,  data/auth）
 * 同号必须各扫各的凭据，不能共用（否则 code=440 互踢）。
 *
 * ⚠️ 不要在此写死设备槽号。槽位由 WhatsApp 服务端分配，每次重新扫码都会
 * 递增且不回收旧号（实测同一号码上依次出现过 :1 / :2 / :4 / :5），
 * 写死必然过期。进程靠**凭据目录**区分，槽号仅用于展示，
 * 以 `identity.device_slot`（读 creds.json 现取）渲染的卡面 Slot 为准。
 */
const DEVICES = ['notify', 'bot'] as const

interface LoginStatus {
  device: string
  online: boolean
  online_status?: string | null
  online_reason?: string | null
  identity: { number?: string; name?: string; device_slot?: string } | null
  state: string | null
  qr: string | null
  message: string | null
  nonce: string | null
  updated_at: string | null
}

export default function WhatsAppSettings() {
  const { t } = useI18n()
  const [loading, setLoading] = useState(true)
  const [statuses, setStatuses] = useState<Record<string, LoginStatus>>({})
  const [qrImages, setQrImages] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<Record<string, boolean>>({})
  // 每个设备一个轮询定时器句柄；组件卸载 / 完成后清理，避免泄漏。
  const timers = useRef<Record<string, ReturnType<typeof setInterval>>>({})

  const clearTimer = (device: string) => {
    const handle = timers.current[device]
    if (handle) {
      clearInterval(handle)
      delete timers.current[device]
    }
  }

  const fetchStatus = useCallback(
    async (device: string): Promise<LoginStatus | null> => {
      try {
        const res = await api.get('/whatsapp/login/status', { params: { device } })
        const st: LoginStatus = res.data
        setStatuses((prev) => ({ ...prev, [device]: st }))
        return st
      } catch (e: any) {
        message.error(t('settings.waLoginStatusError') + ': ' + (e?.response?.data?.detail || e?.message || e))
        return null
      }
    },
    [t],
  )

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      await Promise.all(DEVICES.map((d) => fetchStatus(d)))
    } finally {
      setLoading(false)
    }
  }, [fetchStatus])

  useEffect(() => {
    loadAll()
    return () => {
      // 卸载时清掉所有轮询定时器
      Object.keys(timers.current).forEach(clearTimer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 拿到新的 QR 字符串就渲染成二维码图片（qrcode 库）。
  const renderQr = useCallback(async (device: string, text: string) => {
    try {
      const url = await QRCode.toDataURL(text, { width: 260, margin: 1 })
      setQrImages((prev) => ({ ...prev, [device]: url }))
    } catch {
      /* 渲染失败留空，由状态文案兜底 */
    }
  }, [])

  const pollOnce = useCallback(
    async (device: string) => {
      const st = await fetchStatus(device)
      if (!st) return
      if (st.state === 'qr' && st.qr) {
        await renderQr(device, st.qr)
      } else {
        setQrImages((prev) => {
          if (!(device in prev)) return prev
          const next = { ...prev }
          delete next[device]
          return next
        })
      }
      if (st.state === 'connected') {
        clearTimer(device)
        setBusy((prev) => ({ ...prev, [device]: false }))
        message.success(t('settings.waLoginSuccess'))
      } else if (st.state === 'error') {
        clearTimer(device)
        setBusy((prev) => ({ ...prev, [device]: false }))
        message.error(t('settings.waLoginFailed') + (st.message ? ': ' + st.message : ''))
      }
    },
    [fetchStatus, renderQr, t],
  )

  const startQr = useCallback(
    async (device: string) => {
      clearTimer(device)
      setQrImages((prev) => {
        const next = { ...prev }
        delete next[device]
        return next
      })
      setBusy((prev) => ({ ...prev, [device]: true }))
      try {
        await api.post('/whatsapp/login/qr', { device })
      } catch (e: any) {
        message.error(t('settings.waLoginRequestError') + ': ' + (e?.response?.data?.detail || e?.message || e))
        setBusy((prev) => ({ ...prev, [device]: false }))
        return
      }
      // 立即拉一次，之后每 2s 轮询。二维码约 20s 轮换，状态文件里始终是最新码。
      pollOnce(device)
      timers.current[device] = setInterval(() => pollOnce(device), 2000)
    },
    [pollOnce, t],
  )

  const onlineTag = (st?: LoginStatus) => {
    if (!st) return <Tag>{t('settings.waLoginStatusUnknown')}</Tag>
    if (st.online) return <Tag color="green" icon={<CheckCircleOutlined />}>{t('settings.waLoginOnline')}</Tag>
    if (st.online_status === 'unknown') return <Tag icon={<QuestionCircleOutlined />}>{t('settings.waLoginStatusUnknown')}</Tag>
    return <Tag color="red" icon={<CloseCircleOutlined />}>{t('settings.waLoginOffline')}</Tag>
  }

  const renderCard = (device: 'notify' | 'bot', titleKey: string, descKey: string) => {
    const st = statuses[device]
    const isBusy = !!busy[device]
    const qrImg = qrImages[device]
    return (
      <CardBase
        key={device}
        title={
          <Space>
            <MobileOutlined style={{ color: WH.teal }} />
            {t(titleKey)}
            {onlineTag(st)}
          </Space>
        }
        style={{ marginBottom: 'var(--wh-space-md)' }}
      >
        <Spin spinning={loading}>
          <div style={{ color: WH.textMuted, fontSize: '0.75rem', marginBottom: '0.625rem' }}>{t(descKey)}</div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--wh-space-md)', marginBottom: '0.625rem', fontSize: '0.8125rem', color: WH.text }}>
            <div>
              {t('settings.waLoginNumber')}: <code style={{ color: WH.teal }}>{st?.identity?.number || '—'}</code>
            </div>
            <div>
              {t('settings.waLoginDeviceSlot')}: <code style={{ color: WH.teal }}>{st?.identity?.device_slot || '—'}</code>
            </div>
            <div>
              {t('settings.waLoginName')}: <code style={{ color: WH.teal }}>{st?.identity?.name || '—'}</code>
            </div>
          </div>

          {st?.online_reason && !st.online && (
            <Alert type="warning" showIcon style={{ marginBottom: 'var(--wh-space-sm)' }} message={st.online_reason} />
          )}

          <div style={{ marginBottom: '0.625rem' }}>
            <Button type="primary" icon={<QrcodeOutlined />} loading={isBusy} onClick={() => startQr(device)}>
              {t('settings.waLoginButton')}
            </Button>
            <Button
              style={{ marginLeft: 'var(--wh-space-sm)' }}
              icon={<ReloadOutlined />}
              disabled={isBusy}
              onClick={() => fetchStatus(device)}
            >
              {t('settings.refresh')}
            </Button>
          </div>

          {isBusy && st?.state === 'waiting' && (
            <div style={{ color: WH.textMuted, fontSize: '0.8125rem' }}>{t('settings.waLoginWaiting')}</div>
          )}

          {qrImg && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 'var(--wh-space-sm)' }}>
              <div style={{ color: WH.text, fontSize: '0.8125rem' }}>{t('settings.waLoginScanHint')}</div>
              <img
                src={qrImg}
                alt={t('settings.waLoginQrAlt')}
                style={{ width: 260, height: 260, borderRadius: 'var(--wh-radius-md)', background: '#fff', padding: 8 }}
              />
            </div>
          )}

          <Alert
            style={{ marginTop: 'var(--wh-space-md)' }}
            type="warning"
            showIcon
            message={t('settings.waLoginWarning')}
          />
        </Spin>
      </CardBase>
    )
  }

  return (
    <div style={{ padding: 'var(--wh-space-sm) var(--wh-space-xs)' }}>
      {/* 页面标题由 App 全局 Header（菜单「系统设置」）+ Tab 标签给出，页内不再重复 */}
      <div style={{ marginBottom: '0.75rem' }}>
        <div style={{ color: WH.textMuted, fontSize: '0.75rem' }}>
          {t('settings.waLoginSubtitle')}
        </div>
      </div>

      {renderCard('notify', 'settings.waLoginNotifyTitle', 'settings.waLoginNotifyDesc')}
      {renderCard('bot', 'settings.waLoginBotTitle', 'settings.waLoginBotDesc')}
    </div>
  )
}
