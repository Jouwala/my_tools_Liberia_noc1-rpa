#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Interactive ROI Selector - Help you find the correct filter box location
This will take a screenshot and let you visually inspect different regions
"""
from PIL import ImageGrab
import cv2
import numpy as np
import os
import datetime


def log(msg):
    print("[14:%s] %s" % (datetime.datetime.now().strftime("%M:%S"), msg))


def capture_roi_debug(x_pct, y_pct, w_pct, h_pct, screen_w, screen_h):
    """Capture and save ROI for debugging."""
    x1 = int(screen_w * x_pct)
    y1 = int(screen_h * y_pct)
    x2 = int(screen_w * (x_pct + w_pct))
    y2 = int(screen_h * (y_pct + h_pct))
    
    full = ImageGrab.grab()
    roi = full.crop((x1, y1, x2, y2))
    
    timestamp = datetime.datetime.now().strftime("%H%M%S")
    output_path = rf"templates\_roi_test_{timestamp}.png"
    
    roi.save(output_path)
    
    print("\n" + "="*60)
    print("ROI CAPTURED:")
    print(f"  Screen: {screen_w}x{screen_h}")
    print(f"  Config: ({x_pct:.2f}, {y_pct:.2f}, {w_pct:.2f}, {h_pct:.2f})")
    print(f"  Pixel:  ({x1},{y1}) to ({x2},{y2})")
    print(f"  Size:   {x2-x1}x{y2-y1}")
    print(f"  Saved:  {output_path}")
    print("="*60)
    
    return output_path


def main():
    from PIL import ImageGrab
    
    log("=== INTERACTIVE ROI SELECTOR ===")
    log("Use this tool to find the CORRECT ROI for filter input box\n")
    
    # Get screen resolution
    screen = ImageGrab.grab()
    screen_w, screen_h = screen.size
    print(f"Screen resolution: {screen_w}x{screen_h}\n")
    
    # Ask user where the filter box might be
    print("Where is your U31 filter input box located?")
    print("(Enter values between 0.0 and 1.0)")
    print("")
    
    while True:
        try:
            print("Try configuration:")
            
            # Default suggestion based on typical U31 layout
            test_x = float(input("  X start (% of screen width, e.g., 0.7 for 70%% right side): "))
            test_y = float(input("  Y start (% of screen height, e.g., 0.2 for top area): "))
            test_w = float(input("  Width (% of screen, e.g., 0.2 for 20%%): "))
            test_h = float(input("  Height (% of screen, e.g., 0.08 for small strip): "))
            
            # Capture ROI
            output_file = capture_roi_debug(test_x, test_y, test_w, test_h, screen_w, screen_h)
            
            print("\n✓ ROI captured and saved!")
            print("Open the image and check if the filter box is inside.")
            print("If NO, press Enter to try again with new coordinates.\n")
            
            input()
            
        except KeyboardInterrupt:
            print("\n\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")
            print("Press Enter to try again...\n")
            input()


if __name__ == '__main__':
    main()
