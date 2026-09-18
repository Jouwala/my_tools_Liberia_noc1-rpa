// Settings「任务配置」页签：逐任务查看/修改 cron 与启用状态，支持单任务/全量导入导出配置
import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Col, Divider, Input, List, message, Row, Select, Space, Switch, Tag, Typography, Upload,
} from 'antd'
import {
  DownloadOutlined, InboxOutlined, SaveOutlined, UploadOutlined,
} from '@ant-design/icons'
import api from '../../api'
import { useI18n } from '../../i18n'
import { WH } from '../../theme'
import TaskConfigFileEditor from './TaskConfigFileEditor'

const { Text } = Typography

interface TaskItem {
  task_id: string
  name: string
  name_zh?: string
  name_en?: string
  description: string
  category: string
  gateway: string
  enabled: boolean
  current_cron: string
  default_cron: string
  next_run: string | null
}

interface TaskConfig {
  task_id: string
  name: string
  name_en: string
  description: string
  category: string
  gateway: string
  cron: string
  enabled: boolean
  default_cron: string
  updated_at: string | null
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export default function TaskConfigTab() {
  const { locale } = useI18n()
  const zh = locale === 'zh'
  const L = {
    title: zh ? '任务配置' : 'Task Config',
    subtitle: zh ? '逐任务查看/修改调度（cron）与启用状态，可单任务或全量导入导出配置（JSON）。' : 'View/edit per-task schedule (cron) and enabled state; import/export single or all task configs as JSON.',
    search: zh ? '搜索任务（中/英文名、ID）' : 'Search tasks (name / id)',
    noMatch: zh ? '没有匹配的任务' : 'No matching tasks',
    loading: zh ? '加载中...' : 'Loading...',
    selectHint: zh ? '从左侧选择一个任务' : 'Select a task from the left',
    cron: zh ? '调度表达式 (cron)' : 'Schedule (cron)',
    cronHint: zh ? '5 段式：分 时 日 月 周，例如 0 8 * * *' : '5 fields: minute hour day month weekday, e.g. 0 8 * * *',
    enabled: zh ? '启用' : 'Enabled',
    nextRun: zh ? '下次运行' : 'Next run',
    defaultCron: zh ? '默认调度' : 'Default',
    updatedAt: zh ? '配置更新时间' : 'Updated at',
    save: zh ? '保存' : 'Save',
    saved: zh ? '配置已保存' : 'Config saved',
    saveFailed: zh ? '保存失败' : 'Save failed',
    export: zh ? '导出本任务' : 'Export this task',
    exportAll: zh ? '导出全部' : 'Export all',
    exported: zh ? '已导出' : 'Exported',
    importTitle: zh ? '导入配置' : 'Import Config',
    importHint: zh ? '粘贴 JSON（单对象或 {"configs": [...]} 数组），或选择 .json 文件，然后点击「应用导入」。每项独立校验，失败只影响该项。' : 'Paste JSON (single object or {"configs": [...]} array), or pick a .json file, then click "Apply Import". Each item is validated independently.',
    importPlaceholder: zh ? '[{"task_id": "eflow_sync", "cron": "30 * * * *", "enabled": true}]' : '[{"task_id": "eflow_sync", "cron": "30 * * * *", "enabled": true}]',
    importApply: zh ? '应用导入' : 'Apply Import',
    importOk: zh ? '导入完成' : 'Import finished',
    applied: zh ? '已应用' : 'Applied',
    errors: zh ? '失败项' : 'Errors',
    importFail: zh ? '导入失败' : 'Import failed',
    invalidJson: zh ? 'JSON 格式无效' : 'Invalid JSON',
    desc: zh ? '描述' : 'Description',
    gateway: zh ? '网关' : 'Gateway',
  }

  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [cfg, setCfg] = useState<TaskConfig | null>(null)
  const [cronText, setCronText] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [saving, setSaving] = useState(false)
  const [importText, setImportText] = useState('')
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<{ applied: string[]; errors: { task_id: string; error: string }[] } | null>(null)
  // —— 网元配置（cm_data_sync 流程）——
  const [cmFlows, setCmFlows] = useState<{ name: string; type: string; path: string; ne_count: number; ne_list: string[] }[]>([])
  const [cmFlowName, setCmFlowName] = useState<string | null>(null)
  const [cmNeList, setCmNeList] = useState<string[]>([])
  const [cmNewNe, setCmNewNe] = useState('')
  const [cmSavingNe, setCmSavingNe] = useState(false)
  const [cmImportOpen, setCmImportOpen] = useState(false)
  const [cmImportText, setCmImportText] = useState('')
  const [cmImporting, setCmImporting] = useState(false)
  const [cmImportResult, setCmImportResult] = useState<{ applied: string[]; errors: { index: number | string; error: string }[] } | null>(null)
  // —— 通用配置文件管理（注册了配置文件的任务，如 packet_loss_sync）——
  const [cfgTasks, setCfgTasks] = useState<string[]>([])

  useEffect(() => {
    api.get('/task-configs')
      .then((res) => setCfgTasks((res.data.configs || []).map((c: { task_id: string }) => c.task_id)))
      .catch(() => setCfgTasks([]))
  }, [])

  const loadCmFlows = () => {
    api.get('/cm-flows')
      .then((res) => {
        const flows = (res.data.flows || []) as { name: string; type: string; path: string; ne_count: number; ne_list: string[] }[]
        setCmFlows(flows)
        if (flows.length) {
          const keep = flows.find((f) => f.name === cmFlowName)
          const first = keep || flows[0]
          setCmFlowName(first.name)
          setCmNeList([...(first.ne_list || [])])
        } else {
          setCmFlowName(null)
          setCmNeList([])
        }
      })
      .catch(() => message.error(zh ? '加载流程配置失败' : 'Failed to load flows'))
  }

  useEffect(() => {
    if (selected === 'cm_data_sync') loadCmFlows()
    else { setCmFlowName(null); setCmNeList([]) }
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [selected])

  const selectCmFlow = (name: string) => {
    const f = cmFlows.find((x) => x.name === name)
    if (f) { setCmFlowName(name); setCmNeList([...(f.ne_list || [])]) }
  }

  const addCmNe = () => {
    const ne = cmNewNe.trim()
    if (!ne) return
    if (!/^SubNetwork=\d+,ManagedElement=\d+$/.test(ne)) {
      message.error(zh ? '格式应为 SubNetwork=X,ManagedElement=Y' : 'Format: SubNetwork=X,ManagedElement=Y')
      return
    }
    if (cmNeList.includes(ne)) { message.warning(zh ? '网元已存在' : 'NE already exists'); return }
    setCmNeList([...cmNeList, ne])
    setCmNewNe('')
  }

  const saveCmNeList = () => {
    if (!cmFlowName) return
    setCmSavingNe(true)
    api.put(`/cm-flows/${encodeURIComponent(cmFlowName)}/ne-list`, { ne_list: cmNeList })
      .then((res) => {
        if (res.data && res.data.success === false) message.error((res.data.error) || '')
        else { message.success(zh ? '网元清单已保存' : 'NE list saved'); loadCmFlows() }
      })
      .catch((e) => message.error((e?.response?.data?.detail) || (zh ? '保存失败' : 'Save failed')))
      .finally(() => setCmSavingNe(false))
  }

  const exportCmFlows = () => {
    api.get('/cm-flows/export')
      .then((res) => {
        downloadJson(`cm_flows_${new Date().toISOString().slice(0, 10)}.json`, res.data)
        message.success(zh ? '已导出' : 'Exported')
      })
      .catch(() => message.error(zh ? '导出失败' : 'Export failed'))
  }

  const applyCmFlowImport = () => {
    let parsed: unknown
    try { parsed = JSON.parse(cmImportText) } catch { message.error(L.invalidJson); return }
    const flows = Array.isArray(parsed) ? parsed : (parsed as { flows?: unknown[] })?.flows
    if (!Array.isArray(flows)) { message.error(L.invalidJson); return }
    setCmImporting(true)
    api.post('/cm-flows/import', { flows })
      .then((res) => {
        setCmImportResult(res.data)
        if (res.data.errors && res.data.errors.length) message.warning(zh ? '部分项导入失败' : 'Some items failed')
        else message.success(zh ? '流程配置已导入' : 'Flows imported')
        loadCmFlows()
      })
      .catch(() => message.error(zh ? '导入失败' : 'Import failed'))
      .finally(() => setCmImporting(false))
  }

  const loadTasks = () => {
    api.get('/tasks?lang=' + locale)
      .then((res) => {
        const list: TaskItem[] = res.data.tasks || res.data || []
        setTasks(list)
      })
      .catch(() => message.error(L.loading))
  }

  useEffect(() => { loadTasks() /* eslint-disable-line react-hooks/exhaustive-deps */ }, [locale])

  useEffect(() => {
    if (!selected) { setCfg(null); return }
    api.get(`/tasks/${selected}/config`)
      .then((res) => {
        setCfg(res.data)
        setCronText(res.data.cron || '')
        setEnabled(!!res.data.enabled)
        setImportResult(null)
      })
      .catch(() => message.error(L.loading))
  }, [selected, locale])

  const groups = useMemo(() => {
    const kw = search.trim().toLowerCase()
    const filtered = tasks.filter((t) => {
      if (!kw) return true
      return (t.task_id + ' ' + (t.name || '') + ' ' + (t.name_zh || '') + ' ' + (t.name_en || '')).toLowerCase().includes(kw)
    })
    const map = new Map<string, TaskItem[]>()
    filtered.forEach((t) => {
      const g = t.gateway || 'system'
      if (!map.has(g)) map.set(g, [])
      map.get(g)!.push(t)
    })
    return [...map.entries()]
  }, [tasks, search])

  const save = () => {
    if (!selected) return
    setSaving(true)
    api.post(`/tasks/${selected}/config`, { cron: cronText.trim() || undefined, enabled })
      .then((res) => {
        if (res.data && res.data.success === false) {
          message.error(L.saveFailed + ': ' + (res.data.error || ''))
        } else {
          message.success(L.saved)
          loadTasks()
          api.get(`/tasks/${selected}/config`).then((r) => setCfg(r.data))
        }
      })
      .catch((e) => message.error(L.saveFailed + ': ' + (e?.response?.data?.detail || '')))
      .finally(() => setSaving(false))
  }

  const exportOne = () => {
    if (!cfg) return
    downloadJson(`task_config_${cfg.task_id}.json`, cfg)
    message.success(L.exported)
  }

  const exportAll = () => {
    api.get('/tasks/config/export')
      .then((res) => {
        downloadJson(`task_config_all_${new Date().toISOString().slice(0, 10)}.json`, res.data)
        message.success(L.exported)
      })
      .catch(() => message.error(L.saveFailed))
  }

  const applyImport = () => {
    let parsed: unknown
    try {
      parsed = JSON.parse(importText)
    } catch {
      message.error(L.invalidJson)
      return
    }
    const configs = Array.isArray(parsed) ? parsed : (parsed as { configs?: unknown[] })?.configs
    if (!Array.isArray(configs)) {
      message.error(L.invalidJson)
      return
    }
    setImporting(true)
    api.post('/tasks/config/import', { configs })
      .then((res) => {
        const r = res.data
        setImportResult({ applied: r.applied || [], errors: r.errors || [] })
        if (r.errors && r.errors.length) message.warning(L.importFail)
        else message.success(L.importOk)
        loadTasks()
        if (selected) {
          api.get(`/tasks/${selected}/config`).then((rr) => {
            setCfg(rr.data); setCronText(rr.data.cron || ''); setEnabled(!!rr.data.enabled)
          })
        }
      })
      .catch(() => message.error(L.importFail))
      .finally(() => setImporting(false))
  }

  const inputStyle = { background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0, 217, 255,0.25)', color: WH.text }

  return (
    <div style={{ maxWidth: 'min(100%, 75rem)' }}>
      <Text style={{ color: WH.textMuted, fontSize: '0.8125rem' }}>{L.subtitle}</Text>
      <Row gutter={{ xs: 8, md: 16 }} style={{ marginTop: '0.875rem' }}>
        {/* 左：任务列表 */}
        <Col xs={24} md={9}>
          <Card size="small" styles={{ body: { padding: 'var(--wh-space-sm)', background: WH.bg } }}>
            <Input.Search
              allowClear placeholder={L.search} value={search} onChange={(e) => setSearch(e.target.value)}
              style={{ marginBottom: 'var(--wh-space-sm)' }} styles={{ input: inputStyle }}
            />
            <div style={{ maxHeight: 'calc(100vh - 320px)', overflow: 'auto', paddingRight: 'var(--wh-space-xs)' }}>
              {groups.length === 0 && <Text style={{ color: WH.textDim, fontSize: '0.75rem' }}>{L.noMatch}</Text>}
              {groups.map(([g, items]) => (
                <div key={g} style={{ marginBottom: '0.375rem' }}>
                  <Text style={{ color: WH.teal, fontSize: '0.6875rem', fontWeight: 600 }}>◈ {g} ({items.length})</Text>
                  <List
                    size="small" dataSource={items}
                    renderItem={(t) => (
                      <List.Item
                        onClick={() => setSelected(t.task_id)}
                        style={{
                          cursor: 'pointer', padding: 'var(--wh-space-xs) var(--wh-space-sm)', borderRadius: 'var(--wh-radius-sm)', marginTop: '0.125rem',
                          background: selected === t.task_id ? 'rgba(0, 217, 255,0.12)' : 'transparent',
                          border: selected === t.task_id ? '1px solid rgba(0, 217, 255,0.4)' : '1px solid transparent',
                        }}
                      >
                        <Space style={{ width: '100%', justifyContent: 'space-between', gap: '0.375rem' }}>
                          <span style={{ fontSize: '0.75rem', color: WH.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {locale === 'zh' ? (t.name_zh || t.name) : (t.name_en || t.name)}
                          </span>
                          <Tag color={t.enabled ? 'green' : 'red'} style={{ fontSize: '0.625rem', marginRight: 0 }}>
                            {t.enabled ? 'ON' : 'OFF'}
                          </Tag>
                        </Space>
                      </List.Item>
                    )}
                  />
                </div>
              ))}
            </div>
          </Card>
        </Col>

        {/* 右：配置面板 */}
        <Col xs={24} md={15}>
          {!cfg ? (
            <Card size="small" styles={{ body: { background: WH.bg, textAlign: 'center', padding: 'var(--wh-space-2xl)' } }}>
              <Text style={{ color: WH.textMuted }}>{L.selectHint}</Text>
            </Card>
          ) : (
            <Card
              size="small"
              title={<Text style={{ color: WH.text, fontSize: '0.875rem' }}>{cfg.name} <Text style={{ color: WH.textDim, fontSize: '0.75rem' }}>({cfg.task_id})</Text></Text>}
              styles={{ header: { background: 'var(--wh-page-bg)' }, body: { background: WH.bg } }}
            >
              <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
                <Text style={{ color: WH.textDim, fontSize: '0.75rem' }}>{L.desc}: {cfg.description || '-'}</Text>
              </div>
              <Space wrap style={{ marginBottom: '0.75rem', gap: 'var(--wh-space-sm)' }}>
                <Tag>{L.gateway}: {cfg.gateway || '-'}</Tag>
                <Tag>{L.defaultCron}: {cfg.default_cron || '-'}</Tag>
                {cfg.updated_at && <Tag color="blue">{L.updatedAt}: {String(cfg.updated_at).slice(0, 16).replace('T', ' ')}</Tag>}
              </Space>

              <Space direction="vertical" style={{ width: '100%', gap: 'var(--wh-space-sm)' }}>
                <div>
                  <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.cron}</Text>
                  <Input
                    value={cronText}
                    onChange={(e) => setCronText(e.target.value)}
                    placeholder="0 8 * * *"
                    style={{ marginTop: 'var(--wh-space-xs)', ...inputStyle }}
                  />
                  <Text style={{ color: WH.textDim, fontSize: '0.6875rem' }}>{L.cronHint}</Text>
                </div>
                <div>
                  <Space style={{ gap: 'var(--wh-space-sm)' }}>
                    <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.enabled}</Text>
                    <Switch checked={enabled} onChange={setEnabled} />
                    {cfg && (() => {
                      const t = tasks.find((x) => x.task_id === cfg.task_id)
                      return t?.next_run ? (
                        <Text style={{ color: WH.textDim, fontSize: '0.6875rem' }}>
                          {L.nextRun}: {String(t.next_run).slice(0, 16).replace('T', ' ')}
                        </Text>
                      ) : null
                    })()}
                  </Space>
                </div>
                <Space style={{ gap: 'var(--wh-space-sm)' }}>
                  <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save} style={{ background: WH.teal, borderColor: WH.teal }}>
                    {L.save}
                  </Button>
                  <Button icon={<DownloadOutlined />} onClick={exportOne}>{L.export}</Button>
                  <Button icon={<DownloadOutlined />} onClick={exportAll}>{L.exportAll}</Button>
                </Space>
              </Space>

              <Divider style={{ borderColor: 'rgba(0, 217, 255,0.15)', margin: '0.875rem 0' }} />
              <div>
                <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.importTitle}</Text>
                <Input.TextArea
                  rows={4} value={importText} onChange={(e) => setImportText(e.target.value)}
                  placeholder={L.importPlaceholder}
                  style={{ marginTop: 'var(--wh-space-xs)', ...inputStyle }}
                />
                <Space style={{ marginTop: '0.375rem', gap: 'var(--wh-space-sm)' }}>
                  <Upload
                    accept=".json,application/json" showUploadList={false} beforeUpload={(file) => {
                      file.text().then((txt) => setImportText(txt))
                      return false
                    }}
                  >
                    <Button icon={<UploadOutlined />} size="small">{zh ? '选择 .json 文件' : 'Pick .json'}</Button>
                  </Upload>
                  <Button type="primary" size="small" icon={<InboxOutlined />} loading={importing} onClick={applyImport}>
                    {L.importApply}
                  </Button>
                </Space>
                <Text style={{ color: WH.textDim, fontSize: '0.6875rem', display: 'block', marginTop: 'var(--wh-space-xs)' }}>{L.importHint}</Text>
                {importResult && (
                  <div style={{ marginTop: 'var(--wh-space-sm)' }}>
                    {importResult.applied.length > 0 && (
                      <Alert
                        type="success" showIcon style={{ marginBottom: '0.375rem' }}
                        message={`${L.applied}: ${importResult.applied.join(', ')}`}
                      />
                    )}
                    {importResult.errors.length > 0 && (
                      <Alert
                        type="error" showIcon
                        message={`${L.errors} (${importResult.errors.length})`}
                        description={importResult.errors.map((e) => `${e.task_id}: ${e.error}`).join('；')}
                      />
                    )}
                  </div>
                )}
              </div>

              {selected === 'cm_data_sync' && (
                <>
                  <Divider style={{ borderColor: 'rgba(0, 217, 255,0.15)', margin: '0.875rem 0' }} />
                  <div>
                    <Text style={{ color: WH.textMuted, fontSize: '0.75rem', fontWeight: 600 }}>
                      🗂️ {zh ? '网元配置（RAN CM 流程，来源 new_url.txt / cm_flows.json）' : 'NE Config (RAN CM flows)'}
                    </Text>
                    <div style={{ marginTop: '0.375rem', display: 'flex', gap: 'var(--wh-space-sm)', alignItems: 'center', flexWrap: 'wrap' }}>
                      <Select
                        style={{ width: 'min(100%, 12.5rem)' }}
                        value={cmFlowName || undefined}
                        onChange={selectCmFlow}
                        options={cmFlows.map((f) => ({ value: f.name, label: `${f.name} (${f.ne_count})` }))}
                      />
                      <Button size="small" icon={<DownloadOutlined />} onClick={exportCmFlows}>
                        {zh ? '导出流程配置' : 'Export flows'}
                      </Button>
                      <Button size="small" icon={<UploadOutlined />} onClick={() => setCmImportOpen(!cmImportOpen)}>
                        {zh ? '导入流程配置' : 'Import flows'}
                      </Button>
                    </div>
                    {cmFlowName && (
                      <div style={{ marginTop: 'var(--wh-space-sm)' }}>
                        <Text style={{ color: WH.textDim, fontSize: '0.6875rem' }}>
                          {zh ? '网元清单（SubNetwork=X,ManagedElement=Y）' : 'NE list'}
                        </Text>
                        <div style={{ marginTop: 'var(--wh-space-xs)' }}>
                          {cmNeList.map((ne, i) => (
                            <Tag
                              key={ne + '_' + i} closable
                              onClose={() => setCmNeList(cmNeList.filter((_, j) => j !== i))}
                              style={{ marginBottom: 'var(--wh-space-xs)' }}
                            >
                              {ne}
                            </Tag>
                          ))}
                          {cmNeList.length === 0 && (
                            <Text style={{ color: WH.textDim, fontSize: '0.6875rem' }}>{zh ? '（空）' : '(empty)'}</Text>
                          )}
                        </div>
                        <Space wrap style={{ marginTop: '0.375rem', gap: 'var(--wh-space-sm)' }}>
                          <Input
                            size="small" value={cmNewNe} onChange={(e) => setCmNewNe(e.target.value)}
                            placeholder="SubNetwork=1,ManagedElement=3"
                            onPressEnter={addCmNe}
                            style={{ width: 'min(100%, 16.25rem)', ...inputStyle }}
                          />
                          <Button size="small" onClick={addCmNe}>{zh ? '添加' : 'Add'}</Button>
                          <Button
                            size="small" type="primary" loading={cmSavingNe} onClick={saveCmNeList}
                            style={{ background: WH.teal, borderColor: WH.teal }}
                          >
                            {zh ? '保存网元清单' : 'Save NE list'}
                          </Button>
                        </Space>
                        <Text style={{ color: WH.textDim, fontSize: '0.6875rem', display: 'block', marginTop: 'var(--wh-space-xs)' }}>
                          {zh
                            ? '保存后写入 cm_flows.json 成为生效配置（new_url.txt 保留为参考）；网元失效时同步会自动跳过并在执行历史中记录具体原因。'
                            : 'Saving writes cm_flows.json as the effective config (new_url.txt kept as reference); invalid NEs are auto-skipped with reasons recorded in run history.'}
                        </Text>
                      </div>
                    )}
                    {cmImportOpen && (
                      <div style={{ marginTop: 'var(--wh-space-sm)' }}>
                        <Input.TextArea
                          rows={4} value={cmImportText} onChange={(e) => setCmImportText(e.target.value)}
                          placeholder='{"flows": [{"name": "SDR", "type": "exportvermo", "path": "/api/tpdatahandle/v1/exportmultivermofile", "payload": {"neList": [...]}}]}'
                          style={{ ...inputStyle }}
                        />
                        <Button
                          size="small" type="primary" loading={cmImporting} onClick={applyCmFlowImport}
                          style={{ marginTop: '0.375rem', background: WH.teal, borderColor: WH.teal }}
                        >
                          {zh ? '应用流程导入' : 'Apply flow import'}
                        </Button>
                        {cmImportResult && (
                          <div style={{ marginTop: 'var(--wh-space-sm)' }}>
                            {cmImportResult.applied.length > 0 && (
                              <Alert type="success" showIcon style={{ marginBottom: '0.375rem' }}
                                message={`${zh ? '已应用' : 'Applied'}: ${cmImportResult.applied.join(', ')}`} />
                            )}
                            {cmImportResult.errors.length > 0 && (
                              <Alert type="error" showIcon
                                message={`${zh ? '失败项' : 'Errors'} (${cmImportResult.errors.length})`}
                                description={cmImportResult.errors.map((e) => `${e.index}: ${e.error}`).join('；')} />
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </>
              )}
              {selected && cfgTasks.includes(selected) && (
                <TaskConfigFileEditor taskId={selected} zh={locale === 'zh'} />
              )}
            </Card>
          )}
        </Col>
      </Row>
    </div>
  )
}
