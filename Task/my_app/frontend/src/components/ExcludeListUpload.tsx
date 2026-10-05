/* ==================== NUR 排除名单上传（TT_Exclude） ====================
 * 从 TableBrowser 抽出的独立组件。抽出来的理由有两个：
 *   1. TableBrowser.tsx 已 900+ 行（存量超限文件），按 AGENTS.md 三.2
 *      「改到它们时不得继续无度膨胀」，新功能应独立成模块；
 *   2. 这个上传与同页的「自定义导入」是**两套语义**：自定义导入由用户指定
 *      表名，而排除名单是**固定表名 tt_exclude + 全量替换**，还多两道护栏
 *      （票号格式校验、dry-run）。放一起会让人误以为可以自定表名。
 *
 * 为什么这个名单必须落库而非继续拉 FTP：
 *   xlsx 名单是隐形的、无法审计，且「拉取时间 ≠ 内容时间」会让人把
 *   「名单过时导致最近几天 NUR 全 0」误判成「计算算错了」（真实踩坑）。
 * ================================================================ */
import { useEffect, useState } from 'react'
import { Alert, Button, Descriptions, Modal, Upload, message } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'

export default function ExcludeListUpload({ open, onClose }: {
  open: boolean
  onClose: () => void
}) {
  const { t } = useI18n()
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState<any>(null)   // dry-run 结果
  const [meta, setMeta] = useState<any>(null)         // 当前名单元信息

  // 每次打开都重置并重拉元信息：名单可能刚被别处改过，显示旧值会误导
  useEffect(() => {
    if (!open) return
    setFile(null); setPreview(null); setMeta(null)
    let alive = true
    api.get('/tables/exclude-meta')
      .then(r => { if (alive) setMeta(r.data) })
      .catch(() => { /* 元信息拿不到不阻断上传 */ })
    return () => { alive = false }
  }, [open])

  const submit = async (dryRun: boolean) => {
    if (!file) return
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('dry_run', String(dryRun))
      // 不传 uploaded_by：系统无多用户体系（helpContent.ts:950），
      // 后端记客户端 IP 作为操作来源；前端伪造用户名只会产生误导性审计数据。
      const r = await api.post('/tables/import-exclude', fd)
      if (dryRun) {
        setPreview(r.data)
      } else {
        message.success(t('table.exDone', { n: r.data.change.after_count }))
        onClose()
      }
    } catch (err: any) {
      message.error(err.response?.data?.detail || err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title={t('table.exTitle')}
      open={open}
      onCancel={() => !busy && onClose()}
      width={'min(90vw, 38rem)' as any}
      footer={[
        <Button key="cancel" disabled={busy} onClick={onClose}>{t('table.cancel')}</Button>,
        <Button key="dry" disabled={!file} loading={busy} onClick={() => submit(true)}>
          {t('table.exPreview')}
        </Button>,
        <Button key="ok" type="primary" disabled={!file} loading={busy} onClick={() => submit(false)}>
          {t('table.exApply')}
        </Button>,
      ]}
    >
      <Alert type="info" showIcon style={{ marginBottom: 'var(--wh-space-md)' }}
        message={t('table.exIntro')} description={t('table.exIntroDesc')} />

      {/* 显示「内容时间」而非拉取时间 —— 后者会让人误以为名单很新（真实踩坑） */}
      <Descriptions size="small" column={1} style={{ marginBottom: 'var(--wh-space-md)' }}
        items={[
          { key: 'n', label: t('table.exCurCount'), children: meta ? `${meta.count}` : '—' },
          { key: 't', label: t('table.exCurTime'), children: meta?.import_time || '—' },
          { key: 'b', label: t('table.exCurBy'), children: meta?.uploaded_by || '—' },
          { key: 'f', label: t('table.exCurFile'), children: meta?.source_file || '—' },
        ]} />

      <div style={{ marginBottom: 'var(--wh-space-xs)', color: '#555' }}>{t('table.exFilePh')}</div>
      <Upload
        beforeUpload={() => false}
        maxCount={1}
        accept=".xlsx,.xls,.csv"
        fileList={file ? [{ uid: '-1', name: file.name, status: 'done' } as any] : []}
        onChange={(info: any) => {
          setFile(info.fileList[0]?.originFileObj || null)
          setPreview(null)
        }}
        onRemove={() => { setFile(null); setPreview(null) }}
      >
        <Button icon={<UploadOutlined />}>{t('table.exFilePh')}</Button>
      </Upload>

      {/* dry-run 结果：先看清「加几条、删几条」再决定是否落库 */}
      {preview && (
        <div style={{ marginTop: 'var(--wh-space-md)' }}>
          <Alert
            type={preview.parse?.invalid ? 'warning' : 'success'} showIcon
            message={t('table.exPreviewTitle')}
            description={
              <div style={{ fontSize: '0.8125rem' }}>
                <div>{t('table.exPreviewRows', {
                  before: preview.change.before_count, after: preview.change.after_count })}</div>
                <div>{t('table.exPreviewDiff', {
                  add: preview.change.added, del: preview.change.removed })}</div>
                <div>{t('table.exPreviewCol', { col: preview.parse?.column })}</div>
                {preview.parse?.invalid > 0 && (
                  <div style={{ color: '#fa8c16' }}>
                    {t('table.exPreviewInvalid', {
                      n: preview.parse.invalid, s: (preview.parse.invalid_samples || []).join(', ') })}
                  </div>
                )}
              </div>
            } />
        </div>
      )}
    </Modal>
  )
}
