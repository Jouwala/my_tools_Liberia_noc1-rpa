# 局域网访问配置

Data Insight MVP 项目支持局域网内其他电脑通过 IP 地址访问。

> **注意**：本项目与 MTN_Comsal 项目共用端口（7038/7090），**不可同时运行**。

## 端口配置

| 服务 | 端口 | 说明 |
|------|------|------|
| 后端 (FastAPI) | 7038 | uvicorn 监听 0.0.0.0 |
| 前端 (Vite) | 7090 | Vite dev server 监听 0.0.0.0 |

## 配置步骤

### 1. 配置防火墙（首次运行）

右键以**管理员身份**运行 `firewall_setup.bat`，自动放行 7090 和 7038 端口。

### 2. 启动服务

双击 `start.bat` 启动前后端服务。启动成功后会显示本机 IP 地址：

```
============================================
  Data Insight MVP is running!
============================================

  Local access:
    Frontend: http://localhost:7090
    Backend:  http://localhost:7038

  LAN access (for other computers):
    Frontend: http://192.168.1.101:7090
    Backend:  http://192.168.1.101:7038
```

### 3. 其他电脑访问

在浏览器输入本机 IP + 端口号：
- 前端：`http://<本机IP>:7090`
- 后端：`http://<本机IP>:7038`

## 确认本机 IP

如果不确定本机 IP，在命令行执行：

```batch
ipconfig | findstr /i "IPv4"
```

输出示例：
```
IPv4 Address. . . . . . . . . . . : 192.168.1.101
```

## 常见问题

### Q: 防火墙已配置，但其他电脑仍无法访问？

1. **确认 IP 地址正确**：本机 IP 可能变化，使用 `ipconfig` 重新查看
2. **确认服务已启动**：`start.bat` 窗口保持运行状态
3. **确认防火墙规则**：以管理员身份重新运行 `firewall_setup.bat`
4. **确认无端口冲突**：本项目与 MTN_Comsal 不可同时运行

### Q: 修改端口后如何更新配置？

需要同步修改以下 3 个文件：

1. `frontend/vite.config.ts` - 修改 `port` 和 `proxy.target`
2. `start.bat` - 修改 uvicorn 启动参数和显示信息
3. `firewall_setup.bat` - 修改端口号

修改完成后重新运行 `firewall_setup.bat` 更新防火墙规则。
