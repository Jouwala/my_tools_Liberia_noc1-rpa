#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CS EMS KPI Code - Improved Template Matching with ROI Search
Uses region-of-interest (ROI) searching for reliable UI element detection
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
EMSWAIT_TIMEOUT = 30

# ===== ROI (Region of Interest) Configuration =====
# Define where each UI element should be located within the U31 window
# Format: (x_start_pct, y_start_pct, width_pct, height_pct)
# IMPORTANT: Values are percentages of SCREEN SIZE (0-1.0)
# Example: Filter box is typically in the top-right area
ROI_CONFIG = {
    'filter_box': {
        # Adjust these values based on your actual U31 window layout
        # Current: Start at 70% from left, 20% from top, search in 25% width x 8% height area
        'location': (0.70, 0.20, 0.25, 0.08),
        'template_size_estimate': (100, 30)
    },
    'query_button': {
        'location': (0.75, 0.32, 0.15, 0.08),
        'template_size_estimate': (80, 40)
    },
    'export_button': {
        'location': (0.05, 0.80, 0.15, 0.10),
        'template_size_estimate': (120, 40)
    }
}

# Detection settings
MATCH_THRESHOLD_HIGH = 0.85  # For precise matching first
MATCH_THRESHOLD_LOW = 0.60   # Fallback if high threshold fails
MAX_MATCH_ATTEMPTS = 3       # Try multiple times with slight variations


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg))


# Global variable for window enumeration
_found_hwnd = None
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
            return False
    except Exception as e:
        log("EnumWindows callback error: %s" % str(e))
    return True


_enum_callback_instance = WNDENUMPROC(enum_windows_callback)


def maximize_u31_window():
    """Maximize U31 EMS window."""
    global _found_hwnd
    _found_hwnd = None
    
    user32 = ctypes.windll.user32
    result = user32.EnumWindows(_enum_callback_instance, 0)
    
    if not _found_hwnd:
        log("ERROR: Could not find U31 window")
        return False
    
    # Bring to front and maximize
    user32.SetForegroundWindow(_found_hwnd)
    time.sleep(0.5)
    
    SW_SHOWMAXIMIZED = 3
    user32.ShowWindow(_found_hwnd, SW_SHOWMAXIMIZED)
    time.sleep(0.5)
    
    log("U31 window maximized")
    return True


def create_roi_screenshot(x_pct, y_pct, w_pct, h_pct):
    """Capture screenshot and crop to ROI based on percentage coordinates."""
    full_screen = ImageGrab.grab()
    screen_w, screen_h = full_screen.size
    
    x1 = int(screen_w * x_pct)
    y1 = int(screen_h * y_pct)
    x2 = int(screen_w * (x_pct + w_pct))
    y2 = int(screen_h * (y_pct + h_pct))
    
    roi = full_screen.crop((x1, y1, x2, y2))
    return roi, (x1, y1), roi.size


def find_template_in_roi(template_name, x_pct, y_pct, w_pct, h_pct, threshold=MATCH_THRESHOLD_HIGH):
    """
    Find template within a specific ROI region for more reliable detection.
    Returns (absolute_x, absolute_y) or None if not found.
    """
    # Get ROI screenshot
    roi_img, roi_offset, roi_size = create_roi_screenshot(x_pct, y_pct, w_pct, h_pct)
    
    # Convert ROI to numpy array
    np_roi = np.array(roi_img)
    try:
        roi_rgb = cv2.cvtColor(np_roi, cv2.COLOR_RGB2BGR)
    except Exception as e:
        log("ROI conversion error: %s" % str(e))
        return None
    
    log("Searching '%s' in ROI (%d,%d) to (%d,%d)" % (
        template_name, roi_offset[0], roi_offset[1], 
        roi_offset[0]+roi_size[0]-1, roi_offset[1]+roi_size[1]-1))
    
    # Load template
    template_path = os.path.join(TEMPLATES_DIR, template_name)
    if not os.path.exists(template_path):
        log("Template file NOT FOUND: %s" % template_name)
        return None
    
    try:
        pil_template = Image.open(template_path).convert('RGB')
        np_template = np.array(pil_template)
        template_bgr = cv2.cvtColor(np_template, cv2.COLOR_RGB2BGR)
        
        if template_bgr.size == 0:
            log("ERROR: Cannot load template image")
            return None
        
    except Exception as e:
        log("ERROR loading template: %s" % str(e))
        return None
    
    h_t, w_t = template_bgr.shape[:2]
    
    # Try multiple thresholds
    for current_threshold in [threshold, MATCH_THRESHOLD_LOW]:
        res = cv2.matchTemplate(roi_rgb, template_bgr, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= current_threshold)
        pts = list(zip(*loc[::-1]))
        
        if len(loc[0]) > 0:
            best_score = max(res[loc[0], loc[1]])
            best_pt = pts[0]
            
            # Convert ROI coordinates to absolute screen coordinates
            abs_x = roi_offset[0] + best_pt[0] + w_t // 2
            abs_y = roi_offset[1] + best_pt[1] + h_t // 2
            
            log("✓ Found at score %.4f: absolute (%d, %d)" % (best_score, abs_x, abs_y))
            return (abs_x, abs_y)
    
    log("✗ Template '%s' NOT FOUND in ROI" % template_name)
    return None


def click_at_position(x, y, label=""):
    """Click at specified position with visual confirmation."""
    if label:
        log("⚠️  Clicking %s at (%d, %d)" % (label, x, y))
    else:
        log("⚠️  Moving cursor to (%d, %d)" % (x, y))
    
    SAFE_MODE = True
    if SAFE_MODE:
        log("SAFE MODE: Verifying position...")
        pyautogui.moveTo(x, y, duration=0.3)
        time.sleep(2)
        log("Position verified. Press ENTER to click...")
        try:
            input()
        except:
            pass
    
    try:
        pyautogui.click(x, y)
        time.sleep(0.5)
        return True
    except Exception as e:
        log("Click error: %s" % str(e))
        return False


def type_into_element(x, y, text, label=""):
    """Type text into element at specified position."""
    if label:
        log("Typing '%s' into %s..." % (text, label))
    else:
        log("Typing '%s' at (%d, %d)..." % (text, x, y))
    
    # Move to position and double-click
    pyautogui.moveTo(x, y, duration=0.2)
    time.sleep(0.3)
    pyautogui.click(x, y)
    time.sleep(0.3)
    pyautogui.click(x, y)  # Double-click to select
    time.sleep(0.5)
    
    # Type text
    pyautogui.write(text)
    time.sleep(0.5)
    
    log("Text entered successfully")
    return True


def process_template_simple(template_name, month_date_str):
    """Simple workflow using ROI-based detection."""
    log("\n=== Processing: %s ===" % template_name)
    
    # Step 1: Maximize window
    if not maximize_u31_window():
        return False
    
    time.sleep(2)
    
    # Step 2: Input template name into filter box (ROI search)
    log("Step 1: Finding filter box...")
    filter_pos = find_template_in_roi(
        "Enter the keyword to filter 输入框.png",
        ROI_CONFIG['filter_box']['location'][0],
        ROI_CONFIG['filter_box']['location'][1],
        ROI_CONFIG['filter_box']['location'][2],
        ROI_CONFIG['filter_box']['location'][3]
    )
    
    if filter_pos is None:
        log("ERROR: Could not find filter box!")
        return False
    
    log("Filter box found at: %s" % str(filter_pos))
    
    # Type template name
    type_into_element(filter_pos[0], filter_pos[1], template_name)
    time.sleep(1)
    
    # Step 3: Click Query button (if needed)
    # ... Continue with rest of workflow
    
    log("Template %s processing completed" % template_name)
    return True


def main():
    parser = argparse.ArgumentParser(description="CS KPI with ROI-based Template Matching")
    parser.add_argument("--month", type=str, help="YYYYMM target month")
    parser.add_argument("--debug", action="store_true", help="Show diagnostic information")
    args = parser.parse_args()
    
    # Diagnostic mode: show screen resolution and ROI calculations
    if args.debug:
        from PIL import ImageGrab
        screen = ImageGrab.grab()
        screen_w, screen_h = screen.size
        
        log("=== SCREEN DIAGNOSTIC ===")
        log("Screen resolution: %dx%d" % (screen_w, screen_h))
        log("")
        log("Testing ROI calculations for filter_box:")
        
        x_pct, y_pct, w_pct, h_pct = ROI_CONFIG['filter_box']['location']
        x1 = int(screen_w * x_pct)
        y1 = int(screen_h * y_pct)
        x2 = int(screen_w * (x_pct + w_pct))
        y2 = int(screen_h * (y_pct + h_pct))
        
        log("  Config: (%.2f, %.2f, %.2f, %.2f)" % (x_pct, y_pct, w_pct, h_pct))
        log("  Pixel range: (%d, %d) to (%d, %d)" % (x1, y1, x2, y2))
        log("  ROI size: %dx%d pixels" % (x2-x1, y2-y1))
        log("")
        log("If coordinates look reasonable, run without --debug to test detection.")
        return
    
    log("Starting CS KPI automation with improved ROI-based matching")
    log("This uses localized region searches instead of full-screen scanning")
    
    # Test ROI search with filter box
    log("\n=== Testing Filter Box Detection ===")
    result = find_template_in_roi(
        "Enter the keyword to filter 输入框.png",
        ROI_CONFIG['filter_box']['location'][0],
        ROI_CONFIG['filter_box']['location'][1],
        ROI_CONFIG['filter_box']['location'][2],
        ROI_CONFIG['filter_box']['location'][3]
    )
    
    if result:
        log("✓ SUCCESS: Filter box detected at %s" % str(result))
        log("\nNext step: Run with --month parameter to process all templates")
    else:
        log("✗ FAILED: Could not detect filter box")
        log("SOLUTION: Adjust ROI_CONFIG parameters in this script")
        log("Current filter_box ROI: %s" % str(ROI_CONFIG['filter_box']['location']))
    
    # Process all templates if month specified
    if args.month:
        templates = [
            "VOICE_TRAFFIC_TEMPLATE_OSS",
            "VLR_SUBSCRIBERS_TEMPLATE_OSS", 
            "USSD_RATIO_TEMPLATE_OSS",
            "TDD_DATA_TRAFFIC_TEMPLATE_OSS",
            "LOCATION_UPDATE_TEMPLATE_OSS",
            "LICENSE_OCCUPANCY_TEMPLATE_OSS",
            "DATA_SUBSCRIBERS_TEMPLATE_OSS",
        ]
        
        success_count = 0
        for tpl in templates:
            log("\n[%d/%d] Processing %s" % (templates.index(tpl)+1, len(templates), tpl))
            if process_template_simple(tpl, args.month):
                success_count += 1
        
        log("\n=== Summary ===")
        log("Successful: %d/%d" % (success_count, len(templates)))


if __name__ == '__main__':
    main()
