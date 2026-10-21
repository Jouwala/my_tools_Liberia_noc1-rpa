# -*- coding: utf-8 -*-
"""GIS 根因聚合服务（gis_rca_service）的纯函数测试，不访问数据库。

覆盖：空输入早退形状 / A 簇最深祖先归属（两级故障不互相吞）/ 范围外根因标注 /
B 簇 10 分钟时间窗 / C 簇 impact_site_list 兼容解析（sid + 站名、分号逗号）/
cause_type 关键词优先级 / LLM 降级路径。
"""
import unittest

from backend.services import gis_rca_service as svc

T0 = 1_700_000_000_000  # 固定基准时间（毫秒）


def _row(sid, *, title="2G site down", path="--", raised=T0, tt="", osp="",
         impact="", impact_num=None, rootcount=None, name=None, sev="Critical"):
    return {
        "site_id": str(sid),
        "site_name": name or f"S{sid}",
        "region": "R1",
        "province_county": "",
        "alarm_title": title,
        "alarmcode": "9980",
        "oss_specific_problem": osp or title,
        "tt_id": tt,
        "severity": sev,
        "raised_ms": raised,
        "link_path": path,
        "transmission_type": "Satellite Link" if path == "--" else "MW",
        "mw_layer": "1",
        "impact_site_list": impact,
        "impact_site_number": impact_num,
        "rootcount": rootcount,
    }


def _fixture():
    """拓扑：100(核心) → 200(中间) → {210, 211}(叶子)；300/301/302 卫星站。

    100 与 200 同时在告警 —— 验证「每个断站只归属最深告警祖先」：
      200 归 100；210/211 归 200（而不是被远端的 100 吞掉）。
    """
    rows = [
        # 核心站 100：传输中断，自带 impact 清单（逗号分隔，只匹配到 200）
        _row(100, title="MW LINK DOWN", path="100", raised=T0 - 600_000,
             impact="200,9999", impact_num=2, name="Alpha"),
        # 中间站 200：断电；其 impact 清单用分号 + 站名混排（210 是 sid、Delta 是 211 的站名）
        _row(200, title="SITE OUTAGE DUE TO POWER OFF", path="100>200",
             raised=T0, impact="210;Delta", impact_num=2, name="Bravo"),
        # 叶子站：2 分钟后跟着断（验证时间贴近加分）
        _row(210, path="100>200>210", raised=T0 + 120_000, name="Charlie"),
        _row(211, path="100>200>211", raised=T0 + 130_000, name="Delta"),
        # 卫星站：300/301 同窗（5 分钟内）成 B 簇；302 晚 25 分钟应被切到新窗
        _row(300, path="--", raised=T0 + 300_000, name="Echo"),
        _row(301, path="--", raised=T0 + 600_000, name="Foxtrot"),
        _row(302, path="--", raised=T0 + 1_800_000, name="Golf"),
    ]
    site_info = {
        str(r["site_id"]): {"site_name": r["site_name"], "lat": 1.0, "lng": 2.0, "region": "R1"}
        for r in rows
    }
    # 范围内排除 100（核心，验证范围外根因标注）与 302（验证窗口切割后不落单成簇）
    in_scope = {"200", "210", "211", "300", "301"}
    return rows, in_scope, site_info


class ChainAndParsingTest(unittest.TestCase):
    def test_chain_of_variants(self):
        self.assertEqual(svc._chain_of("4542>3297>4070"), ["4542", "3297", "4070"])
        self.assertEqual(svc._chain_of("--"), [])
        self.assertEqual(svc._chain_of(""), [])
        self.assertEqual(svc._chain_of(None), [])
        # 非数字 token 被剔除，不参与祖先匹配
        self.assertEqual(svc._chain_of("a>100>200"), ["100", "200"])

    def test_parse_impact_mixed_separators(self):
        sids, names = svc._parse_impact("200, 210;Charlie Delta\n9")
        self.assertEqual(sids, ["200", "210", "9"])
        self.assertEqual(names, ["Charlie", "Delta"])

    def test_cause_type_priority_power_over_site_outage(self):
        # "SITE OUTAGE DUE TO POWER OFF" 的真实根因是电源：POWER 必须压过 SITE OUTAGE
        self.assertEqual(svc._cause_type_of(["SITE OUTAGE DUE TO POWER OFF"]), "power")
        self.assertEqual(svc._cause_type_of(["MW LINK DOWN"]), "transmission")
        self.assertEqual(svc._cause_type_of(["Fiber Break"]), "fiber")
        self.assertEqual(svc._cause_type_of(["2G site down"]), "site_outage")
        self.assertEqual(svc._cause_type_of(["anything else"]), "other")


class ComputeRcaTest(unittest.TestCase):
    def test_empty_input_shape(self):
        out = svc.compute_rca([], set(), {})
        self.assertEqual(out["clusters"], [])
        self.assertTrue(out["meta"]["empty"])
        self.assertEqual(out["meta"]["alarm_rows"], 0)

    def test_deepest_ancestor_and_two_level_faults(self):
        rows, in_scope, info = _fixture()
        out = svc.compute_rca(rows, in_scope, info)
        clusters = {c["cluster_id"]: c for c in out["clusters"]}

        # 210/211 归 200（最深告警祖先），而不是被 100 吞掉
        c200 = clusters["topo:200"]
        self.assertEqual({m["site_id"] for m in c200["members"]}, {"210", "211"})
        self.assertEqual(c200["cause_type"], "power")
        self.assertTrue(c200["root_in_scope"])

        # 200 自身又是 100 的下游：两级故障各成一簇，不互相合并
        c100 = clusters["topo:100"]
        self.assertEqual({m["site_id"] for m in c100["members"]}, {"200"})
        self.assertEqual(c100["cause_type"], "transmission")
        # 100 不在筛选范围内 → 完整展示 + 范围外标注（用户已定决策）
        self.assertFalse(c100["root_in_scope"])
        self.assertFalse(c100["root"]["in_scope"])

    def test_same_cause_window_and_exclusion(self):
        rows, in_scope, info = _fixture()
        out = svc.compute_rca(rows, in_scope, info)
        same = [c for c in out["clusters"] if c["kind"] == "same_cause"]
        # 300/301 同窗成簇；302 晚 25 分钟落进新窗、单站不成簇
        self.assertEqual(len(same), 1)
        self.assertEqual({m["site_id"] for m in same[0]["members"]}, {"300", "301"})
        self.assertEqual(same[0]["evidence"]["shared_problem"], "2G site down")
        # B 簇无链路 → 不在 members 里塞 link_path 证据
        self.assertEqual(same[0]["evidence"]["link_paths"], [])

    def test_eflow_impact_corroboration(self):
        rows, in_scope, info = _fixture()
        out = svc.compute_rca(rows, in_scope, info)
        clusters = {c["cluster_id"]: c for c in out["clusters"]}
        # 200 的 impact "210;Delta"（sid + 站名混排）应命中 210 与 211
        ev = clusters["topo:200"]["evidence"]["eflow_impact"]
        self.assertIsNotNone(ev)
        self.assertEqual(set(ev["matched_members"]), {"210", "211"})
        # eFlow 佐证把置信度抬到拓扑簇上限
        self.assertEqual(clusters["topo:200"]["confidence"], 0.95)
        # 100 的 impact "200,9999" 只命中 200（9999 无对应站，不该误配）
        ev100 = clusters["topo:100"]["evidence"]["eflow_impact"]
        self.assertEqual(ev100["matched_members"], ["200"])

    def test_meta_caliber(self):
        rows, in_scope, info = _fixture()
        meta = svc.compute_rca(rows, in_scope, info)["meta"]
        self.assertEqual(meta["alarm_rows"], 7)
        self.assertEqual(meta["alarmed_sites"], 7)
        self.assertEqual(meta["in_scope_sites"], 5)
        self.assertEqual(meta["with_link_path"], 3)      # 200/210/211
        self.assertEqual(meta["satellite_sites"], 2)      # 300/301（302 范围外）
        self.assertEqual(meta["topology_clusters"], 2)
        self.assertEqual(meta["same_cause_clusters"], 1)
        self.assertFalse(meta["empty"])
        self.assertFalse(meta["truncated"])

    def test_members_carry_alarm_fields(self):
        rows, in_scope, info = _fixture()
        # 新行**故意不带 path**（默认 '--'）：链路是站点属性，任一行有链即可归属
        # —— 验证行间容错（首警恰好是缺路径行也不能让站点错失拓扑簇）。
        rows.append(_row(210, title="3G site down", raised=T0 + 90_000, tt="TT1"))
        out = svc.compute_rca(rows, in_scope, info)
        c200 = {c["cluster_id"]: c for c in out["clusters"]}["topo:200"]
        m210 = next(m for m in c200["members"] if m["site_id"] == "210")
        self.assertEqual(m210["alarm_count"], 2)
        self.assertEqual(m210["tt_id"], "TT1")
        self.assertEqual(m210["link_path"], "100>200>210")


class NarrativeTest(unittest.TestCase):
    def test_local_provider_short_circuits(self):
        rows, in_scope, info = _fixture()
        result = svc.compute_rca(rows, in_scope, info)
        out = svc.rca_narrative(result, provider="local")
        self.assertEqual(out["provider"], "local")
        self.assertIn("拓扑根因簇", out["analysis"])

    def test_no_key_degrades(self):
        rows, in_scope, info = _fixture()
        result = svc.compute_rca(rows, in_scope, info)
        out = svc.rca_narrative(result, provider="openai", api_key="")
        self.assertEqual(out["provider"], "local")

    def test_bad_endpoint_falls_back_with_note(self):
        rows, in_scope, info = _fixture()
        result = svc.compute_rca(rows, in_scope, info)
        # 指向必然拒绝连接的本机端口：走异常路径 → 降级 + note 透出原因
        out = svc.rca_narrative(result, provider="openai", api_key="k",
                                base_url="http://127.0.0.1:1/v1")
        self.assertEqual(out["provider"], "local")
        self.assertIn("note", out)
        self.assertIn("AI 调用失败", out["note"])

    def test_english_local_summary(self):
        rows, in_scope, info = _fixture()
        result = svc.compute_rca(rows, in_scope, info)
        text = svc.local_summary(result, lang="en")
        self.assertIn("topology cluster", text)


if __name__ == "__main__":
    unittest.main()
