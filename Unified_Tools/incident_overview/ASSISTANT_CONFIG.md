# 虚拟助手电话/短信通知配置指南

## 概述

虚拟助手支持多种电话和短信服务提供商。您需要选择一个服务商并配置相应的凭证。

## 配置方式

### 方式1：环境变量（推荐）

在启动应用前设置环境变量：

**Windows (PowerShell):**
```powershell
$env:PHONE_SERVICE_PROVIDER="aliyun"
$env:ALIYUN_ACCESS_KEY="your_access_key"
$env:ALIYUN_ACCESS_SECRET="your_access_secret"
$env:ALIYUN_TTS_CODE="your_tts_code"
```

**Windows (CMD):**
```cmd
set PHONE_SERVICE_PROVIDER=aliyun
set ALIYUN_ACCESS_KEY=your_access_key
set ALIYUN_ACCESS_SECRET=your_access_secret
set ALIYUN_TTS_CODE=your_tts_code
```

**Linux/Mac:**
```bash
export PHONE_SERVICE_PROVIDER=aliyun
export ALIYUN_ACCESS_KEY=your_access_key
export ALIYUN_ACCESS_SECRET=your_access_secret
export ALIYUN_TTS_CODE=your_tts_code
```

### 方式2：创建 .env 文件（推荐用于开发）

在项目根目录创建 `.env` 文件：

```env
PHONE_SERVICE_PROVIDER=aliyun
ALIYUN_ACCESS_KEY=your_access_key
ALIYUN_ACCESS_SECRET=your_access_secret
ALIYUN_TTS_CODE=your_tts_code
ALIYUN_REGION=cn-hangzhou

SMS_SERVICE_PROVIDER=aliyun
ALIYUN_SMS_SIGN_NAME=your_sign_name
ALIYUN_SMS_TEMPLATE_CODE=your_template_code
```

然后在代码中加载（需要安装 python-dotenv）：
```python
from dotenv import load_dotenv
load_dotenv()
```

---

## 方案1：阿里云服务（国内推荐）

### 电话通知配置

1. **注册阿里云账号并开通语音服务**
   - 访问：https://dyvms.console.aliyun.com/
   - 开通"语音服务"

2. **创建语音模板**
   - 在控制台创建TTS模板
   - 记录模板代码（TtsCode）

3. **获取AccessKey**
   - 访问：https://ram.console.aliyun.com/manage/ak
   - 创建AccessKey ID和Secret

4. **安装SDK**
   ```bash
   pip install aliyun-python-sdk-core aliyun-python-sdk-dyvmsapi
   ```

5. **配置环境变量**
   ```bash
   PHONE_SERVICE_PROVIDER=aliyun
   ALIYUN_ACCESS_KEY=your_access_key
   ALIYUN_ACCESS_SECRET=your_access_secret
   ALIYUN_TTS_CODE=your_tts_template_code
   ALIYUN_REGION=cn-hangzhou  # 可选，默认cn-hangzhou
   ```

### 短信通知配置

1. **开通短信服务**
   - 访问：https://dysms.console.aliyun.com/
   - 开通"短信服务"

2. **创建签名和模板**
   - 创建短信签名（SignName）
   - 创建短信模板（TemplateCode）
   - 模板中可以使用变量，如：`您的工单{{content}}需要处理`

3. **配置环境变量**
   ```bash
   SMS_SERVICE_PROVIDER=aliyun
   ALIYUN_ACCESS_KEY=your_access_key  # 与电话服务共用
   ALIYUN_ACCESS_SECRET=your_access_secret  # 与电话服务共用
   ALIYUN_SMS_SIGN_NAME=your_sign_name
   ALIYUN_SMS_TEMPLATE_CODE=your_template_code
   ```

---

## 方案2：Twilio（国际服务）

### 电话通知配置

1. **注册Twilio账号**
   - 访问：https://www.twilio.com/
   - 注册账号并获取试用额度

2. **获取凭证**
   - Account SID
   - Auth Token
   - 购买或使用试用电话号码

3. **安装SDK**
   ```bash
   pip install twilio
   ```

4. **配置环境变量**
   ```bash
   PHONE_SERVICE_PROVIDER=twilio
   TWILIO_ACCOUNT_SID=your_account_sid
   TWILIO_AUTH_TOKEN=your_auth_token
   TWILIO_PHONE_NUMBER=+1234567890  # 您的Twilio号码
   ```

### 短信通知配置

1. **配置环境变量**
   ```bash
   SMS_SERVICE_PROVIDER=twilio
   TWILIO_ACCOUNT_SID=your_account_sid  # 与电话服务共用
   TWILIO_AUTH_TOKEN=your_auth_token  # 与电话服务共用
   TWILIO_PHONE_NUMBER=+1234567890  # 与电话服务共用
   ```

---

## 方案3：腾讯云服务

### 电话通知配置

1. **注册腾讯云账号并开通语音服务**
   - 访问：https://console.cloud.tencent.com/vms
   - 开通"语音服务"

2. **创建语音模板**
   - 在控制台创建语音模板
   - 记录模板ID

3. **获取SecretId和SecretKey**
   - 访问：https://console.cloud.tencent.com/cam/capi
   - 创建API密钥

4. **安装SDK**
   ```bash
   pip install tencentcloud-sdk-python
   ```

5. **配置环境变量**
   ```bash
   PHONE_SERVICE_PROVIDER=tencent
   TENCENT_SECRET_ID=your_secret_id
   TENCENT_SECRET_KEY=your_secret_key
   TENCENT_TEMPLATE_ID=your_template_id
   ```

### 短信通知配置

1. **开通短信服务**
   - 访问：https://console.cloud.tencent.com/sms
   - 开通"短信服务"

2. **创建应用、签名和模板**
   - 创建短信应用（AppId）
   - 创建短信签名（SignName）
   - 创建短信模板（TemplateID）

3. **配置环境变量**
   ```bash
   SMS_SERVICE_PROVIDER=tencent
   TENCENT_SECRET_ID=your_secret_id  # 与电话服务共用
   TENCENT_SECRET_KEY=your_secret_key  # 与电话服务共用
   TENCENT_SMS_APP_ID=your_app_id
   TENCENT_SMS_TEMPLATE_ID=your_template_id
   TENCENT_SMS_SIGN_NAME=your_sign_name
   ```

---

## 测试配置

### 测试电话通知

1. 配置好环境变量后，重启Flask应用
2. 在虚拟助手面板中点击"立即检查并通知"
3. 查看日志，应该显示实际的服务商名称（不再是"模拟模式"）

### 验证配置

如果配置正确，日志中会显示：
- `服务商: aliyun` (或 twilio/tencent)
- `电话通知已发送` (而不是"模拟模式")

如果配置错误，会显示具体的错误信息，如：
- `配置不完整`
- `SDK未安装`
- `调用失败: [具体错误]`

---

## 常见问题

### 1. 如何知道配置是否生效？

查看应用日志，如果显示"模拟模式"说明未配置，如果显示服务商名称（如"aliyun"）说明已配置。

### 2. 可以同时配置多个服务商吗？

可以，电话和短信可以分别配置不同的服务商：
- `PHONE_SERVICE_PROVIDER=aliyun` (电话用阿里云)
- `SMS_SERVICE_PROVIDER=twilio` (短信用Twilio)

### 3. 如何切换到模拟模式？

设置 `PHONE_SERVICE_PROVIDER=none` 或 `SMS_SERVICE_PROVIDER=none`

### 4. 国内推荐哪个服务商？

- **电话通知**：推荐阿里云（价格便宜，稳定性好）
- **短信通知**：推荐阿里云或腾讯云（国内到达率高）

### 5. 如何查看详细的错误信息？

查看Flask应用的终端输出，会显示详细的错误堆栈信息。

---

## 安全建议

1. **不要将凭证提交到代码仓库**
   - 使用环境变量或 `.env` 文件（已加入 `.gitignore`）

2. **定期轮换AccessKey**
   - 定期更换API密钥以提高安全性

3. **限制IP访问**
   - 在服务商控制台设置IP白名单

4. **监控使用量**
   - 定期检查服务使用量，避免异常消费

---

## 快速开始示例

### 使用阿里云（最简单）

```bash
# 1. 安装SDK
pip install aliyun-python-sdk-core aliyun-python-sdk-dyvmsapi aliyun-python-sdk-dysmsapi

# 2. 设置环境变量（Windows PowerShell）
$env:PHONE_SERVICE_PROVIDER="aliyun"
$env:ALIYUN_ACCESS_KEY="LTAI5t..."
$env:ALIYUN_ACCESS_SECRET="xxx..."
$env:ALIYUN_TTS_CODE="TTS_123456"

$env:SMS_SERVICE_PROVIDER="aliyun"
$env:ALIYUN_SMS_SIGN_NAME="您的签名"
$env:ALIYUN_SMS_TEMPLATE_CODE="SMS_123456"

# 3. 重启Flask应用
python app.py
```

配置完成后，虚拟助手就会实际发送电话和短信通知了！
