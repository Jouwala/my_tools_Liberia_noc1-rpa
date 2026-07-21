import pandas as pd
import os
import sys
import re

# 解决 Windows CMD 中文输出编码问题
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "report")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# 1. 接网后接收的备件详细清单（Inbound）
# ─────────────────────────────────────────────
def generate_inbound_report():
    df = pd.read_excel(os.path.join(DATA_DIR, "spinbound.xlsx"))

    # 筛选关键字段
    cols = [
        "Inbound No.", "Status", "Inbound Type",
        "Warehouse Name", "Domain", "Sub Domain",
        "Material No.", "Serial No.", "Material Name",
        "Material Type", "Inbound Qty", "Unit",
        "Location No.", "Location Name", "Material Status",
        "Ownership", "Received From", "Date Of Deliver",
        "Request Time", "Inbound Time", "Closed Time",
    ]
    report = df[[c for c in cols if c in df.columns]].copy()

    # 按 Inbound Time 排序（有值的在前）
    if "Inbound Time" in report.columns:
        report = report.sort_values("Inbound Time", na_position="last").reset_index(drop=True)

    out_path = os.path.join(OUTPUT_DIR, "1_inbound_received_parts.xlsx")
    report.to_excel(out_path, index=False, sheet_name="Inbound Parts")

    total = len(report)
    qty_col = "Inbound Qty" if "Inbound Qty" in report.columns else None
    total_qty = report[qty_col].sum() if qty_col else "N/A"
    print(f"[完成] 1. 接收备件清单: {total} 条记录, 总数量: {total_qty}")
    print(f"       输出: {out_path}")
    return report


# ─────────────────────────────────────────────
# 2. 到目前为止已经使用的备件详细清单（Outbound）
# ─────────────────────────────────────────────
def generate_outbound_report():
    df = pd.read_excel(os.path.join(DATA_DIR, "spoutbound.xlsx"))

    cols = [
        "Outbound No.", "Status", "Outbound Type",
        "Warehouse Name", "Domain", "Sub Domain",
        "Material No.", "Serial No.", "Material Name",
        "Material Type", "Outbound Qty", "Unit",
        "Location No.", "Location Name", "Material Status",
        "Ownership", "Recipient", "Related Ticket Type",
        "Related Ticket No.", "Related Ticket Site Id",
        "Request Time", "Outbound Time", "Closed Time",
        "Borrow Duration", "Damage Description",
    ]
    report = df[[c for c in cols if c in df.columns]].copy()

    if "Outbound Time" in report.columns:
        report = report.sort_values("Outbound Time", na_position="last").reset_index(drop=True)

    out_path = os.path.join(OUTPUT_DIR, "2_outbound_used_parts.xlsx")
    report.to_excel(out_path, index=False, sheet_name="Outbound Parts")

    total = len(report)
    qty_col = "Outbound Qty" if "Outbound Qty" in report.columns else None
    total_qty = report[qty_col].sum() if qty_col else "N/A"
    print(f"[完成] 2. 已使用备件清单: {total} 条记录, 总数量: {total_qty}")
    print(f"       输出: {out_path}")
    return report


# ─────────────────────────────────────────────
# 3. 当前库存详细清单（Inventory）
# ─────────────────────────────────────────────
def generate_inventory_report():
    df = pd.read_excel(os.path.join(DATA_DIR, "spinventory.xlsx"))

    cols = [
        "Serial No.", "part_type", "Material No.", "Material Name",
        "material_type", "Material Status", "Warehouse Id", "Warehouse Name",
        "OwnerShip", "Domain", "Sub Domain",
        "Material Type", "Stock Qty", "Unit ",
        "Location Name", "Storage Age",
        "Material Manufacture", "Damage Description",
        "Reserve Qty", "Reserve Ticket No.",
    ]
    report = df[[c for c in cols if c in df.columns]].copy()

    # 按仓库 + 位置排序
    sort_cols = [c for c in ["Warehouse Name", "Location Name", "Material No."] if c in report.columns]
    if sort_cols:
        report = report.sort_values(sort_cols).reset_index(drop=True)

    out_path = os.path.join(OUTPUT_DIR, "3_current_inventory.xlsx")
    report.to_excel(out_path, index=False, sheet_name="Current Inventory")

    total = len(report)
    qty_col = "Stock Qty" if "Stock Qty" in report.columns else None
    total_qty = report[qty_col].sum() if qty_col else "N/A"
    unique_materials = report["Material No."].nunique() if "Material No." in report.columns else "N/A"
    print(f"[完成] 3. 当前库存清单: {total} 条记录, 总库存数量: {total_qty}, 不同物料编号: {unique_materials}")
    print(f"       输出: {out_path}")
    return report


# ─────────────────────────────────────────────
# 汇总统计
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# 4. 按 Material Type 汇总统计（入库/出库/库存）
# ─────────────────────────────────────────────
def normalize_sn(sn):
    """去除 SN 中的仓库/仓位后缀，统一为标准格式"""
    s = str(sn).strip()
    # 去掉形如 -Monrovia Warehouse_01-0101, -Gbarnga DOP_01-0101 等后缀
    s = re.sub(r'-[A-Za-z][\w ]*_\d+-\d+$', '', s)
    return s


def generate_material_type_summary():
    df_in  = pd.read_excel(os.path.join(DATA_DIR, "spinbound.xlsx"))
    df_out = pd.read_excel(os.path.join(DATA_DIR, "spoutbound.xlsx"))
    df_inv = pd.read_excel(os.path.join(DATA_DIR, "spinventory.xlsx"))

    inbound_sum  = df_in.groupby("Material Type")["Inbound Qty"].sum().rename("Inbound Qty")
    outbound_sum = df_out.groupby("Material Type")["Outbound Qty"].sum().rename("Outbound Qty")
    stock_sum    = df_inv.groupby("Material Type")["Stock Qty"].sum().rename("Stock Qty")

    summary = pd.concat([inbound_sum, outbound_sum, stock_sum], axis=1).fillna(0).astype(int)
    summary.index.name = "Material Type"

    # 差异 = 库存 - (入库 - 出库)
    summary["Diff"] = summary["Stock Qty"] - (summary["Inbound Qty"] - summary["Outbound Qty"])
    summary = summary.sort_values("Stock Qty", ascending=False).reset_index()

    # 添加合计行
    total_row = pd.DataFrame([{
        "Material Type": "合计",
        "Inbound Qty": summary["Inbound Qty"].sum(),
        "Outbound Qty": summary["Outbound Qty"].sum(),
        "Stock Qty": summary["Stock Qty"].sum(),
        "Diff": summary["Diff"].sum(),
    }])
    summary = pd.concat([summary, total_row], ignore_index=True)

    out_path = os.path.join(OUTPUT_DIR, "4_material_type_summary.xlsx")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="Material Type Summary")

        # ── 归一化SN集合 ──
        in_sns_norm  = {normalize_sn(s) for s in df_in["Serial No."].dropna().astype(str)}
        out_sns_norm = {normalize_sn(s) for s in df_out["Serial No."].dropna().astype(str)}
        inv_sns_norm = {normalize_sn(s) for s in df_inv["Serial No."].dropna().astype(str)}

        # ── Sheet A：库存有，无入库记录（Diff正方向，使库存多出）──
        diff_plus_rows = []
        for _, row in df_inv.iterrows():
            sn_raw  = str(row["Serial No."]) if pd.notna(row["Serial No."]) else ""
            sn_norm = normalize_sn(sn_raw)
            if sn_norm not in in_sns_norm:
                in_out = sn_norm in out_sns_norm
                diff_plus_rows.append({
                    "Serial No.": sn_raw,
                    "Serial No.(标准化)": sn_norm,
                    "Material No.": row.get("Material No.", ""),
                    "Material Name": row.get("Material Name", ""),
                    "Material Type": row.get("Material Type", ""),
                    "Domain": row.get("Domain", ""),
                    "Stock Qty": row.get("Stock Qty", 0),
                    "Unit": row.get("Unit ", ""),
                    "Material Status": row.get("Material Status", ""),
                    "Warehouse Name": row.get("Warehouse Name", ""),
                    "Location Name": row.get("Location Name", ""),
                    "Ownership": row.get("OwnerShip", ""),
                    "Storage Age": row.get("Storage Age", ""),
                    "Damage Description": row.get("Damage Description", ""),
                    "差异原因": "有出库记录，无入库记录（疑似入库数据缺失）" if in_out
                                else "库存有，入库/出库均无记录（疑似初始库存未录入或调拨未记录）",
                })
        diff_plus_df = pd.DataFrame(diff_plus_rows) if diff_plus_rows else pd.DataFrame()
        if len(diff_plus_df) > 0:
            diff_plus_df = diff_plus_df.sort_values(["Material Type", "Stock Qty"], ascending=[True, False])
        diff_plus_df.to_excel(writer, index=False, sheet_name="A_库存多_无入库记录")

        # ── Sheet B：入库有，但不在库存也不在出库（Diff负方向，使库存少了）──
        diff_minus_rows = []
        for _, row in df_in.iterrows():
            sn_raw  = str(row["Serial No."]) if pd.notna(row["Serial No."]) else ""
            sn_norm = normalize_sn(sn_raw)
            if sn_norm not in inv_sns_norm and sn_norm not in out_sns_norm:
                diff_minus_rows.append({
                    "Serial No.": sn_raw,
                    "Material No.": row.get("Material No.", ""),
                    "Material Name": row.get("Material Name", ""),
                    "Material Type": row.get("Material Type", ""),
                    "Domain": row.get("Domain", ""),
                    "Inbound Qty": row.get("Inbound Qty", 0),
                    "Unit": row.get("Unit", ""),
                    "Inbound Type": row.get("Inbound Type", ""),
                    "Inbound No.": row.get("Inbound No.", ""),
                    "Warehouse Name": row.get("Warehouse Name", ""),
                    "Location Name": row.get("Location Name", ""),
                    "Ownership": row.get("Ownership", ""),
                    "Material Status": row.get("Material Status", ""),
                    "Inbound Time": row.get("Inbound Time", ""),
                    "差异原因": "已入库，但库存和出库均无记录（疑似丢失或数据未同步）",
                })
        diff_minus_df = pd.DataFrame(diff_minus_rows) if diff_minus_rows else pd.DataFrame()
        if len(diff_minus_df) > 0:
            diff_minus_df = diff_minus_df.sort_values(["Material Type", "Inbound Qty"], ascending=[True, False])
        diff_minus_df.to_excel(writer, index=False, sheet_name="B_入库有_不在库存")

        # ── Sheet C：未解释残差（SN在入库和库存都存在，但数量对不上）──
        # 按归一化SN汇总三表数量（用DataFrame避免MultiIndex问题）
        _in = df_in[["Serial No.", "Material Type", "Inbound Qty"]].copy()
        _in["_sn"] = _in["Serial No."].astype(str).apply(normalize_sn)
        in_by_sn = _in.groupby(["_sn", "Material Type"])["Inbound Qty"].sum().reset_index().rename(columns={"Inbound Qty": "in_qty"})

        _out = df_out[["Serial No.", "Material Type", "Outbound Qty"]].copy()
        _out["_sn"] = _out["Serial No."].astype(str).apply(normalize_sn)
        out_by_sn = _out.groupby(["_sn", "Material Type"])["Outbound Qty"].sum().reset_index().rename(columns={"Outbound Qty": "out_qty"})

        _inv = df_inv[["Serial No.", "Material Type", "Stock Qty"]].copy()
        _inv["_sn"] = _inv["Serial No."].astype(str).apply(normalize_sn)
        inv_by_sn = _inv.groupby(["_sn", "Material Type"])["Stock Qty"].sum().reset_index().rename(columns={"Stock Qty": "stk_qty"})

        # 合并三表
        merged = in_by_sn.merge(inv_by_sn, on=["_sn", "Material Type"], how="inner")
        merged = merged.merge(out_by_sn, on=["_sn", "Material Type"], how="left")
        merged["out_qty"] = merged["out_qty"].fillna(0).astype(int)
        merged["expected"] = merged["in_qty"] - merged["out_qty"]
        merged["residual"] = merged["stk_qty"] - merged["expected"]

        # 只保留残差不为0的
        c_data = merged[merged["residual"] != 0].copy()

        # 补充详细信息
        sn_detail = df_inv.copy()
        sn_detail["_sn"] = sn_detail["Serial No."].astype(str).apply(normalize_sn)
        detail = sn_detail.groupby("_sn").agg(
            mat_no=("Material No.", "first"),
            mat_name=("Material Name", "first"),
            domain=("Domain", "first"),
            wh_names=("Warehouse Name", lambda x: ", ".join(x.dropna().unique())),
            loc_names=("Location Name", lambda x: ", ".join(x.dropna().unique())),
        ).reset_index()

        c_data = c_data.merge(detail, on="_sn", how="left")
        c_data["差异原因"] = c_data.apply(
            lambda r: f"SN同时存在入库和库存，但数量不一致（入库{r['in_qty']}-出库{r['out_qty']}={r['expected']}，实际库存{r['stk_qty']}）", axis=1)

        diff_c_df = c_data[["_sn", "mat_no", "mat_name", "Material Type", "domain",
                             "in_qty", "out_qty", "expected", "stk_qty", "residual",
                             "wh_names", "loc_names", "差异原因"]].rename(columns={
            "_sn": "Serial No.(标准化)", "mat_no": "Material No.", "mat_name": "Material Name",
            "domain": "Domain", "in_qty": "Inbound Qty(入库)", "out_qty": "Outbound Qty(出库)",
            "expected": "Expected(入库-出库)", "stk_qty": "Stock Qty(实际库存)",
            "residual": "C_残差(库存-预期)", "wh_names": "Warehouse Name", "loc_names": "Location Name",
        })
        diff_c_df = diff_c_df.sort_values(["Material Type", "C_残差(库存-预期)"], ascending=[True, False])
        diff_c_df.to_excel(writer, index=False, sheet_name="C_未解释残差_数量不一致")

        # ── Sheet 对账总表：按 Material Type 拆解差异 ──
        plus_by_type  = diff_plus_df.groupby("Material Type")["Stock Qty"].sum().rename("A_库存多(无入库)") if len(diff_plus_df) > 0 else pd.Series(dtype=int, name="A_库存多(无入库)")
        minus_by_type = diff_minus_df.groupby("Material Type")["Inbound Qty"].sum().rename("B_入库多(不在库存)") if len(diff_minus_df) > 0 else pd.Series(dtype=int, name="B_入库多(不在库存)")
        c_by_type     = diff_c_df.groupby("Material Type")["C_残差(库存-预期)"].sum().rename("C_数量不一致") if len(diff_c_df) > 0 else pd.Series(dtype=int, name="C_数量不一致")

        all_types = sorted(set(plus_by_type.index) | set(minus_by_type.index) | set(c_by_type.index))
        reconcile = pd.DataFrame({"Material Type": all_types}).set_index("Material Type")
        reconcile["A_库存多(无入库)"]   = plus_by_type.reindex(reconcile.index).fillna(0).astype(int)
        reconcile["B_入库多(不在库存)"] = minus_by_type.reindex(reconcile.index).fillna(0).astype(int)
        reconcile["C_数量不一致"]       = c_by_type.reindex(reconcile.index).fillna(0).astype(int)
        reconcile["A-B+C(SN级合计)"]   = reconcile["A_库存多(无入库)"] - reconcile["B_入库多(不在库存)"] + reconcile["C_数量不一致"]
        diff_map = summary.set_index("Material Type")["Diff"].to_dict()
        reconcile["Summary Diff"]       = reconcile.index.map(lambda x: diff_map.get(x, 0)).astype(int)
        reconcile["D_其他未追溯"]       = reconcile["Summary Diff"] - reconcile["A-B+C(SN级合计)"]
        reconcile["是否对上"]           = reconcile.apply(
            lambda r: "✓" if r["A_库存多(无入库)"] - r["B_入库多(不在库存)"] + r["C_数量不一致"] + r["D_其他未追溯"] == r["Summary Diff"] else "✗", axis=1)
        reconcile = reconcile.reset_index()

        rec_total = pd.DataFrame([{
            "Material Type": "合计",
            "A_库存多(无入库)": reconcile["A_库存多(无入库)"].sum(),
            "B_入库多(不在库存)": reconcile["B_入库多(不在库存)"].sum(),
            "C_数量不一致": reconcile["C_数量不一致"].sum(),
            "A-B+C(SN级合计)": reconcile["A-B+C(SN级合计)"].sum(),
            "Summary Diff": reconcile["Summary Diff"].sum(),
            "D_其他未追溯": reconcile["D_其他未追溯"].sum(),
            "是否对上": "✓",
        }])
        reconcile = pd.concat([reconcile, rec_total], ignore_index=True)
        reconcile.to_excel(writer, index=False, sheet_name="对账总表")

    print(f"\n[完成] 4. Material Type 汇总统计:")
    print(summary.to_string(index=False))
    print(f"\n  Sheet '对账总表':")
    print(reconcile.to_string(index=False))
    print(f"\n  A_库存多(无入库): {len(diff_plus_df)} 条")
    print(f"  B_入库多(不在库存): {len(diff_minus_df)} 条")
    print(f"  C_未解释残差(数量不一致): {len(diff_c_df)} 条")
    print(f"\n       输出: {out_path}")
    return summary


def print_summary(inbound, outbound, inventory):
    print("\n" + "=" * 60)
    print("                    汇 总 统 计")
    print("=" * 60)

    # 入库统计
    print(f"\n【入库 Inbound】")
    print(f"  总记录数 : {len(inbound)}")
    if "Inbound Type" in inbound.columns:
        type_counts = inbound["Inbound Type"].value_counts()
        for t, c in type_counts.items():
            print(f"    - {t}: {c} 条")
    if "Domain" in inbound.columns:
        print(f"  按 Domain:")
        for d, c in inbound["Domain"].value_counts().items():
            print(f"    - {d}: {c} 条")

    # 出库统计
    print(f"\n【出库 Outbound】")
    print(f"  总记录数 : {len(outbound)}")
    if "Outbound Type" in outbound.columns:
        type_counts = outbound["Outbound Type"].value_counts()
        for t, c in type_counts.items():
            print(f"    - {t}: {c} 条")
    if "Domain" in outbound.columns:
        print(f"  按 Domain:")
        for d, c in outbound["Domain"].value_counts(dropna=False).items():
            print(f"    - {d}: {c} 条")

    # 库存统计
    print(f"\n【当前库存 Inventory】")
    print(f"  总记录数 : {len(inventory)}")
    if "Material Status" in inventory.columns:
        status_counts = inventory["Material Status"].value_counts()
        for s, c in status_counts.items():
            print(f"    - {s}: {c} 条")
    if "Warehouse Name" in inventory.columns:
        print(f"  按仓库:")
        for w, c in inventory["Warehouse Name"].value_counts().items():
            print(f"    - {w}: {c} 条")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    print("正在生成备件统计报表...\n")
    inbound = generate_inbound_report()
    outbound = generate_outbound_report()
    inventory = generate_inventory_report()
    print_summary(inbound, outbound, inventory)
    generate_material_type_summary()
    print("\n所有报表已保存到 report/ 目录下。")
