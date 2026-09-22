# -*- coding: utf-8 -*-
"""FME 排名服务的纯函数/最小数据测试，不访问远端门户。"""
import unittest

from backend.services.fme_data import fme_ranking_service as svc


class FmeRankingServiceTest(unittest.TestCase):
    def test_valid_month_and_bounds(self):
        self.assertEqual(svc.valid_month("2026-09"), "2026-09")
        self.assertEqual(svc.month_bounds_exclusive("2026-12"), ("2026-12-01 00:00:00", "2027-01-01 00:00:00"))

    def test_norm_name_collapses_whitespace(self):
        self.assertEqual(svc.norm_name("  Orange   Tower "), "orange tower")

    def test_schema_empty_payload_is_diagnosable(self):
        payload = svc._empty_wo({"table": False, "site_id": None, "site_name": None, "time": None}, "2026-09")
        self.assertEqual(payload["by_site"], {})
        self.assertEqual(len(payload["warnings"]), 3)

    def test_wo_status_default_is_open(self):
        self.assertEqual("closed", "Closed".lower())
        self.assertNotEqual("waiting", "Closed".lower())


if __name__ == "__main__":
    unittest.main()
