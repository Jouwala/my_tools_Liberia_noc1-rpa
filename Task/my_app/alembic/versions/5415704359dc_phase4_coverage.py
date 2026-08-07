"""phase4_coverage

Revision ID: 5415704359dc
Revises: 0002_task_queue
Create Date: 2026-08-07 20:56:08.802213

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from alembic import context


# revision identifiers, used by Alembic.
revision: str = '5415704359dc'
down_revision: Union[str, None] = '0002_task_queue'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None





def _table_exists(name: str) -> bool:
    """升级用表存在性检查：SQLite / PostgreSQL 通用。

    离线生成 SQL 时无法连接数据库，按『表不存在』处理以生成建表语句。
    """
    if context.is_offline_mode():
        return False
    bind = op.get_bind()
    return bind.dialect.has_table(bind, name)


def _table_exists_for_downgrade(name: str) -> bool:
    """回退用表存在性检查：离线生成 SQL 时按『表存在』处理以生成删表语句。"""
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    return bind.dialect.has_table(bind, name)



def upgrade() -> None:
    if not _table_exists('_metadata'):
        op.create_table('_metadata',
        sa.Column('table_name', sa.TEXT(), nullable=True),
        sa.Column('row_count', sa.INTEGER(), nullable=True),
        sa.Column('col_count', sa.INTEGER(), nullable=True),
        sa.Column('columns_json', sa.TEXT(), nullable=True)
        )
    if not _table_exists('era_sites'):
        op.create_table('era_sites',
        sa.Column('unnamed', sa.TEXT(), nullable=True),
        sa.Column('site_id', sa.TEXT(), nullable=True),
        sa.Column('site_name', sa.TEXT(), nullable=True),
        sa.Column('site_type', sa.TEXT(), nullable=True),
        sa.Column('tx', sa.TEXT(), nullable=True),
        sa.Column('comment', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_era_sites_site_id ON era_sites (site_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_era_sites_site_name ON era_sites (site_name)"))
    if not _table_exists('flm_database'):
        op.create_table('flm_database',
        sa.Column('site_name', sa.TEXT(), nullable=True),
        sa.Column('site_class', sa.TEXT(), nullable=True),
        sa.Column('site_id', sa.TEXT(), nullable=True),
        sa.Column('col_2g_id', sa.REAL(), nullable=True),
        sa.Column('col_3g_id', sa.REAL(), nullable=True),
        sa.Column('col_4g_id', sa.REAL(), nullable=True),
        sa.Column('county', sa.TEXT(), nullable=True),
        sa.Column('warehouse_dop', sa.TEXT(), nullable=True),
        sa.Column('warehouse_keeper', sa.TEXT(), nullable=True),
        sa.Column('current_orange_team', sa.TEXT(), nullable=True),
        sa.Column('area', sa.TEXT(), nullable=True),
        sa.Column('fme_plan', sa.TEXT(), nullable=True),
        sa.Column('eflow_account', sa.TEXT(), nullable=True),
        sa.Column('latitude', sa.REAL(), nullable=True),
        sa.Column('longitude', sa.REAL(), nullable=True),
        sa.Column('project_phase', sa.TEXT(), nullable=True),
        sa.Column('tower_type', sa.TEXT(), nullable=True),
        sa.Column('tower_height', sa.TEXT(), nullable=True),
        sa.Column('cluster', sa.TEXT(), nullable=True),
        sa.Column('col_4th_sector', sa.REAL(), nullable=True),
        sa.Column('fdn', sa.TEXT(), nullable=True),
        sa.Column('trm_type', sa.TEXT(), nullable=True),
        sa.Column('vip_sites_backbone', sa.TEXT(), nullable=True),
        sa.Column('hub_sites_y_n', sa.TEXT(), nullable=True),
        sa.Column('no_of_victims', sa.REAL(), nullable=True),
        sa.Column('victims_list', sa.TEXT(), nullable=True),
        sa.Column('site_type', sa.TEXT(), nullable=True),
        sa.Column('area_1', sa.TEXT(), nullable=True),
        sa.Column('site_priority', sa.TEXT(), nullable=True),
        sa.Column('col_2g_90', sa.TEXT(), nullable=True),
        sa.Column('col_3g_90', sa.TEXT(), nullable=True),
        sa.Column('col_4g_90', sa.TEXT(), nullable=True),
        sa.Column('质差站点', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_flm_database_site_id ON flm_database (site_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_flm_database_site_name ON flm_database (site_name)"))
    if not _table_exists('flm_team'):
        op.create_table('flm_team',
        sa.Column('unnamed_1', sa.TEXT(), nullable=True),
        sa.Column('unnamed_2', sa.TEXT(), nullable=True),
        sa.Column('unnamed_3', sa.TEXT(), nullable=True),
        sa.Column('unnamed_4', sa.TEXT(), nullable=True),
        sa.Column('unnamed_5', sa.TEXT(), nullable=True),
        sa.Column('unnamed_6', sa.TEXT(), nullable=True),
        sa.Column('unnamed_7', sa.TEXT(), nullable=True),
        sa.Column('unnamed_8', sa.TEXT(), nullable=True),
        sa.Column('unnamed_9', sa.TEXT(), nullable=True),
        sa.Column('unnamed_10', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    if not _table_exists('flm_team_information'):
        op.create_table('flm_team_information',
        sa.Column('unnamed_1', sa.TEXT(), nullable=True),
        sa.Column('unnamed_2', sa.TEXT(), nullable=True),
        sa.Column('unnamed_3', sa.TEXT(), nullable=True),
        sa.Column('unnamed_4', sa.TEXT(), nullable=True),
        sa.Column('unnamed_5', sa.TEXT(), nullable=True),
        sa.Column('unnamed_6', sa.TEXT(), nullable=True),
        sa.Column('unnamed_7', sa.TEXT(), nullable=True),
        sa.Column('unnamed_8', sa.TEXT(), nullable=True),
        sa.Column('unnamed_9', sa.TEXT(), nullable=True),
        sa.Column('unnamed_10', sa.TEXT(), nullable=True),
        sa.Column('unnamed_11', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    if not _table_exists('flm_team_new'):
        op.create_table('flm_team_new',
        sa.Column('unnamed_1', sa.TEXT(), nullable=True),
        sa.Column('unnamed_2', sa.TEXT(), nullable=True),
        sa.Column('unnamed_3', sa.TEXT(), nullable=True),
        sa.Column('unnamed_4', sa.TEXT(), nullable=True),
        sa.Column('unnamed_5', sa.TEXT(), nullable=True),
        sa.Column('unnamed_6', sa.TEXT(), nullable=True),
        sa.Column('unnamed_7', sa.TEXT(), nullable=True),
        sa.Column('unnamed_8', sa.TEXT(), nullable=True),
        sa.Column('unnamed_9', sa.TEXT(), nullable=True),
        sa.Column('unnamed_10', sa.TEXT(), nullable=True),
        sa.Column('unnamed_11', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    if not _table_exists('gateway_sites'):
        op.create_table('gateway_sites',
        sa.Column('sn', sa.INTEGER(), nullable=True),
        sa.Column('gateway', sa.TEXT(), nullable=True),
        sa.Column('county', sa.TEXT(), nullable=True),
        sa.Column('latitude', sa.REAL(), nullable=True),
        sa.Column('longitude', sa.REAL(), nullable=True),
        sa.Column('dependent_sites', sa.INTEGER(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    if not _table_exists('history_alarm'):
        op.create_table('history_alarm',
        sa.Column('moc', sa.TEXT(), nullable=True),
        sa.Column('site_status', sa.TEXT(), nullable=True),
        sa.Column('historyservertime', sa.INTEGER(), nullable=True),
        sa.Column('alarmcodestatistics', sa.TEXT(), nullable=True),
        sa.Column('networktype', sa.TEXT(), nullable=True),
        sa.Column('type', sa.TEXT(), nullable=True),
        sa.Column('auxiliarycount', sa.REAL(), nullable=True),
        sa.Column('clearstate', sa.INTEGER(), nullable=True),
        sa.Column('additionaltextzh', sa.TEXT(), nullable=True),
        sa.Column('alarmchangedtime', sa.INTEGER(), nullable=True),
        sa.Column('site_name', sa.TEXT(), nullable=True),
        sa.Column('alarm_source', sa.TEXT(), nullable=True),
        sa.Column('ackstatename', sa.TEXT(), nullable=True),
        sa.Column('id', sa.INTEGER(), nullable=True),
        sa.Column('mocname', sa.TEXT(), nullable=True),
        sa.Column('alarmkey', sa.TEXT(), nullable=True),
        sa.Column('createtypename', sa.TEXT(), nullable=True),
        sa.Column('yearofraised', sa.INTEGER(), nullable=True),
        sa.Column('link_path', sa.TEXT(), nullable=True),
        sa.Column('relatedmename4db', sa.TEXT(), nullable=True),
        sa.Column('col_2g_cells', sa.TEXT(), nullable=True),
        sa.Column('positionname', sa.TEXT(), nullable=True),
        sa.Column('reasoncode', sa.INTEGER(), nullable=True),
        sa.Column('assigned_time', sa.REAL(), nullable=True),
        sa.Column('assigned_user', sa.TEXT(), nullable=True),
        sa.Column('nbiid', sa.TEXT(), nullable=True),
        sa.Column('neip', sa.TEXT(), nullable=True),
        sa.Column('restypename', sa.TEXT(), nullable=True),
        sa.Column('clearinfo', sa.TEXT(), nullable=True),
        sa.Column('intermittenceduplicatedkey', sa.TEXT(), nullable=True),
        sa.Column('relationflag', sa.INTEGER(), nullable=True),
        sa.Column('dayofraisedtime', sa.TEXT(), nullable=True),
        sa.Column('clearsystemid', sa.TEXT(), nullable=True),
        sa.Column('aid', sa.TEXT(), nullable=True),
        sa.Column('originalreasontype', sa.TEXT(), nullable=True),
        sa.Column('append_ttid', sa.TEXT(), nullable=True),
        sa.Column('ran_site_type', sa.TEXT(), nullable=True),
        sa.Column('thana', sa.TEXT(), nullable=True),
        sa.Column('offsetalarmraisedtime', sa.INTEGER(), nullable=True),
        sa.Column('division', sa.TEXT(), nullable=True),
        sa.Column('district', sa.TEXT(), nullable=True),
        sa.Column('cleartype', sa.INTEGER(), nullable=True),
        sa.Column('naffiltered', sa.INTEGER(), nullable=True),
        sa.Column('mw_layer', sa.TEXT(), nullable=True),
        sa.Column('vendor', sa.TEXT(), nullable=True),
        sa.Column('timezoneid', sa.TEXT(), nullable=True),
        sa.Column('power_infomation', sa.TEXT(), nullable=True),
        sa.Column('assigned_status', sa.TEXT(), nullable=True),
        sa.Column('match_count', sa.REAL(), nullable=True),
        sa.Column('alarmcode', sa.INTEGER(), nullable=True),
        sa.Column('reason_type', sa.TEXT(), nullable=True),
        sa.Column('acksystemid', sa.TEXT(), nullable=True),
        sa.Column('commenttext', sa.TEXT(), nullable=True),
        sa.Column('sales_area', sa.TEXT(), nullable=True),
        sa.Column('sales_region', sa.TEXT(), nullable=True),
        sa.Column('sales_territory', sa.TEXT(), nullable=True),
        sa.Column('perceivedseverity', sa.INTEGER(), nullable=True),
        sa.Column('transmission_type', sa.TEXT(), nullable=True),
        sa.Column('additionaltexten', sa.TEXT(), nullable=True),
        sa.Column('site_id', sa.TEXT(), nullable=True),
        sa.Column('relationflagname', sa.TEXT(), nullable=True),
        sa.Column('assign_rulename', sa.TEXT(), nullable=True),
        sa.Column('hourofday', sa.INTEGER(), nullable=True),
        sa.Column('hourofraisedtime', sa.INTEGER(), nullable=True),
        sa.Column('col_5g_cells', sa.TEXT(), nullable=True),
        sa.Column('alarmraisedtime', sa.INTEGER(), nullable=True),
        sa.Column('ackuserid', sa.TEXT(), nullable=True),
        sa.Column('delay_flag', sa.TEXT(), nullable=True),
        sa.Column('acktime', sa.INTEGER(), nullable=True),
        sa.Column('platinum_site', sa.TEXT(), nullable=True),
        sa.Column('relatedrules', sa.TEXT(), nullable=True),
        sa.Column('weekofraisedtime', sa.INTEGER(), nullable=True),
        sa.Column('site_vip_level', sa.TEXT(), nullable=True),
        sa.Column('monthofraised', sa.INTEGER(), nullable=True),
        sa.Column('me', sa.TEXT(), nullable=True),
        sa.Column('site_attribute', sa.TEXT(), nullable=True),
        sa.Column('latest_match_time', sa.REAL(), nullable=True),
        sa.Column('createtype', sa.TEXT(), nullable=True),
        sa.Column('backup_type', sa.TEXT(), nullable=True),
        sa.Column('visible', sa.INTEGER(), nullable=True),
        sa.Column('tt_info', sa.TEXT(), nullable=True),
        sa.Column('servertime', sa.INTEGER(), nullable=True),
        sa.Column('respathtoken', sa.TEXT(), nullable=True),
        sa.Column('tt_id', sa.TEXT(), nullable=True),
        sa.Column('respath', sa.TEXT(), nullable=True),
        sa.Column('infrastructure_type', sa.TEXT(), nullable=True),
        sa.Column('dayandhour', sa.TEXT(), nullable=True),
        sa.Column('restype', sa.TEXT(), nullable=True),
        sa.Column('offsetalarmclearedtime', sa.INTEGER(), nullable=True),
        sa.Column('sequence', sa.INTEGER(), nullable=True),
        sa.Column('durationname', sa.TEXT(), nullable=True),
        sa.Column('first_match_time', sa.REAL(), nullable=True),
        sa.Column('intermittencecount', sa.INTEGER(), nullable=True),
        sa.Column('cell_name', sa.TEXT(), nullable=True),
        sa.Column('alarmtrace', sa.TEXT(), nullable=True),
        sa.Column('codename', sa.TEXT(), nullable=True),
        sa.Column('alarm_title', sa.TEXT(), nullable=True),
        sa.Column('alarmclearedtime', sa.INTEGER(), nullable=True),
        sa.Column('position', sa.TEXT(), nullable=True),
        sa.Column('assigned_type', sa.TEXT(), nullable=True),
        sa.Column('region', sa.TEXT(), nullable=True),
        sa.Column('maintain_status', sa.TEXT(), nullable=True),
        sa.Column('linkname', sa.TEXT(), nullable=True),
        sa.Column('alarmsource', sa.TEXT(), nullable=True),
        sa.Column('commenttime', sa.INTEGER(), nullable=True),
        sa.Column('clearuserid', sa.TEXT(), nullable=True),
        sa.Column('alarmtypename', sa.TEXT(), nullable=True),
        sa.Column('col_3g_cells', sa.TEXT(), nullable=True),
        sa.Column('power_maintainer', sa.TEXT(), nullable=True),
        sa.Column('link', sa.TEXT(), nullable=True),
        sa.Column('generator', sa.TEXT(), nullable=True),
        sa.Column('perceivedseverityname', sa.TEXT(), nullable=True),
        sa.Column('nmcreasoncode', sa.INTEGER(), nullable=True),
        sa.Column('dayofmonth', sa.INTEGER(), nullable=True),
        sa.Column('duration', sa.INTEGER(), nullable=True),
        sa.Column('commentuserid', sa.TEXT(), nullable=True),
        sa.Column('relatedruletype', sa.TEXT(), nullable=True),
        sa.Column('operations', sa.TEXT(), nullable=True),
        sa.Column('additionaltext', sa.TEXT(), nullable=True),
        sa.Column('admc', sa.INTEGER(), nullable=True),
        sa.Column('ackstate', sa.INTEGER(), nullable=True),
        sa.Column('pop_site', sa.TEXT(), nullable=True),
        sa.Column('assign_delay', sa.TEXT(), nullable=True),
        sa.Column('clearservertime', sa.INTEGER(), nullable=True),
        sa.Column('col_4g_cells', sa.TEXT(), nullable=True),
        sa.Column('mename', sa.TEXT(), nullable=True),
        sa.Column('alarmtype', sa.INTEGER(), nullable=True),
        sa.Column('admcname', sa.TEXT(), nullable=True),
        sa.Column('rootcount', sa.REAL(), nullable=True),
        sa.Column('subcenter', sa.TEXT(), nullable=True),
        sa.Column('circle', sa.TEXT(), nullable=True),
        sa.Column('commentsystemid', sa.TEXT(), nullable=True),
        sa.Column('cleartypename', sa.TEXT(), nullable=True),
        sa.Column('oss_specific_problem', sa.TEXT(), nullable=True),
        sa.Column('assign_start_time', sa.REAL(), nullable=True),
        sa.Column('ackinfo', sa.TEXT(), nullable=True),
        sa.Column('object_name', sa.TEXT(), nullable=True),
        sa.Column('site_class', sa.TEXT(), nullable=True),
        sa.Column('original_me', sa.TEXT(), nullable=True),
        sa.Column('cell', sa.TEXT(), nullable=True),
        sa.Column('originalspecificproblem', sa.TEXT(), nullable=True),
        sa.Column('province', sa.TEXT(), nullable=True),
        sa.Column('tenant', sa.TEXT(), nullable=True),
        sa.Column('neuid', sa.TEXT(), nullable=True),
        sa.Column('probe_name', sa.TEXT(), nullable=True),
        sa.Column('standardcode', sa.TEXT(), nullable=True),
        sa.Column('probeid', sa.TEXT(), nullable=True),
        sa.Column('vimrespool', sa.TEXT(), nullable=True),
        sa.Column('servicetype', sa.TEXT(), nullable=True),
        sa.Column('locationinfo', sa.TEXT(), nullable=True),
        sa.Column('smpim', sa.TEXT(), nullable=True),
        sa.Column('largearea', sa.TEXT(), nullable=True),
        sa.Column('smres', sa.TEXT(), nullable=True),
        sa.Column('menotfound', sa.TEXT(), nullable=True),
        sa.Column('smservarch', sa.TEXT(), nullable=True),
        sa.Column('smcimtenant', sa.TEXT(), nullable=True),
        sa.Column('smcim', sa.TEXT(), nullable=True),
        sa.Column('smregion', sa.TEXT(), nullable=True),
        sa.Column('pvflag', sa.TEXT(), nullable=True),
        sa.Column('smvimarch', sa.TEXT(), nullable=True),
        sa.Column('ns', sa.TEXT(), nullable=True),
        sa.Column('sbiversion', sa.TEXT(), nullable=True),
        sa.Column('standardname', sa.TEXT(), nullable=True),
        sa.Column('reasonname', sa.TEXT(), nullable=True),
        sa.Column('land', sa.TEXT(), nullable=True),
        sa.Column('alarmstandardid', sa.TEXT(), nullable=True),
        sa.Column('smnetype', sa.TEXT(), nullable=True),
        sa.Column('smcnodetype', sa.TEXT(), nullable=True),
        sa.Column('ran_type', sa.TEXT(), nullable=True),
        sa.Column('impact_site_list', sa.TEXT(), nullable=True),
        sa.Column('impact_site_number', sa.TEXT(), nullable=True),
        sa.Column('_sync_time', sa.TEXT(), nullable=True)
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_history_alarm_alarmraisedtime ON history_alarm (alarmraisedtime)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_history_alarm_region ON history_alarm (region)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_history_alarm_site_id ON history_alarm (site_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_history_alarm_tt_id ON history_alarm (tt_id)"))
    if not _table_exists('inband_details'):
        op.create_table('inband_details',
        sa.Column('Inbound No.', sa.TEXT(), nullable=True),
        sa.Column('Status', sa.TEXT(), nullable=True),
        sa.Column('Inbound Type', sa.TEXT(), nullable=True),
        sa.Column('Return To Original Warehouse', sa.TEXT(), nullable=True),
        sa.Column('Warehouse Name', sa.TEXT(), nullable=True),
        sa.Column('Supplement', sa.TEXT(), nullable=True),
        sa.Column('Request Time', sa.TEXT(), nullable=True),
        sa.Column('WarehouseId', sa.TEXT(), nullable=True),
        sa.Column('Description', sa.TEXT(), nullable=True),
        sa.Column('Material No.', sa.TEXT(), nullable=True),
        sa.Column('Serial No.', sa.TEXT(), nullable=True),
        sa.Column('Material Name', sa.TEXT(), nullable=True),
        sa.Column('Domain', sa.TEXT(), nullable=True),
        sa.Column('Sub Domain', sa.TEXT(), nullable=True),
        sa.Column('Material Type', sa.TEXT(), nullable=True),
        sa.Column('Material Manage Type', sa.TEXT(), nullable=True),
        sa.Column('Manage By Code', sa.TEXT(), nullable=True),
        sa.Column('Inbound Qty', sa.INTEGER(), nullable=True),
        sa.Column('Return Qty', sa.REAL(), nullable=True),
        sa.Column('Unit', sa.TEXT(), nullable=True),
        sa.Column('Location No.', sa.TEXT(), nullable=True),
        sa.Column('Location Name', sa.TEXT(), nullable=True),
        sa.Column('Material Status', sa.TEXT(), nullable=True),
        sa.Column('Ownership', sa.TEXT(), nullable=True),
        sa.Column('Material Manufacture', sa.REAL(), nullable=True),
        sa.Column('Price', sa.REAL(), nullable=True),
        sa.Column('Damage Description', sa.TEXT(), nullable=True),
        sa.Column('EECN', sa.REAL(), nullable=True),
        sa.Column('ECCN Status', sa.TEXT(), nullable=True),
        sa.Column('Scan Status', sa.TEXT(), nullable=True),
        sa.Column('Scan Failure Reason', sa.TEXT(), nullable=True),
        sa.Column('Vendor', sa.TEXT(), nullable=True),
        sa.Column('Revision', sa.REAL(), nullable=True),
        sa.Column('Material Remark', sa.TEXT(), nullable=True),
        sa.Column('PO Number', sa.REAL(), nullable=True),
        sa.Column('Category', sa.TEXT(), nullable=True),
        sa.Column('Received From', sa.TEXT(), nullable=True),
        sa.Column('Date Of Deliver', sa.TEXT(), nullable=True),
        sa.Column('Delivery Instructions', sa.TEXT(), nullable=True),
        sa.Column('Replacement Date', sa.TEXT(), nullable=True),
        sa.Column('Create Time', sa.TEXT(), nullable=True),
        sa.Column('Current Handler', sa.REAL(), nullable=True),
        sa.Column('Inbound Time', sa.TEXT(), nullable=True),
        sa.Column('Closed Time', sa.TEXT(), nullable=True),
        sa.Column('Verify Detail', sa.TEXT(), nullable=True),
        sa.Column('Update Detail', sa.TEXT(), nullable=True),
        sa.Column('Create Detail', sa.TEXT(), nullable=True),
        sa.Column('Confirm Detail', sa.TEXT(), nullable=True),
        sa.Column('Closed Detail', sa.TEXT(), nullable=True),
        sa.Column('update_time', sa.TEXT(), nullable=True),
        sa.Column('update_date', sa.TEXT(), nullable=True)
        )
    if not _table_exists('inventory_details'):
        op.create_table('inventory_details',
        sa.Column('Serial No.', sa.TEXT(), nullable=True),
        sa.Column('Material No.', sa.TEXT(), nullable=True),
        sa.Column('Material Name', sa.TEXT(), nullable=True),
        sa.Column('Material Status', sa.TEXT(), nullable=True),
        sa.Column('Warehouse Id', sa.TEXT(), nullable=True),
        sa.Column('Warehouse Name', sa.TEXT(), nullable=True),
        sa.Column('OwnerShip', sa.TEXT(), nullable=True),
        sa.Column('Domain', sa.TEXT(), nullable=True),
        sa.Column('Sub Domain', sa.TEXT(), nullable=True),
        sa.Column('ECCN Status', sa.TEXT(), nullable=True),
        sa.Column('Storage Age', sa.TEXT(), nullable=True),
        sa.Column('Material Manufacture', sa.TEXT(), nullable=True),
        sa.Column('Material Type', sa.TEXT(), nullable=True),
        sa.Column('Stock Qty', sa.INTEGER(), nullable=True),
        sa.Column('Unit ', sa.TEXT(), nullable=True),
        sa.Column('Damage Description', sa.TEXT(), nullable=True),
        sa.Column('ECCN', sa.TEXT(), nullable=True),
        sa.Column('Location Name', sa.TEXT(), nullable=True),
        sa.Column('Reserve Qty', sa.INTEGER(), nullable=True),
        sa.Column('Reserve Ticket No.', sa.TEXT(), nullable=True),
        sa.Column('update_time', sa.TEXT(), nullable=True),
        sa.Column('update_date', sa.TEXT(), nullable=True)
        )
    if not _table_exists('isp_sites'):
        op.create_table('isp_sites',
        sa.Column('nr', sa.INTEGER(), nullable=True),
        sa.Column('site_id', sa.REAL(), nullable=True),
        sa.Column('site_name', sa.TEXT(), nullable=True),
        sa.Column('province_county', sa.TEXT(), nullable=True),
        sa.Column('fme_name', sa.TEXT(), nullable=True),
        sa.Column('fme_contact_1', sa.TEXT(), nullable=True),
        sa.Column('fme_contact_2', sa.TEXT(), nullable=True),
        sa.Column('latitude', sa.REAL(), nullable=True),
        sa.Column('longitude', sa.REAL(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_isp_sites_site_id ON isp_sites (site_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_isp_sites_site_name ON isp_sites (site_name)"))
    if not _table_exists('landlord_sites'):
        op.create_table('landlord_sites',
        sa.Column('unnamed_1', sa.TEXT(), nullable=True),
        sa.Column('unnamed_2', sa.TEXT(), nullable=True),
        sa.Column('unnamed_3', sa.TEXT(), nullable=True),
        sa.Column('unnamed_4', sa.TEXT(), nullable=True),
        sa.Column('unnamed_5', sa.TEXT(), nullable=True),
        sa.Column('unnamed_6', sa.TEXT(), nullable=True),
        sa.Column('unnamed_7', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    if not _table_exists('master_site_db'):
        op.create_table('master_site_db',
        sa.Column('site_id', sa.INTEGER(), nullable=True),
        sa.Column('site_name', sa.TEXT(), nullable=True),
        sa.Column('gateway', sa.TEXT(), nullable=True),
        sa.Column('network_type', sa.TEXT(), nullable=True),
        sa.Column('region', sa.TEXT(), nullable=True),
        sa.Column('province_county', sa.TEXT(), nullable=True),
        sa.Column('fme_name', sa.TEXT(), nullable=True),
        sa.Column('fme_contact_1', sa.TEXT(), nullable=True),
        sa.Column('fme_contact_2', sa.TEXT(), nullable=True),
        sa.Column('supervisor', sa.TEXT(), nullable=True),
        sa.Column('latitude', sa.REAL(), nullable=True),
        sa.Column('longitude', sa.REAL(), nullable=True),
        sa.Column('trm_type', sa.TEXT(), nullable=True),
        sa.Column('site_type', sa.TEXT(), nullable=True),
        sa.Column('victims', sa.INTEGER(), nullable=True),
        sa.Column('victims_1', sa.TEXT(), nullable=True),
        sa.Column('vip_site', sa.TEXT(), nullable=True),
        sa.Column('hub_site', sa.TEXT(), nullable=True),
        sa.Column('aml_sites', sa.TEXT(), nullable=True),
        sa.Column('landlord_sites', sa.TEXT(), nullable=True),
        sa.Column('site_caregory', sa.TEXT(), nullable=True),
        sa.Column('power_vendor', sa.TEXT(), nullable=True),
        sa.Column('power_sources', sa.TEXT(), nullable=True),
        sa.Column('ms_or_project', sa.TEXT(), nullable=True),
        sa.Column('on_air_time', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_master_site_db_region ON master_site_db (region)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_master_site_db_site_id ON master_site_db (site_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_master_site_db_site_name ON master_site_db (site_name)"))
    if not _table_exists('ocrule_details'):
        op.create_table('ocrule_details',
        sa.Column('ruleName', sa.TEXT(), nullable=True),
        sa.Column('ruleType', sa.TEXT(), nullable=True),
        sa.Column('woType', sa.TEXT(), nullable=True),
        sa.Column('triggerStep', sa.TEXT(), nullable=True),
        sa.Column('rulePriority', sa.REAL(), nullable=True),
        sa.Column('targetHandlerName', sa.TEXT(), nullable=True),
        sa.Column('targetHandlerId', sa.TEXT(), nullable=True),
        sa.Column('status', sa.TEXT(), nullable=True),
        sa.Column('createTime', sa.TEXT(), nullable=True),
        sa.Column('updateTime', sa.TEXT(), nullable=True),
        sa.Column('createBy', sa.TEXT(), nullable=True),
        sa.Column('updateBy', sa.TEXT(), nullable=True),
        sa.Column('description', sa.TEXT(), nullable=True),
        sa.Column('update_time', sa.TEXT(), nullable=True),
        sa.Column('update_date', sa.TEXT(), nullable=True)
        )
    if not _table_exists('outband_details'):
        op.create_table('outband_details',
        sa.Column('Outbound No.', sa.TEXT(), nullable=True),
        sa.Column('Status', sa.TEXT(), nullable=True),
        sa.Column('Warehouse Name', sa.TEXT(), nullable=True),
        sa.Column('Outbound Type', sa.TEXT(), nullable=True),
        sa.Column('Need Repair Return', sa.TEXT(), nullable=True),
        sa.Column('Recipient', sa.TEXT(), nullable=True),
        sa.Column('Recipient Phone', sa.TEXT(), nullable=True),
        sa.Column('Supplement', sa.TEXT(), nullable=True),
        sa.Column('Request Time', sa.TEXT(), nullable=True),
        sa.Column('Related Ticket Type', sa.TEXT(), nullable=True),
        sa.Column('Description', sa.TEXT(), nullable=True),
        sa.Column('Repair Vendor', sa.TEXT(), nullable=True),
        sa.Column('Repair/Replace SLA', sa.REAL(), nullable=True),
        sa.Column('SLA Expected Finish Time', sa.TEXT(), nullable=True),
        sa.Column('Domain', sa.TEXT(), nullable=True),
        sa.Column('Location Name', sa.TEXT(), nullable=True),
        sa.Column('ECCN Status', sa.TEXT(), nullable=True),
        sa.Column('Sub Domain', sa.REAL(), nullable=True),
        sa.Column('Create Time', sa.TEXT(), nullable=True),
        sa.Column('Outbound Time', sa.TEXT(), nullable=True),
        sa.Column('Closed Time', sa.TEXT(), nullable=True),
        sa.Column('Borrow Duration', sa.REAL(), nullable=True),
        sa.Column('Related Ticket No.', sa.TEXT(), nullable=True),
        sa.Column('Related Ticket Site Id', sa.TEXT(), nullable=True),
        sa.Column('Related Ticket Title', sa.TEXT(), nullable=True),
        sa.Column('Related Ticket Create Time', sa.TEXT(), nullable=True),
        sa.Column('Related Ticket Status', sa.TEXT(), nullable=True),
        sa.Column('Serial No.', sa.TEXT(), nullable=True),
        sa.Column('Material No.', sa.TEXT(), nullable=True),
        sa.Column('Location No.', sa.TEXT(), nullable=True),
        sa.Column('Material Status', sa.TEXT(), nullable=True),
        sa.Column('Material Name', sa.TEXT(), nullable=True),
        sa.Column('Ownership', sa.TEXT(), nullable=True),
        sa.Column('Outbound Qty', sa.INTEGER(), nullable=True),
        sa.Column('Stock Qty', sa.INTEGER(), nullable=True),
        sa.Column('Unit', sa.TEXT(), nullable=True),
        sa.Column('Material Manage Type', sa.TEXT(), nullable=True),
        sa.Column('Specification', sa.REAL(), nullable=True),
        sa.Column('Material Param', sa.REAL(), nullable=True),
        sa.Column('Material Manufacture', sa.REAL(), nullable=True),
        sa.Column('Material Type', sa.TEXT(), nullable=True),
        sa.Column('Return Serial No.', sa.TEXT(), nullable=True),
        sa.Column('Damage Description', sa.TEXT(), nullable=True),
        sa.Column('Scan Status', sa.TEXT(), nullable=True),
        sa.Column('Scan Failure Reason', sa.TEXT(), nullable=True),
        sa.Column('Closed Detail', sa.TEXT(), nullable=True),
        sa.Column('Return Detail', sa.TEXT(), nullable=True),
        sa.Column('Confirm Detail', sa.TEXT(), nullable=True),
        sa.Column('Create Detail', sa.TEXT(), nullable=True),
        sa.Column('Update Detail', sa.TEXT(), nullable=True),
        sa.Column('Verify Detail', sa.TEXT(), nullable=True),
        sa.Column('update_time', sa.TEXT(), nullable=True),
        sa.Column('update_date', sa.TEXT(), nullable=True)
        )
    if not _table_exists('person'):
        op.create_table('person',
        sa.Column('objectid', sa.TEXT(), nullable=True),
        sa.Column('name', sa.TEXT(), nullable=True),
        sa.Column('gender', sa.TEXT(), nullable=True),
        sa.Column('address', sa.REAL(), nullable=True),
        sa.Column('nationality', sa.REAL(), nullable=True),
        sa.Column('phone', sa.TEXT(), nullable=True),
        sa.Column('phone_2', sa.REAL(), nullable=True),
        sa.Column('age', sa.REAL(), nullable=True),
        sa.Column('idnumber', sa.TEXT(), nullable=True),
        sa.Column('managed_regions', sa.TEXT(), nullable=True),
        sa.Column('email', sa.TEXT(), nullable=True),
        sa.Column('status', sa.TEXT(), nullable=True),
        sa.Column('remark', sa.TEXT(), nullable=True),
        sa.Column('datasource', sa.REAL(), nullable=True),
        sa.Column('domain', sa.REAL(), nullable=True),
        sa.Column('sub_company', sa.REAL(), nullable=True),
        sa.Column('skill', sa.REAL(), nullable=True),
        sa.Column('groups', sa.TEXT(), nullable=True),
        sa.Column('managedorganization', sa.TEXT(), nullable=True),
        sa.Column('exclude_dispach', sa.REAL(), nullable=True),
        sa.Column('sms_group', sa.REAL(), nullable=True),
        sa.Column('contractor', sa.TEXT(), nullable=True),
        sa.Column('department', sa.REAL(), nullable=True),
        sa.Column('office', sa.REAL(), nullable=True),
        sa.Column('longitude', sa.REAL(), nullable=True),
        sa.Column('latitude', sa.REAL(), nullable=True),
        sa.Column('position', sa.REAL(), nullable=True),
        sa.Column('sub_region_leader', sa.TEXT(), nullable=True),
        sa.Column('region_leader', sa.REAL(), nullable=True),
        sa.Column('skill1type', sa.REAL(), nullable=True),
        sa.Column('level1score', sa.REAL(), nullable=True),
        sa.Column('skill2type', sa.REAL(), nullable=True),
        sa.Column('level2score', sa.REAL(), nullable=True),
        sa.Column('skill3type', sa.REAL(), nullable=True),
        sa.Column('level3score', sa.REAL(), nullable=True),
        sa.Column('leavestatus', sa.TEXT(), nullable=True),
        sa.Column('_sync_time', sa.TEXT(), nullable=True)
        )
    op.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS u_person ON person (objectid)"))
    if not _table_exists('realtime_alarm'):
        op.create_table('realtime_alarm',
        sa.Column('moc', sa.TEXT(), nullable=True),
        sa.Column('site_status', sa.TEXT(), nullable=True),
        sa.Column('networktype', sa.TEXT(), nullable=True),
        sa.Column('type', sa.TEXT(), nullable=True),
        sa.Column('auxiliarycount', sa.REAL(), nullable=True),
        sa.Column('clearstate', sa.INTEGER(), nullable=True),
        sa.Column('alarmchangedtime', sa.INTEGER(), nullable=True),
        sa.Column('alarm_source', sa.TEXT(), nullable=True),
        sa.Column('site_name', sa.TEXT(), nullable=True),
        sa.Column('ackstatename', sa.TEXT(), nullable=True),
        sa.Column('id', sa.INTEGER(), nullable=True),
        sa.Column('mocname', sa.TEXT(), nullable=True),
        sa.Column('alarmkey', sa.TEXT(), nullable=True),
        sa.Column('link_path', sa.TEXT(), nullable=True),
        sa.Column('col_2g_cells', sa.TEXT(), nullable=True),
        sa.Column('positionname', sa.TEXT(), nullable=True),
        sa.Column('reasoncode', sa.INTEGER(), nullable=True),
        sa.Column('nbiid', sa.TEXT(), nullable=True),
        sa.Column('neip', sa.TEXT(), nullable=True),
        sa.Column('restypename', sa.TEXT(), nullable=True),
        sa.Column('intermittenceduplicatedkey', sa.TEXT(), nullable=True),
        sa.Column('relationflag', sa.INTEGER(), nullable=True),
        sa.Column('aid', sa.TEXT(), nullable=True),
        sa.Column('originalreasontype', sa.TEXT(), nullable=True),
        sa.Column('ran_site_type', sa.TEXT(), nullable=True),
        sa.Column('offsetalarmraisedtime', sa.INTEGER(), nullable=True),
        sa.Column('thana', sa.TEXT(), nullable=True),
        sa.Column('division', sa.TEXT(), nullable=True),
        sa.Column('district', sa.TEXT(), nullable=True),
        sa.Column('naffiltered', sa.INTEGER(), nullable=True),
        sa.Column('mw_layer', sa.TEXT(), nullable=True),
        sa.Column('vendor', sa.TEXT(), nullable=True),
        sa.Column('timezoneid', sa.TEXT(), nullable=True),
        sa.Column('assigned_status', sa.TEXT(), nullable=True),
        sa.Column('power_infomation', sa.TEXT(), nullable=True),
        sa.Column('match_count', sa.REAL(), nullable=True),
        sa.Column('alarmcode', sa.INTEGER(), nullable=True),
        sa.Column('reason_type', sa.TEXT(), nullable=True),
        sa.Column('acksystemid', sa.TEXT(), nullable=True),
        sa.Column('commenttext', sa.TEXT(), nullable=True),
        sa.Column('sales_area', sa.TEXT(), nullable=True),
        sa.Column('sales_region', sa.TEXT(), nullable=True),
        sa.Column('sales_territory', sa.TEXT(), nullable=True),
        sa.Column('perceivedseverity', sa.INTEGER(), nullable=True),
        sa.Column('transmission_type', sa.TEXT(), nullable=True),
        sa.Column('site_id', sa.TEXT(), nullable=True),
        sa.Column('relationflagname', sa.TEXT(), nullable=True),
        sa.Column('assign_rulename', sa.TEXT(), nullable=True),
        sa.Column('col_5g_cells', sa.TEXT(), nullable=True),
        sa.Column('alarmraisedtime', sa.INTEGER(), nullable=True),
        sa.Column('ackuserid', sa.TEXT(), nullable=True),
        sa.Column('delay_flag', sa.TEXT(), nullable=True),
        sa.Column('acktime', sa.INTEGER(), nullable=True),
        sa.Column('platinum_site', sa.TEXT(), nullable=True),
        sa.Column('relatedrules', sa.TEXT(), nullable=True),
        sa.Column('site_vip_level', sa.TEXT(), nullable=True),
        sa.Column('me', sa.TEXT(), nullable=True),
        sa.Column('latest_match_time', sa.REAL(), nullable=True),
        sa.Column('site_attribute', sa.TEXT(), nullable=True),
        sa.Column('backup_type', sa.TEXT(), nullable=True),
        sa.Column('visible', sa.INTEGER(), nullable=True),
        sa.Column('servertime', sa.INTEGER(), nullable=True),
        sa.Column('respath', sa.TEXT(), nullable=True),
        sa.Column('infrastructure_type', sa.TEXT(), nullable=True),
        sa.Column('restype', sa.TEXT(), nullable=True),
        sa.Column('sequence', sa.INTEGER(), nullable=True),
        sa.Column('durationname', sa.TEXT(), nullable=True),
        sa.Column('first_match_time', sa.REAL(), nullable=True),
        sa.Column('intermittencecount', sa.INTEGER(), nullable=True),
        sa.Column('cell_name', sa.TEXT(), nullable=True),
        sa.Column('codename', sa.TEXT(), nullable=True),
        sa.Column('alarm_title', sa.TEXT(), nullable=True),
        sa.Column('position', sa.TEXT(), nullable=True),
        sa.Column('maintain_status', sa.TEXT(), nullable=True),
        sa.Column('region', sa.TEXT(), nullable=True),
        sa.Column('linkname', sa.TEXT(), nullable=True),
        sa.Column('alarmsource', sa.TEXT(), nullable=True),
        sa.Column('commenttime', sa.INTEGER(), nullable=True),
        sa.Column('alarmtypename', sa.TEXT(), nullable=True),
        sa.Column('col_3g_cells', sa.TEXT(), nullable=True),
        sa.Column('link', sa.TEXT(), nullable=True),
        sa.Column('power_maintainer', sa.TEXT(), nullable=True),
        sa.Column('generator', sa.TEXT(), nullable=True),
        sa.Column('perceivedseverityname', sa.TEXT(), nullable=True),
        sa.Column('nmcreasoncode', sa.INTEGER(), nullable=True),
        sa.Column('commentuserid', sa.TEXT(), nullable=True),
        sa.Column('relatedruletype', sa.TEXT(), nullable=True),
        sa.Column('operations', sa.TEXT(), nullable=True),
        sa.Column('ackstate', sa.INTEGER(), nullable=True),
        sa.Column('additionaltext', sa.TEXT(), nullable=True),
        sa.Column('admc', sa.INTEGER(), nullable=True),
        sa.Column('pop_site', sa.TEXT(), nullable=True),
        sa.Column('assign_delay', sa.TEXT(), nullable=True),
        sa.Column('clearstatename', sa.TEXT(), nullable=True),
        sa.Column('col_4g_cells', sa.TEXT(), nullable=True),
        sa.Column('mename', sa.TEXT(), nullable=True),
        sa.Column('alarmtype', sa.INTEGER(), nullable=True),
        sa.Column('admcname', sa.TEXT(), nullable=True),
        sa.Column('subcenter', sa.TEXT(), nullable=True),
        sa.Column('circle', sa.TEXT(), nullable=True),
        sa.Column('commentsystemid', sa.TEXT(), nullable=True),
        sa.Column('cleartypename', sa.TEXT(), nullable=True),
        sa.Column('oss_specific_problem', sa.TEXT(), nullable=True),
        sa.Column('ackinfo', sa.TEXT(), nullable=True),
        sa.Column('object_name', sa.TEXT(), nullable=True),
        sa.Column('site_class', sa.TEXT(), nullable=True),
        sa.Column('original_me', sa.TEXT(), nullable=True),
        sa.Column('ran_type', sa.TEXT(), nullable=True),
        sa.Column('cell', sa.TEXT(), nullable=True),
        sa.Column('assigned_time', sa.REAL(), nullable=True),
        sa.Column('assigned_user', sa.TEXT(), nullable=True),
        sa.Column('append_ttid', sa.TEXT(), nullable=True),
        sa.Column('tt_info', sa.TEXT(), nullable=True),
        sa.Column('assigned_type', sa.TEXT(), nullable=True),
        sa.Column('assign_start_time', sa.REAL(), nullable=True),
        sa.Column('tt_id', sa.TEXT(), nullable=True),
        sa.Column('originalspecificproblem', sa.TEXT(), nullable=True),
        sa.Column('province', sa.TEXT(), nullable=True),
        sa.Column('tenant', sa.TEXT(), nullable=True),
        sa.Column('neuid', sa.TEXT(), nullable=True),
        sa.Column('probe_name', sa.TEXT(), nullable=True),
        sa.Column('standardcode', sa.TEXT(), nullable=True),
        sa.Column('probeid', sa.TEXT(), nullable=True),
        sa.Column('vimrespool', sa.TEXT(), nullable=True),
        sa.Column('servicetype', sa.TEXT(), nullable=True),
        sa.Column('locationinfo', sa.TEXT(), nullable=True),
        sa.Column('smpim', sa.TEXT(), nullable=True),
        sa.Column('largearea', sa.TEXT(), nullable=True),
        sa.Column('smres', sa.TEXT(), nullable=True),
        sa.Column('menotfound', sa.TEXT(), nullable=True),
        sa.Column('smservarch', sa.TEXT(), nullable=True),
        sa.Column('smcimtenant', sa.TEXT(), nullable=True),
        sa.Column('smcim', sa.TEXT(), nullable=True),
        sa.Column('smregion', sa.TEXT(), nullable=True),
        sa.Column('pvflag', sa.TEXT(), nullable=True),
        sa.Column('smvimarch', sa.TEXT(), nullable=True),
        sa.Column('ns', sa.TEXT(), nullable=True),
        sa.Column('sbiversion', sa.TEXT(), nullable=True),
        sa.Column('standardname', sa.TEXT(), nullable=True),
        sa.Column('reasonname', sa.TEXT(), nullable=True),
        sa.Column('land', sa.TEXT(), nullable=True),
        sa.Column('alarmstandardid', sa.TEXT(), nullable=True),
        sa.Column('smnetype', sa.TEXT(), nullable=True),
        sa.Column('smcnodetype', sa.TEXT(), nullable=True),
        sa.Column('_sync_time', sa.TEXT(), nullable=True)
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_realtime_alarm_alarmraisedtime ON realtime_alarm (alarmraisedtime)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_realtime_alarm_site_id ON realtime_alarm (site_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_realtime_alarm_site_name ON realtime_alarm (site_name)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_realtime_alarm_tt_id ON realtime_alarm (tt_id)"))
    if not _table_exists('satellite_sites'):
        op.create_table('satellite_sites',
        sa.Column('unnamed_1', sa.TEXT(), nullable=True),
        sa.Column('unnamed_2', sa.TEXT(), nullable=True),
        sa.Column('unnamed_3', sa.TEXT(), nullable=True),
        sa.Column('unnamed_4', sa.TEXT(), nullable=True),
        sa.Column('unnamed_5', sa.TEXT(), nullable=True),
        sa.Column('unnamed_6', sa.TEXT(), nullable=True),
        sa.Column('unnamed_7', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    if not _table_exists('sla_priority'):
        op.create_table('sla_priority',
        sa.Column('unnamed_2', sa.TEXT(), nullable=True),
        sa.Column('unnamed_3', sa.TEXT(), nullable=True),
        sa.Column('unnamed_4', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    if not _table_exists('special_sites'):
        op.create_table('special_sites',
        sa.Column('nr', sa.INTEGER(), nullable=True),
        sa.Column('site_name', sa.TEXT(), nullable=True),
        sa.Column('province_county', sa.TEXT(), nullable=True),
        sa.Column('fme_name', sa.TEXT(), nullable=True),
        sa.Column('fme_contact_1', sa.TEXT(), nullable=True),
        sa.Column('fme_contact_2', sa.TEXT(), nullable=True),
        sa.Column('latitude', sa.REAL(), nullable=True),
        sa.Column('longitude', sa.REAL(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_special_sites_site_name ON special_sites (site_name)"))
    if not _table_exists('startlink_era_sites'):
        op.create_table('startlink_era_sites',
        sa.Column('ne_id', sa.INTEGER(), nullable=True),
        sa.Column('ne_name', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    if not _table_exists('topology'):
        op.create_table('topology',
        sa.Column('id', sa.INTEGER(), nullable=True),
        sa.Column('site_a_id', sa.TEXT(), nullable=True),
        sa.Column('site_a_name', sa.TEXT(), nullable=True),
        sa.Column('site_b_id', sa.TEXT(), nullable=True),
        sa.Column('site_b_name', sa.TEXT(), nullable=True),
        sa.Column('hop_count', sa.INTEGER(), nullable=True),
        sa.Column('hop_path', sa.TEXT(), nullable=True),
        sa.Column('a_is_hub', sa.INTEGER(), server_default=sa.text('0'), nullable=True),
        sa.Column('b_is_hub', sa.INTEGER(), server_default=sa.text('0'), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_topology_site_a ON topology (site_a_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_topology_site_b ON topology (site_b_id)"))
    if not _table_exists('transfer_details'):
        op.create_table('transfer_details',
        sa.Column('update_time', sa.TEXT(), nullable=True),
        sa.Column('update_date', sa.TEXT(), nullable=True)
        )
    if not _table_exists('victim_topology'):
        op.create_table('victim_topology',
        sa.Column('sn', sa.INTEGER(), nullable=True),
        sa.Column('site_id', sa.INTEGER(), nullable=True),
        sa.Column('site_name', sa.TEXT(), nullable=True),
        sa.Column('victim_list', sa.TEXT(), nullable=True),
        sa.Column('victim_count', sa.INTEGER(), nullable=True),
        sa.Column('gw', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_victim_topology_site_id ON victim_topology (site_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_victim_topology_site_name ON victim_topology (site_name)"))
    if not _table_exists('vip_site_list'):
        op.create_table('vip_site_list',
        sa.Column('sn', sa.INTEGER(), nullable=True),
        sa.Column('site_id', sa.INTEGER(), nullable=True),
        sa.Column('site_name', sa.TEXT(), nullable=True),
        sa.Column('network_type', sa.TEXT(), nullable=True),
        sa.Column('region', sa.TEXT(), nullable=True),
        sa.Column('province_county', sa.TEXT(), nullable=True),
        sa.Column('victims', sa.INTEGER(), nullable=True),
        sa.Column('victims_1', sa.TEXT(), nullable=True),
        sa.Column('_source_file', sa.TEXT(), nullable=True),
        sa.Column('_source_sheet', sa.TEXT(), nullable=True),
        sa.Column('_import_time', sa.TEXT(), nullable=True)
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_vip_site_list_region ON vip_site_list (region)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_vip_site_list_site_id ON vip_site_list (site_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_vip_site_list_site_name ON vip_site_list (site_name)"))


def downgrade() -> None:
    if _table_exists_for_downgrade('vip_site_list'):
        op.drop_table('vip_site_list')
    if _table_exists_for_downgrade('victim_topology'):
        op.drop_table('victim_topology')
    if _table_exists_for_downgrade('transfer_details'):
        op.drop_table('transfer_details')
    if _table_exists_for_downgrade('topology'):
        op.drop_table('topology')
    if _table_exists_for_downgrade('startlink_era_sites'):
        op.drop_table('startlink_era_sites')
    if _table_exists_for_downgrade('special_sites'):
        op.drop_table('special_sites')
    if _table_exists_for_downgrade('sla_priority'):
        op.drop_table('sla_priority')
    if _table_exists_for_downgrade('satellite_sites'):
        op.drop_table('satellite_sites')
    if _table_exists_for_downgrade('realtime_alarm'):
        op.drop_table('realtime_alarm')
    if _table_exists_for_downgrade('person'):
        op.drop_table('person')
    if _table_exists_for_downgrade('outband_details'):
        op.drop_table('outband_details')
    if _table_exists_for_downgrade('ocrule_details'):
        op.drop_table('ocrule_details')
    if _table_exists_for_downgrade('master_site_db'):
        op.drop_table('master_site_db')
    if _table_exists_for_downgrade('landlord_sites'):
        op.drop_table('landlord_sites')
    if _table_exists_for_downgrade('isp_sites'):
        op.drop_table('isp_sites')
    if _table_exists_for_downgrade('inventory_details'):
        op.drop_table('inventory_details')
    if _table_exists_for_downgrade('inband_details'):
        op.drop_table('inband_details')
    if _table_exists_for_downgrade('history_alarm'):
        op.drop_table('history_alarm')
    if _table_exists_for_downgrade('gateway_sites'):
        op.drop_table('gateway_sites')
    if _table_exists_for_downgrade('flm_team_new'):
        op.drop_table('flm_team_new')
    if _table_exists_for_downgrade('flm_team_information'):
        op.drop_table('flm_team_information')
    if _table_exists_for_downgrade('flm_team'):
        op.drop_table('flm_team')
    if _table_exists_for_downgrade('flm_database'):
        op.drop_table('flm_database')
    if _table_exists_for_downgrade('era_sites'):
        op.drop_table('era_sites')
    if _table_exists_for_downgrade('_metadata'):
        op.drop_table('_metadata')
