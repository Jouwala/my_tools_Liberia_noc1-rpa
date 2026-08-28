import os
from PIL import Image
import cv2

TEMPLATES_DIR = r'd:\01_RPA\Task\my_app\backend\services\cn_ems\templates'

print("Testing all templates in directory:")
all_files = os.listdir(TEMPLATES_DIR)

for f_name in all_files:
    path = os.path.join(TEMPLATES_DIR, f_name)
    if not f_name.endswith('.txt'):  # Skip non-image files
        print("\n=== %s ===" % f_name)
        print("Path: %s" % path)
        print("Exists:", os.path.exists(path))
        
        # Try PIL
        try:
            img = Image.open(path)
            print("PIL OK: Format=%s Size=%dx%d Mode=%s" % (img.format, img.size[0], img.size[1], img.mode))
        except Exception as e:
            print("PIL Error:", str(e))
            continue
            
        # Try OpenCV - convert to numpy first with PIL
        try:
            pil_img = Image.open(path).convert('RGB')
            import numpy as np
            np_img = np.array(pil_img)
            img_cv = cv2.cvtColor(np_img, cv2.COLOR_RGB2BGR)
            print("OpenCV OK via PIL: Shape=%s DType=%s" % (img_cv.shape, img_cv.dtype))
        except Exception as e:
            print("OpenCV via PIL Error:", str(e))
