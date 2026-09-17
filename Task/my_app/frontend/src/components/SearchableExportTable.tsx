import type { HTMLAttributes } from 'react'
import { Button, Input, Table } from 'antd'
import { DownloadOutlined, SearchOutlined } from '@ant-design/icons'
import { useI18n } from '../i18n'

interface SearchableExportTableProps {
  /** 表格数据（已过滤） */
  data: any[]
  /** 表格列定义 */
  columns: any[]
  /** 搜索关键字（受控） */
  search: string
  /** 搜索关键字变更回调 */
  onSearchChange: (value: string) => void
  /** 导出按钮点击回调 */
  onExport: () => void
  /** 导出按钮文案（已翻译） */
  exportText: string
  /** 行 key 生成函数 */
  rowKey: (record: any, index?: number) => string
  /** 无障碍标签（描述本表格内容） */
  ariaLabel: string
  /** 行级属性；传 onClick 即可让整行可点击（下钻用），记得同时给 style.cursor='pointer' */
  onRow?: (record: any, index?: number) => HTMLAttributes<HTMLElement>
}

// 通用「搜索框 + 导出按钮 + 表格」组合，供下钻/明细类抽屉复用
export function SearchableExportTable({
  data, columns, search, onSearchChange, onExport, exportText, rowKey, ariaLabel, onRow,
}: SearchableExportTableProps) {
  const { t } = useI18n()
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', marginBottom: 'var(--wh-space-sm)' }}>
        <Input
          prefix={<SearchOutlined />}
          placeholder={t('table.searchPlaceholder')}
          allowClear
          size="small"
          style={{ width: 'min(100%, 15.625rem)' }}
          value={search}
          onChange={e => onSearchChange(e.target.value)}
          aria-label={`${ariaLabel} ${t('table.searchPlaceholder')}`}
        />
        <Button type="primary" size="small" icon={<DownloadOutlined />} onClick={onExport} aria-label={exportText}>
          {exportText}
        </Button>
      </div>
      <div className="wh-table-responsive">
        <Table
          dataSource={data}
          columns={columns}
          size="small"
          rowKey={rowKey}
          pagination={{ pageSize: 10, size: 'small', showTotal: (total: number) => `${total} items` }}
          scroll={{ x: 'max-content' }}
          aria-label={ariaLabel}
          onRow={onRow}
        />
      </div>
    </>
  )
}
