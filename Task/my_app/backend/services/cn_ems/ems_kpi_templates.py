# -*- coding: utf-8 -*-
"""
ems_kpi_templates.py — 从 Query_Template.xml 与 samples/*.xlsx 提取 KPI 模板定义。

数据来源:
  1. Query_Template.xml       — 模板名 / poid / moType / neTypeList (由用户提供)
  2. samples/<模板名>.xlsx    — "Index or Counter" sheet:
        KPI 行:   <KPI名> | <公式, 如 C409710006*100/C409710007>
        counter 行: C<poid><序号> | <counter 描述, 如 The Current User Number of HLR>
  3. 原始测量 XML (SFTP 下载) — counter 名 = <poid>.<描述, 空格替换为 ##@##>

映射关系 (已实测验证):
  C407410012  ==  poid 40741 家族第 12 个 counter ==  40741.Times##@##of##@##Receiving##@##ANC
  描述法:     描述 "Times of Receiving ANC" → 40741.Times##@##of##@##Receiving##@##ANC (一致)

公式变量:
  Gr = 天粒度秒数 = 86400
"""

import os
import re
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
XML_PATH = os.path.join(HERE, "Query_Template.xml")
SAMPLES_DIR = os.path.join(HERE, "samples")

_REF_RE = re.compile(r"C(\d{5})(\d{4})")   # C<poid5><idx4>
_OPS = ("*", "/", "+", "-", "(", ")", "Gr")


def parse_query_templates(xml_path=XML_PATH):
    """解析 Query_Template.xml, 返回 [{name, poid, moType, neTypes, kpiName}]"""
    templates = []
    # 文件是 GBK 编码
    raw = open(xml_path, "rb").read()
    try:
        text = raw.decode("gbk")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    # XML 声明可能 GBK; 手动剥掉声明后按 utf-8 解析不可靠, 直接正则+ET
    root = ET.fromstring(text)
    for q in root.findall("queryTemplate"):
        name = q.get("name")
        poid = None
        mo_type = None
        ne_types = []
        idx = q.find("index")
        if idx is not None:
            p = idx.find("poid")
            if p is not None and p.text:
                poid = p.text.strip()
            m = idx.find("moType")
            if m is not None and m.text:
                mo_type = m.text.strip()
            ntl = idx.find("neTypeList")
            if ntl is not None:
                for ne in ntl.findall("netype"):
                    if ne.get("id"):
                        ne_types.append(ne.get("id"))
        templates.append({
            "name": name, "poid": poid, "moType": mo_type, "neTypes": ne_types,
        })
    return templates


def _strip(s):
    return s.strip() if s else ""


def parse_sample_formula(xlsx_path):
    """解析 samples/<模板>.xlsx 的 'Index or Counter' sheet.

    返回: {kpi_name, formula, counters: {ref: desc}}
    """
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    sheet = None
    for sn in wb.sheetnames:
        if "Index" in sn or "Counter" in sn:
            sheet = wb[sn]
            break
    if sheet is None:
        sheet = wb[wb.sheetnames[0]]

    kpi_name = None
    formula = None
    counters = {}   # ref -> desc
    for row in sheet.iter_rows(values_only=True):
        if not row:
            continue
        a = _strip(str(row[0])) if row[0] is not None else ""
        b = _strip(str(row[1])) if len(row) > 1 and row[1] is not None else ""
        if not a:
            continue
        if a == "Index or Counter":
            continue
        m = _REF_RE.match(a)
        if m:
            counters[a] = b
            continue
        # 可能是 KPI 行: a=KPI名, b=公式 (含 C 引用)
        if _REF_RE.search(b) or b.strip() == "Gr" or "/Gr" in b:
            kpi_name = a
            formula = b
        else:
            # a 无 C 前缀但 b 无公式 → 可能是 KPI 名为 a, 无公式(单 counter)
            if kpi_name is None and _REF_RE.search(a) is False and not a.startswith("C"):
                kpi_name = a
    wb.close()
    return {"kpi_name": kpi_name, "formula": formula, "counters": counters}


def resolve_raw_counter_names(ref, desc, fallback_poid=None):
    """C<poid><idx> + 描述 → 可能的原始测量 XML counter 名列表.

    实测发现两种命名格式:
      1. 描述式: <poid>.<描述, 空格 → ##@##>  (MSC/USPP 等大多数)
         C407410012 -> 40741.Times##@##of##@##Receiving##@##ANC
      2. C引用式: <poid>.C<完整引用>           (xGW 等)
         C048680018 -> 04868.C048680018  (实际数据中 counter 名为 4868.C04868XXXX)
    """
    m = _REF_RE.match(ref)
    poid = m.group(1) if m else (fallback_poid or "")
    desc_name = desc.replace(" ", "##@##")
    names = [poid + "." + desc_name]
    # 也生成 C引用式
    names.append(poid + "." + ref)
    # poid 去前导零的变体
    poid_plain = str(int(poid)) if poid.isdigit() else poid
    if poid_plain != poid:
        names.append(poid_plain + "." + desc_name)
        names.append(poid_plain + "." + ref)
    return names


def tokenize_formula(formula):
    """把公式切成 token 列表: ['C407160012', '/', 'Gr'] 等"""
    if not formula:
        return []
    tokens = []
    i = 0
    n = len(formula)
    while i < n:
        ch = formula[i]
        if ch.isspace():
            i += 1
            continue
        # 识别 Gr 常量 (Gr = 粒度秒数)
        if formula[i:i+2] in ("Gr", "gr"):
            tokens.append("Gr")
            i += 2
            continue
        if ch.isdigit() or ch == 'C':
            j = i
            while j < n and (formula[j].isdigit() or formula[j] == 'C'):
                j += 1
            tokens.append(formula[i:j])
            i = j
            continue
        if ch in _OPS:
            tokens.append(ch)
            i += 1
            continue
        # 未知字符 (如 %)
        tokens.append(ch)
        i += 1
    return tokens


def formula_refs(formula):
    """公式中用到的所有 C 引用 (去重, 保持顺序)"""
    refs = []
    seen = set()
    for t in tokenize_formula(formula):
        if _REF_RE.match(t) and t not in seen:
            seen.add(t)
            refs.append(t)
    return refs


def evaluate_formula(formula, counter_values, gr=86400):
    """按公式计算 KPI.

    counter_values: {ref: 数值} (ref 如 C407160012), 未提供则视为 0
    gr: 天粒度秒数 (公式里的 Gr)
    返回 float 或 None(公式无法解析)
    """
    tokens = tokenize_formula(formula)
    if not tokens:
        return None
    # 转成可求值表达式
    expr = []
    for t in tokens:
        if t == "Gr":
            expr.append(str(float(gr)))
        elif _REF_RE.match(t):
            v = counter_values.get(t, 0)
            expr.append(str(float(v)))
        else:
            expr.append(t)
    try:
        return eval(" ".join(expr), {"__builtins__": {}}, {})
    except Exception:
        return None


if __name__ == "__main__":
    tpls = parse_query_templates()
    print("=== Query_Template.xml 模板 ===")
    for t in tpls:
        print("  %-36s poid=%-6s moType=%s neTypes=%s" % (
            t["name"], t["poid"], t["moType"], ",".join(t["neTypes"])))
    print("\n=== samples 公式 ===")
    for t in tpls:
        xp = os.path.join(SAMPLES_DIR, t["name"] + ".xlsx")
        if not os.path.exists(xp):
            print("  !! 缺样本: %s" % xp)
            continue
        s = parse_sample_formula(xp)
        print("  %-36s KPI=%-40s formula=%s" % (t["name"], s["kpi_name"], s["formula"]))
        for ref, desc in sorted(s["counters"].items()):
            print("      %s -> %s" % (ref, " / ".join(resolve_raw_counter_names(ref, desc, t["poid"]))))
