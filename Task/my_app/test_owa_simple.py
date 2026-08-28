# -*- coding: utf-8 -*-
"""快速测试 OWA 访问 - 简单版本"""

from playwright.sync_api import sync_playwright
import time

print("Test start...")
p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page()

try:
    print("Step 1: Access OWA login page...")
    page.goto('https://exchmail.orange-cit.ci/owa/', timeout=30000)
    time.sleep(3)
    
    print(f"URL: {page.url}")
    print(f"Title: {page.title()}")
    
    # Check input boxes
    inputs = page.locator('input[type="email"]').all()
    count = len(inputs)
    print(f"Email input boxes: {count}")
    
    if count > 0:
        print("\nResult: OWA accessible")
        page.screenshot(path='test_ok.png')
    else:
        print("\nResult: No input box")
        page.screenshot(path='test_error.png')
        
except Exception as e:
    print(f"\nError: {e}")
    page.screenshot(path='test_exception.png')
    
finally:
    browser.close()
    p.stop()
