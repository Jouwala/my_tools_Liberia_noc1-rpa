# -*- coding: utf-8 -*-
"""快速测试 OWA 访问"""

from playwright.sync_api import sync_playwright
import time

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page()

print('Step 1: Access OWA login page...')
try:
    page.goto('https://exchmail.orange-cit.ci/owa/', timeout=30000)
    time.sleep(3)
    print(f'✓ URL: {page.url}')
    print(f'✓ Page title: {page.title()}')
    
    # Check if we can see any input fields
    email_inputs = len(page.locator('input[type="email"]').all())
    print(f'✓ Email inputs found: {email_inputs}')
    
    if email_inputs > 0:
        print('✓ OWA 页面可访问，可以登录')
    else:
        print('✗ 未找到邮箱输入框，页面结构可能已改变')
        page.screenshot(path='test_owa_access.png')
        
except Exception as e:
    print(f'✗ 错误：{e}')
    page.screenshot(path='test_error.png')
    
finally:
    browser.close()
    p.stop()
