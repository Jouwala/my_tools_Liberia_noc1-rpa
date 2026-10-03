/**
 * WoClosePanel —— WO 清理（批量关闭 WaitConfirm 工单）
 * =============================================================================
 * 挂在 eflow_qa 页面左栏。链路与字段全部来自 2026-10-01 的实机抓包验证
 * （backend/services/eflow_wo_close.py 模块注释有完整记录）：
 *   ① POST /eflow-wo/base/detail?woId=  → 找待办 Confirm op 的 id
 *   ② POST /eflow-wo/base/process       → opEntity{id, operationResult:"7"}
 *   ③ 回读 detail 复核 Closed
 *
 * 交互按「TT 批量核查」同一套模式：上传清单 / 粘贴 / 模板下载 →
 * 只读预检过目 → 勾选确认 → 提交 → 逐单结果 + Excel 导出。
 * 提交是不可逆的生产写操作，所以「预检 → 勾选 → 二次确认」不可省。
 */
import { useCallback, useMemo, useState } from 'react'
import { Alert, Button, Checkbox, Input, Modal, Space, Table, Tag, Tooltip, Typography, Upload, message } from 'antd'
import {
  ClearOutlined,
  DownloadOutlined,
  ScissorOutlined,
  ThunderboltOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import * as XLSX from 'xlsx'

import api from '../api'
import { useI18n } from '../i18n'
import { useTheme } from '../theme'
import { exportAoaReport, exportReport } from '../utils/excelReport'

const { Text } = Typography

/** WO 单号形态：WO + 12 位数字（与后端 normalize_wo_list 同规则） */
const WO_TOKEN_SPLIT = /[\s,;，；\t|]+/
const WO_TOKEN_RE = /^WO\d{12}$/

/** 从任意单元格值里取出 WO 单号（与 EflowQa 的 pickTtTokens 同思路） */
function pickWoTokens(value: unknown): string[] {
  if (value === null || value === undefined) return []
  return String(value)
    .split(WO_TOKEN_SPLIT)
    .map(s => s.trim().toUpperCase())
    .filter(s => WO_TOKEN_RE.test(s))
}

function dedupeWoTokens(tokens: string[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of tokens) {
    for (const tok of pickWoTokens(raw)) {
      if (seen.has(tok)) continue
      seen.add(tok)
      out.push(tok)
    }
  }
  return out
}

/** 解析上传文件（xlsx/xls/csv/txt）→ 去重后的 WO 单号数组 */
async function parseWoListFile(file: File): Promise<string[]> {
  const name = (file.name || '').toLowerCase()
  const out: string[] = []
  if (name.endsWith('.txt') || name.endsWith('.csv')) {
    const text = await file.text()
    for (const tok of pickWoTokens(text)) out.push(tok)
  } else {
    const buf = await file.arrayBuffer()
    const wb = XLSX.read(buf, { type: 'array' })
    for (const sheetName of wb.SheetNames) {
      const grid: unknown[][] = XLSX.utils.sheet_to_json(wb.Sheets[sheetName], {
        header: 1, blankrows: false, raw: false, defval: '',
      })
      for (const row of grid) for (const cell of row) for (const tok of pickWoTokens(cell)) out.push(tok)
    }
  }
  return [...new Set(out)]
}

/** 判定 Tag 颜色 */
function actionColor(action: string | undefined): string | undefined {
  switch (action) {
    case 'closed': return 'green'
    case 'failed': return 'red'
    case 'skipped': return 'orange'
    case 'not_found': return 'default'
    default: return undefined
  }
}

interface Props {
  isMobile: boolean
}

export default function WoClosePanel({ isMobile }: Props) {
  const { t } = useI18n() as any
  const { isDark } = useTheme() as any
  const panelBg = isDark ? '#0f2744' : '#ffffff'
  const border = isDark ? '1px solid rgba(0, 217, 255,0.2)' : '1px solid #d9e6f2'

  const [text, setText] = useState('')
  const [file, setFile] = useState('')
  const [checking, setChecking] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [checkData, setCheckData] = useState<any>(null)
  const [submitData, setSubmitData] = useState<any>(null)
  const [checked, setChecked] = useState<Record<string, boolean>>({})

  const tokens = useMemo(() => dedupeWoTokens([text]), [text])
  const closableRows = useMemo(
    () => (checkData?.rows || []).filter((r: any) => r.closable),
    [checkData],
  )
  const checkedCount = useMemo(
    () => closableRows.filter((r: any) => checked[r.wo_num]).length,
    [closableRows, checked],
  )

  /** 只读预检 */
  const runCheck = useCallback((tokensArg?: string[]) => {
    const list = dedupeWoTokens(tokensArg && tokensArg.length ? tokensArg : [text])
    if (!list.length) {
      setError(t('qa.woClose.emptyInput'))
      return
    }
    setChecking(true)
    setError('')
    setSubmitData(null)
    api.post('/eflow-qa/wo-close/check', { wos: list })
      .then(res => {
        setCheckData(res.data)
        // 默认全选可关单
        const init: Record<string, boolean> = {}
        for (const r of res.data.rows || []) if (r.closable) init[r.wo_num] = true
        setChecked(init)
      })
      .catch((e: any) => {
        setCheckData(null)
        setError(e?.response?.data?.detail || t('qa.woClose.checkFailed'))
      })
      .finally(() => setChecking(false))
  }, [text, t])

  const onFile = useCallback(async (f: File) => {
    try {
      const list = await parseWoListFile(f)
      setFile(f.name || '')
      if (!list.length) {
        setError(t('qa.woClose.noWoInFile'))
        return false
      }
      setText(list.join('\n'))
      runCheck(list)
    } catch {
      setError(t('qa.woClose.fileFailed'))
    }
    return false // 阻止 antd 自动上传（纯本地解析）
  }, [runCheck, t])

  /** 下载填写模板（与 TT 批量核查模板同思路：说明里不出现真实单号） */
  const downloadTemplate = useCallback(async () => {
    try {
      await exportAoaReport({
        filename: 'wo_close_template.xlsx',
        sheetName: t('qa.woClose.templateSheet'),
        title: t('qa.woClose.templateTitle'),
        subtitle: t('qa.woClose.templateSubtitle'),
        header: [t('qa.woClose.templateColWo'), t('qa.woClose.templateColNote')],
        rows: tokens.map(tok => [tok, '']),
        columnWidths: [26, 46],
        tabColor: '#B5121B',
      })
    } catch {
      message.error(t('qa.woClose.checkFailed'))
    }
  }, [tokens, t])

  /** 真正提交（二次确认后） */
  const doSubmit = useCallback(() => {
    const list = closableRows.filter((r: any) => checked[r.wo_num]).map((r: any) => r.wo_num)
    if (!list.length) {
      message.warning(t('qa.woClose.nothingSelected'))
      return
    }
    setSubmitting(true)
    setError('')
    api.post('/eflow-qa/wo-close/submit', { wos: list })
      .then(res => {
        setSubmitData(res.data)
        // 提交后把预检结果换成提交结果（同一张表展示）
        setCheckData(null)
        setChecked({})
        message.success(t('qa.woClose.submitDone', {
          n: res.data?.summary?.closed ?? 0, total: res.data?.summary?.total ?? 0,
        }))
      })
      .catch((e: any) => {
        setError(e?.response?.data?.detail || t('qa.woClose.submitFailed'))
      })
      .finally(() => setSubmitting(false))
  }, [closableRows, checked, t])

  const confirmSubmit = useCallback(() => {
    const list = closableRows.filter((r: any) => checked[r.wo_num]).map((r: any) => r.wo_num)
    if (!list.length) {
      message.warning(t('qa.woClose.nothingSelected'))
      return
    }
    Modal.confirm({
      title: t('qa.woClose.confirmTitle', { n: list.length }),
      content: (
        <div style={{ maxHeight: 260, overflow: 'auto' }}>
          <Text type="warning" style={{ display: 'block', marginBottom: 8 }}>
            {t('qa.woClose.confirmWarning')}
          </Text>
          {list.map((w: string) => <Tag key={w} style={{ marginBottom: 4 }}>{w}</Tag>)}
        </div>
      ),
      okText: t('qa.woClose.confirmOk'),
      okButtonProps: { danger: true },
      cancelText: t('qa.woClose.confirmCancel'),
      onOk: doSubmit,
    })
  }, [closableRows, checked, doSubmit, t])

  /** 导出结果 Excel */
  const exportResult = useCallback(async () => {
    const rows: any[] = submitData?.rows || checkData?.rows || []
    if (!rows.length) {
      message.warning(t('qa.woClose.exportEmpty'))
      return
    }
    const d = new Date()
    const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}_${String(d.getHours()).padStart(2, '0')}${String(d.getMinutes()).padStart(2, '0')}`
    try {
      await exportReport([{
        name: t('qa.woClose.sheetResult'),
        title: t('qa.woClose.title'),
        tabColor: '#2F5496',
        header: [
          t('qa.woClose.col.wo'), t('qa.woClose.col.action'), t('qa.woClose.col.status'),
          t('qa.woClose.col.site'), t('qa.woClose.col.message'),
        ],
        rows: rows.map(r => [
          r.wo_num,
          r.action === 'closed' ? t('qa.woClose.action.closed')
            : r.action === 'skipped' ? t('qa.woClose.action.skipped')
            : r.action === 'not_found' ? t('qa.woClose.action.notFound')
            : r.closable === false && r.reason ? t('qa.woClose.action.notClosable')
            : t('qa.woClose.action.failed'),
          r.status || r.status_before || '—',
          r.site || r.display_name || '—',
          r.reason || r.message || '—',
        ]),
        columnWidths: [20, 14, 18, 26, 44],
      }], `wo_close_result_${stamp}.xlsx`)
    } catch {
      message.error(t('qa.woClose.exportFailed'))
    }
  }, [submitData, checkData, t])

  const stat = (label: string, value: number | undefined, color?: string) => (
    <Tag color={color} style={{ margin: 0, padding: '2px 10px', fontSize: 13 }}>
      {label} <b>{value ?? 0}</b>
    </Tag>
  )

  const columns = [
    {
      title: t('qa.woClose.col.wo'),
      dataIndex: 'wo_num',
      width: 160,
      fixed: isMobile ? undefined : ('left' as const),
      render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span>,
    },
    {
      title: t('qa.woClose.col.closable'),
      dataIndex: 'closable',
      width: 110,
      render: (_: any, r: any) => {
        if (submitData) {
          // 提交后视图：显示动作结果
          return (
            <Tag color={actionColor(r.action)} style={{ margin: 0 }}>
              {r.action === 'closed' ? t('qa.woClose.action.closed')
                : r.action === 'skipped' ? t('qa.woClose.action.skipped')
                : r.action === 'not_found' ? t('qa.woClose.action.notFound')
                : t('qa.woClose.action.failed')}
            </Tag>
          )
        }
        return r.closable
          ? <Tag color="green" style={{ margin: 0 }}>{t('qa.woClose.yes')}</Tag>
          : <Tag color="orange" style={{ margin: 0 }}>{t('qa.woClose.no')}</Tag>
      },
    },
    {
      title: t('qa.woClose.col.status'),
      dataIndex: 'status',
      width: 130,
      render: (v: string, r: any) => v || r.status_before || '—',
    },
    { title: t('qa.woClose.col.site'), dataIndex: 'site', width: 150, ellipsis: true,
      render: (v: string, r: any) => v || r.display_name || '—' },
    {
      title: t('qa.woClose.col.select'),
      width: 70,
      render: (_: any, r: any) => (r.closable && !submitData
        ? <Checkbox
            checked={!!checked[r.wo_num]}
            onChange={e => setChecked(prev => ({ ...prev, [r.wo_num]: e.target.checked }))}
          />
        : null),
    },
    { title: t('qa.woClose.col.reason'), dataIndex: 'reason', ellipsis: true,
      render: (v: string, r: any) => v || r.message || '—' },
  ]

  const resultRows = submitData?.rows || checkData?.rows || []
  const summary = submitData?.summary || checkData?.summary

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
        <ScissorOutlined style={{ color: '#B5121B' }} />
        <Text strong style={{ fontSize: 16 }}>{t('qa.woClose.title')}</Text>
        <Space style={{ marginLeft: 'auto' }} wrap>
          <Button size="small" icon={<ClearOutlined />} onClick={() => {
            setText(''); setFile(''); setCheckData(null); setSubmitData(null)
            setError(''); setChecked({})
          }}>
            {t('qa.woClose.clear')}
          </Button>
        </Space>
      </div>
      <div style={{ fontSize: 12, color: isDark ? '#aebbd4' : '#64748b', marginBottom: 10 }}>
        {t('qa.woClose.subtitle')}
      </div>

      {/* 输入区 */}
      <div style={{
        border, borderRadius: 8, padding: '10px 14px', marginBottom: 10,
        background: isDark ? 'rgba(181,18,27,0.10)' : '#fdf6f6',
      }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
          <Upload accept=".xlsx,.xls,.csv,.txt" showUploadList={false} beforeUpload={onFile}>
            <Button icon={<UploadOutlined />}>{t('qa.woClose.upload')}</Button>
          </Upload>
          <Tooltip title={t('qa.woClose.templateTip')}>
            <Button icon={<DownloadOutlined />} onClick={downloadTemplate}>
              {t('qa.woClose.template')}
            </Button>
          </Tooltip>
          {file && <Tag color="red">{file}</Tag>}
          <Text type="secondary" style={{ fontSize: 12 }}>{t('qa.woClose.uploadHint')}</Text>
        </div>
        <Input.TextArea
          rows={4}
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder={t('qa.woClose.placeholder')}
        />
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}>
          <Button type="primary" loading={checking} onClick={() => runCheck()}>
            {checking ? t('qa.woClose.checking') : t('qa.woClose.check')}
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('qa.woClose.parsed', { n: tokens.length })}
          </Text>
        </div>
      </div>

      {!!error && <Alert type="error" showIcon message={error} style={{ marginBottom: 10 }} />}

      {/* 预检结果 / 提交结果 */}
      {!!resultRows.length && summary && (
        <div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8, alignItems: 'center' }}>
            {submitData ? (
              <>
                {stat(t('qa.woClose.stat.total'), summary.total)}
                {stat(t('qa.woClose.stat.closed'), summary.closed, 'green')}
                {stat(t('qa.woClose.stat.skipped'), summary.skipped, 'orange')}
                {stat(t('qa.woClose.stat.failed'), summary.failed, 'red')}
                {stat(t('qa.woClose.stat.notFound'), summary.not_found)}
              </>
            ) : (
              <>
                {stat(t('qa.woClose.stat.total'), summary.total)}
                {stat(t('qa.woClose.stat.closable'), summary.closable, 'green')}
                {stat(t('qa.woClose.stat.notClosable'), summary.not_closable, 'orange')}
              </>
            )}
            <Space style={{ marginLeft: 'auto' }} wrap>
              {!submitData && (
                <Button
                  type="primary"
                  danger
                  icon={<ThunderboltOutlined />}
                  disabled={!checkedCount}
                  loading={submitting}
                  onClick={confirmSubmit}
                >
                  {t('qa.woClose.submit', { n: checkedCount })}
                </Button>
              )}
              <Button size="small" icon={<DownloadOutlined />} onClick={exportResult}>
                {t('qa.woClose.export')}
              </Button>
            </Space>
          </div>
          {!!checkData?.invalid?.length && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 8 }}
              message={t('qa.woClose.invalid', {
                n: checkData.invalid.length, list: checkData.invalid.slice(0, 8).join('、'),
              })}
            />
          )}
          <Table
            size="small"
            columns={columns as any}
            dataSource={resultRows}
            rowKey={(r: any, i?: number) => `${r.wo_num}-${i}`}
            pagination={{ pageSize: 20, showSizeChanger: false, showTotal: n => `${n}` }}
            scroll={isMobile ? undefined : { x: 760 }}
          />
        </div>
      )}
    </div>
  )
}
