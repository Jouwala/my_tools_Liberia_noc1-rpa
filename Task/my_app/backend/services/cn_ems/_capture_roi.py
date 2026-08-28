#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quick ROI screenshot tool"""
from PIL import ImageGrab
import cv2
import numpy as np
import os
import datetime

# Your screen and ROI settings
SCREEN_W, SCREEN_H = 2560, 1440
X_PCT, Y_PCT, W_PCT, H_PCT = 0.70, 0.20, 0.25, 0.08

x1 = int(SCREEN_W * X_PCT)
y1 = int(SCREEN_H * Y_PCT)
x2 = int(SCREEN_W * (X_PCT + W_PCT))
y2 = int(SCREEN_H * (Y_PCT + H_PCT))

print(f"Screen: {SCREEN_W}x{SCREEN_H}")
print(f"ROI: ({x1},{y1}) to ({x2},{y2})")
print(f"ROI size: {x2-x1}x{y2-y1}")

# Capture ROI
full = ImageGrab.grab()
roi = full.crop((x1, y1, x2, y2))

# Save timestamped screenshot
timestamp = datetime.datetime.now().strftime("%H%M%S")
output_path = rf"templates\_roi_debug_{timestamp}.png"
roi.save(output_path)

print(f"\n✓ ROI screenshot saved to: {output_path}")
print("Check if the filter input box is visible in this image!")
