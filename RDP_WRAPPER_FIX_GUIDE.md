# RDP Wrapper 多用户登录修复指南

## 问题诊断

你的系统：**Windows 10 Pro Build 26200**（非常新的版本）

当前状态：
- ❌ Wrapper state: **Not installed**
- ✅ Service state: Running
- ✅ Listener state: Listening

**根本原因**：Windows 版本太新，标准 RDP Wrapper v1.6.2 不支持，需要 RDPPatcher 补丁。

---

## 🚀 快速修复步骤

### 方案 A：自动修复（推荐）

#### 第 1 步：运行 RDPPatcher 补丁

1. **右键点击** `install_rdppatcher.bat`
2. 选择 **"以管理员身份运行"**
3. 等待下载完成
4. RDPPatcher 会自动打开
5. 在 RDPPatcher 窗口中：
   - 点击 **"Patch"** 按钮
   - 等待补丁完成（可能需要几分钟）
   - 如果提示重启，请重启计算机

#### 第 2 步：重新安装 RDP Wrapper

1. **右键点击** `fix_rdp_wrapper.bat`
2. 选择 **"以管理员身份运行"**
3. 等待安装完成

#### 第 3 步：验证状态

1. 打开 `C:\Program Files\RDP Wrapper\RDPConf.exe`
2. 检查状态应该显示：
   - ✅ **Wrapper state: Installed**
   - ✅ Service state: Running
   - ✅ Listener state: Fully Supported
   - ✅ Single Session: Disabled

---

### 方案 B：手动修复（如果方案 A 失败）

#### 第 1 步：下载最新配置文件

1. 访问：https://github.com/sebaxakerhtc/rdpwrap.ini
2. 下载最新的 `rdpwrap.ini`
3. 替换到：`C:\Program Files\RDP Wrapper\rdpwrap.ini`

#### 第 2 步：下载并运行 RDPPatcher

1. 访问：https://github.com/SniperThrilla/rdpwrap/releases/download/pythonoverhaul/RDPPatcher.exe
2. 下载 `RDPPatcher.exe`
3. **右键点击** → **"以管理员身份运行"**
4. 点击 **"Patch"** 按钮
5. 等待完成后重启计算机

#### 第 3 步：重新安装 RDP Wrapper

运行 `fix_rdp_wrapper.bat`（管理员权限）

---

## 🔧 常见问题排查

### 问题 1：仍然显示 "Not installed"

**原因**：Windows Defender 阻止了安装

**解决**：
```powershell
# 添加排除项（已自动执行）
Add-MpPreference -ExclusionPath 'C:\Program Files\RDP Wrapper'

# 临时关闭实时保护（如果需要）
Set-MpPreference -DisableRealtimeMonitoring $true
```

### 问题 2：RDPPatcher 下载失败

**原因**：网络问题或 GitHub 被墙

**解决**：
1. 使用代理或 VPN
2. 手动下载后放到 `C:\Program Files\RDP Wrapper\`

### 问题 3：补丁后仍然无法多用户登录

**可能原因**：
- Windows 组策略限制
- 远程桌面服务未正确启动

**解决**：
```cmd
# 检查远程桌面服务
sc query TermService

# 重启服务
net stop TermService /y
net start TermService

# 检查注册表设置
reg query "HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server" /v fSingleSessionPerUser
```

应该返回：`fSingleSessionPerUser    REG_DWORD    0x0`

---

## 📋 完整命令清单

```cmd
# 停止远程桌面服务
net stop TermService /y

# 卸载旧版本
cd "C:\Program Files\RDP Wrapper"
uninstall.bat

# 重新安装
RDPWInst.exe -i

# 启动服务
net start TermService

# 验证状态
RDPConf.exe
```

---

## ⚠️ 重要提示

1. **始终以管理员权限运行脚本**
2. **Windows 更新后可能需要重新打补丁**
3. **建议定期更新 rdpwrap.ini 配置文件**
4. **如果遇到安全软件拦截，请添加白名单**

---

## 📞 获取帮助

如果以上步骤都无法解决问题，请提供：

1. RDPConf.exe 的完整截图
2. 运行 `fix_rdp_wrapper.bat` 时的错误信息
3. Windows 版本号：`winver` 命令的输出

---

**最后更新**：2026-07-03  
**适用系统**：Windows 10/11 Build 22000+
