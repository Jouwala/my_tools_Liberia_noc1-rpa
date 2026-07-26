# 虚拟助手快速配置指南

## 为什么没有收到电话通知？

根据您的日志，检测到了 3rd_Power 工单，但没有发送电话，原因是：

1. **工单已被标记为已处理** - 系统会避免重复通知
2. **后端API未配置** - 当前返回的是模拟响应，未实际发送电话

## 快速配置步骤（以阿里云为例）

### 步骤1：安装SDK

```bash
pip install aliyun-python-sdk-core aliyun-python-sdk-dyvmsapi aliyun-python-sdk-dysmsapi
```

### 步骤2：获取阿里云凭证

1. 登录阿里云控制台：https://ram.console.aliyun.com/manage/ak
2. 创建AccessKey，获取：
   - AccessKey ID
   - AccessKey Secret

### 步骤3：开通语音服务

1. 访问：https://dyvms.console.aliyun.com/
2. 开通"语音服务"
3. 创建TTS模板，获取模板代码（TtsCode）

### 步骤4：配置环境变量

**Windows PowerShell:**
```powershell
$env:PHONE_SERVICE_PROVIDER="aliyun"
$env:ALIYUN_ACCESS_KEY="LTAI5txxxxxxxxxxxxx"
$env:ALIYUN_ACCESS_SECRET="xxxxxxxxxxxxxxxxxxxxx"
$env:ALIYUN_TTS_CODE="TTS_123456789"
```

**Windows CMD:**
```cmd
set PHONE_SERVICE_PROVIDER=aliyun
set ALIYUN_ACCESS_KEY=LTAI5txxxxxxxxxxxxx
set ALIYUN_ACCESS_SECRET=xxxxxxxxxxxxxxxxxxxxx
set ALIYUN_TTS_CODE=TTS_123456789
```

**Linux/Mac:**
```bash
export PHONE_SERVICE_PROVIDER=aliyun
export ALIYUN_ACCESS_KEY=LTAI5txxxxxxxxxxxxx
export ALIYUN_ACCESS_SECRET=xxxxxxxxxxxxxxxxxxxxx
export ALIYUN_TTS_CODE=TTS_123456789
```

### 步骤5：重启Flask应用

重启应用后，环境变量才会生效。

### 步骤6：测试

1. 在虚拟助手面板点击"清除已处理记录"
2. 点击"立即检查并通知"
3. 查看日志，应该显示：
   - `服务商: aliyun`（不再是"none"）
   - `电话通知已发送`（不再是"模拟模式"）

## 验证配置是否生效

查看Flask应用的终端输出，如果看到：
- ✅ `服务商: aliyun` - 配置成功
- ❌ `服务商: none` 或 `模拟模式` - 配置未生效

## 其他服务商

### Twilio（国际服务）

```bash
pip install twilio
```

```powershell
$env:PHONE_SERVICE_PROVIDER="twilio"
$env:TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxx"
$env:TWILIO_AUTH_TOKEN="your_auth_token"
$env:TWILIO_PHONE_NUMBER="+1234567890"
```

### 腾讯云

```bash
pip install tencentcloud-sdk-python
```

```powershell
$env:PHONE_SERVICE_PROVIDER="tencent"
$env:TENCENT_SECRET_ID="your_secret_id"
$env:TENCENT_SECRET_KEY="your_secret_key"
$env:TENCENT_TEMPLATE_ID="your_template_id"
```

## 使用 .env 文件（推荐）

1. 在项目目录创建 `.env` 文件
2. 添加配置：
   ```
   PHONE_SERVICE_PROVIDER=aliyun
   ALIYUN_ACCESS_KEY=your_key
   ALIYUN_ACCESS_SECRET=your_secret
   ALIYUN_TTS_CODE=your_code
   ```
3. 安装 python-dotenv：
   ```bash
   pip install python-dotenv
   ```
4. 重启应用（代码已自动支持加载.env文件）

## 详细文档

更多配置选项和故障排除，请查看：`ASSISTANT_CONFIG.md`
