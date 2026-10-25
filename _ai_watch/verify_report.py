# -*- coding: utf-8 -*-
"""用 Playwright 验证周报 HTML 的渲染与交互。

使用 channel="chrome" 驱动本机 Chrome，无需下载 Chromium。
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(BASE, "AI动态观测周报_20261024.html")
SHOT_DIR = os.path.join(BASE, "_shots")


def main():
    os.makedirs(SHOT_DIR, exist_ok=True)
    url = "file:///" + REPORT.replace("\\", "/")

    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        page.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))

        page.goto(url, wait_until="load")
        page.wait_for_timeout(900)

        # --- 结构检查 ---
        title = page.title()
        tweets = page.locator("#tweets .tweet").count()
        cards = page.locator(".card").count()
        tables = page.locator("table.tbl").count()
        fb = page.locator(".fbtn").count()
        stats = page.locator(".stat").count()
        props = page.locator(".pill").count()
        h2 = page.locator("h2").all_inner_texts()
        verdict = page.locator(".verdict li").count()

        print("标题:", title)
        print("推文条目: %d | 卡片: %d | 表格: %d | 筛选按钮: %d | 统计卡: %d | 属性徽章: %d"
              % (tweets, cards, tables, fb, stats, props))
        print("章节:", " / ".join(h2))
        print("结论条数:", verdict)

        assert tweets > 80, "推文数量异常: %d" % tweets
        assert cards >= 25, "卡片数量异常"
        assert tables == 2, "表格数量异常"
        assert verdict == 4, "结论应为 4 条"
        assert stats == 4, "统计卡应为 4 个"

        # 顶部顺序：先看结论必须在分类明细之前
        order = page.evaluate("""() => {
            const secs=[...document.querySelectorAll('section')];
            return secs.map(s=>{
                const h=s.querySelector('h2');
                return h?h.innerText.trim():'';
            });
        }""")
        print("章节顺序:", order)
        assert order[0] == "先看结论", "首个章节应为「先看结论」"

        page.screenshot(path=os.path.join(SHOT_DIR, "01_top.png"), clip={
            "x": 0, "y": 0, "width": 1440, "height": 1500})

        # --- 交互 1：账号筛选 ---
        all_btn = page.locator('.fbtn[data-f="all"]')
        before = page.locator("#tweets .tweet").count()
        all_btn.click()
        page.wait_for_timeout(300)
        after_all = page.locator("#tweets .tweet").count()
        assert after_all == before, "「全部」筛选结果应不变"

        acct_btn = page.locator('.fbtn[data-f="mistralai"]')
        acct_btn.click()
        page.wait_for_timeout(400)
        filtered = page.locator("#tweets .tweet").count()
        on_class = page.locator('.fbtn.on').get_attribute("data-f")
        handles = page.locator("#tweets .handle").all_inner_texts()
        non_mistral = [h for h in handles if h != "@mistralai"]
        print("筛选 @mistralai: %d 条 (全部 %d 条), on=%s, 混入其他账号: %d"
              % (filtered, before, on_class, len(non_mistral)))
        assert 0 < filtered < before, "账号筛选未生效"
        assert on_class == "mistralai", "选中态未切换"
        assert not non_mistral, "筛选结果混入了其他账号"

        page.screenshot(path=os.path.join(SHOT_DIR, "02_filter.png"), clip={
            "x": 0, "y": 0, "width": 1440, "height": 1200})

        # --- 交互 2：关键词搜索 ---
        all_btn.click()
        page.wait_for_timeout(200)
        page.fill("#q", "open weights")
        page.wait_for_timeout(500)
        hits = page.locator("#tweets .tweet").count()
        texts = page.locator("#tweets .tw-x").all_inner_texts()
        bad = [t for t in texts if "open weights" not in t.lower()]
        print("搜索 'open weights': %d 条命中, 不匹配数: %d" % (hits, len(bad)))
        assert hits > 0, "关键词搜索无结果"
        assert not bad, "搜索结果包含不匹配项"

        page.screenshot(path=os.path.join(SHOT_DIR, "03_search.png"), clip={
            "x": 0, "y": 0, "width": 1440, "height": 1000})

        # --- 交互 3：无结果时显示空状态 ---
        page.fill("#q", "zzzznotexistzzz")
        page.wait_for_timeout(500)
        empty_visible = page.locator("#none").is_visible()
        empty_count = page.locator("#tweets .tweet").count()
        print("无结果时空状态可见:", empty_visible, "| 条目数:", empty_count)
        assert empty_visible, "空状态未显示"
        assert empty_count == 0, "无结果时仍有条目"

        # --- 交互 4：清空搜索恢复 ---
        page.fill("#q", "")
        page.wait_for_timeout(500)
        restored = page.locator("#tweets .tweet").count()
        print("清空搜索后恢复:", restored)
        assert restored == before, "清空搜索未恢复全部"

        # --- 布局检查：无横向溢出 ---
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        print("横向溢出像素:", overflow)
        assert overflow <= 2, "存在横向滚动: %dpx" % overflow

        # --- 全文截图 ---
        page.screenshot(path=os.path.join(SHOT_DIR, "04_full.png"), full_page=True)

        browser.close()

    if errors:
        print("\n!! 页面错误:")
        for e in errors:
            print("  ", e)
        sys.exit(1)
    print("\n=== 全部检查通过 ===")


if __name__ == "__main__":
    main()
