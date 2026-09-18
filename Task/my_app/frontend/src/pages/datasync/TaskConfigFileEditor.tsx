// 通用任务配置文件编辑器（Settings「任务配置」页签 -> 配置文件管理）
// schema 驱动：int/str/bool/object/table 自动渲染；支持保存/导出/导入。
import { useEffect, useState } from 'react'
import {
  Alert, Button, Divider, Input, InputNumber, message, Space, Switch, Tag, Typography, Upload,
} from 'antd'
import { DownloadOutlined, PlusOutlined, SaveOutlined, UploadOutlined } from '@ant-design/icons'
import api from '../../api'
import { WH } from '../../theme'

const { Text } = Typography

type Schema = Record<string, any>

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export default function TaskConfigFileEditor({ taskId, zh }: { taskId: string; zh: boolean }) {
  const L = {
    loading: zh ? '加载配置...' : 'Loading config...',
    desc: zh ? '配置文件管理（时间范围 / 指标模板 / 网元 / URL 等，保存后下次同步生效）' : 'Config file management (time range / templates / NEs / URLs; takes effect on next sync)',
    save: zh ? '保存配置' : 'Save config',
    saved: zh ? '配置已保存' : 'Config saved',
    saveFailed: zh ? '保存失败' : 'Save failed',
    export: zh ? '导出配置' : 'Export',
    import: zh ? '导入配置' : 'Import',
    importApply: zh ? '应用导入' : 'Apply import',
    importHint: zh ? '粘贴完整配置 JSON 后点击应用（整体替换，校验失败不影响已保存配置）' : 'Paste full config JSON then Apply (full replace; invalid items rejected)',
    invalidJson: zh ? 'JSON 格式无效' : 'Invalid JSON',
    importDone: zh ? '配置已导入' : 'Config imported',
    add: zh ? '添加' : 'Add',
    del: zh ? '删除' : 'Delete',
    noConfig: zh ? '暂无配置内容' : 'No config',
  }

  const [meta, setMeta] = useState<{ description?: string; description_en?: string; schema?: Schema } | null>(null)
  const [config, setConfig] = useState<Record<string, any> | null>(null)
  const [edit, setEdit] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)
  const [importText, setImportText] = useState('')
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<{ applied?: string[]; errors?: { index: number | string; error: string }[] } | null>(null)

  const load = () => {
    api.get(`/task-configs/${taskId}`)
      .then((res) => {
        setMeta(res.data.meta)
        setConfig(res.data.config || {})
        // 编辑副本只保留 schema 键（内部字段原样保留在文件里）
        const e: Record<string, any> = {}
        const schema = (res.data.meta?.schema || {}) as Schema
        Object.keys(schema).forEach((k) => {
          if (k in res.data.config) e[k] = JSON.parse(JSON.stringify(res.data.config[k]))
        })
        setEdit(e)
      })
      .catch(() => message.error(L.loading))
  }

  useEffect(() => { load() /* eslint-disable-line react-hooks/exhaustive-deps */ }, [taskId, zh])

  const schema = (meta?.schema || {}) as Schema

  const setField = (key: string, value: any) => setEdit((prev) => ({ ...prev, [key]: value }))

  const setTableItem = (key: string, idx: number, field: string, value: any) => {
    setEdit((prev) => {
      const rows = Array.isArray(prev[key]) ? [...prev[key]] : []
      rows[idx] = { ...rows[idx], [field]: value }
      return { ...prev, [key]: rows }
    })
  }

  const addTableRow = (key: string, fields: Schema) => {
    setEdit((prev) => {
      const row: Record<string, any> = {}
      Object.keys(fields).forEach((f) => {
        row[f] = fields[f].type === 'bool' ? false : fields[f].type === 'int' ? 0 : ''
      })
      return { ...prev, [key]: [...(Array.isArray(prev[key]) ? prev[key] : []), row] }
    })
  }

  const removeTableRow = (key: string, idx: number) => {
    setEdit((prev) => ({
      ...prev,
      [key]: (Array.isArray(prev[key]) ? prev[key] : []).filter((_: any, i: number) => i !== idx),
    }))
  }

  const labelOf = (sub: any) => (zh ? sub.label_zh : sub.label_en || sub.label_zh) || ''

  const inputStyle = { background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0, 217, 255,0.25)', color: WH.text }

  const renderScalar = (key: string, sub: any, value: any) => {
    const t = sub.type
    if (t === 'int') {
      return <InputNumber size="small" value={value} min={sub.min} max={sub.max}
        onChange={(v) => setField(key, v ?? sub.min ?? 0)} style={{ width: 'min(100%, 7.5rem)', ...inputStyle }} />
    }
    if (t === 'bool') {
      return <Switch size="small" checked={!!value} onChange={(v) => setField(key, v)} />
    }
    if (t === 'json') {
      const raw = typeof value === 'string' ? value : JSON.stringify(value ?? {}, null, 2)
      return (
        <Input.TextArea size="small" rows={4} value={raw}
          style={{ ...inputStyle, fontFamily: 'monospace', fontSize: '0.6875rem' }}
          onChange={(e) => {
            const txt = e.target.value
            try { setField(key, JSON.parse(txt)) } catch { setField(key, txt) }
          }} />
      )
    }
    return <Input size="small" value={value ?? ''} onChange={(e) => setField(key, e.target.value)} style={{ ...inputStyle }} />
  }

  const renderField = (key: string, sub: any, value: any, depth = 0) => {
    const t = sub.type
    const indent = { marginLeft: `calc(var(--wh-space-md) * ${depth})`, marginTop: 'var(--wh-space-xs)' }
    if (t === 'object') {
      return (
        <div key={key} style={indent}>
          <Text style={{ color: WH.teal, fontSize: '0.75rem', fontWeight: 600 }}>▸ {labelOf(sub)}</Text>
          <div style={{ marginLeft: 'var(--wh-space-sm)' }}>
            {Object.entries((sub.fields || {}) as Record<string, any>).map(([k, s]) => (
              <div key={k} style={{ marginTop: '0.375rem' }}>
                <Text style={{ color: WH.textMuted, fontSize: '0.6875rem', display: 'block' }}>{labelOf(s)}</Text>
                {renderScalar(k, s, (value && value[k]) ?? (s.type === 'bool' ? false : s.type === 'int' ? 0 : ''))}
              </div>
            ))}
          </div>
        </div>
      )
    }
    if (t === 'table') {
      const rows = Array.isArray(value) ? value : []
      return (
        <div key={key} style={indent}>
          <Text style={{ color: WH.teal, fontSize: '0.75rem', fontWeight: 600 }}>▸ {labelOf(sub)} ({rows.length})</Text>
          {rows.map((row: any, i: number) => (
            <div key={i} style={{
              marginTop: '0.375rem', padding: 'var(--wh-space-sm)', borderRadius: 'var(--wh-radius-sm)',
              border: '1px solid rgba(0, 217, 255,0.15)', background: 'rgba(0,0,0,0.15)',
            }}>
              <Space wrap style={{ gap: '0.375rem' }}>
                {Object.entries(sub.fields || {}).map(([f, s]: [string, any]) => (
                  <span key={f}>
                    <Text style={{ color: WH.textMuted, fontSize: '0.625rem', display: 'block' }}>{labelOf(s)}</Text>
                    {s.type === 'bool'
                      ? <Switch size="small" checked={!!row[f]} onChange={(v) => setTableItem(key, i, f, v)} />
                      : <Input size="small" value={row[f] ?? ''} style={{ width: 'min(100%, 10rem)', ...inputStyle }}
                          onChange={(e) => setTableItem(key, i, f, e.target.value)} />}
                  </span>
                ))}
                <Button size="small" danger type="text" onClick={() => removeTableRow(key, i)}>{L.del}</Button>
              </Space>
            </div>
          ))}
          <Button size="small" type="dashed" icon={<PlusOutlined />} style={{ marginTop: '0.375rem' }}
            onClick={() => addTableRow(key, sub.fields || {})}>
            {L.add} {labelOf(sub)}
          </Button>
        </div>
      )
    }
    return (
      <div key={key} style={indent}>
        <Text style={{ color: WH.textMuted, fontSize: '0.6875rem', display: 'block' }}>{labelOf(sub)}</Text>
        {renderScalar(key, sub, value)}
      </div>
    )
  }

  const save = () => {
    setSaving(true)
    api.put(`/task-configs/${taskId}`, edit)
      .then((res) => {
        if (res.data && res.data.success === false) {
          message.error((res.data.error) || L.saveFailed)
        } else {
          message.success(L.saved)
          load()
        }
      })
      .catch((e) => message.error((e?.response?.data?.detail) || L.saveFailed))
      .finally(() => setSaving(false))
  }

  const exportCfg = () => {
    api.get(`/task-configs/${taskId}/export`)
      .then((res) => { downloadJson(`task_config_${taskId}.json`, res.data); message.success(L.saved) })
      .catch(() => message.error(L.saveFailed))
  }

  const applyImport = () => {
    let parsed: unknown
    try { parsed = JSON.parse(importText) } catch { message.error(L.invalidJson); return }
    setImporting(true)
    api.post(`/task-configs/${taskId}/import`, parsed)
      .then((res) => {
        setImportResult(res.data)
        if (res.data.errors && res.data.errors.length) message.warning(L.saveFailed)
        else { message.success(L.importDone); load() }
      })
      .catch(() => message.error(L.invalidJson))
      .finally(() => setImporting(false))
  }

  return (
    <div>
      <Divider style={{ borderColor: 'rgba(0, 217, 255,0.15)', margin: '0.875rem 0' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--wh-space-sm)' }}>
        <Text style={{ color: WH.textMuted, fontSize: '0.75rem', fontWeight: 600 }}>
          ⚙️ {zh ? '配置文件管理' : 'Config File Management'}
          {meta?.description && <span style={{ fontWeight: 400 }}> — {zh ? meta.description : meta.description_en || meta.description}</span>}
        </Text>
        <Space>
          <Button size="small" icon={<DownloadOutlined />} onClick={exportCfg}>{L.export}</Button>
          <Upload accept=".json,application/json" showUploadList={false}
            beforeUpload={(file) => { file.text().then((t) => setImportText(t)); return false }}>
            <Button size="small" icon={<UploadOutlined />}>{L.import}</Button>
          </Upload>
        </Space>
      </div>
      {config === null ? (
        <Text style={{ color: WH.textDim, fontSize: '0.75rem' }}>{L.loading}</Text>
      ) : (
        <>
          <div style={{ marginTop: '0.625rem' }}>
            {Object.keys(schema).map((k) => renderField(k, schema[k], edit[k]))}
          </div>
          <Space style={{ marginTop: '0.625rem' }}>
            <Button type="primary" size="small" icon={<SaveOutlined />} loading={saving} onClick={save}
              style={{ background: WH.teal, borderColor: WH.teal }}>
              {L.save}
            </Button>
          </Space>
          <div style={{ marginTop: '0.625rem' }}>
            <Input.TextArea rows={3} value={importText} onChange={(e) => setImportText(e.target.value)}
              placeholder={L.importHint} style={{ ...inputStyle }} />
            <Button size="small" type="primary" loading={importing} onClick={applyImport} style={{ marginTop: '0.375rem', background: WH.teal, borderColor: WH.teal }}>
              {L.importApply}
            </Button>
            {importResult && (
              <div style={{ marginTop: '0.375rem' }}>
                {importResult.applied && importResult.applied.length > 0 && (
                  <Alert type="success" showIcon style={{ marginBottom: 'var(--wh-space-xs)' }}
                    message={`${zh ? '已应用' : 'Applied'}: ${importResult.applied.join(', ')}`} />
                )}
                {importResult.errors && importResult.errors.length > 0 && (
                  <Alert type="error" showIcon
                    message={`${zh ? '失败项' : 'Errors'} (${importResult.errors.length})`}
                    description={importResult.errors.map((e) => `${e.index}: ${e.error}`).join('；')} />
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
