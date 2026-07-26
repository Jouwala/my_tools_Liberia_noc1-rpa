import pandas as pd
import os

base_dir = r'd:\Dong\pythonproject2026\Tools\Unified_Tools'

mappings = {
    'WareHouseDashBoard_CG': {
        'inband_details': [
            ('入库类型/whinType', 'Inbound Type'),
            ('入库单号/woNum', 'Inbound No.'),
            ('状态/status', 'Status'),
            ('创建时间/createTime', 'Inbound Time'),
            ('仓库/warehouseID', 'Warehouse Name'),
        ],
        'outband_details': [
            ('ticketNum/ticketNum', 'Outbound No.'),
            ('单据状态/status', 'Status'),
            ('出库单类型/whoutType', 'Outbound Type'),
            ('outboundTime/outboundTime', 'Outbound Time'),
            ('仓库/warehouseID', 'Warehouse Name'),
        ],
        'inventory_details': [
            ('Serial No.', 'Serial No.'),
            ('Material Type', 'Material Type'),
            ('update_date', 'update_date'),
            ('Warehouse Name', 'Warehouse Name'),
            ('update_time', 'update_time'),
        ],
    },
    'WareHouseDashBoard_UG': {
        'inband_details': [
            ('In Stock Number', 'Inbound No.'),
            ('Status', 'Status'),
            ('Confirm Time', 'Inbound Time'),
            ('Warehouse Name', 'Warehouse Name'),
            ('In Stock Type', 'Inbound Type'),
            ('Quantity', 'Inbound Qty'),
        ],
        'outband_details': [
            ('Out Stock Number', 'Outbound No.'),
            ('Status', 'Status'),
            ('Confirm Time', 'Outbound Time'),
            ('Warehouse Name', 'Warehouse Name'),
            ('Out Type', 'Outbound Type'),
            ('Quantity', 'Stock Qty'),
        ],
        'inventory_details': [
            ('Serial No.', 'Serial No.'),
            ('Material Type', 'Material Type'),
            ('update_date', 'update_date'),
            ('Warehouse Name', 'Warehouse Name'),
            ('update_time', 'update_time'),
        ],
    },
    'WareHouseDashBoard_NPL': {
        'inband_details': [
            ('Order Number/woNum', 'Inbound No.'),
            ('Status/status', 'Status'),
            ('Create Time/createTime', 'Inbound Time'),
            ('Warehouse/warehouseID', 'Warehouse Name'),
            ('Type/whinType', 'Inbound Type'),
            ('Material Num/materialNum', 'Inbound Qty'),
        ],
        'outband_details': [
            ('Order Number/woNum', 'Outbound No.'),
            ('Status/status', 'Status'),
            ('Outbound Time/outboundTime', 'Outbound Time'),
            ('Warehouse/warehouseID', 'Warehouse Name'),
            ('Outstock Type/whoutType', 'Outbound Type'),
            ('Material Num/materialNum', 'Stock Qty'),
        ],
        'inventory_details': [
            ('Serial No.', 'Serial No.'),
            ('Material Type', 'Material Type'),
            ('update_date', 'update_date'),
            ('Warehouse Name', 'Warehouse Name'),
            ('update_time', 'update_time'),
        ],
    },
    'WareHouseDashBoard_MMR': {
        'inband_details': [
            ('Order Number/woNum', 'Inbound No.'),
            ('Status/status', 'Status'),
            ('Create Time/createTime', 'Inbound Time'),
            ('Warehouse/warehouseID', 'Warehouse Name'),
            ('Type/whinType', 'Inbound Type'),
            ('Material Num/materialNum', 'Inbound Qty'),
        ],
        'outband_details': [
            ('Order Number/woNum', 'Outbound No.'),
            ('Status/status', 'Status'),
            ('Outbound Time/outboundTime', 'Outbound Time'),
            ('Warehouse/warehouseID', 'Warehouse Name'),
            ('Outstock Type/whoutType', 'Outbound Type'),
            ('Material Num/materialNum', 'Stock Qty'),
        ],
        'inventory_details': [
            ('Serial No.', 'Serial No.'),
            ('Material Type', 'Material Type'),
            ('update_date', 'update_date'),
            ('Warehouse Name', 'Warehouse Name'),
            ('update_time', 'update_time'),
        ],
    },
}

for folder, tables in mappings.items():
    rows = []
    for table_name, columns in tables.items():
        for column_name, mapping_name in columns:
            rows.append({
                'db_table_name': table_name,
                'column_name': column_name,
                'column_mapping_name': mapping_name,
            })
    
    df = pd.DataFrame(rows)
    output_dir = os.path.join(base_dir, folder, 'detect_column_name')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'column_mapping.xlsx')
    df.to_excel(output_path, index=False)
    print(f'Created: {output_path}')

print('Done!')
