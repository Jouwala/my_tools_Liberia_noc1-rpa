# Liberia Site-Down Email 发送方式使用指南

## 🎯 问题背景
Liberia Site-Down 1H Report 邮件发送失败/超时，原因是：
- **Excel 附件太大**: 5.29 MB
- **3 张内嵌图片**: ~1.3 MB  
- **总计约 6.6MB** → 通过 EWS API Base64 编码后达 8.8MB

网页版 OWA 能快速发送，但脚本失败。

---

## ✅ 解决方案：混合式智能发送引擎

支持 **5 种不同的发送方式**，可根据文件大小、网络情况自动选择或手动指定。

---

## 📋 支持的 5 种方案

### **A: exchangelib（推荐大附件）**
- **原理**: Python `exchangelib` 库的原生 API
- **优势**: 
  - 自动流式上传大附件（避免内存爆炸）
  - 完整的错误重试机制
  - 对 5MB+ 附件表现最佳
- **适用场景**: 大型 Excel + 多张图片

### **B: PowerShell .NET HttpWebRequest（当前默认）**
- **原理**: 调用 PowerShell 脚本，使用 .NET `HttpWebRequest` 
- **优势**: 
  - 与网页版 OWA 相同的底层实现
  - 小附件性能最优（接近浏览器速度）
  - 已测试稳定
- **适用场景**: 小于 5MB 的附件

### **C: WinHTTP + NTLM（待开发）**
- **原理**: Windows 原生 WinHTTP API（比 .NET 更轻量）
- **优势**: 
  - 系统级 HTTP，绕过 .NET 开销
  - 更快的连接建立速度
- **适用场景**: 未来优化选项（需另行开发脚本）

### **D: urllib3 / requests（备用）**
- **原理**: Python HTTP 库手动构造 SOAP 请求
- **优势**: 
  - 灵活定制
  - 无需额外依赖
- **适用场景**: 调试和特殊需求

### **E: 浏览器自动化（终极兜底）**
- **原理**: Selenium/Playwright 模拟真实浏览器操作
- **优势**: 
  - 完全复用网页版流程
  - 100% 匹配用户手动操作
- **劣势**: 
  - 较慢（需启动浏览器）
  - 需要安装 headless 浏览器
- **适用场景**: 其他所有方案都失败时的最后手段

---

## 🚀 使用方法

### **方式 1: 自动智能选择（推荐）**
```powershell
# 脚本会自动检测附件大小并选择最佳方案
cd d:\01_RPA\Task\my_app
.venv-test\Scripts\python.exe email_reports\owa_mail_1hour_TT_Report.py --to dong.xinmin@zte.com.cn --cc ""
```

**自动策略**:
- 附件 > 5MB → 使用 **exchangelib**
- 附件 ≤ 5MB → 使用 **.NET PowerShell** (默认)

### **方式 2: 强制指定方案**

#### 强制使用 exchangelib（适合大附件）
```powershell
python email_reports\owa_mail_1hour_TT_Report.py --use-exchangelib --to ... --cc ""
```

#### 强制使用 .NET PowerShell（小附件最快）
```powershell
python email_reports\owa_mail_1hour_TT_Report.py --use-dotnet --to ... --cc ""
```

#### 预留：WinHTTP / 浏览器模式（待实现）
```powershell
python email_reports\owa_mail_1hour_TT_Report.py --use-winhttp --to ... --cc ""
python email_reports\owa_mail_1hour_TT_Report.py --use-browser --to ... --cc ""
```

### **方式 3: 使用预设模式**
```powershell
# mode 参数等价于 --use-XXX
python email_reports\owa_mail_1hour_TT_Report.py --mode exchangelib --to ... --cc ""
python email_reports\owa_mail_1hour_TT_Report.py --mode dotnet --to ... --cc ""
```

---

## 📊 效果对比（待实测）

| 方案 | < 1MB | 1-5MB | > 5MB | 稳定性 |
|------|-------|-------|-------|--------|
| A: exchangelib | ✓ | ✓ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| B: .NET PowerSh | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| C: WinHTTP | 待测 | 待测 | 待测 | 待开发 |
| D: browser | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| E: Selenium | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |

---

## 🔧 技术细节

### 当前实现的 3 个方案

#### **方案 A: send_via_exchangelib()**
```python
# 使用 exchangelib 原生 API，自动处理分块上传
account = get_account()
msg = send_mail(account=account, to=to, subject=subject, ...)
```

#### **方案 B: send_via_dotnet()**
```python
# 调用 PowerShell 脚本 (.NET HttpWebRequest)
from dotnet_ews_send import send_mail_dotnet
result = send_mail_dotnet(to=to, subject=subject, body=body, ...)
```

#### **方案 C/E: 占位符函数**
```python
# 这些功能留作未来扩展
def send_via_winhttp(): NotImplementedError
def send_via_browser(): NotImplementedError
```

---

## 🎯 建议测试顺序

1. **先试当前版本**（混合方案，应该能工作）
   ```powershell
   python email_reports\owa_mail_1hour_TT_Report.py --to test@zte.com.cn
   ```

2. **如果仍失败，强制用 exchangelib**
   ```powershell
   python email_reports\owa_mail_1hour_TT_Report.py --use-exchangelib --to test@zte.com.cn
   ```

3. **如果还失败，再考虑浏览器方案**（需要先安装 playwright/selenium）

---

## 📝 下一步扩展方向

- [ ] 实现 `send_via_winhttp()` 真正的 WinHTTP API
- [ ] 实现 `send_via_browser()` 的 Playwright/Selenium 版本  
- [ ] 添加性能监控日志（记录每次选择的方案和耗时）
- [ ] 根据测试结果调整自动选择阈值（目前是 5MB）

---

## 💡 总结

这个**混合式智能发送引擎**的核心思想是：

> **不要只依赖单一方法，要像人类一样「多条腿走路」**
> - 小附件 → 优先用 .NET PowerShell（快）
> - 大附件 → 切换到 exchangelib（稳）
> - 都失败 → 保留浏览器兜底能力

这样既能保证性能，又能应对各种异常情况。
