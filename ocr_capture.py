import ddddocr
import cv2
import numpy as np
from collections import Counter

image_path = r'D:\01_RPA\TMP\111.png'

# 验证码常见约束（按实际场景调整）
EXPECTED_LEN = 6          # 验证码长度，不确定可设为 None
CHARSET = None            # 例: "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def preprocess_image(image_bytes, method="default"):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes

    h, w = img.shape[:2]

    if method == "gray":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        return cv2.imencode('.png', binary)[1].tobytes()

    elif method == "gray_invert":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
        return cv2.imencode('.png', binary)[1].tobytes()

    elif method == "adaptive":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        return cv2.imencode('.png', binary)[1].tobytes()

    elif method == "denoise":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray, None, 6, 7, 21)
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return cv2.imencode('.png', binary)[1].tobytes()

    elif method == "sharpen":
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharpened = cv2.filter2D(img, -1, kernel)
        gray = cv2.cvtColor(sharpened, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        return cv2.imencode('.png', binary)[1].tobytes()

    elif method == "otsu":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return cv2.imencode('.png', binary)[1].tobytes()

    elif method == "crop_margin":
        margin = int(min(w, h) * 0.05)
        cropped = img[margin:h - margin, margin:w - margin]
        return cv2.imencode('.png', cropped)[1].tobytes()

    elif method == "scale_up":
        scaled = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return cv2.imencode('.png', binary)[1].tobytes()

    elif method == "scale_up_raw":
        scaled = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        return cv2.imencode('.png', scaled)[1].tobytes()

    else:
        return image_bytes


def is_valid_result(text):
    if not text or not str(text).strip():
        return False
    text = str(text).strip()
    if EXPECTED_LEN is not None and len(text) != EXPECTED_LEN:
        return False
    if CHARSET is not None and any(c not in CHARSET for c in text):
        return False
    return True


def ocr_once(ocr, image_bytes):
    try:
        return (ocr.classification(image_bytes) or "").strip()
    except Exception:
        return ""


def recognize_best(image_bytes):
    """多预处理 × 双模型投票，只返回最优识别字符串。"""
    methods = {
        "default": 3,
        "otsu": 2,
        "crop_margin": 2,
        "scale_up_raw": 2,
        "scale_up": 1,
        "sharpen": 1,
        "gray": 1,
        "adaptive": 1,
        "gray_invert": 1,
        "denoise": 1,
    }

    ocr_std = ddddocr.DdddOcr(show_ad=False)
    ocr_beta = ddddocr.DdddOcr(show_ad=False, beta=True)

    votes = Counter()
    fallback = Counter()

    for method, weight in methods.items():
        processed = preprocess_image(image_bytes, method)
        for ocr in (ocr_std, ocr_beta):
            text = ocr_once(ocr, processed)
            if not text:
                continue
            fallback[text] += 1
            if is_valid_result(text):
                votes[text] += weight

    if votes:
        return votes.most_common(1)[0][0]
    if fallback:
        return fallback.most_common(1)[0][0]
    return ""


def ocr_image(path):
    """从图片路径识别验证码，返回最优结果字符串。"""
    with open(path, 'rb') as f:
        return recognize_best(f.read())


# ========== 给 RPA / 其他脚本用 ==========
# 方式1：直接赋给变量
captcha = ocr_image(image_path)
print(captcha)   # 只输出最终结果，例如: e6Qk29

# 方式2：被其他 py 导入时使用
# from ocr_capture import ocr_image, recognize_best
# code = ocr_image(r'D:\01_RPA\TMP\111.png')
# code = recognize_best(image_bytes)  # 已有图片 bytes 时
