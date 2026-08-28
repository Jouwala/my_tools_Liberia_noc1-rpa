#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
真正的手动坐标拾取工具 - 需要 EMS 客户端已经打开
这个工具会等待您点击实际的 UI 元素，然后记录正确的位置
"""
import time
import pyautogui


def click_and_record(label, wait_seconds=15):
    """
    Wait for user to click on a specific UI element, then record coordinates.
    
    Args:
        label: Description of what to click (e.g., "Filter input box")
        wait_seconds: Time to wait before expecting the click
    """
    print("\n" + "="*60)
    print("%s - COORDINATE PICKER" % label.upper())
    print("="*60)
    print("\nInstructions:")
    print("1. Make sure your U31 EMS client is OPEN and VISIBLE")
    print("2. Locate the %s on screen" % label.lower())
    print("3. I'll wait %d seconds..." % wait_seconds)
    print("4. Then move your mouse cursor OVER the %s" % label.lower())
    print("5. Press 'Enter' or just wait...")
    print("6. I'll read the exact coordinates and save them\n")
    
    # Show remaining time
    print("Timer started... You have %d seconds:\n" % wait_seconds)
    time.sleep(wait_seconds)
    
    # Record current position
    x, y = pyautogui.position()
    print("✓ Detected position: (%d, %d)" % (x, y))
    
    # Additional verification
    print("\nIMPORTANT: Please verify on screen that this position corresponds")
    print("to the %s. If WRONG, press Ctrl+C to cancel and try again." % label)
    
    return (x, y)


def main():
    print("="*60)
    print("U31 EMS CLIENT - MANUAL COORDINATE PICKER")
    print("="*60)
    print("\n⚠️  WARNING: This tool requires U31 EMS Client to be OPEN!")
    print("   If you don't see the client window, DON'T proceed!\n")
    
    input("Press Enter when U31 client is ready... ")
    
    # Step 1: Filter Input Box
    filter_coords = click_and_record(
        "Filter Input Box",
        wait_seconds=20
    )
    
    # Step 2: Query Button  
    query_coords = click_and_record(
        "Query by Template Button (red icon)",
        wait_seconds=20
    )
    
    # Step 3: Export CSV Button
    export_coords = click_and_record(
        "Export CSV button",
        wait_seconds=20
    )
    
    # Save results
    print("\n" + "="*60)
    print("COORDINATES SAVED!")
    print("="*60)
    print("\nTo use in your automation script:")
    print("\n# In cs_ems_kpi_code_image.py, replace template matching with:")
    print("FILTER_BOX_COORDS = %s" % str(filter_coords))
    print("QUERY_BUTTON_COORDS = %s" % str(query_coords))
    print("EXPORT_BUTTON_COORDS = %s" % str(export_coords))
    print("\nThen create helper functions that use these fixed coordinates\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n✖ Aborted by user")
        exit(1)
