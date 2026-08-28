#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CS EMS KPI Code - Image-based Automation (Fallback from JAB)
Uses PIL, pyautogui, and OpenCV for template matching to automate NetNumen U31 GUI.
No JAB required - works on any Java Swing app.

Template files needed in 'templates/' directory (CHINESE names):
- Enter the keyword to filter输入框.png (filter edit box)
- Query by Template红色按钮.png (red button icon)
- Time Selection tab 标签.png (tab label)
- Export CSV按钮.png (export button)
- 时间确认.png (time confirmation OK button)

Workflow per template:
1. Filter box: Find by template -> click -> input name + Enter
2. Click "Query by Template" button by template match
3. Wait for modal -> Click Time Selection tab
4. Month input -> Customize radio -> Start/End date fields -> OK
5. Export button -> Choose CSV format -> Save location

Date format: YYYY/MM/DD
Start time = target_month - 1 month
End time = target_month

Author: Qoder
Date: 2026-08-25
"""
import sys
import os
import time
import argparse
from datetime import datetime, timedelta
import ctypes
from ctypes import wintypes

import cv2
import numpy as np
from PIL import Image, ImageGrab
import pyautogui

# Configuration
TEMPLATES_DIR = r"d:\01_RPA\Task\my_app\backend\services\cn_ems\templates"
OUTPUT_DIR = r"d:\01_RPA\Task\my_app\backend\services\cn_ems\csv_out"
MATCH_THRESHOLD = 0.45  # Very low threshold for robust matching even when UI changes
EMSWAIT_TIMEOUT = 30
DEBUG_MODE = True  # Enable debug screenshot saving


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg))


# Global variable for window enumeration
_found_hwnd = None

# Define callback type using ctypes.CFUNCTYPE
WNDENUMPROC = ctypes.CFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def enum_windows_callback(hwnd, lparam):
    """Callback function for EnumWindows (WNDENUMPROC signature)."""
    global _found_hwnd
    try:
        user32 = ctypes.windll.user32
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if "NetNumen U31" in buf.value:
            _found_hwnd = hwnd
            return False  # Stop enumeration
    except Exception as e:
        log("EnumWindows callback error: %s" % str(e))
    return True  # Continue enumeration

# Create proper callback instance
_enum_callback_instance = WNDENUMPROC(enum_windows_callback)


def maximize_u31_window():
    """Maximize U31 EMS window."""
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    
    global _found_hwnd
    _found_hwnd = None
    
    # Enumerate windows with callback
    result = user32.EnumWindows(_enum_callback_instance, 0)
    if not result:
        log("Warning: EnumWindows failed")
    
    hwnd = _found_hwnd
    
    if not hwnd:
        log("Error: Could not find U31 window")
        return False
    
    # Bring to front
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    
    # Maximize
    SW_SHOWMAXIMIZED = 3
    user32.ShowWindow(hwnd, SW_SHOWMAXIMIZED)
    time.sleep(0.5)
    
    log("U31 window maximized")
    return True


def find_template(template_name, threshold=MATCH_THRESHOLD):
    """Find template on current screenshot. Returns (center_x, center_y) or None."""
    log("Looking for template '%s' with threshold %.2f..." % (template_name, threshold))
    
    # Check for actual filename with quotes
    all_files = os.listdir(TEMPLATES_DIR)
    
    # Try exact match first, removing surrounding single quotes if present
    matched_file = None
    for f in all_files:
        stripped_f = f.strip("'")  # Remove surrounding single quotes
        if f == template_name or stripped_f == template_name:
            matched_file = f  # Use original filename (with quotes if present)
            break
    
    if not matched_file:
        log("ERROR: Template file not found: %s" % template_name)
        return None
    
    template_path = os.path.join(TEMPLATES_DIR, matched_file)
    log("Found file: %s" % matched_file)
    
    # Read image using PIL first to handle Chinese filenames properly
    try:
        pil_img = Image.open(template_path)
        pil_img = pil_img.convert('RGB')  # Ensure RGB mode
        np_img = np.array(pil_img)
        # Convert to BGR for OpenCV
        template = cv2.cvtColor(np_img, cv2.COLOR_RGB2BGR)
        
        if template is None or template.size == 0:
            log("ERROR: Failed to convert template: %s" % template_path)
            return None
    except Exception as e:
        log("ERROR: Cannot load template via PIL: %s - %s" % (template_path, str(e)))
        import traceback
        traceback.print_exc()
        return None
    
    screen_pil = ImageGrab.grab()
    np_img = np.array(screen_pil)
    try:
        screen_rgb = cv2.cvtColor(np_img, cv2.COLOR_RGB2BGR)
    except Exception as e:
        log("cv2.cvtColor error: %s" % str(e))
        return None
    
    # Debug: Save current screenshot with overlay showing template location
    if DEBUG_MODE:
        import datetime
        debug_path = "templates/_debug_screenshot_%s.png" % datetime.datetime.now().strftime("%H%M%S")
        cv2.imwrite(debug_path, screen_rgb)
        log("DEBUG: Saved screenshot to %s (review for verification)" % debug_path)
    
    h, w = template.shape[:2]
    log("Template size: %dx%d" % (w, h))
    
    try:
        res = cv2.matchTemplate(screen_rgb, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        pts = list(zip(*loc[::-1]))
        
        # Show best match value
        if len(loc[0]) > 0:
            best_score = max(res[loc[0], loc[1]])
            log("Best match score: %.4f at (%d, %d) with %d locations found" % (
                best_score, loc[0][0], loc[1][0], len(pts)))
        
        if pts:
            best_pt = pts[0]
            center_x = best_pt[0] + w // 2
            center_y = best_pt[1] + h // 2
            log("Found '%s' at (%d, %d), center=(%d, %d)" % (template_name, best_pt[0], best_pt[1], center_x, center_y))
            return (center_x, center_y)
        else:
            log("Template '%s' NOT FOUND on screen" % template_name)
            return None
    except Exception as e:
        log("ERROR in find_template for '%s': %s" % (template_name, str(e)))
        import traceback
        traceback.print_exc()
        return None


def click_template(template_name):
    """Click center of matched template."""
    pos = find_template(template_name)
    if pos is None:
        log("ERROR: Cannot click '%s' - template not found" % template_name)
        return False
    x, y = pos
    try:
        pyautogui.click(x, y)
    except Exception as e:
        log("pyautogui.click failed at (%d,%d): %s" % (x, y, str(e)))
        return False
    time.sleep(0.5)
    return True


def type_in_field(template_name, text):
    """
    Type text into the filter input field using manual-confirmed coordinates.
    SAFETY: Waits for user confirmation before any clicks.
    """
    log("=== Typing '%s' into filter box (SAFE MODE) ===" % text)
    
    pos = find_template(template_name)
    if pos is None:
        log("ERROR: Template not found!")
        return False
    
    center_x, center_y = pos
    log("Template FOUND at screen coordinates: (%d, %d)" % (center_x, center_y))
    
    # CRITICAL SAFETY: Add confirmation before any destructive action
    SAFE_MODE = True  # Enable manual confirmation for clicks
    if SAFE_MODE:
        log("⚠️  SAFE MODE ACTIVATED")
        log("Mouse will move to verify position. Will NOT click automatically.")
        log("Please VERIFY on screen that (%d, %d) is the correct filter box!") % (center_x, center_y)
        pyautogui.moveTo(center_x, center_y, duration=0.3)
        time.sleep(2)  # Let user inspect
        # Ask for manual confirmation
        input("Press ENTER after confirming location is CORRECT...")
        log("User confirmed. Continuing...")
    
    try:
        # Strategy 1: Double-click to ensure focus and select existing content
        log("Strategy 1: Double-click to focus...")
        maximize_u31_window()
        time.sleep(0.5)
        
        # Click twice to ensure focus into Java Swing component
        pyautogui.click(center_x, center_y)
        time.sleep(0.4)
        pyautogui.click(center_x, center_y)  # Second click to select text
        time.sleep(0.5)
        
        # Strategy 2: Ctrl+A to select all, then overwrite (most reliable for text inputs)
        log("Strategy 2: Select all + Overwrite...")
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.write(text)
        time.sleep(0.5)
        pyautogui.press('enter')
        time.sleep(1)
        
        log("Typing completed successfully")
        return True
        
    except Exception as e:
        log("Input error: %s" % str(e))
        import traceback
        traceback.print_exc()
        return False


def calculate_date_range(target_month_str):
    """Calculate start and end dates given a target month string like '202608'.
    Returns (start_date_str, end_date_str) in "YYYY/MM/DD" format."""
    year = int(target_month_str[:4])
    month = int(target_month_str[4:6])
    
    # End date: last day of target month
    if month == 12:
        end_year, end_month = year + 1, 1
    else:
        end_year, end_month = year, month + 1
    
    # Determine days in each month
    def days_in_month(y, m):
        if m == 12:
            next_m = datetime(y+1, 1, 1)
        else:
            next_m = datetime(y, m+1, 1)
        prev_m = next_m - timedelta(days=1)
        return prev_m.day
    
    start_day = 1
    start_month = month - 1
    start_year = year
    if start_month == 0:
        start_month = 12
        start_year = year - 1
    
    end_day = days_in_month(year, month)
    
    start_str = "%d/%02d/%02d" % (start_year, start_month, start_day)
    end_str = "%d/%02d/%02d" % (end_year, end_month, end_day)
    
    log("Date range: %s (start) to %s (end)" % (start_str, end_str))
    return start_str, end_str


def process_template_with_dates(template_name, month_date_str):
    """Process a single CS KPI template with proper date handling."""
    log("=== Processing template: %s ===" % template_name)
    log("Target month: %s" % month_date_str)
    
    # STEP 1: Window maximization
    if not maximize_u31_window():
        log("Failed to maximize U31 window")
        return False
    
    time.sleep(2)  # Wait for user to confirm window is ready
    log("Window maximized. Press ENTER to continue...")
    try:
        input()
        log("Confirmed, proceeding...")
    except:
        pass
    
    # Main workflow (will proceed step by step with confirmations)
    try:
        
        # Step 2: Input template name in filter box
        log("Step 2: Inputting template name...")
        if not type_in_field("Enter the keyword to filter 输入框.png", template_name):
            log("ERROR: Failed to input template name")
            return False
        time.sleep(1)
                
        log("Template name entered. Press ENTER to proceed...")
        try:
            input()
            log("Confirmed, continuing...")
        except:
            pass
        
        # Step 3: Click "Query by Template" button
        log("Step 3: Clicking Query by Template...")
        if not click_template("Query by Template 红色按钮.png"):
            log("ERROR: Cannot click Query by Template")
            return False
        time.sleep(2)
                
        log("Query triggered. Press ENTER to continue...")
        try:
            input()
            log("Confirmed, continuing...")
        except:
            pass
        
        # Step 4: Handle Time Selection dialog
        log("Step 3: Activating Time Selection tab...")
        if not click_template("Time Selection tab 标签.png"):
            log("WARNING: Time Selection tab not found, trying keyboard...")
            pyautogui.hotkey('ctrl', 'tab')
            time.sleep(1)
        time.sleep(1)
        
        # Step 5: Select Customize option
        log("Step 4: Setting customize date range...")
        pyautogui.press('tab')
        time.sleep(0.3)
        pyautogui.press('space')
        time.sleep(0.5)
        
        # Step 6: Calculate and input date range
        start_date, end_date = calculate_date_range(month_date_str)
        
        log("Step 5: Inputting start date: %s" % start_date)
        for _ in range(5):
            pyautogui.press('tab')
            time.sleep(0.2)
        pyautogui.write(start_date)
        time.sleep(0.3)
        
        log("Step 6: Inputting end date: %s" % end_date)
        pyautogui.press('tab')
        time.sleep(0.3)
        pyautogui.write(end_date)
        time.sleep(0.5)
        
        log("Step 7: Pressing OK...")
        if click_template("时间确认.png"):
            time.sleep(2)
        else:
            log("WARNING: 时间确认 button not found, using ENTER key")
            pyautogui.press('enter')
            time.sleep(2)
        
        # Step 8: Trigger export
        log("Step 8: Clicking Export CSV...")
        if not click_template("Export CSV按钮.png"):
            log("ERROR: Cannot click Export CSV")
            return False
        time.sleep(3)
        
        # Step 9: File save dialog
        log("Step 9: Auto-saving...")
        time.sleep(2)
        pyautogui.press('tab')
        time.sleep(0.3)
        pyautogui.press('tab')
        time.sleep(0.3)
        pyautogui.press('enter')
        
        log("Template %s completed successfully!" % template_name)
        return True
    except Exception as e:
        log("CRITICAL ERROR: %s" % str(e))
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="CS KPI Image Automation")
    parser.add_argument("--month", type=str, help="YYYYMM target month")
    parser.add_argument("--date", type=str, help="YYYY/MM/DD date range")
    args = parser.parse_args()
    
    # Create output directory
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    templates = [
        "VOICE_TRAFFIC_TEMPLATE_OSS",
        "VLR_SUBSCRIBERS_TEMPLATE_OSS", 
        "USSD_RATIO_TEMPLATE_OSS",
        "TDD_DATA_TRAFFIC_TEMPLATE_OSS",
        "LOCATION_UPDATE_TEMPLATE_OSS",
        "LICENSE_OCCUPANCY_TEMPLATE_OSS",
        "DATA_SUBSCRIBERS_TEMPLATE_OSS",
    ]
    
    month_date = None
    if args.month:
        month_date = args.month
    elif args.date:
        parts = args.date.split("/")
        if len(parts) >= 2:
            month_date = parts[0][-2:] + parts[1].zfill(2)
    
    if not month_date:
        log("ERROR: Please specify --month YYYYMM or --date YYYY/MM/DD")
        sys.exit(1)
    
    log("Starting CS KPI image automation")
    log("Target month: %s" % month_date)
    
    success_count = 0
    fail_count = 0
    
    for i, tpl in enumerate(templates, 1):
        log("\n[%d/%d] Processing %s" % (i, len(templates), tpl))
        try:
            success = process_template_with_dates(tpl, month_date)
            if success:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            fail_count += 1
            log("ERROR processing %s: %s" % (tpl, str(e)))
    
    log("\n=== Complete ===")
    log("Success: %d, Failed: %d" % (success_count, fail_count))


if __name__ == '__main__':
    main()
