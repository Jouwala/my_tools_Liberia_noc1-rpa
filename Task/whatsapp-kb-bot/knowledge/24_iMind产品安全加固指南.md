[图]

iMind
安全加固指南

产品版本：V6.26.30.F30

法律声明

若接收中兴通讯股份有限公司（以下称为“中兴通讯”）的此份文档，即表示您已同意以下条款。若不同意以下条款，请停止使用本文档。

本文档版权所有中兴通讯股份有限公司。保留任何未在本文档中明示授予的权利。文档中涉及中兴通讯的专有信息。未经中兴通讯事先书面许可，任何单位和个人不得复制、传递、分发、使用和泄漏该文档以及该文档包含的任何图片、表格、数据及其他信息。

和是中兴通讯的注册商标。中兴通讯产品的名称和标志是中兴通讯的商标或注册商标。在本文档中提及的其他产品或公司名称可能是其各自所有者的商标或注册商标。在未经中兴通讯或第三方权利人事先书面同意的情况下，阅读本文档并不表示以默示、不可反言或其他方式授予阅读者任何使用本文档中出现的任何标记的权利。 [图]

本产品符合有关环境保护和人身安全方面的设计要求，产品的存放、使用和弃置应遵照产品手册、相关合同或相关国法律、法规的要求进行。

本文档按“现状”和“仅此状态”提供。本文档中的信息随着中兴通讯产品和技术的进步将不断更新，中兴通讯不再通知此类信息的更新。
中兴通讯股份有限公司
**注意**：地址:
**注意**：中国深圳市科技南路55号
**注意**：邮编
**注意**：518057
**注意**：网站:
**注意**：http://support.zte.com.cn
**注意**：邮箱:
**注意**：800@zte.com.cn

版本更新说明
资料版本
日期
作者
审核者
批准者
A
2026-9-26
黄振宇
周艳
宋军

关于这篇文档
手册说明

## 该手册是依据安全加固策略，从攻击行为、安全策略和配置方法等方面指导用户加强网络安全和产品安全。

读者对象

## 本文档适用于负责配置和管理产品的运维工程师。您应该熟悉对应的领域基础知识，且具有丰富的网络部署与管理经验。

内容介绍

| 章节 | 描述 |
|---|---|
| 1 适用范围 | 本文档针对的产品版本 |
| 2 概述 | 产品安全加固的背景 |
| 3 安全加固项 | 安全加固执行条目 |
| 4 安全加固操作 | 具体安全加固操作方法 |
| 5 回退 | 回退操作执行方法 |
| 6 默认安全配置项 | 产品中默认已配置的安全项 |

目录
1. 适用范围1
2. 概述1
2.1 安全体系架构1
2.2 加固策略2
2.3 注意事项2
3. 安全加固项2
4. 安全加固操作3
4.1 加固流程3
4.2 加固前的准备和检查4
4.2.1 工具获取4
4.2.2 工具安装5
4.2.3 工具登录6
4.2.4 工具全局参数的设置7
4.3 操作系统加固8
4.3.1 安全加固条目8
4.3.2 使用inspector安全加固工具对系统加固36
4.4 非root启动安全加固43
4.4.1 非root启动43
4.4.2 非root启动支持的场景44
4.4.3 非root阶段一45
4.4.4 非root阶段二45
4.4.5 非root阶段三46
4.4.6 非root阶段四47
4.5 iDN平台组件安全加固48
4.5.1 执行的加固项48
4.5.2 Log组件加密算法选择48
4.5.3 密钥管理50
4.5.4 备份恢复完整性校验配置51
4.5.5 个人隐私保护加固52
4.5.6 文件传输协议选择52
4.5.7 账号策略54
4.5.8 密码策略选择55
4.5.9 IP限定策略56
4.5.10 认证参数57
4.5.11 禁用ZTE短信中心58
4.6 加固后的检查59
4.6.1 操作系统加固检查59
4.6.2 非root启动加固检查62
4.6.3 iDN平台组件加固检查62
5. 回退62
5.1 操作系统加固回退62
5.1.1 选择PAAS安全基线回退模板62
5.1.2 连接测试或互信63
5.1.3 执行回退63
5.2 非root加固回退64
5.3 iDN平台组件加固回退64
6. 默认安全配置项64
6.1 操作系统默认安全71
6.1.1 Linux登录系统相关配置71
6.1.2 Linux账号管理相关配置72
6.1.3 audit相关配置73
6.1.4 鉴权相关配置74
6.1.5 系统配置74
6.1.6 Linux日志管理相关配置75
6.1.7 系统维护相关配置75
6.1.8 网络配置76
6.1.9 系统服务配置78
6.2 iDN组件默认安全78

# 适用范围

## 本文档适用于iMind V6.26.30.F30的安全合规配置工作，适用于分布式系统的CGSL v5/v6系统。

# 概述

## 产品安全加固的目的是“通过配置、设置、协议限制来减小攻击面”（来源于《产品安全要求总则》），使得产品免于或减小所受网络安全攻击的影响。

## 产品安全加固主要内容包含产品安全合规配置和产品安全漏洞补丁两方面，加固对象为包括产品所使用的第三方软件（如操作系统、数据库、虚拟化组件等）和固件，以及部分自研模块。

## 安全合规配置是通过对加固对象中安全相关的配置项进行合理的设置，减小对象的攻击面，例如关闭不必要的端口、不必要的系统服务等；安全漏洞补丁是通过对加固对象的漏洞缺陷通过补丁升级的方式，使加固对象免予或减小遭受该漏洞带来的攻击影响，例如各类CVE漏洞、CNVD漏洞的补丁升级处理等。

安全体系架构

## iMind智能运维平台聚焦跨域运维场景，基于公司星云通信大模型和AI平台，提供被动运维和主动运维的闭环智能运维能力，实现智能事件管理，支撑我司网络智能运维产品向能力开放的架构演进，提升网络智能运维产品在运维监控排障场景下的自智能力从L2到L3,L4的演进，助力运营商自智网络能力等级的提升。

## iMind平台同时提供了核心网虚拟化网络运维保障能力，支撑CCN GSO产品在5GC，虚拟化运维保障领域国内外市场的集采、FOA测试及规模商用。

## [图]

加固策略

## 针对基于CGSL操作系统安装的环境，需要进行操作系统加固，详见4.3章节。

注意事项
加固前，请关注以下注意事项：
加固前必须执行“4.2 加固前准备和检查”。
Inspector执行安全加固后，名称上带有【重启OS生效】标识的加固项可能需要重启节点才能生效，因此，当有此标识的加固项检查失败时，请确认加固后是否重启过OS。如果没有，请在重启OS后重新进行检查。
执行安全加固后，如果通过SSH方式登录到PaaS节点上执行一个命令的时间超过5分钟，连接就会中断，造成命令执行失败。 即使命令执行中有打印输出也会中断连接。

# 安全加固项

| 加固类型 | 加固项 | 应对风险 | 加固阶段 | 工具支持 | 系统影响 |
|---|---|---|---|---|---|
| 容器启动 | 非root启动 | 最小权限 | 首次开局，升级 | 配置文件 | 无 |
| iDN平台组件 | iDN平台组件安全加固 | 信息泄露，不安全的加密算法等 | 首次开局，升级 | 配置文件，界面 | 无 |
| 操作系统 | 操作系统安全加固 | 暴力破解，网络攻击，网络嗅探，拒绝服务等 | 首次开局，升级 | TCF版本集成Inspector工具，安装后使用 | 无 |

# 安全加固操作

加固流程

## 首次开局/新建网络的加固流程如下图所示：

## [图]

## 其中操作系统加固由TCF系统附带的Inspector工具完成

## 系统升级后的加固流程如下图所示：

## [图]

加固前的准备和检查
此小节概述在操作系统安装后、iDN平台组件加固前应该执行的加固操作
工具获取
工具需要从TECS OpenPalette发布的版本包中或者从公司Support网站获取。
使用文档所要求的加固工具执行。
表格中列示的工具版本为示例，供参考。安全加固时请使用对应版本里的工具。

| 工具版本 | 工具路径 | 版本发布号（Support网站） |
|---|---|---|
| inspector_V07.23.10.06_230306 | TECS OpenPalette发布的版本包中，示例： TCFV7.23.20.03_tools.tar!/Inspector/inspector_V07.23.10.06_230306.bin |  |

工具安装
安装位置说明
TECS OpenPalette产品使用TECS Inspector工具时，需要先在PaaS controller节点上手工进行安装。

## 下面以场景6为例来说明工具的安装步骤（示例版本是inspector_v07.22.10.16_221112.bin，其他版本操作步骤一致）

## 步骤1：ssh到环境的PaaS控制节点，su root切换到root用户。

## 步骤2：将工具安装包inspector_v07.22.10.16_221112.bin上传到该节点，比如/home/vtu目录下：

## [图]

## 步骤3：执行下面命令开始安装：

## sh inspector_v07.22.10.16_221112.bin install

## [图]

## 关于工具安装的补充说明：

## 如果该节点上已经安装过TECS Inspector工具，则本次安装时会自动卸载后重新安装。

## 工具不支持HA，如果因重启等原因主节点发生了切换，则需要在新的主节点上重新安装。

## 如果工具安装的节点做了故障节点恢复，则需要在恢复后的节点上重新安装。

工具登录
推荐使用Chrome浏览器登录，登录地址为：https://工具安装的节点ip:8001。
用户名、密码为OpenPalette portal登录的用户名和密码。
登录成功：
[图]
[图]
工具全局参数的设置

## 登录TECS Inspector后，选择“配置”-“COMMON”菜单，可以设置工具的一些全局参数。如下图：

## [图]

## [图]

## 这些参数被修改、保存后，必须重新执行“节点互信”操作才能生效：

## [图]

## [图]

## 对安全加固操作关系比较密切的是“超时时长”、“节点最大并发数”两个参数，下面重点加以介绍。

##### 超时时长

## “超时时长”指的是每条加固项执行的最大时长，默认1800s，超过这个时长加固项没有执行结束的话，工具就会报该加固项超时失败。

## 提醒：加固时间跟环境的IO、节点数等有关，如果某加固项因执行超时失败，请将“超时时长”设置为3600s后重新执行。

##### 节点最大并发数

## “节点最大并发数”指的是相关操作执行时支持的最大节点并发数，工具默认值10，表示相关操作同时可以在10个节点上执行，如果选择的节点数量大于10，则工具会自动分批在其他节点上执行，导致执行时间会变长。

## 当需要支持超大规模场景时，比如选择的节点数量为2000，则可以通过修改“节点最大并发数”参数，来到达缩短执行时间的目的。并发数设置越大，执行时间就越短，参数上限为2000。

操作系统加固
安全加固条目

| 加固项编号 | 加固项目名称 | 检查说明 | 检查标准 | 处理建议 |
|---|---|---|---|---|
| OS-PRE-001 | 前置任务(必选项) | 加固、检查、回退操作前需要执行的任务 | 加固、检查、回退操作前需要执行的任务 | 加固、检查、回退操作前需要执行的任务 |
| OS-ACCESS-001 | 确保默认启用crond服务 | 检查crond服务是否设置自启动 | #systemctl is-enabled crond enabled | 默认自启动 |
| OS-ACCESS-002 | 确保设置cron相关配置文件权限 | 检查是否设置cron相关文件权限。 | /etc/crontab /etc/cron.hourly /etc/cron.daily /etc/weekly /etc/cron.monthly /etc/cron.d文件权限不高于600，属组和属主为root | 参考检查标准修改文件权限 |
| OS-ACCESS-003 | 确保cron仅限于授权用户 | 检查/etc/cron.deny文件；检查/etc/cron.allow配置允许用户。此加固的参数cron_user默认设置为：etcd,ubuntu | /etc/cron.deny不存在； /etc/cron.allow配置root nova keystone用户 | # rm /etc/cron.deny# touch /etc/cron.allow# chmod og-rwx /etc/cron.allow# chown root:root /etc/cron.allow# echo "root" > /etc/cron.allow # echo "nova" > /etc/cron.allow # echo "keystone" > /etc/cron.allow |
| OS-ACCESS-004 | 确保设置sshd配置文件权限 | 检查是否设置/etc/ssh/sshd_config文件权限。 | /etc/ssh/sshd_config属组属主为root；文件权限不高于600 | # chown root：root /etc/ssh/sshd_config# chmod og-rwx /etc/ssh/sshd_config |
| OS-ACCESS-005 | 确保ssh协议设置为2 | 检查是否设置ssh协议；ssh支持两种不同且不兼容的协议：ssh1和ssh2。ssh1是原始协议，存在安全问题。ssh2更先进更安全。 | # grep "^Protocol" /etc/ssh/sshd_configProtocol 2 | 修改/etc/ssh/sshd_config添加Protocol 2并重启sshd服务 |
| OS-ACCESS-006 | 确保设置SSH日志级别INFO | 检查是否设置ssh日志级别，INFO参数指定将记录登录和注销活动。 | # grep "^LogLevel" /etc/ssh/sshd_configLogLevel INFO | 修改/etc/ssh/sshd_config添加LogLevel INFO并重启sshd服务 |
| OS-ACCESS-007 | 确保禁用X11转发 | 检查是否设置禁用X11转发，X11转发参数提供通过连接隧道X11流量的能力，以启用远程图形连接。 | 检查/etc/ssh/sshd_config和/etc/ssh/sshd_config.d/目录下的文件中是否设置了X11Forwarding no | 在sshd_config中设置X11Forwarding no, /etc/ssh/sshd_config.d/目录下的所有文件中如果配置了X11Forwarding, 则必须设置为X11Forwarding no, 重启sshd服务 |
| OS-ACCESS-008 | 确保设置MaxAuthTries | 检查是否设置最大允许尝试次数，MaxAuthTries参数指定每个连接允许的最大身份验证尝试次数。当登录失败计数达到一半时，错误消息将写入系统日志文件，详细说明登录失败。 | # grep "^MaxAuthTries" /etc/ssh/sshd_configMaxAuthTries 4 | 修改/etc/ssh/sshd_config添加MaxAuthTries 4并重启sshd服务 |
| OS-ACCESS-009 | 确保启用IgnoreRhosts | IgnoreRhosts 参数指定.rhosts和.shosts文件不会在RhostsRSAAuthentication或HostbasedAuthentication中使用。 | # grep "^IgnoreRhosts" /etc/ssh/sshd_config IgnoreRhosts yes | 修改/etc/ssh/sshd_config添加IgnoreRhosts yes并重启sshd服务 |
| OS-ACCESS-010 | 确保禁用 HostbasedAuthentication | HostbasedAuthentication 参数指定是否允许通过.rhosts或/etc/hosts.equiv用户的受信任主机进行身份验证，以及成功的公钥客户端主机身份验证。此选项仅适用于ssh协议版本2 | # grep "^HostbasedAuthentication" /etc/ssh/sshd_config HostbasedAuthentication no | 修改/etc/ssh/sshd_config添加HostbasedAuthentication no并重启sshd服务 |
| OS-ACCESS-011 | 确保禁用root登录 | 检查是否设置禁止root用户远程登录 | # grep "^PermitRootLogin" /etc/ssh/sshd_configPermitRootLogin no | 修改/etc/ssh/sshd_config添加PermitRootLogin no并重启sshd服务 |
| OS-ACCESS-012 | 确保禁用PermitEmptyPasswords | PermitEmptyPasswords参数指定ssh服务器是否允许使用空密码字符串登录帐户，系统不允许空密码账户登录。 | # grep "^PermitEmptyPasswords" /etc/ssh/sshd_configPermitEmptyPasswords no | 修改/etc/ssh/sshd_config添加PermitEmptyPasswords no 并重启sshd服务 |
| OS-ACCESS-013 | 确保禁用PermitUserEnvironment | PermitUserEnvironment允许用户向ssh守护进程提供环境选项，但是是不安全的。 | # grep PermitUserEnvironment /etc/ssh/sshd_config PermitUserEnvironment no | 修改/etc/ssh/sshd_config添加PermitUserEnvironment no并重启sshd服务 |
| OS-ACCESS-014 | 确保配置ssh空闲超时间隔 | ClientAliveInterval 和 ClientAliveCountMax 控制ssh会话超时。当设置了客户端变量时，在指定的时间长度内没有活动的ssh会话将被终止。当设定客户端可变最大值时，SSHD将向每位客户端之间发送生存信息。 | # grep "^ClientAliveInterval" /etc/ssh/sshd_configClientAliveInterval 300# grep "^ClientAliveCountMax" /etc/ssh/sshd_config ClientAliveCountMax 0 | 修改/etc/ssh/sshd_config添加ClientAliveInterval 300 和ClientAliveCountMax 0并重启sshd服务 |
| OS-ACCESS-015 | 确保设置SSH警告语 | ssh登录时显示警告信息，在登录成功前不泄漏服务器信息检查。 | # grep "^Banner" /etc/ssh/sshd_configBanner /etc/issue.net | 修改/etc/ssh/sshd_config添加Banner /etc/issue.net并重启sshd服务 |
| OS-ACCESS-016 | 确保设置 ssh服务端认证最大并发数 | 设置ssh服务端认证最大并发数量 | # grep "^MaxStartups" /etc/ssh/sshd_config MaxStartups 5000:30:6000 | 修改/etc/ssh/sshd_config添加MaxStartups 5000:30:6000并重启sshd服务 |
| OS-ACCESS-017 | 确保关闭ssh最近一次登录提示 | 关闭ssh最近一次登录提示 | # grep "^PrintLastLog" /etc/ssh/sshd_config PrintLastLog no | 修改/etc/ssh/sshd_config添加PrintLastLog no并重启sshd服务 |
| OS-ACCESS-018 | 确保禁用telnet协议 | 系统禁用telnet协议 | 检查配置文件/etc/xinetd.d/telnet是否存在，不存在合规。如果存在，检查是否配置disable = yes。 | 检查配置文件/etc/xinetd.d/telnet是否存在，不存在合规。如果存在，添加配置disable = yes |
| OS-ACCESS-019 | 确保配置ftp旗标 | 设置系统ftp登录警告语 | 如果不存在/etc/vsftpd/vsftpd.conf认为通过； #grep "^ftpd_banner=" /etc/vsftpd/vsftpd.conf ftpd_banner=/etc/issue | 根据检查标准修改配置文件 |
| OS-ACCESS-020 | 禁止使用Tunnel设备 | 禁止使用Tunnel设备 | # grep '^PermitTunnel' /etc/ssh/sshd_config PermitTunnel no | 修改/etc/ssh/sshd_config添加PermitTunnel no |
| OS-ACCESS-021 | 禁止SSH Agent转发 | 禁止SSH Agent转发 | grep '^AllowAgentForwarding' /etc/ssh/sshd_config \nAllowAgentForwarding no | 修改/etc/ssh/sshd_config配置AllowAgentForwarding no |
| OS-ACCESS-022 | 设置LoginGraceTime值 | 设置LoginGraceTime值 | # grep '^LoginGraceTime' /etc/ssh/sshd_config \LoginGraceTime 60 | 修改/etc/ssh/sshd_config添加LoginGraceTime 60 |
| OS-ACCESS-023 | 设置ssh访问用户限制 | 是否配置了AllowUsers | 文件/etc/ssh/sshd_config中配置了AllowUsers | 根据需要在文件/etc/ssh/sshd_config中配置AllowUsers |
| OS-ACCESS-024 | 确保禁止连接转发到SSH客户端端口 | 确保禁止连接转发到SSH客户端端口 | 查看/etc/ssh/sshd_config是否设置了GatewayPorts no | 修改/etc/ssh/sshd_config添加GatewayPorts no |
| OS-ACCESS-025 | 设置SSH服务器秘钥交换算法 | 检查/etc/ssh/sshd_config中是否设置了KexAlgorithms | grep '^KexAlgorithms' /etc/ssh/sshd_config 输出是否不为空 | 在/etc/ssh/sshd_config中设置KexAlgorithms curve25519-sha256@libssh.org,diffie-hellman-group-exchange-sha256,ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521 |
| OS-ACCESS-026 | 确保设置Ciphers加密算法 | 是否配置了Ciphers | grep '^\s*Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr' /etc/ssh/sshd_config | echo 'Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr' >> /etc/ssh/sshd_config |
| OS-ACCESS-027 | 确保设置MACs加密算法 | 是否配置了MACs | grep '^\s*MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com,hmac-sha2-512,hmac-sha2-256' /etc/ssh/sshd_config | echo 'MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com,hmac-sha2-512,hmac-sha2-256' >> /etc/ssh/sshd_config |
| OS-ACCESS-028 | 设置SSH服务器/客户端认证算法 | 设置SSH服务器/客户端认证算法 | grep '^\s*CASignatureAlgorithms ecdsa-sha2-nistp521,ecdsa-sha2-nistp384,ecdsa-sha2-nistp256' /etc/ssh/sshd_config;grep '^\s*HostKeyAlgorithms ecdsa-sha2-nistp521,ecdsa-sha2-nistp384,ecdsa-sha2-nistp256' /etc/ssh/sshd_config | echo 'CASignatureAlgorithms ecdsa-sha2-nistp521,ecdsa-sha2-nistp384,ecdsa-sha2-nistp256' >> /etc/ssh/sshd_config;echo 'HostKeyAlgorithms ecdsa-sha2-nistp521,ecdsa-sha2-nistp384,ecdsa-sha2-nistp256' >> /etc/ssh/sshd_config |
| OS-ACCESS-029 | 屏蔽或删除无用的用户 | 检查是否屏蔽或删除无用的用户:games uucp lp ftp news mail | 检查是否屏蔽或删除无用的用户:games uucp lp ftp news mail | 屏蔽或删除无用的用户:games uucp lp ftp news mail |
| OS-ACCESS-030 | 屏蔽或删除无用的用户组 | 检查是否屏蔽或删除无用的用户组:lp mail news uucp games ftp floppy mailnull | 检查是否屏蔽或删除无用的用户组:lp mail news uucp games ftp floppy mailnull | 屏蔽或删除无用的用户组:lp mail news uucp games ftp floppy mailnull |
| OS-ACCESS-032 | 确保at/cron仅限于授权用户，并设置白名单 | 确保at/cron仅限于授权用户，并设置白名单 | 检查/etc/at.allow中是否存在etcd; 检查/etc/cron.allow中是否存在etcd | chmod 600 /etc/cron.allow;chmod 600 /etc/at.allow;chown root:root /etc/cron.allow;chown root:root /etc/at.allow;echo 'etcd' >> /etc/at.allow;echo 'etcd' >> /etc/cron.allow |
| OS-ACCESS-033 | 确保未配置telnet端口 | 检查未配置telnet端口 | 检查/etc/services文件中，(telnet 23)行是否被注释 | 检查/etc/services文件中，(telnet 23)行是否被注释 |
| OS-ACCESS-036 | 确保已启用SSH PAM | 确保/etc/ssh/sshd_config中配置了UsePAM yes | 确保/etc/ssh/sshd_config中配置了UsePAM yes | 确保/etc/ssh/sshd_config中配置了UsePAM yes |
| OS-ACCOUNT-001 | 确保配置密码生命周期 | 设置允许管理员账户密码生命周期；设置密码到期前N天开始提示，密码修改时间间隔以达到账户密码保护要求。本加固项设置密码生命周期的用户会排除如下系统预置用户：ubuntu,root,pict,tecs,backup,itool,vtu,hacluster。 | # grep PASS_MAX_DAYS /etc/login.defsPASS_MAX_DAYS 90# grep PASS_MIN_DAYS /etc/login.defsPASS_MIN_DAYS 7# grep PASS_MIN_LEN /etc/login.defsPASS_MIN_LEN 8# grep PASS_WARN_AGE /etc/login.defsPASS_WARN_AGE 14 | 根据检查标准修改/etc/login.defs配置 |
| OS-ACCOUNT-002 | 对预置用户设置密码最大有效期 | 根据配置对预置用户设置密码最大有效期系统预置用户为：ubuntu,root,pict,tecs,backup,itool,vtu,hacluster。 | 根据配置对预置用户(root、ubuntu等)设置密码最大有效期 | chage -M 90 root;chage -M 90 ubuntu |
| OS-ACCOUNT-003 | 设置锁定inactive账号 | 设置锁定inactive账号 | 运行useradd -D \|grep INACTIVE查看是否INACTIVE设置值不为-1 | 执行sudo useradd -D -f 30 |
| OS-ACCOUNT-004 | 确保系统帐户不可登录 | 限制系统内部使用的账户不允许作为登录用户使用。 | # egrep -v "^\+" /etc/passwd \| awk -F： '($1!="root" && $1!="sync" && $1!="shutdown" && $1!="halt" && $3<1000 && $7!="/sbin/nologin" && $7!="/bin/false") {print}'输出为空 | 删除或锁定无关系统账户 |
| OS-ACCOUNT-005 | 确保root帐户的默认组GID为0 | 为root帐户使用gid 0有助于防止非特权用户意外访问根拥有的文件。 | # grep "^root:" /etc/passwd \| cut -f4 -d：0 | 无 |
| OS-ACCOUNT-006 | 确保设置用户umask值 | 默认umask确定用户创建的文件的权限。创建文件的用户有权通过chmod命令让其他人读取其文件和目录。默认情况下，希望允许他人读取其文件和目录的用户可以通过将umask命令插入其主目录中的标准shell配置文件（.profile、.bashrc等）来选择不同的默认umask。 | # grep "^umask" /etc/bashrc umask 022 # grep "^umask" /etc/profile umask 022上述输出中的022为举例，实际为加固项参数2设置的umask值。 | 根据检查标准修改配置文件 |
| OS-ACCOUNT-007 | 确保对su命令访问限制 | su命令允许用户作为另一个用户运行命令或shell。该程序已被sudo取代，sudo允许对特权访问进行更精细的控制。通常，su命令可以由任何用户执行。通过在/etc/pam.d/su中取消对pam wheel.so语句的注释，su命令将只允许wheel组中的用户执行su | # grep pam_wheel.so /etc/pam.d/su auth required pam_wheel.so use_uid | 根据检查标准修改配置文件 |
| OS-ACCOUNT-008 | 确保限制ftp匿名访问 | 限制ftp匿名用户的访问 | 不存在/etc/vsftpd/vsftpd.conf认为通过。 #grep "^anonymous_enable=NO" /etc/vsftpd/vsftpd.conf anonymous_enable=NO | 根据检查标准修改配置文件 |
| OS-ACCOUNT-009 | 确保设置登录会话超时退出 | 限制非活动的登录会话超时强制退出 | #grep "TMOUT" /etc/profile export TMOUT=300 | 根据检查标准修改配置文件 |
| OS-ACCOUNT-010 | 非root用户nologin限制 | 限制sshd非root用户nologin | #grep "pam_noloin.so" /etc/pam.d/sshd account required pam_nologin.so | /etc/pam.d/sshd文件中删除account required pam_nologin.so |
| OS-ACCOUNT-012 | 限制root登录不安全终端 | 限制root登录不安全终端 | 配置文件/etc/pam.d/login包含auth [user_unknown=ignore success=ok ignore=ignore auth_err=die default=bad] pam_securetty.so | 根据检查标准修改配置文件 |
| OS-ACCOUNT-013 | 检查是否记录帐户登录日志 | 检查是否记录帐户登录日志 | # grep '^LASTLOG_ENAB' /etc/login.defs \nLASTLOG_ENAB yes \n# grep '^FAILLOG_ENAB' /etc/login.defs \nFAILLOG_ENAB yes | 根据检查标准修改/etc/login.defs配置 |
| OS-ACCOUNT-014 | 配置history历史命令数目和bash_history文件中的记录数 | 配置history历史命令数目和bash_history文件中的记录数 | #grep 'HISTSIZE' /etc/profile \\nexport HISTSIZE=100 \\n grep 'HISTFILESIZE' /etc/profile | 根据检查标准修改配置文件 |
| OS-ACCOUNT-015 | 设置bootloader密码 | 设置bootloader密码 | 修改/etc/grub.d/01_users文件增加bootloader的密码设置，并执行grub2-mkconfig命令使设置生效 | 根据检查标准修改配置文件 |
| OS-ACCOUNT-016 | 设置rescue认证 | 设置rescue认证 | 查看/etc/sysconfig/init确认是否配置了SINGLE=/sbin/sulogin | 在/etc/sysconfig/init增加SINGLE=/sbin/sulogin配置 |
| OS-ACCOUNT-017 | 确保root用户登录仅限于系统控制台 | 是否配置了root用户登录仅限于系统控制台 | 文件/etc/securetty中配置了console | echo 'console' > /etc/securetty |
| OS-ACCOUNT-018 | 通过规则文件限制用户本地登录(非SSH) | 检查是否存在/etc/security/userdenyfile | 检查是否存在/etc/security/userdenyfile | touch /etc/security/userdenyfile |
| OS-ACCOUNT-019 | 禁止普通用户查看其他用户的登录信息 | 检查/bin/w的权限是否为750 | stat -c '%a' /bin/w | chmod g-w,o-rwx /bin/w |
| OS-ACCOUNT-020 | 删除用户别名 | 删除用户别名。用户为：games ingres system toor uucp manager dumper operator decode | 是否已经删除用户别名 | 删除用户别名 |
| OS-ACCOUNT-021 | /etc/sysconfig/init中设置umask 027 | 检查/etc/sysconfig/init中是否存在umask 027 | grep '^\s*umask 027' /etc/sysconfig/init 输出是否不为空 | echo 'umask 027' >> /etc/sysconfig/init |
| OS-ACCOUNT-022 | 设置/etc/security权限为600 | 检查/etc/security权限为600 | stat -c %a /etc/security/ \|grep 600 输出是否不为空 | chmod 600 /etc/security |
| OS-ACCOUNT-023 | 确保删除ftp用户 | 确保删除ftp用户 | 检查节点上不存在ftp用户 | 检查节点上不存在ftp用户 |
| OS-ACCOUNT-024 | 设置tecs账号sudo白名单 | 检查tecs账号是否设置了用户sudo白名单 | 检查tecs账号是否设置了用户sudo白名单 | 为tecs账号配置sudo白名单 |
| OS-ACCOUNT-025 | 设置itool账号sudo白名单 | 检查itool账号是否无法使用sudo | 检查itool账号是否无法使用sudo | 设置itool账号无法使用sudo |
| OS-AUDIT-001 | 确保已启用内核启动的审核 | 检查是否设置内核参数GRUB_CMDLINE_LINUX="audit=1" | #grep "audit=1" /etc/default/grub输出不为空 | /etc/default/grub文件GRUB_CMDLINE_LINUX的行增加audit=1并执行grub2-mkconfig重新生成grub.cfg |
| OS-AUDIT-002 | 确保收集修改日期和时间信息的事件 | 检查audit设置记录日期和时间信息修改的事件 | # grep time-change /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务： -a always，exit -F arch=b64 -S adjtimex -S settimeofday -k time-change-a always，exit -F arch=b32 -S adjtimex -S settimeofday -S stime -k time-change-a always，exit -F arch=b64 -S clock_settime -k time-change-a always，exit -F arch=b32 -S clock_settime -k time-change-w /etc/localtime -p wa -k time-change |
| OS-AUDIT-003 | 确保收集修改用户/组信息的事件 | 检查audit设置记录用户/用户组修改的事件 | # grep identify /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务： -w /etc/group -p wa -k identity-w /etc/passwd -p wa -k identity-w /etc/gshadow -p wa -k identity-w /etc/shadow -p wa -k identity-w /etc/security/opasswd -p wa -k identity |
| OS-AUDIT-004 | 确保收集修改系统网络环境的事件 | 检查audit设置记录系统网络修改的事件 | # grep system-locale /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务： -a always，exit -F arch=b64 -S sethostname -S setdomainname -k system-locale-a always，exit -F arch=b32 -S sethostname -S setdomainname -k system-locale-w /etc/issue -p wa -k system-locale-w /etc/issue.net -p wa -k system-locale-w /etc/hosts -p wa -k system-locale-w /etc/sysconfig/network -p wa -k system-locale |
| OS-AUDIT-005 | 确保收集修改系统强制访问控制的事件 | 检查audit设置记录系统强制访问控制并修改的事件 | # grep MAC-policy /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务：-w /etc/selinux/ -p wa -k MAC-policy-w /usr/share/selinux/ -p wa -k MAC-policy |
| OS-AUDIT-006 | 确保收集登录和注销事件 | 检查audit设置记录登录和注销事件 | # grep logins /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务： -w /var/log/lastlog -p wa -k logins-w /var/run/faillock/ -p wa -k logins-w /var/log/faillog -p wa -k logins-w /var/log/tallylog -p wa -k logins |
| OS-AUDIT-007 | 确保收集会话启动信息 | 检查audit设置记录会话启动信息事件 | # grep session /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务：-w /var/run/utmp -p wa -k session-w /var/log/wtmp -p wa -k logins-w /var/log/btmp -p wa -k logins |
| OS-AUDIT-008 | 确保收集任意访问控制权限修改事件 | 检查audit设置记录任意访问控制权限修改事件 | # grep perm_mod /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务：-a always，exit -F arch=b64 -S chmod -S fchmod -S fchmodat -F auid>=1000 -F auid!=4294967295 -k perm_mod-a always，exit -F arch=b32 -S chmod -S fchmod -S fchmodat -F auid>=1000 -F auid!=4294967295 -k perm_mod-a always，exit -F arch=b64 -S chown -S fchown -S fchownat -S lchown -F auid>=1000 -F auid!=4294967295 -k perm_mod-a always，exit -F arch=b32 -S chown -S fchown -S fchownat -S lchown -F auid>=1000 -F auid!=4294967295 -k perm_mod-a always，exit -F arch=b64 -S setxattr -S lsetxattr -S fsetxattr -S removexattr -S lremovexattr -S fremovexattr -F auid>=1000 -F auid!=4294967295 -k perm_mod-a always，exit -F arch=b32 -S setxattr -S lsetxattr -S fsetxattr -S removexattr -S lremovexattr -S fremovexattr -F auid>=1000 -F auid!=4294967295 -k perm_mod |
| OS-AUDIT-009 | 确保收集未成功的未授权文件访问尝试 | 检查audit设置记录未成功的未授权文件访问尝试事件 | # grep access /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务：-a always，exit -F arch=b64 -S creat -S open -S openat -S truncate -S ftruncate -F exit=-EACCES -F auid>=1000 -F auid!=4294967295 -k access-a always，exit -F arch=b32 -S creat -S open -S openat -S truncate -S ftruncate -F exit=-EACCES -F auid>=1000 -F auid!=4294967295 -k access-a always，exit -F arch=b64 -S creat -S open -S openat -S truncate -S ftruncate -F exit=-EPERM -F auid>=1000 -F auid!=4294967295 -k access-a always，exit -F arch=b32 -S creat -S open -S openat -S truncate -S ftruncate -F exit=-EPERM -F auid>=1000 -F auid!=4294967295 -k access |
| OS-AUDIT-010 | 确保成功收集文件系统装载 | 检查audit设置记录文件系统装载事件 | # grep mounts /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务：-a always，exit -F arch=b64 -S mount -F auid>=1000 -F auid!=4294967295 -k mounts-a always，exit -F arch=b32 -S mount -F auid>=1000 -F auid!=4294967295 -k mounts |
| OS-AUDIT-011 | 确保收集用户的文件删除事件 | 检查audit设置记录用户对文件的删除事件 | # grep delete /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务：-a always，exit -F arch=b64 -S unlink -S unlinkat -S rename -S renameat -F auid>=1000 -F auid!=4294967295 -k delete-a always，exit -F arch=b32 -S unlink -S unlinkat -S rename -S renameat -F auid>=1000 -F auid!=4294967295 -k delete |
| OS-AUDIT-012 | 确保收集对系统管理范围（sudoers）的更改 | 检查audit设置记录对系统管理范围（sudoers）的修改 | # grep scope /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务：-w /etc/sudoers -p wa -k scope-w /etc/sudoers.d -p wa -k scope |
| OS-AUDIT-013 | 确保收集系统管理员操作 | 检查audit设置记录系统管理员操作事件 | # grep tactions /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务：-w /var/log/sudo.log -p wa -k actions |
| OS-AUDIT-014 | 确保收集内核模块加载和卸载 | 检查audti设置收集内核模块加载和卸载事件 | # grep modules /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务：-w /sbin/insmod -p x -k modules-w /sbin/rmmod -p x -k modules-w /sbin/modprobe -p x -k modules-a always，exit -F arch=b64 -S init_module -S delete_module -k modules |
| OS-AUDIT-015 | 确保设置审计日志存储参数 | 检查audit配置文件是否设置日志存存储参数 | # grep max_log_file /etc/audit/auditd.conf有设置值# grep max_log_file_action /etc/audit/auditd.conf与设置的参数一致 | /etc/audit/auditd.conf配置max_log_file 32和max_log_file_action KEEP_LOGS or ROTATE |
| OS-AUDIT-016 | 确保收集特权程序的使用 | 检查系统是否对特权程序进行审计 | audit审计规则包含对所有特权程序的审计 | 对系统特权程序设置审计规则 |
| OS-AUDIT-017 | 确保记录dockerrunc修改的事件 | 检查系统是否记录dockerrunc修改的事件 | # grep docker-runc /etc/audit/audit.rules不为空 | 在文件/etc/audit/rules.d/audit.rules中添加规则并重启auditd服务：-w /usr/bin/docker-runc -k docker |
| OS-AUDIT-018 | 确保审核配置是不可变的 | 检查审核配置是不可变的 | # grep "^[[：space：]]*\-e [[：space：]]*2$" /etc/audit/rules.d/audit.rules-e 2 | 在文件/etc/audit/rules.d/audit.rules最后添加-e 2 并重启auditd服务 |
| OS-AUDIT-019 | 配置audit的磁盘空间不足的处理 | 配置audit的磁盘空间不足的处理 | 查看/etc/audit/auditd.conf是否设置了space_left_action = email及admin_space_left_action = halt | 在文件/etc/audit/auditd.conf修改space_left_action = email及admin_space_left_action = halt并重启auditd服务 |
| OS-AUTHN-001 | 确保设置密码哈希算法为sha-512 | 设置密码加密算法为SHA-512，账户设置或修改密码都会使用新算法到存储中。 | #grep -E '^\s*password\s+sufficient\s+pam_unix.so\s+.*sha512\s*.*$' /etc/pam.d/password-auth /etc/pam.d/system-auth | /etc/pam.d/password-auth /etc/pam.d/system-auth 中password sufficient pam_unix.so的行设置sha512 |
| OS-AUTHN-002 | 确保配置了密码创建要求 | 系统设置创建密码的要求，使得用户设置（修改）密码达到安全要求。 | 检查配置文件/etc/pam.d/system-auth设置密码复杂度参数：try_first_pass difok=5 minlen=8 dcredit=-1 ucredit=-1 lcredit=-1 nocredit=-1 minclass=3 检查配置文件/etc/security/pwquality.conf 设置密码复杂度参数：difok = 5 minlen = 8 dcredit = -1 ucredit = -1 lcredit = -1 nocredit = -1 minclass = 3 | 在/etc/pam.d/system-auth中pam_pwquality.so的行设置密码复杂度参数；在配置文件/etc/security/pwquality.conf中设置difok=5 minlen=8 dcredit=-1 ucredit=-1 lcredit=-1 nocredit=-1 minclass=3参数 |
| OS-AUTHN-003 | 确保配置了密码尝试失败的锁定(faillock) | 配置密码尝试失败的锁定，用户输错密码达到设定次数将被锁定。 | 检查配置文件/etc/pam.d/su /etc/pam.d/system-auth /etc/pam.d/password-auth设置pam_faillock锁定时间和锁定次数 | 在配置文件/etc/pam.d/system-auth /etc/pam.d/password-auth文件第三行添加auth required pam_faillock.so preauth audit silent deny=5 unlock_time=900\nauth [success=1 default=bad] pam_unix.so\nauth [default=die] pam_faillock.so authfail audit deny=5 unlock_time=900\nauth sufficient pam_faillock.so authsucc audit deny=5 unlock_time=900 |
| OS-AUTHN-004 | 确保限制密码重复使用 | 限制账户密码重复使用 | # grep -P "password\h+(requisite\|sufficient)\h+(pam_pwhistory\.so\|pam_unix\.so)" /etc/pam.d/password-auth输出中的remember=5或更多# grep -P "password\h+(requisite\|sufficient)\h+(pam_pwhistory\.so\|pam_unix\.so)" /etc/pam.d/system-auth输出中的remember=5或更多 | 在配置文件/etc/pam.d/password-auth 和 /etc/pam.d/system-auth中配置'password requisite pam_pwhistory.so enforce_for_root remember=5' |
| OS-AUTHN-006 | 配置密码复杂度要求使用的模块 | 是否根据配置选择使用pam_cracklib.so模块或pam_pwquality.so模块 | 检查/etc/pam.d/system-auth和/etc/pam.d/password-auth中是否使用了配置的密码复杂度模块 | 当参数为0时，在/etc/pam.d/system-auth和/etc/pam.d/password-auth中设置pam_cracklib.so模块;当参数为1时，设置pam_pwquality.so模块 |
| OS-AUTHN-008 | 限制用户登录失败尝试次数 | 限制用户登录失败尝试次数 | 限制用户登录失败尝试次数 | 在/etc/pam.d/system-auth和/etc/pam.d/password-auth中限制用户登录失败尝试次数 |
| OS-AUTHN-009 | 禁止root用户近端登录 | 禁止root用户近端登录 | grep 'auth required pam_succeed_if.so user != root quiet' /etc/pam.d/login 输出是否不为空 | echo 'auth required pam_succeed_if.so user != root quiet' >> /etc/pam.d/login |
| OS-AUTHN-010 | 设置密码失败次数和锁定时间 | 检查是否设置了密码失败次数和锁定时间 | 检查/etc/pam.d/login中是否存在pam_tally2.so deny=5 unlock_time=1800相关配置 | 在/etc/pam.d/login中根据参数设置pam_tally2.so deny=5 unlock_time=1800 |
| OS-CONFIG-001 | 确保设置/home分区挂载参数 | 检查/home分区设置nodev挂载参数；nodev不解析文件系统上的块特殊设备 | 1.检查/etc/fstab中/home分区设置挂载参数nodev 2.mount \|grep "/home"\|grep nodev 输出结果不为空 | 1./etc/fstab中设置/home分区挂载参数nodev 2. mount -o remount，nodev /home |
| OS-CONFIG-002 | 确保设置/dev/shm分区挂载参数 | 检查/dev/shm分区是否设置nosuid，nodev，noexec挂载参数；noexec 不允许执行此文件系统上的二进制文件；nodev不解析文件系统上的块特殊设备；nosuid禁止suid操作和设定 sgid 位 | 1.检查/dev.shm中/home分区设置挂载参数nosuid，nodev，noexec 2.mount \|grep "/dev/shm"\|grep nosuid\|grep nodev \|grep noexec 输出结果不为空 | 1./etc/fstab中设置/dev/shm挂载参数nosuid，nodev ，noexec 2. mount -o remount，nodev /home |
| OS-CONFIG-003 | 【重启OS生效】确保设置bootloader文件权限 | 检查系统启动文件grub.cfg文件权限 | 1.检查/boot/grub2/grub.cfg权限是否不高于640，属组和属主是否是root用户；文件不存在认为通过 2.检查/boot/efi/EFI/cgsl/grub.cfg权限是否不高于640，属组和属主是否是root用户；文件不存在认为通过 | 1.chmod 600 /boot/grub2/grub.cfg ； chown root：root /boot/grub2/grub.cfg 2.修改/etc/fstab中/boot/efi分区挂参数为uid=0，gid=0，umask=0177，重启系统生效 |
| OS-CONFIG-004 | 确保限制core dump | 检查系统是否设置了限制进程core dump | 1.# grep "hard [[：space：]]*core" /etc/security/limits.conf * hard core 0 2.# sysctl fs.suid_dumpable fs.suid_dumpable = 03.# grep "soft [[：space：]]*core" /etc/security/limits.conf * soft core 0 4. grep "^[[：space：]]*kernel.core_pattern" /etc/sysctl.conf kernel.core_pattern=/var/log/coredump/core-sig%s-pid%p-uid%u-%e5.grep "^[[：space：]]*DefaultLimitCORE" /etc/systemd/system.conf DefaultLimitCORE=06.grep "^[[：space：]]*ulimit -S -c 0" /etc/profile ulimit -S -c 0 >/dev/null 2>&1 | 1.配置文件/etc/security/limits.conf中添加行* hard core 0 2.配置文件/etc/security/limits.conf中添加行* soft core 0 3.配置文件/etc/sysctl.conf中添加fs.suid_dumpable = 0并执行sysctl -p4.配置文件/etc/sysctl.conf 中添加kernel.core_pattern=/var/log/coredump/core-sig%s-pid%p-uid%u-%e5.配置文件/etc/systemd/system.conf中添加DefaultLimitCORE=06.配置文件/etc/profile中添加ulimit -S -c 0 >/dev/null 2>&1 |
| OS-CONFIG-005 | 命令行警告语 | 检查系统中警告语文件内容及文件权限是否正确 | 1.检查/etc/issue /etc/motd /etc/issue.net不显示系统版本信息，如： # egrep '(\\v\|\\r\|\\m\|\\s)' /etc/motd 2.检查/etc/issue /etc/motd /etc/issue.net文件权限等于644，文件属组和属主为root | 配置合理的警告语，根据检查标准设置文件权限 |
| OS-CONFIG-006 | 确保设置sudo安全策略 | 设置sudo只能从psuedo-pty运行 | 检查/etc/sudoers 设置Defaults use_pty | 检查/etc/sudoers 设置Defaults use_pty |
| OS-CONFIG-007 | 确保设置系统内核ASLR参数 | 检查系统设置randomize_va_space | sysctl -a 2>/dev/null\|grep '^kernel.randomize_va_space =' | 设置kernel.randomize_va_space = 2 |
| OS-CONFIG-009 | 确保在/tmp分区上设置nodev、nosuid和noexec选项 | 检查在/tmp分区上是否设置nodev、nosuid和noexec选项 | mount \| grep ' /tmp ' \| grep nosuid \| grep nodev \| grep noexec 是否输出为空 | 在文件/etc/fstab中的/tmp分区上设置nodev、nosuid、noexec |
| OS-CONFIG-011 | 确保gpgcheck全局激活 | 检查文件/etc/yum.conf和/etc/yum.repos.d/下所有文件中是否gpgcheck=1 | grep 'gpgcheck\s*=\s*1' /etc/yum.conf 是否输出不为空grep 'gpgcheck\s*=\s*1' /etc/yum.repos.d/所有文件 是否输出不为空 | 在/etc/yum.conf和/etc/yum.repos.d/下所有文件中增加gpgcheck=1 |
| OS-GRUB-001 | 【重启OS生效】检查处理器预测执行漏洞 | 检查grub性能参数是否存在 | 文件/etc/default/grub里不能含有如下性能参数:spec_store_bypass_disable=off nospectre_v1=off mds=off nopti spectre_v2=off tsx_async_abort=off l1tf=off kvm.nx_huge_pages_recovery_ratio=0 pti=off | 去掉grub某些性能参数spec_store_bypass_disable=off nospectre_v1=off mds=off nopti spectre_v2=off tsx_async_abort=off l1tf=off kvm.nx_huge_pages_recovery_ratio=0 pti=off根据OS版本不同，本加固项有时需要重启后才会生效。 |
| OS-LOG-001 | 确保rsyslog服务开启 | 检查rsyslog是否默认启动 | #systemctl is-active rsyslog active #systemctl is-enable rsyslog enable | 设置服务默认启动 |
| OS-LOG-002 | 确保配置日志记录(CIS,VDF,CMCC) | 检查rsyslog配置记录系统日志、鉴权日志、cron日志等 | #grep '^daemon.\\*' /etc/rsyslog.conf不为空#grep '^kern.\\*' /etc/rsyslog.conf不为空#grep '^syslog.\\*' /etc/rsyslog.conf不为空#grep '^lpr,news,uucp,local0,local1,local2,local3,local4,local5,local6.\\*' /etc/rsyslog.conf不为空 | 根据检查标准设置日志记录，并重启rsyslog服务 |
| OS-LOG-002-2 | 确保配置日志记录(AIS) | 检查/etc/rsyslog.conf中是否存在auth,user.* | grep -e '\\s*auth,user.\\* \\s*\\/var\\/log\\/messages' /etc/rsyslog.conf不为空 | echo -e 'auth,user.* /var/log/messages' >> /etc/rsyslog.conf |
| OS-LOG-003 | 确保rsyslog文件默认权限 | 检查rsyslog配置默认日志文件权限； 设置/var/log下日志文件权限 | # grep "^\$FileCreateMode" /etc/rsyslog.conf$FileCreateMode 0640 | 根据检查标准设置/etc/rsyslog.conf文件$FileCreateMode 0640参数；修改/var/log下日志文件默认权限不高于640，属主属组为root |
| OS-LOG-004 | 确保设置rsyslog发送到远程日志服务器 | 检查rsyslog配置远程日志服务器 | # grep "^*.*[^I][^I]*@" /etc/rsyslog.conf *.* @@loghost.example.com | 配置远程日志服务器*.* @@{server_ip}并重启rsyslog服务 |
| OS-LOG-005 | 安装AIDE监控 | 安装AIDE监控 | 运行rpm -qa aide查看是否安装了aide软件包，并运行crontab -l 命令确认是否设置了/usr/sbin/aide --check的定时任务 | 安装aide软件包并添加/usr/sbin/aide --check的定时任务 |
| OS-LOG-006 | 确保设置journal日志存储 | 设置journal日志转储；设置日志永久写入磁盘 | 检查/etc/systemd/journald.conf设置Compress=yes Storage=persistent | 在文件/etc/systemd/journald.conf设置Compress=yes Storage=persistent |
| OS-LOG-007 | 确保配置了对所有日志文件的权限 | 是否配置了对所有日志文件的权限 | 根据PaaS系统实际需要设置所有日志文件的权限 | 根据PaaS系统实际需要设置所有日志文件的权限 |
| OS-LOG-009 | 设置日志轮转的文件数量 | 检查/etc/logrotate.d/下所有配置文件中是否设置了rotate | 检查/etc/logrotate.d/下所有配置文件中是否设置了rotate | 在/etc/logrotate.d/下所有配置文件中设置rotate |
| OS-LOG-010 | 设置日志轮转的文件大小 | 检查/etc/logrotate.d/下所有配置文件中是否设置了size | 检查/etc/logrotate.d/下所有配置文件中是否设置了size | 在/etc/logrotate.d/下所有配置文件中设置size |
| OS-LOG-011 | 设置系统日志的最大轮转留存日期 | 检查/etc/logrotate.d/syslog中是否设置maxage 90 | grep '^\s*maxage\s*90' /etc/logrotate.d/syslog | 在/etc/logrotate.d/syslog中设置maxage 90 |
| OS-LOG-012 | 设置rsyslog日志文件权限 | 检查是否设置rsyslog日志文件权限 | 检查/var/log/spooler、/var/log/boot.log、/var/log/maillog文件权限 | touch /var/log/spooler;touch /var/log/boot.log;touch /var/log/maillog;chmod 600 /var/log/spooler;chmod 600 /var/log/boot.log;chmod 600 /var/log/maillog;chown root:root /var/log/spooler;chown root:root /var/log/boot.log;chown root:root /var/log/maillog |
| OS-LOG-013 | 检查安全事件日志配置 | 检查/etc/rsyslog.conf中是否存在*.err;kern.debug;daemon.notice /var/log/messages | grep -e '\s*\*\.err;kern.debug;daemon.notice\s*\/var\/log\/messages' /etc/rsyslog.conf | echo -e '*.err;kern.debug;daemon.notice /var/log/messages' >> /etc/rsyslog.conf |
| OS-MAINTEN-001 | 确保设置账户密码相关文件权限 | 设置账户密码相关配置文件权限 | /etc/passwd /etc/shadow /etc/group文件权限不大于644，属组和属主为root | 根据检查标准修改文件权限 |
| OS-MAINTEN-002 | 确保设置sysctl.conf文件权限 | 设置内核参数配置文件权限 | /etc/sysctl.conf 文件权限等于600，，属组和属主为root | 根据检查标准修改文件权限 |
| OS-MAINTEN-003 | 确保不存在空密码账户 | 系统不允许存在空密码的账户，否则不安全。 | # cat /etc/shadow \| awk -F： '($2 == "" ) { print $1}'输出为空 | 无 |
| OS-MAINTEN-004 | 确保只有root账户UID为0 | 只允许root账户的uid为0 | #cat /etc/passwd \| awk -F： '($3 == 0) { print $1 }' root | 无 |
| OS-MAINTEN-005 | 确保存在用户家目录与设置权限 | 检查账户存在家目录并且文件夹权限合理 | 要求账户存在家目录即：/home/testuser；目录权限默认700 | 创建用户家目录并且修改权限 |
| OS-MAINTEN-006 | 锁定无关账户 | 检查系统是否存在无关账户 | 锁定无关账户：adm,apache,at,avahi,bin,daemon,dbus,distcache,ftp,games,gdm,gopher,haldaemon,irc,ldap,listen,lp,mail,mailnull,man,mysql,named,news,nfsnobody,noaccess,nobody,nobody4,nscd,ntp,operator,pcap,pop,postfix,rpc,rpcuser,rpm,sabayon,smmsp,snort,squid,uucp,vcsa,webalizer,webservd,wwwrun,xfs | 锁定无关账户：adm,apache,at,avahi,bin,daemon,dbus,distcache,ftp,games,gdm,gopher,haldaemon,irc,ldap,listen,lp,mail,mailnull,man,mysql,named,news,nfsnobody,noaccess,nobody,nobody4,nscd,ntp,operator,pcap,pop,postfix,rpc,rpcuser,rpm,sabayon,smmsp,snort,squid,uucp,vcsa,webalizer,webservd,wwwrun,xfs |
| OS-MAINTEN-007 | 确保关闭系统信任主机 | 查看系统配置信息是否不存在信任主机，即检查系统中是否有.netrc .rhosts hosts.equiv的文件 | # find / -maxdepth 3 -name .netrc 2>/dev/null # find / -maxdepth 3 -name .rhosts 2>/dev/null # find / -maxdepth 3 -name hosts.equiv 2>/dev/null输出为空 | 删除无关文件 |
| OS-MAINTEN-008 | Bash安全漏洞检查 | 检查Bash是否存在漏洞，确保子变量不会被识别为全局变量 | #env VAR='() { ：；}； echo Bash is vulnerable!' bash -c "echo Bash Test" Bash Test | 无 |
| OS-MAINTEN-009 | 禁用CTRL+ALT+DEL | 禁止通过CTRL+ALT+DEL组合键控制主机 | 不存在 /usr/lib/systemd/system/ctrl-alt-del.target文件 | 备份或删除 /usr/lib/systemd/system/ctrl-alt-del.target |
| OS-MAINTEN-010 | 检查不必要的启动项 | 限制系统使用不必要的启动项程序 | # ls /etc/rc2.d/* /etc/rc3.d/* /etc/rc4.d/* /etc/rc5.d/* 2>/dev/null\|egrep "lp\|rpc\|snmpdx\|keyserv\|nscd\|Volmgt\|uucp\|dmi\|sendmail\|autoinstall"\|wc -l 0 | 删除或备份无关启动项 |
| OS-MAINTEN-011 | 绿盟检查重要目录或文件权限设置 | 检查下面目录权限是否为750:/etc/rc0.d//etc/rc1.d//etc/rc2.d//etc/rc3.d//etc/rc4.d//etc/rc5.d//etc/rc6.d/ | 检查下面目录权限是否为750:/etc/rc0.d//etc/rc1.d//etc/rc2.d//etc/rc3.d//etc/rc4.d//etc/rc5.d//etc/rc6.d/ | chmod 750 /etc/rc0.d/chmod 750 /etc/rc1.d/chmod 750 /etc/rc2.d/chmod 750 /etc/rc3.d/chmod 750 /etc/rc4.d/chmod 750 /etc/rc5.d/chmod 750 /etc/rc6.d/ |
| OS-MAINTEN-012 | 确保设置系统关键文件权限 | 设置系统关键文件权限 | /etc/default/* /etc/init.d/* /etc/rc*.d/文件禁止777 | 根据检查标准修改文件权限 |
| OS-MAINTEN-013 | 确保设置polkit默认管理权限 | 检查polkit默认管理权限是否为root | 文件/etc/polkit-1/rules.d/50-default.rules中的return内容为“unix-user:root” | 将polkit配置文件/etc/polkit-1/rules.d/50-default.rules中return内容修改为“unix-user:root” |
| OS-MAINTEN-014 | 删除tcpdump包 | 是否删除了tcpdump包 | rpm -q tcpdump 是否存在tcpdump包 | yum erase tcpdump -y >/dev/null |
| OS-MAINTEN-015 | 删除strace包 | 是否删除了strace包 | rpm -q strace 是否存在strace包 | yum erase strace -y >/dev/null |
| OS-MAINTEN-016 | 删除gdb包 | 是否删除了gdb包 | rpm -q gdb 是否存在gdb包 | yum erase gdb -y >/dev/null |
| OS-MAINTEN-017 | 删除gcc包 | 是否删除了gcc包 | rpm -q gcc 是否存在gcc包 | yum erase gcc -y >/dev/null |
| OS-MAINTEN-018 | 删除cpp包 | 是否删除了cpp包 | rpm -q cpp 是否存在cpp包 | yum erase cpp -y >/dev/null |
| OS-MAINTEN-019 | 锁定无关用户 | 检查是否锁定无关用户 | 锁定无关用户 | 锁定无关用户 |
| OS-MAINTEN-023 | 确保部分rpm包不被安装 | 检查talk,xorg-x11*,avahi,cups,ypbind,telnet,rsh,vsftpd是否被安装 | rpm -qa \|grep '^$servicename' | rpm -e 已经安装的rpm包 |
| OS-MAINTEN-025 | 删除wget包 | 是否删除了wget包 | rpm -q wget 是否存在wget包 | yum erase wget -y >/dev/null |
| OS-MAINTEN-026 | 卸载SNMP | 检查net-snmp是否安装 | rpm -q net-snmp\|grep 'is not installed | yum erase net-snmp -y |
| OS-NETWORK-001 | 确保禁用数据包重定向发送 | 确保禁用数据包重定向发送；ICMP重定向用于向其他主机发送路由信息，由于主机本身不充当路由器（在仅主机配置中），因此无需发送重定向 | #sysctl -n net.ipv4.conf.all.send_redirects 0 #sysctl -n net.ipv4.conf.default.send_redirects 0 | 配置文件/etc/sysctl.conf添加net.ipv4.conf.all.send_redirects = 0并执行sysctl -p配置文件/etc/sysctl.conf添加net.ipv4.conf.default.send_redirects = 0并执行sysctl -p |
| OS-NETWORK-002 | 确保不接受源路由数据包 | 确保不接受源路由数据包；在网络中，源路由允许发送方部分或完全指定通过网络的路由。相反，非源路由数据包的传输路径由网络中的路由器决定。在某些情况下，系统可能无法路由或无法从某些位置访问（例如，专用地址与Internet路由），因此需要使用源 路由数据包。 | #sysctl -n net.ipv4.conf.all.accept_source_route 0 #sysctl -n net.ipv4.conf.default.accept_source_route 0 | 配置文件/etc/sysctl.conf添加net.ipv4.conf.all.accept_source_route = 0并执行sysctl -p配置文件/etc/sysctl.conf添加net.ipv4.conf.default.accept_source_route = 0并执行sysctl -p |
| OS-NETWORK-003 | 确保不接受ICMP重定向 | 确保不接受ICMP重定向；ICMP重定向消息是传递路由信息并告诉主机（充当路由器）通过备用路径发送数据包的数据包。这是一种允许外部路由设备更新系统路由表的方法。通过将net.ipv4.conf.all.accept_重定向设置为0，系统将不接受任何ICMP重定向消息，因此不允许外部人员更新系统的路由表 | #sysctl -n net.ipv4.conf.all.accept_redirects 0 #sysctl -n net.ipv4.conf.default.accept_redirects 0 | 配置文件/etc/sysctl.conf添加net.ipv4.conf.all.accept_redirects = 0并执行sysctl -p配置文件/etc/sysctl.conf添加net.ipv4.conf.default.accept_redirects = 0并执行sysctl -p |
| OS-NETWORK-004 | 确保不接受安全的ICMP重定向 | 确保不接受安全的ICMP重定向；安全的ICMP重定向与ICMP重定向相同，只是它们来自默认网关列表上列出的网关。假设您的系统知道这些网关，并且它们很可能是安全的。 | #sysctl -n net.ipv4.conf.all.secure_redirects 0 #sysctl -n net.ipv4.conf.default.secure_redirects 0 | 配置文件/etc/sysctl.conf添加net.ipv4.conf.all.secure_redirects = 0并执行sysctl -p 配置文件/etc/sysctl.conf添加net.ipv4.conf.default.secure_redirects = 0并执行sysctl -p |
| OS-NETWORK-005 | 确保记录可疑数据包 | 确保记录可疑数据包；启用后，此功能会将源地址不可路由的数据包记录到内核日志中。 | #sysctl -n net.ipv4.conf.all.log_martians 0 #sysctl -n net.ipv4.conf.default.log_martians 0 | 配置文件/etc/sysctl.conf添加net.ipv4.conf.all.log_martians = 0并执行sysctl -p 配置文件/etc/sysctl.conf添加net.ipv4.conf.default.log_martians = 0并执行sysctl -p |
| OS-NETWORK-006 | 确保忽略广播的ICMP请求 | 确保忽略广播的ICMP请求；将net.ipv4.icp_echo_ignore_broadcasts设置为1将使系统忽略对广播和多播地址的所有ICMP echo和时间戳请求。 | #sysclt -n net.ipv4.icmp_echo_ignore_broadcasts 1 | 配置文件/etc/sysctl.conf添加net.ipv4.icmp_echo_ignore_broadcasts = 1并执行sysctl -p |
| OS-NETWORK-007 | 确保忽略伪造的ICMP响应 | 确保忽略伪造的ICMP响应；将icmp_ignore_bogus_error_responses设置为1，可防止内核记录虚假响应（RFC-1122不兼容）的广播折射，防止文件系统用无用的日志消息填充。 | #sysctl -n net.ipv4.icmp_ignore_bogus_error_responses 1 | 配置文件/etc/sysctl.conf添加net.ipv4.icmp_ignore_bogus_error_responses = 1并执行sysctl -p |
| OS-NETWORK-008 | 确保启用反向路径筛选 | 确保启用反向路径筛选；将net.ipv4.conf.all.rp_filter和net.ipv4.conf.default.rp_filter设置为1将强制Linux内核对接收到的数据包使用反向路径筛选来确定数据包是否有效。本质上，通过反向路径过滤，如果返回数据包没有从对应的源数据包来自的同一个接口流出，则会丢弃该数据包（如果设置了Log_Martian，则会记录该数据包）。 | #sysctl -n net.ipv4.conf.all.rp_filter 1 #sysctl -n net.ipv4.conf.default.rp_filter 1 | 配置文件/etc/sysctl.conf添加net.ipv4.conf.all.rp_filter = 1并执行sysctl -p 配置文件/etc/sysctl.conf添加net.ipv4.conf.default.rp_filter = 1并执行sysctl -p |
| OS-NETWORK-009 | 确保启用了TCP SYN Cookies | 确保启用了TCP SYN Cookies；当设置tcp-syncookies时，内核将正常处理tcp-syn数据包，直到半开连接队列满为止，此时syn-cookie功能开始发挥作用。SYN cookies的工作原理是根本不使用SYN队列。相反，内核只是简单地用syn ack回复syn，但它将包含一个专门编制的TCP序列号，该序列号对源和目标IP地址和端口号以及发送数据包的时间进行编码。一个合法的连接将发送带有特制序列号的三路握手的ACK包。 这允许系统验证是否已收到对SYN cookie的有效响应，并允许连接，即使队列中没有对应的SYN。 | #sysctl -n net.ipv4.tcp_syncookies 1 | 配置文件/etc/sysctl.conf添加net.ipv4.tcp_syncookies = 1并执行sysctl -p |
| OS-NETWORK-010 | 确保不接受IPv6重定向 | 确保不接受IPv6重定向；此设置阻止系统接受ICMP重定向。ICMP重定向告诉系统发送流量的备用路由。 | #sysctl -n net.ipv6.conf.all.accept_redirects0#sysctl -n net.ipv6.conf.default.accept_redirects0 | 配置文件/etc/sysctl.conf添加net.ipv6.conf.all.accept_redirects = 0并执行sysctl -p 配置文件/etc/sysctl.conf添加net.ipv6.conf.default.accept_redirects = 0并执行sysctl -p |
| OS-NETWORK-011 | 确保设置dnsmasq顺序解析 | 检查dnsmasq是否配置顺序解析参数 | #grep "^[[：space：]]*strict-order" /etc/dnsmasq.conf strict-order | /etc/dnsmasq.conf添加strict-order并重启服务 |
| OS-NETWORK-012 | 确保不接受IPv6的RA通告 | 确保不接受IPv6的RA通告 | #sysctl -n net.ipv6.conf.all.accept_ra0#sysctl -n net.ipv6.conf.default.accept_ra0 | 配置文件/etc/sysctl.conf添加net.ipv6.conf.all.accept_ra = 0并执行sysctl -p ;配置文件/etc/sysctl.conf添加net.ipv6.conf.default.accept_ra = 0并执行sysctl -p |
| OS-NETWORK-014 | 确保设置禁用传输协议驱动 | 确保禁用dccp sctp rds tipc cramfs freevxfs jffs2 hfs hfsplus squashfs udf数据传输协议驱动 | 检查某模块时, 执行'lsmod \| grep 模块名'命令, 返回为空, 说明已经禁用。以dccp为例: 'lsmod \| grep dccp' | 设置禁用dccp sctp rds tipc cramfs freevxfs jffs2 hfs hfsplus squashfs udf数据传输协议驱动 |
| OS-NETWORK-015 | 设置是否启用通过路由器通告前缀自动配置IPv6地址 | 根据配置设置autoconf | #sysctl -n net.ipv6.conf.all.autoconf1#sysctl -n net.ipv6.conf.default.autoconf1 | 配置文件/etc/sysctl.conf添加net.ipv6.conf.all.autoconf = 1并执行sysctl -p ;配置文件/etc/sysctl.conf添加net.ipv6.conf.default.autoconf = 1并执行sysctl -p |
| OS-NETWORK-016 | 确保IPv6已禁用 | 根据配置判断是否禁用IPv6 | 如果参数IPV6_DISABLED=1, 'modprobe -c\|grep ipv6\|grep disable' 返回 'options ipv6 disable=1'；如果参数IPV6_DISABLED=0, 'modprobe -c\|grep ipv6\|grep disable' 返回为空或 'options ipv6 disable=0' | 当参数IPV6_DISABLED=1时，禁用IPv6 |
| OS-NETWORK-017 | 配置IPv4协议堆栈 | 配置IPv4协议堆栈 | #sysctl -n net.ipv4.icmp_ratelimit1000#sysctl -n net.ipv4.icmp_ratemask6168 | 配置文件/etc/sysctl.conf添加net.ipv4.icmp_ratelimit=1000,net.ipv4.icmp_ratemask=6168,并执行sysctl -p |
| OS-NETWORK-018 | 配置IPv6协议堆栈 | 配置IPv6协议堆栈 | #sysctl -n net.ipv6.conf.all.accept_source_route0#sysctl -n net.ipv6.conf.default.accept_source_route0 | 配置文件/etc/sysctl.conf添加net.ipv6.conf.all.accept_source_route=0,net.ipv6.conf.default.accept_source_route=0,并执行sysctl -p |
| OS-NETWORK-019 | 确保设置接受SYN同步包的最大连接数量 | 检查是否配置了net.ipv4.tcp_max_syn_backlog | #sysctl -n net.ipv4.tcp_max_syn_backlog4096 | 配置文件/etc/sysctl.conf添加net.ipv4.tcp_max_syn_backlog=4096,并执行sysctl -p |
| OS-NETWORK-019 | 确保设置接受SYN同步包的最大连接数量 | 检查是否配置了net.ipv4.tcp_max_syn_backlog | #sysctl -n net.ipv4.tcp_max_syn_backlog4096 | 配置文件/etc/sysctl.conf添加net.ipv4.tcp_max_syn_backlog=4096,并执行sysctl -p |
| OS-NETWORK-020 | 加固处理ICMP | 如果参数HARDEN_HANDLING_OF_ICMP为1,则拦截部分类型的ICMP报文.参数为0则不拦截. | bash /paasdata/op-conf/inetrules/icmp_security.sh on check | bash /paasdata/op-conf/inetrules/icmp_security.sh on |
| OS-NETWORK-022 | 确保打开路由转发 | 检查是否设置打开路由转发；转发标志用于告诉系统它是否可以转发数据包 | #sysctl -n net.ipv4.ip_forward 1 | 配置文件/etc/sysctl.conf添加net.ipv4.ip_forward = 1net.ipv6.route.flush = 1并执行sysctl -p |
| OS-NETWORK-023 | 不关闭多IP绑定 | 不关闭多IP绑定 | 检查/etc/host.conf文件中multi参数的值配置为on | /etc/host.conf文件中multi参数的值配置为on |
| OS-SELINUX-001 | 确保SELinux状态正在强制执行以及配置了SELinux策略 | 检查文件/etc/default/grub中是否配置SELINUX=enforcing | grep '^\s*SELINUX\s*=\s*enforcing' /etc/default/grub 是否输出不为空 | 在/etc/default/grub中增加SELINUX=enforcing |
| OS-SELINUX-002 | 【重启OS生效】设置SELinux策略 | 设置selinux策略为disabled、permissive或enforcing | 检查/etc/selinux/config中的SELINUX是否与配置相符 | 在/etc/selinux/config中配置SELINUX为disabled、permissive或enforcing。 |
| OS-SELINUX-003 | 【重启OS生效】设置Docker selinux策略 | 设置docker selinux策略为false或true | docker info --format {{.SecurityOptions}} \| grep selinux“true”表示开启，“false”或不存在表示关闭 | 在/etc/docker/daemon.json中配置selinux-enabled为true或false。 |
| OS-SERVICE-001 | 时钟同步服务 | 检查时钟服务chronyd是否启用 | chronyd服务为active 和 enabled状态 | chronyd默认开启 |
| OS-SERVICE-002 | avahi服务 | 检查avahi-daemon是否关闭 | avahi-daemon服务为inactive 和 disable状态 | avahi-daemon默认关闭 |
| OS-SERVICE-003 | 确保设置邮箱服务器 | 检查系统是否开启邮箱服务器，如果开启需要设置只处理本地邮件 | 检查邮件服务器配置只处理本地邮件 | 设置/etc/postfix/main.cf 参数inet_interfaces = loopback-only |
| OS-SERVICE-004 | 确保配置了NTP | 检查文件/etc/ntp.conf中是否存在ntp需要的配置 | grep 'restrict -6 default kod' /etc/ntp.conf \|grep 'notrap' \|grep 'nomodify' \|grep 'nopeer' \|grep 'noquery' 和 grep 'restrict -4 default kod' /etc/ntp.conf \|grep 'notrap' \|grep 'nomodify' \|grep 'nopeer' \|grep 'noquery'输出都不为空 | 在/etc/ntp.conf中增加'restrict -4 default kod nomodify notrap nopeer noquery和restrict -6 default kod nomodify notrap nopeer noquery' |
| OS-SERVICE-005 | 确保未安装LDAP客户端 | 检查openldap-clients是否被安装 | rpm -q openldap-clients | yum -y remove openldap-clients |
| OS-SERVICE-006 | 配置LDAP支持双因子鉴权认证 | 配置LDAP支持双因子鉴权认证 | 当REMOTE_LDAP不为空时，在/etc/ssh/sshd_config中配置LDAP支持双因子鉴权认证 | 当REMOTE_LDAP不为空时，在/etc/ssh/sshd_config中配置LDAP支持双因子鉴权认证 |
| OS-POST-001 | 后置任务(必选项) | 加固、检查、回退操作后需要执行的任务 | 加固、检查、回退操作后需要执行的任务 | 加固、检查、回退操作后需要执行的任务 |

使用inspector安全加固工具对系统加固

##### 上传加固包版本

## 初次登录时或工具使用过程中加固包有更新时，需要上传加固包版本。

## 通过“版本管理”-“上传版本”来上传加固包：

## [图]

## [图]

## 点击“上传版本”，在弹出的对话框中选择对应的加固包版本，上传成功后，会出现在版本列表中（以PAAS_SEC-v7.22.40.06.13255688.zip为例）：

## [图]

## [图]

##### 执行PaaS加固

执行PaaS加固需要使用工具左侧导航栏上的“安全加固”-“PAAS”菜单。

###### 选择PAAS安全基线加固模板

依次点击“安全加固”-“PAAS”，再点击右侧“请选择模板”下拉框，从中选择“PAAS 安全基线加固 public模板(version:v7.22.40.06)”项（上传加固包后下拉框里才会有这个选项），点击“创建”按钮：
[图]
[图]
选项上的版本号说明：
列表中显示的版本号“version:v7.22.40.06”是加固包的版本号，并不是工具的版本号。
同一类型加固包的不同版本，工具上自动显示并使用最后导入的一个。

###### 连接测试或互信

点击“创建”后会弹出节点互信对话框。
直接使用默认的ubuntu用户，点击“节点互信”按钮：
[图]
[图]

###### 执行加固

互信成功后即可进入执行加固界面：
[图]
[图]

加固前需要先选择节点，点击右上角“选择节点”按钮，在弹出的对话框中选择要加固的节点：
[图]
[图]

点击上方的“立即执行”按钮，或者加固项列表后面“操作”区的“执行”按钮，即可开始执行PaaS加固：
[图]
[图]

加固过程中，可以随时使用“全部停止”按钮中止本次加固的执行。
[图]
[图]
容器启动安全加固
非root启动
安装部署前，使用OKI工具配置容器是否以root启动。应用容器内的业务进程以oes:oes（uid：3001，gid：3001）启动，应用容器的启动脚本仍以root启动。
非root启动的核心是：如何把容器私有文件、持久化卷的文件、HostPath的文件的属主（包括owner和group）由root修改为非root，其中容器私有文件、HostPath的文件的属主修改为oes，而NFS持久化卷的文件的属主修改为nfsnobody:nfsnobody(uid：65534，gid：65534)。NFS持久化卷的文件的属主修改只有部分升级场景需要进行，是否需要修改取决于PaaS的权限压缩开关是否打开。若PaaS的权限压缩开关打开，则升级时不需要修改NFS持久化卷的文件的属主；否则，需要修改。
非root启动支持的场景

| PVC类型 | 场景 | 旧方案（容器以root启动，业务进程以普通用户启动）的支持情况 | 旧方案（容器以root启动，业务进程以普通用户启动）开始支持的版本 | 新方案（容器以普通用户启动）的支持情况 | 新方案（容器以普通用户启动）开始支持的版本 |
|---|---|---|---|---|---|
| 内置NFS | 全新安装（启用权限压缩） | 阶段一 | V1.20.30.05 V1.20.20.06P01HP03 | 阶段四 | V2.22.20.02 |
|  | 从root升级到非root（第一次安装时，已打开了PaaS的权限压缩开关（针对所有用户）） | 阶段二（无需对PVC文件的属主和权限单独处理，可直接支持） | V1.20.40.06P01 | 阶段四（无需对PVC文件的属主和权限单独处理，可直接支持） | V2.22.20.02 |
|  | 从root升级到非root（第一次安装时，未打开PaaS的权限压缩开关，若干次升级后也不会打开） | 阶段二（OTCP暂不支持；无线UME支持） | OTCP OKI暂不支持；无线UME的OKI支持 | 阶段四（OTCP暂不支持；无线UME支持） | V2.22.20.02 |
|  | 从非root升级到非root | 阶段二（无需对PVC文件的属主和权限单独处理，可直接支持） | V1.20.40.06P01 | 阶段四（无需对PVC文件的属主和权限单独处理，可直接支持） | V2.22.20.02 |
| 裸设备+Ceph | 全新安装 | 阶段二（无需对PVC文件的属主和权限单独处理，可直接支持） | OTCP的OKI从2021Q1开始支持 | 阶段四（无需对PVC文件的属主和权限单独处理，可直接支持） | V2.22.20.02 |
|  | 从root升级到非root（升级前是Ceph，升级后也是Ceph） | 阶段二（OTCP暂不支持；无线UME支持） | OTCP OKI暂不支持；无线UME的OKI支持 | 阶段四（OTCP暂不支持；无线UME支持） | V2.22.20.02 |
|  | 从非root升级到非root | 阶段二（无需对PVC文件的属主和权限单独处理，可直接支持） | OTCP的OKI从2021Q1开始支持 | 阶段四（无需对PVC文件的属主和权限单独处理，可直接支持） | V2.22.20.02 |
| All-in-one（裸设备单节点） | 全新安装 | 阶段一 | V1.20.30.05 V1.20.20.06P01HP03 | 阶段四 | V2.22.20.02 |
| GlusterFS | 全新安装 | 阶段三 | V2.21.30.05 | 阶段四 | V2.22.20.02 |

配置方法
非root阶段一
默认还是以root用户启动。部分有需要的局点可以手工打开非root开关，以oes用户（用户名：oes，用户组：oes，uid：3001，gid：3001）启动。以oes用户启动支持全新安装和升级，但分别都只有部分场景是支持的，主要取决于PVC的类型（阶段一不处理PVC，只要PVC能支持权限压缩，就能以oes用户运行）。
是否以oes用户运行，由用户在安装或升级前在OKI的配置文件中指定，OKI会将该标志通过环境变量传递给各个应用容器。不管是否以oes用户运行，应用容器的启动脚本仍以root启动。以oes用户运行后，为了使应用功能正常，需要修改文件的属主为oes。
两种方式：
（1）修改OKI的配置文件修改配置文件 tenant.conf，配置permit_root_start为false，然后使用OKI进行安装。具体可咨询OKI的同事。
（2）如果只是临时验证一下，可以在容器里临时增加环境变量permit_root_start=false（注意只是开发调试阶段临时手工增加，不要合到正式的版本中）。
非root阶段二
非root阶段二是在阶段一的基础上，增加对升级场景的支持，以及对Ceph的支持。非root阶段二与阶段一是兼容的，阶段一所做的所有修改在阶段二仍然适用。在实现阶段二之前，需确保已经实现了阶段一的要求。全新安装的场景下，实现原理与阶段一相同。在部分升级场景下，会涉及PVC上的文件的属主和权限的处理。OTCP从V1.20.40.06P01、V2.21.10.01版本开始支持非root阶段二。
permit_root_start环境变量用来指定容器中的业务进程是否以root用户运行。在非root阶段一，该环境变量由OKI自动注入各个应用容器；但阶段二要求所有应用容器必须在蓝图里显式配置该环境变量。部分涉及PVC文件属主和权限处理的场景的实现步骤如下：
1 NFS+升级前开启权限压缩的升级流程
（1）OKI进行升级操作，升级后可直接以非root运行
（2）由于升级过程不会对NFS上的文件的权限和属主进行处理，因此有可能升级后，PVC上的部分文件的权限较高（例如750），但不影响功能。
2 NFS+升级前未启权限压缩的升级流程；Ceph的升级流程
（1）OKI进行升级操作
（2）升级完成后运行新版本，升级成功后，仍以root运行
（3）开始进行非root改造，停止OKI及其依赖的公共服务之外的所有服务（即OKI和OKI依赖的服务不停止，其他服务停止）
注：脚本由PaaS提供，OKI调用。
（4）手工执行脚本，统一修改持久化卷文件的属主和权限
注：脚本和操作手册单独提供，手工执行，功能如下：
在NFS场景下，会删除PVC上多余的文件、修改PVC上所有文件的属主（nfsnobody）和权限（包括应用的文件和redis/ftp/ldap公共服务的文件）；并打开权限压缩开关
在Ceph场景下，会删除PVC上多余的文件、修改PVC上应用的文件的属主（oes）和权限、ftp公共服务的文件的属主（ftpv3）和权限
（5）OKI提供脚本，统一修改所有业务组件蓝图的环境变量为非root启动
注：脚本由OKI提供：
调用VNPM接口获取service list
对于每个service，做如下操作：调用PaaS接口获取服务的当前部署参数；修改环境变量permit_root_start=false；调用VNPM接口升级服务
修改DB中的用户启动标识，供后续升级使用
（6）启动步骤（3）中停止的所有服务
注：脚本由PaaS提供。
非root阶段三
非root阶段三是在阶段二的基础上，增加对GlusterFS支持。非root阶段三与阶段二是兼容的，阶段二所做的所有修改在阶段三仍然适用。在实现阶段三之前，需确保已经实现了阶段二的要求。
（1）与Ceph类似，可以在应用容器内部修改GlusterFS上的文件的属主和权限。
（2）全新安装前，GlusterFS上是没有文件的，文件都是运行期生成的。只要应用容器以非root启动，生成的文件的属主（oes）和权限（文件是640，目录是750）自然都是正确的。
（3）GlusterFS在各节点上挂载的根目录对应容器内PVC的根目录，这个目录的属主默认是root，权限默认是1777，需要在应用启动脚本中将根目录的属主改为oes:oes，权限改为750。
（4）应用被重新调度到其他节点时，GlusterFS根目录的属主和权限不会还原为root和1777。
（5）当以只读方式挂载PVC时，不能在应用侧做chown、chmod（会报Read-only file system）。这种情况跟ceph类似。因此部分以只读方式挂载的PVC根目录的属主和权限可能无法修改，属主还是默认的root，权限还是默认的1777，这个是正常的。
非root阶段四
非root阶段四是在阶段三的基础上，进一步满足公司容器安全规范对容器运行用户的要求，容器整体以普通用户启动。
（1）应用组件需要添加init容器，init容器以root用户运行。
（2）在init容器中完成预处理动作（尤其是修改hostpath文件的属主和权限、修改PVC根目录的属主和权限）。
（3）修改文件属主和权限的脚本由基础镜像统一提供，各个应用组件在init容器中调用即可。
（4）init容器完成后自动退出，继续以普通用户（oes:oes）启动实际业务容器。
使用ZENAP提供的OKI进行安装升级时：
（1）非root阶段四与前三个阶段是兼容的。
（2）需要满足公司容器安全规范对容器运行用户要求的产品和应用组件，按本文的要求实施后即可满足。
（3）各产品和应用组件也可根据实际需要，自由选择是否、何时实施阶段四。在实施阶段四之前，仍然可以以旧的非root方案运行。
（4）在实现阶段四之前，需确保已经实现了阶段三的要求。
配置回退

## 需在安装部署前配置，不涉及回退。

iDN平台组件安全加固
执行的加固项

| 加固项 | 应对风险 | 默认安全 |
|---|---|---|
| Log组件加密算法选择 | 避免作为客户端，在进行通信的时候，使用被认为不安全的加密算法 | 否 |
| 密钥 | 密钥泄露 | 否 |
| 完整性校验 | 数据安全风险 | 否 |
| 文件传输协议选择 | 避免用户配置选择使用了不安全的文件传输协议 | 是 |
| 文件传输协议选择 | 避免用户配置选择使用了不安全的文件传输协议 | 是 |
| 密码策略 | 暴力破解 机密信息泄露 | 是 |
| 帐号锁定策略 | 用户枚举 暴力破解 用户信息泄露 | 是 |
| IP限定策略 | 限定不安全的攻击源 | 是 |
| 认证参数 | 暴力破解 用户枚举 会话仿冒 | 是 |
| 禁用ZTE短信中心 | 用户信息泄露 | 是 |

Log组件加密算法选择
执行的加固项

## 配置加密TLS、SFTP协议使用的加密算法

## 允许操作的角色：版本定制

## 是否默认安全：否

## 是否可以由产品定制取消“可配选项”：是

配置方法
设置日志SPD安装配置参数log-management
设置 syslog_tls_ciphersuite 进行配置TLS加密算法
1. BSI推荐，且log支持

| BSI推荐，且log支持（16个） | 在”Encrypt-then-MAC“下推荐（8个） log 支持 |
|---|---|
| TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384 TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256 TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384 TLS_ECDH_ECDSA_WITH_AES_256_GCM_SHA384 TLS_ECDH_RSA_WITH_AES_256_GCM_SHA384 TLS_DHE_RSA_WITH_AES_256_GCM_SHA384 TLS_DHE_DSS_WITH_AES_256_GCM_SHA384 TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256 TLS_ECDH_ECDSA_WITH_AES_128_GCM_SHA256 TLS_ECDH_RSA_WITH_AES_128_GCM_SHA256 TLS_DHE_RSA_WITH_AES_128_GCM_SHA256 TLS_DHE_DSS_WITH_AES_128_GCM_SHA256 TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA384 TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA384 TLS_ECDH_ECDSA_WITH_AES_256_CBC_SHA384 TLS_ECDH_RSA_WITH_AES_256_CBC_SHA384 | TLS_DHE_RSA_WITH_AES_256_CBC_SHA256 TLS_DHE_DSS_WITH_AES_256_CBC_SHA256 TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA256 TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256 TLS_ECDH_ECDSA_WITH_AES_128_CBC_SHA256 TLS_ECDH_RSA_WITH_AES_128_CBC_SHA256 TLS_DHE_RSA_WITH_AES_128_CBC_SHA256 TLS_DHE_DSS_WITH_AES_128_CBC_SHA256 |

2. BSI不推荐，或log不支持

| BSI废弃，但是log支持（15个） | BSI不推荐，但是log支持（15个）（4个） | BSI推荐，但log不支持（2个） |
|---|---|---|
| TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA TLS_RSA_WITH_AES_256_CBC_SHA TLS_ECDH_ECDSA_WITH_AES_256_CBC_SHA TLS_ECDH_RSA_WITH_AES_256_CBC_SHA TLS_DHE_RSA_WITH_AES_256_CBC_SHA TLS_DHE_DSS_WITH_AES_256_CBC_SHA TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA TLS_RSA_WITH_AES_128_CBC_SHA TLS_ECDH_ECDSA_WITH_AES_128_CBC_SHA TLS_ECDH_RSA_WITH_AES_128_CBC_SHA TLS_DHE_RSA_WITH_AES_128_CBC_SHA TLS_DHE_DSS_WITH_AES_128_CBC_SHA TLS_EMPTY_RENEGOTIATION_INFO_SCSV | TLS_RSA_WITH_AES_256_GCM_SHA384 TLS_RSA_WITH_AES_128_GCM_SHA256 TLS_RSA_WITH_AES_256_CBC_SHA256 TLS_RSA_WITH_AES_128_CBC_SHA256 | TLS_AES_128_GCM_SHA256 TLS_AES_256_GCM_SHA384 |

## （2）设置sftp_ssh_kex_algorithms、sftp_ssh_host_algorithms、sftp_ssh_cipher_algorithms、sftp_ssh_mac_algorithms进行SFTP加密算法配置

| 配置项 | 取值范围 |
|---|---|
| sftp_ssh_kex_algorithms | ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521,diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha256,diffie-hellman-group-exchange-sha1,diffie-hellman-group1-sha1 |
| sftp_ssh_host_algorithms | ecdsa-sha2-nistp256,ecdsa-sha2-nistp384,ecdsa-sha2-nistp521,ssh-rsa,ssh-dss |
| sftp_ssh_cipher_algorithms | aes128-ctr,aes192-ctr,aes256-ctr,aes128-cbc,aes192-cbc,aes256-cbc,blowfish-cbc,3des-cbc |
| sftp_ssh_mac_algorithms | hmac-sha2-256,hmac-sha2-512,hmac-sha1,hmac-md5,hmac-sha1-96,hmac-md5-96 |

配置确认

## 无

配置回退

## 无

密钥管理
执行的加固项

## 对密钥进行管理

## 是否默认安全：是

## 是否可以由产品定制取消“可配选项”：否

配置方法
配置中心-系统配置-安全配置-秘钥管理进行秘钥配置。
参考以下图片：
[图]

配置确认

## 无

配置回退

## 无

备份恢复完整性校验配置
执行的加固项

## 配置是否对恢复数据完整性进行校验

## 允许操作的角色：系统管理员

## 是否可以由产品定制取消“可配选项”：是

配置方法
配置中心-系统配置-备份恢复配置可以关闭完整性校验
[图]

配置确认

## 无

配置回退

## 配置选项默认安全不涉及失败回退

个人隐私保护加固
执行的加固项

## 开启GDPR选项

## 允许操作的角色：拥有导入License文件权限的用户

## 是否默认安全：是

## 是否可以由产品定制取消“可配选项”：否

配置方法

## 需要申请license文件的模板文件中增加GDPR的控制项，然后导入申请到的license文件。

[图]

配置确认

## 配置GDPR控制项值为true，并且申请的License文件导入成功

配置回退

## 重新导入License文件

文件传输协议选择
配置描述

## 选择文件FTP通讯的协议，配置备份异地服务器的通信协议

## 允许操作的角色：

## PM组件：拥有FTP设置操作权限的用户。

## Log组件：拥有系统管理员角色的用户

## MML组件：拥有命令处理-定时任务权限的用户

## 备份恢复组件：拥有修改备份选项权限的用户

配置方法
PM组件：
性能管理->性能设置->FTP设置
[图]

## LOG组件：

日志管理-日志输出-新建任务，输出方式选择FTP

## [图]

## MML组件：

命令终端-定时任务-设置公共FTP，配置异地服务器信息可以设置协议为ftp或者sftp
[图]

备份恢复组件：
备份恢复-备份选项，配置异地服务器信息可以设置协议为ftp或者sftp
[图]
配置确认

## 用户填写后保存即可

配置回退

## 配置选项不涉及失败回退

账号策略
执行的加固项

## 对账号的锁定策略、有效期进行加固

## 允许操作的角色：安全管理员角色

配置方法
参考以下图片：
[图]
[图]

配置确认

## 无

配置回退

## 配置选项默认安全不涉及失败回退

密码策略选择
执行的加固项

## 对账户密码策略进行配置

## 允许操作的角色：安全管理员角色

## 是否默认安全：是

## 是否可以由产品定制取消“可配选项”：最小长度支持定制

配置方法
参考以下图片：
[图]

配置确认

## 无

配置回退

## 配置选项默认安全不涉及失败回退

IP限定策略
执行的加固项

## 配置IP限定策略，限定不安全攻击源

## 允许操作的角色：安全管理员角色

配置方法
参考以下图片：
[图]

配置确认

## 无

配置回退

## 配置选项默认安全不涉及失败回退

认证参数
执行的加固项

## 配置认证参数，防止暴力破解、用户枚举、会话仿冒

## 允许操作的角色：安全管理员角色

配置方法
参考以下图片：
[图]
[图]
但有些配置可能影响业务，如用户最长在线时间。

配置确认

## 无

配置回退

## 配置选项默认安全不涉及失败回退

禁用ZTE短信中心
执行的加固项

## 不使用ZTE短信中心

## 允许操作的角色：版本定制

## 是否可以由产品定制取消“可配选项”：是

配置方法

## 配置中心不选择ZTE短信中心

可以通过更改版本resource文件或spd文件中前转的环境变量参数FORWARDINFO_ZTESMC_ENABLE来控制是否启用ZTE短信前转功能。
配置确认
[图]
短信前转类型不选择ZTE短信服务
配置回退

## 配置选项默认安全不涉及失败回退

加固后的检查
操作系统加固检查

##### 选择PAAS安全基线检查模板

依次点击“安全加固”-“PAAS”，再点击右侧“请选择模板”下拉框，从中选择“PAAS 安全基线检查 public模板(version:v7.22.40.06)”项（上传加固包后下拉框里才会有这个选项），点击“创建”按钮：
[图]
[图]

##### 连接测试或互信

与执行PaaS加固的操作相同。请参考连接测试或互信

##### 执行检查

与执行PaaS加固的操作相同。请参考执行加固
需要提醒的是：如果加固时修改了某加固项的参数，那么在检查时也必须对该加固项的参数进行相同的修改，否则会检查不通过。
比如加固项“OS-AUTHN-002 确保配置了密码创建要求”，加固时如果修改了“minlen”参数，那么检查时也需要对应修改该参数值与加固时设置的值一样：
[图]
[图]

非root启动加固检查

| 差异项 | 阶段四 | 阶段一至阶段三 |
|---|---|---|
| 启动容器的用户 | oes:oes，uid=3001，gid=3001 | root:root，uid=0，gid=0 |
| 在容器内执行whoami命令 | oes | root |
| 容器的1号进程的启动用户（通过ps命令可查看） | oes | root |
| 容器的实际业务进程（1号进程的子进程）的启动用户（通过ps命令可查看） | oes | oes |

iDN平台组件加固检查

## 参见4.5章节配置确认

# 回退

操作系统加固回退
选择PAAS安全基线回退模板
依次点击“安全加固”-“PAAS”，再点击右侧“请选择模板”下拉框，从中选择“PAAS 安全基线回退 public模板(version:v7.22.40.06)”项（上传加固包后下拉框里才会有这个选项），点击“创建”按钮：
[图]
[图]
连接测试或互信
与执行PaaS加固的操作相同。请参考4.6.1.2章节
执行回退
与执行PaaS加固的操作相同。请参考4.3.2.2.3章节
需要提醒的是：并不是所有加固项都支持回退，有些加固项涉及比如文件删除、文件权限修改、软件包卸载等，将无法回退。
非root加固回退

## 非root加固需在安装部署前配置，不涉及回退。

iDN平台组件加固回退
iDN平台组件加固配置不需要回退，请参考默认安全配置项进行配置修改。

# 默认安全配置项

默认安全配置项的目的是开箱即用（部署时选择自动加固），减少开局时的加固操作。建议在无特殊需求的情况下，不修改默认安全配置项。默认安全配置项参见下表。
表 61 默认安全配置项

| 应对风险 | 配置项 | 出厂默认值 | 验证方法 | 修改方法（可选） |
|---|---|---|---|---|
| OS-ACCESS-003 确保cron仅限于授权用户 | cron_user：用户列表 | etcd,ubuntu | 查看/etc/cron.allow配置 | 通过Inspector修改对应加固项参数 |
| OS-ACCESS-014 确保配置ssh空闲超时间隔 | Interval：发包间隔 CountMax：发送消息最大次数 | Interval默认值300s。 CountMax默认值0。 | ssh连接空闲5分钟后自动断开 | 同上 |
| OS-ACCESS-015 确保设置SSH警告语 | PrintMotd：是否打印motd信息 | 默认值yes， 可选项[yes,no] | grep PrintMotd /etc/ssh/sshd_config | 同上 |
| OS-ACCESS-016 确保设置ssh服务端认证最大并发数 | allow_connections：开始拒绝连接的连接数 reject_probability：连接拒绝概率 limit_connections：全部拒绝连接的连接数 | allow_connections：5000 reject_probability：30 limit_connections：6000 | grep MaxStartups /etc/ssh/sshd_config | 同上 |
| OS-ACCESS-022 设置LoginGraceTime值 | gracetime：登录允许输入密码的时间 | 默认值60s | grep LoginGraceTime /etc/ssh/sshd_config | 同上 |
| OS-ACCESS-025 设置SSH服务器秘钥交换算法 | FIX_CVE_2002_20001：修复CVE_2002_20001漏洞 | 默认值0，不修复。 可选项[0:不修复；1:修复] | grep KexAlgorithms /etc/ssh/sshd_config 参数为默认值0时，输出结果为：KexAlgorithms curve25519-sha256@libssh.org,diffie-hellman-group-exchange-sha256,ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521 参数为1时，输出结果为：KexAlgorithms curve25519-sha256@libssh.org,ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521 | 同上 |
| OS-ACCESS-026 确保设置Ciphers加密算法 | FIX_CVE_2023_48795：修复CVE_2023_48795漏洞 | 默认值0，不修复。 可选项[0:不修复；1:修复] | grep Ciphers /etc/ssh/sshd_config 参数为默认值0时，输出结果为：Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr 参数为1时，输出结果为：Ciphers aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr | 同上 |
| OS-ACCESS-027 确保设置MACs加密算法 | SET_SSHD_MACS_ALGORITHMS：是否设置MACs加密算法 | 默认值0，不设置。 可选项[0:不设置；1:设置默认的MACs；2:设置修复CVE_2023_48795漏洞的MACs] | grep MACs /etc/ssh/sshd_config 参数为默认值0时，输出结果为空或注释； 参数为1时，输出结果为：MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com,hmac-sha2-512,hmac-sha2-256 参数为2时，输出结果为：MACs hmac-sha2-512,hmac-sha2-256 | 同上 |
| OS-ACCESS-034 确保禁用SSH AllowTcpForwarding | AllowTcpForwarding：允许TCP转发 | 默认值yes。 可选项[yes允许,no不允许] | grep AllowTcpForwarding /etc/ssh/sshd_config | 同上 |
| OS-ACCESS-035 确保配置SSH MaxSessions | MaxSessions：最大并行开启的会话 | 2000 | grep MaxSessions /etc/ssh/sshd_config |  |
| OS-ACCOUNT-001 确保配置密码生命周期 | PASS_MAX_DAYS，口令最大有效期 PASS_MIN_DAYS，口令最小有效期 PASS_MIN_LEN，口令最小长度 PASS_WARN_AGE，距离失效时间前n天开始提示 EXCLUDE_USERS，设置密码生命周期的排除用户。当需要排除多个用户时，请使用英文逗号分隔，中间不要有空格，比如：EXCLUDE_USERS=root,tecs。 RESET_USER_PSWD_LAST_MODIFY_DAY：是否自动刷新预置用户（ubuntu,root,pict,tecs,backup,itool）密码修改时间，默认为yes表示刷新，no表示不刷新； | PASS_MAX_DAYS：90天 PASS_MIN_DAYS：7天 PASS_MIN_LEN：8 PASS_WARN_AGE：14天 EXCLUDE_USERS：root RESET_USER_PSWD_LAST_MODIFY_DAY：yes | 密码超过90天后必须修改密码； 密码修改后7天内不允许再次修改密码； 密码最小长度为8位； 密码过期前14天ssh登录时提醒修改密码； 默认情况下设置密码有效期时跳过root账户，即不设置root的密码有效期； 默认情况下每天6:00自动定期刷新预置用户（ubuntu、tecs、pict、root、backup、itool）的密码最后修改时间。 | 同上 |
| OS-ACCOUNT-003 设置锁定inactive账号 | inactive，持续时间，单位天。 userlist，用户列表，即设置inactive的用户列表。 | inactive：默认值为-1，表示不设置帐号禁用 userlist：默认为空值，当使用默认值加固时，只修改配置文件，不设置已经存在的用户。 | 默认情况下不禁用密码已经过期的账户 | 同上 |
| OS-ACCOUNT-006 确保设置用户umask值 | umask：设置UMASK | 默认值027 | grep umask /etc/profile | 同上 |
| OS-ACCOUNT-009 确保设置登录会话超时退出 | timeout：超时时长，表示ssh登录如果不活跃超过这个值后会被强制退出 | 默认值300s | grep TMOUT /etc/profile | 同上 |
| OS-ACCOUNT-012 限制root登录不安全终端 | scantype，是否支持绿盟加固 | 默认值0，表示不支持；参数为1时表示支持 | 查看/etc/pam.d/login配置： 参数为默认值0时，存在配置：auth [user_unknown=ignore success=ok ignore=ignore auth_err=die default=bad] pam_securetty.so 参数为1时，存在配置：auth required pam_securetty.so | 同上 |
| OS-ACCOUNT-014 配置history历史命令数目和bash_history文件中的记录数 | historynumber，历史命令数目 historyfilesize，bash_history文件中保存的记录数 | historynumber，默认参数100 historyfilesize，默认参数100 | grep ^HISTSIZE /etc/profile grep ^HISTFILESIZE /etc/profile | 同上 |
| OS-AUDIT-015 确保设置审计日志存储参数 | max_log_file_action，日志文件size达到最大限制时的操作 | 可选值[KEEP_LOGS, ROTATE]，默认值为ROTATE | grep max_log_file_action /etc/audit/auditd.conf | 同上 |
| OS-AUDIT-019 配置audit的磁盘空间不足的处理 | admin_space_left_halt，磁盘满时是否自动关机 | 默认值为0表示不关机。参数为1时表示磁盘满时自动关机。 | grep admin_space_left_action /etc/audit/auditd.conf 参数为默认值0时，输出为admin_space_left_action = SUSPEND 参数为1时，输出为admin_space_left_action = halt | 同上 |
| OS-AUTHN-002 确保配置了密码创建要求 | retry，允许尝试次数； difok，表示新密码必需与旧密码不同的位数； minlen，设置口令最小字符个数口令最小长度； dcredit，设置口令包含最小数字个数； ucredit，设置口令包含大写字母个数； lcredit，设置口令包含小写字母个数； ocredit，设置口令包含特殊字符个数； minclass，设置口令包含字符类型（数字、大写字母、小写字母、特殊字符）个数； reject_username，设置密码不能包含用户名或用户名逆序（不区分大小写）； | retry，默认值3； difok，默认值5； minlen，默认值8； dcredit，默认值-1，表示至少有一个数字； ucredit，默认值-1，表示至少有一个大写字母； lcredit，默认值-1，表示至少有一个小写字母； ocredit，默认值-1，表示至少有一个特殊字符； minclass，默认值3； reject_username，默认值为空，可选项[空、0、1]，只有为1时生效； | 查看/etc/pam.d/system-auth和/etc/pam.d/password-auth文件 | 同上 |
| OS-AUTHN-003 确保配置了密码尝试失败的锁定(faillock) | unlock_time，登录锁定的时间（s) | 默认值为900s | grep unlock_time /etc/pam.d/password-auth | 同上 |
| OS-AUTHN-004 确保限制密码重复使用 | remember，口令可重复次数 | 默认为5 | grep remember /etc/pam.d/password-auth | 同上 |
| OS-CONFIG-004 确保限制core dump | core_file_size，创建core文件大小 | 默认为0 | grep "soft \s*core" /etc/security/limits.conf grep "hard \s*core" /etc/security/limits.conf | 同上 |
| OS-CONFIG-005 命令行警告语 | banner_info，警告语内容 | 默认值为：“All activities performed on this system will be monitored.” | cat /etc/motd cat /etc/issue cat /etc/issue.net | 同上 |
| OS-CONFIG-011 确保gpgcheck全局激活 | gpgcheck，设置gpgcheck是否激活 | 默认值为0，可选项[0表示不激活；1表示激活] | grep gpgcheck /etc/yum.conf | 同上 |
| OS-MAINTEN-006 锁定无关账户 | useless_accounts，无关账户列表 | 默认值为空。 当该参数为空时会使用系统默认的无关账户列表（adm,apache,at,avahi,bin,daemon,dbus,distcache,ftp,games,gdm,gopher,haldaemon,irc,ldap,listen,lp,mail,mailnull,man,mysql,named,news,nfsnobody,noaccess,nobody,nobody4,nscd,ntp,operator,pcap,pop,postfix,rpc,rpcuser,rpm,sabayon,smmsp,snort,squid,uucp,vcsa,webalizer,webservd,wwwrun,xfs） 如果该参数配置不为空，则只处理参数配置的相关用户。 | 不存在或已锁定默认或设置的无关账户 | 同上 |
| OS-NETWORK-005 确保记录可疑数据包 | log_martians，是否记录可疑数据包 | 默认值为0，不记录。当配置为1时表示记录可疑数据包。 | grep log_martians /etc/sysctl.conf | 同上 |
| OS-NETWORK-015 设置是否启用通过路由器通告前缀自动配置IPv6地址 | IPV6_AUTOCONF，是否启用ipv6 autoconf | 默认值为1，可选项[1表示启用，0表示不启用] | grep autoconf /etc/sysctl.conf | 同上 |
| OS-NETWORK-016 确保IPv6已禁用 | IPV6_DISABLED，是否禁用ipv6 | 默认值为0，可选项[1表示禁用，0表示不禁用] | /etc/modprobe.d/paas_disable_ipv6.conf文件不存在 | 同上 |
| OS-NETWORK-020 加固处理ICMP | HARDEN_HANDLING_OF_ICMP，是否加固ICMP的处理 | 默认为0，可选项[1表示加固，0表示不加固] | 查看inetrules/icmp_security.sh接口 | 同上 |
| OS-NETWORK-023 不关闭多IP绑定 | HOSTCONF_MULTI，表示/etc/hosts文件里面的域名，是否可以对应多个ip地址。 | 默认值on，可选项[on表示可以，off表示不可以] | cat /etc/host.conf | 同上 |
| OS-SELINUX-002 【重启OS生效】设置SELinux策略 | SELINUX_POLICY，SELinux策略 | 默认值在TECS Inspector中是permissive，在共创Inspector中是disabled。 可选项[disabled、permissive和enforcing] | grep "^SELINUX=" /etc/selinux/config | 同上 |
| OS-SERVICE-005 确保未安装LDAP客户端 | needLdapClient，系统是否需要openldap-clients | 默认值0，表示不需要；可选项[0：不需要；1：需要，当需要配置加固项OS-SERVICE-006描述的LDAP时，本参数请设置为1] | rpm -q openldap-clients 默认值情况下输出结果为未安装 | 同上 |
| OS-SERVICE-006 配置LDAP支持双因子鉴权认证 | REMOTE_LDAP，LDAP服务端配置参数 | 默认值为空。 该参数为空时表示不配置LDAP和双因子鉴权，或者取消以前配置的LDAP和双因子鉴权。参数格式及说明请参考《合规加固项目说明.xlsx》 当REMOTE_LDAP参数不为空时，加固项OS-SERVICE-005中的needLdapClient参数请设置为1. | rpm -q openldap-clients 默认值情况下输出结果为未安装 | 同上 |

操作系统默认安全
Linux登录系统相关配置
OS-ACCESS-002 确保设置cron相关配置文件权限
检查是否设置cron相关文件权限。
OS-ACCESS-005 确保ssh协议设置为2
检查是否设置ssh协议；ssh支持两种不同且不兼容的协议：ssh1和ssh2。ssh1是原始协议，存在安全问题。ssh2更先进更安全。
OS-ACCESS-006 确保设置SSH日志级别INFO
检查是否设置ssh日志级别，INFO参数指定将记录登录和注销活动。
OS-ACCESS-007 确保禁用X11转发
检查是否设置禁用X11转发，X11转发参数提供通过连接隧道X11流量的能力，以启用远程图形连接。
OS-ACCESS-008 确保设置MaxAuthTries
检查是否设置最大允许尝试次数，MaxAuthTries参数指定每个连接允许的最大身份验证尝试次数。当登录失败计数达到一半时，错误消息将写入系统日志文件，详细说明登录失败。
OS-ACCESS-009 确保启用IgnoreRhosts
IgnoreRhosts 参数指定.rhosts和.shosts文件不会在RhostsRSAAuthentication或HostbasedAuthentication中使用。
OS-ACCESS-010 确保禁用 HostbasedAuthentication
HostbasedAuthentication 参数指定是否允许通过.rhosts或/etc/hosts.equiv用户的受信任主机进行身份验证，以及成功的公钥客户端主机身份验证。此选项仅适用于ssh协议版本2
OS-ACCESS-011 确保禁用root登录
检查是否设置禁止root用户远程登录
OS-ACCESS-012 确保禁用PermitEmptyPasswords
PermitEmptyPasswords参数指定ssh服务器是否允许使用空密码字符串登录帐户，系统不允许空密码账户登录。
OS-ACCESS-013 确保禁用PermitUserEnvironment
PermitUserEnvironment允许用户向ssh守护进程提供环境选项，但是是不安全的。
OS-ACCESS-016 确保设置 ssh服务端认证最大并发数
设置ssh服务端认证最大并发数量
OS-ACCESS-018 确保禁用telnet协议
系统禁用telnet协议
OS-ACCESS-019 确保配置ftp旗标
设置系统ftp登录警告语
OS-ACCESS-020 禁止使用Tunnel设备
禁止使用Tunnel设备
OS-ACCESS-021 禁止SSH Agent转发
禁止SSH Agent转发
OS-ACCESS-022 设置LoginGraceTime值
设置LoginGraceTime值
OS-ACCESS-024 确保禁止连接转发到SSH客户端端口
确保禁止连接转发到SSH客户端端口
OS-ACCESS-025 设置SSH服务器秘钥交换算法
检查/etc/ssh/sshd_config中是否设置了KexAlgorithms

Linux账号管理相关配置
OS-ACCOUNT-004 确保系统帐户不可登录
限制系统内部使用的账户不允许作为登录用户使用。
OS-ACCOUNT-005 确保root帐户的默认组GID为0
为root帐户使用gid 0有助于防止非特权用户意外访问根拥有的文件。
OS-ACCOUNT-007 确保对su命令访问限制
su命令允许用户作为另一个用户运行命令或shell。该程序已被sudo取代，sudo允许对特权访问进行更精细的控制。通常，su命令可以由任何用户执行。通过在/etc/pam.d/su中取消对pam wheel.so语句的注释，su命令将只允许wheel组中的用户执行su
OS-ACCOUNT-008 确保限制ftp匿名访问
限制ftp匿名用户的访问
OS-ACCOUNT-010 非root用户nologin限制
限制sshd非root用户nologin
OS-ACCOUNT-012 限制root登录不安全终端
限制root登录不安全终端
OS-ACCOUNT-013 检查是否记录帐户登录日志
检查是否记录帐户登录日志
OS-ACCOUNT-017 确保root用户登录仅限于系统控制台
是否配置了root用户登录仅限于系统控制台
OS-ACCOUNT-022 设置/etc/security权限为600
检查/etc/security权限为600

audit相关配置
OS-AUDIT-001 确保已启用内核启动的审核
检查是否设置内核参数GRUB_CMDLINE_LINUX="audit=1"
OS-AUDIT-002 确保收集修改日期和时间信息的事件
检查audit设置记录日期和时间信息修改的事件
OS-AUDIT-003 确保收集修改用户/组信息的事件
检查audit设置记录用户/用户组修改的事件
OS-AUDIT-004 确保收集修改系统网络环境的事件
检查audit设置记录系统网络修改的事件
OS-AUDIT-005 确保收集修改系统强制访问控制的事件
检查audit设置记录系统强制访问控制并修改的事件
OS-AUDIT-006 确保收集登录和注销事件
检查audit设置记录登录和注销事件
OS-AUDIT-007 确保收集会话启动信息
检查audit设置记录会话启动信息事件
OS-AUDIT-008 确保收集任意访问控制权限修改事件
检查audit设置记录任意访问控制权限修改事件
OS-AUDIT-009 确保收集未成功的未授权文件访问尝试
检查audit设置记录未成功的未授权文件访问尝试事件
OS-AUDIT-010 确保成功收集文件系统装载
检查audit设置记录文件系统装载事件
OS-AUDIT-011 确保收集用户的文件删除事件
检查audit设置记录用户对文件的删除事件
OS-AUDIT-012 确保收集对系统管理范围（sudoers）的更改
检查audit设置记录对系统管理范围（sudoers）的修改
OS-AUDIT-013 确保收集系统管理员操作
检查audit设置记录系统管理员操作事件
OS-AUDIT-014 确保收集内核模块加载和卸载
检查audti设置收集内核模块加载和卸载事件
OS-AUDIT-015 确保设置审计日志存储参数
检查audit配置文件是否设置日志存存储参数
OS-AUDIT-016 确保收集特权程序的使用
检查系统是否对特权程序进行审计
OS-AUDIT-019 配置audit的磁盘空间不足的处理
配置audit的磁盘空间不足的处理

鉴权相关配置
OS-AUTHN-001 确保设置密码哈希算法为sha-512
设置密码加密算法为SHA-512，账户设置或修改密码都会使用新算法到存储中。
OS-AUTHN-003 确保配置了密码尝试失败的锁定(faillock)
配置密码尝试失败的锁定，用户输错密码达到设定次数将被锁定。

系统配置
OS-CONFIG-001 确保设置/home分区挂载参数
检查/home分区设置nodev挂载参数；nodev不解析文件系统上的块特殊设备
OS-CONFIG-002 确保设置/dev/shm分区挂载参数
"检查/dev/shm分区是否设置nosuid，nodev，noexec挂载参数；noexec 不允许执行此文件系统上的二进制文件；nodev不解析文件系统上的块特殊设备；nosuid禁止suid操作和设定 sgid 位"
OS-CONFIG-003 【重启OS生效】确保设置bootloader文件权限
检查系统启动文件grub.cfg文件权限
OS-CONFIG-005 命令行警告语
检查系统中警告语文件内容及文件权限是否正确
OS-CONFIG-007 确保设置系统内核ASLR参数
检查系统设置randomize_va_space

Linux日志管理相关配置
OS-LOG-001 确保rsyslog服务开启
检查rsyslog是否默认启动
OS-LOG-003 确保rsyslog文件默认权限
检查rsyslog配置默认日志文件权限； 设置/var/log下日志文件权限
OS-LOG-004 确保设置rsyslog发送到远程日志服务器
检查rsyslog配置远程日志服务器
OS-LOG-005 安装AIDE监控
安装AIDE监控
OS-LOG-006 确保设置journal日志存储
设置journal日志转储；设置日志永久写入磁盘

系统维护相关配置
OS-MAINTEN-001 确保设置账户密码相关文件权限
设置账户密码相关配置文件权限
OS-MAINTEN-002 确保设置sysctl.conf文件权限
设置内核参数配置文件权限
OS-MAINTEN-003 确保不存在空密码账户
系统不允许存在空密码的账户，否则不安全。
OS-MAINTEN-004 确保只有root账户UID为0
只允许root账户的uid为0
OS-MAINTEN-005 确保存在用户家目录与设置权限
检查账户存在家目录并且文件夹权限合理
OS-MAINTEN-006 锁定无关账户
检查系统是否存在无关账户
OS-MAINTEN-007 确保关闭系统信任主机
查看系统配置信息是否不存在信任主机，即检查系统中是否有.netrc .rhosts hosts.equiv的文件
OS-MAINTEN-008 Bash安全漏洞检查
检查Bash是否存在漏洞，确保子变量不会被识别为全局变量
OS-MAINTEN-009 禁用CTRL+ALT+DEL
禁止通过CTRL+ALT+DEL组合键控制主机
OS-MAINTEN-010 检查不必要的启动项
限制系统使用不必要的启动项程序
OS-MAINTEN-012 确保设置系统关键文件权限
设置系统关键文件权限

网络配置
OS-NETWORK-001 确保禁用数据包重定向发送
确保禁用数据包重定向发送；ICMP重定向用于向其他主机发送路由信息，由于主机本身不充当路由器（在仅主机配置中），因此无需发送重定向
OS-NETWORK-002 确保不接受源路由数据包
确保不接受源路由数据包；在网络中，源路由允许发送方部分或完全指定通过网络的路由。相反，非源路由数据包的传输路径由网络中的路由器决定。在某些情况下，系统可能无法路由或无法从某些位置访问（例如，专用地址与Internet路由），因此需要使用源 路由数据包。
OS-NETWORK-003 确保不接受ICMP重定向
确保不接受ICMP重定向；ICMP重定向消息是传递路由信息并告诉主机（充当路由器）通过备用路径发送数据包的数据包。这是一种允许外部路由设备更新系统路由表的方法。通过将net.ipv4.conf.all.accept_重定向设置为0，系统将不接受任何ICMP重定向消息，因此不允许外部人员更新系统的路由表
OS-NETWORK-004 确保不接受安全的ICMP重定向
确保不接受安全的ICMP重定向；安全的ICMP重定向与ICMP重定向相同，只是它们来自默认网关列表上列出的网关。假设您的系统知道这些网关，并且它们很可能是安全的。
OS-NETWORK-006 确保忽略广播的ICMP请求
确保忽略广播的ICMP请求；将net.ipv4.icp_echo_ignore_broadcasts设置为1将使系统忽略对广播和多播地址的所有ICMP echo和时间戳请求。
OS-NETWORK-007 确保忽略伪造的ICMP响应
确保忽略伪造的ICMP响应；将icmp_ignore_bogus_error_responses设置为1，可防止内核记录虚假响应（RFC-1122不兼容）的广播折射，防止文件系统用无用的日志消息填充。
OS-NETWORK-008 确保启用反向路径筛选
确保启用反向路径筛选；将net.ipv4.conf.all.rp_filter和net.ipv4.conf.default.rp_filter设置为1将强制Linux内核对接收到的数据包使用反向路径筛选来确定数据包是否有效。本质上，通过反向路径过滤，如果返回数据包没有从对应的源数据包来自的同一个接口流出，则会丢弃该数据包（如果设置了Log_Martian，则会记录该数据包）。
OS-NETWORK-009 确保启用了TCP SYN Cookies
确保启用了TCP SYN Cookies；当设置tcp-syncookies时，内核将正常处理tcp-syn数据包，直到半开连接队列满为止，此时syn-cookie功能开始发挥作用。SYN cookies的工作原理是根本不使用SYN队列。相反，内核只是简单地用syn ack回复syn，但它将包含一个专门编制的TCP序列号，该序列号对源和目标IP地址和端口号以及发送数据包的时间进行编码。一个合法的连接将发送带有特制序列号的三路握手的ACK包。 这允许系统验证是否已收到对SYN cookie的有效响应，并允许连接，即使队列中没有对应的SYN。
OS-NETWORK-010 确保不接受IPv6重定向
确保不接受IPv6重定向；此设置阻止系统接受ICMP重定向。ICMP重定向告诉系统发送流量的备用路由。
OS-NETWORK-011 确保设置dnsmasq顺序解析
检查dnsmasq是否配置顺序解析参数
OS-NETWORK-014 确保设置禁用传输协议驱动
确保禁用dccp sctp rds tipc cramfs freevxfs jffs2 hfs hfsplus squashfs udf数据传输协议驱动
OS-NETWORK-017 配置IPv4协议堆栈
配置IPv4协议堆栈
OS-NETWORK-018 配置IPv6协议堆栈
配置IPv6协议堆栈
OS-NETWORK-020 加固处理ICMP
如果参数HARDEN_HANDLING_OF_ICMP为1,则拦截部分类型的ICMP报文.参数为0则不拦截.
OS-NETWORK-022 确保打开路由转发
检查是否设置打开路由转发；转发标志用于告诉系统它是否可以转发数据包
OS-NETWORK-023 不关闭多IP绑定
不关闭多IP绑定

系统服务配置
OS-SERVICE-001 时钟同步服务
检查时钟服务chronyd是否启用
OS-SERVICE-002 avahi服务
检查avahi-daemon是否关闭
OS-SERVICE-004 确保配置了NTP
检查文件/etc/ntp.conf中是否存在ntp需要的配置

iDN组件默认安全

| 应对风险 | 配置项 | 出厂默认值 |
|---|---|---|
| GDPR | 个人数据信息保护 | 默认使能 |
| 最小特权 | OKI非root启动 | OKI config.conf文件permit_root_start=true |
| 避免用户配置选择使用了不安全的协议 | 文件传输协议选择 | PM组件、Log组件、MML组件：sftp 备份恢复组件：无（不启用异地服务器） |
| 暴力破解 机密信息泄露 | 密码策略 | 默认帐号规则 |
| 用户枚举 暴力破解 用户信息泄露 | 帐号锁定策略 | 默认帐号规则 |
| 限定不安全的攻击源 | IP限定策略 | 默认帐号规则 |
| 暴力破解 用户枚举 会话仿冒 | 认证参数 |  |
| 用户信息泄露 | 禁用ZTE短信中心 | V3.24.20.05及其之前的版本默认启用ZTE短信转发功能 V3.24.20.06RC1及其之后的版本默认禁用ZTE短信 |
