[图]
iMind 融合版安装手册iMind-AIO版
产品版本：V6.26.30.F30B3
[图]

法律声明 [图]
本文档著作权由中兴通讯股份有限公司享有。文中涉及中兴通讯股份有限公司的专有信息，未经中兴通讯股份有限公司书面许可，任何单位和个人不得使用和泄漏该文档以及该文档包含的任何图片、表格、数据及其他信息。
本文档中的信息随着中兴通讯股份有限公司产品和技术的进步将不断更新，中兴通讯股份有限公司不再通知此类信息的更新。
和是中兴通讯股份有限公司的注册商标。本文档中提及/出现的其它产品、服务或企业名称的商标及其它权益由各自的权利人拥有。未经中兴通讯或其它权利人事先书面同意，本文档不以任何方式授予任何人使用本文档上出现的任何名称、标识、标志等的权利。 [图]
本产品符合关于环境保护和人身安全方面的设计要求，产品的存放、使用和弃置应遵照产品手册、相关合同或相关国法律、法规的要求进行。
您购买的产品、服务或特性等应受中兴通讯商业合同和条款的约束，本文档中描述的全部或部分产品、服务或特性可能不在您的购买或使用范围之内。除非合同另有约定，中兴通讯对本文档内容不做任何明示或暗示的声明或保证。

第三方嵌入式软件使用限制声明：
如果与本产品配套交付了Oracle、Sybase/SAP、Veritas、Microsoft、Vmware、Redhat这些第三方嵌入式软件，只允许作为本产品的组件，与本产品捆绑使用。当本产品被废弃时，这些第三方软件的授权许可同时作废，不可转移。这些嵌入式软件由ZTE给最终用户提供技术支持。

法律声明
本文档著作权由中兴通讯股份有限公司享有。文中涉及中兴通讯股份有限公司的专有信息，未经中兴通讯股份有限公司书面许可，任何单位和个人不得使用和泄漏该文档以及该文档包含的任何图片、表格、数据及其他信息。
本文档中的信息随着中兴通讯股份有限公司产品和技术的进步将不断更新，中兴通讯股份有限公司不再通知此类信息的更新。
和是中兴通讯股份有限公司的注册商标。本文档中提及/出现的其它产品、服务或企业名称的商标及其它权益由各自的权利人拥有。未经中兴通讯或其它权利人事先书面同意，本文档不以任何方式授予任何人使用本文档上出现的任何名称、标识、标志等的权利。 [图]
本产品符合关于环境保护和人身安全方面的设计要求，产品的存放、使用和弃置应遵照产品手册、相关合同或相关国法律、法规的要求进行。
您购买的产品、服务或特性等应受中兴通讯商业合同和条款的约束，本文档中描述的全部或部分产品、服务或特性可能不在您的购买或使用范围之内。除非合同另有约定，中兴通讯对本文档内容不做任何明示或暗示的声明或保证。

第三方嵌入式软件使用限制声明：
如果与本产品配套交付了Oracle、Sybase/SAP、Veritas、Microsoft、Vmware、Redhat这些第三方嵌入式软件，只允许作为本产品的组件，与本产品捆绑使用。当本产品被废弃时，这些第三方软件的授权许可同时作废，不可转移。这些嵌入式软件由ZTE给最终用户提供技术支持。

资料编号:

# iMind版本包准备

版本包目录结构如下图（内容仅限参考）：
[图]
[图]

| 版本类型 | 版本文件名称 | 备注 |
|---|---|---|
| iDN_Kit_SI_AIO | iDN_Kit_SI_AIO-V**.tar.gz | AIOUX工具包 |
| iMind-V6.** | extend-scripts-**.tar.gz | iMind扩展脚本 |
|  | iMind_aiomanifest.json | iMind配置文件 |
|  | iMind-V6.26.30.F10B3.tar.gz | iMind版本包 |
|  | meta.conf | iMind配置文件 |
| TSM-V8.** | 目录下全部内容 | 技术服务所有版本包 |
| ZXVMAX-O | caas_aiomanifest.json | NIP扩展脚本配置文件 |
|  | extend-scripts-nip-template-V18.**.tar.gz | NIP扩展脚本 |
|  | extend-scripts-V18.**.tar.gz | NIP扩展脚本 |

# AIOUX工具安装部署

说明：保证AIOUX工具部署在服务器网络开通允许访问的任意节点上。建议AIOUX工具建议部署在第一控制节点上。

## AIOUX配置文件

备注：需要调整的地方见红色字体说明，IP地址等规划需要与LLD规划保持一致。AIOUX配置toml文件在后续安装，升级TSM和iMind应用都要用，请永久保存。

### annotations配置

【annotations.controller的pass_ip】: 实际controller节点ip地址，多个地址用分号分开
【annotations.minion的pass_ip:】 实际minion节点的ip地址，多个地址用分号分开，没有可不填
【annotations.lld 中dir= 】：TCF配置文件存放实际路径，在控制节点一上新建目录/home/pict/TCFconfig(在启动AIOUX工具的服务器路径)
----------------配置样例-------------------------
[annotations]
[annotations.controller]
username = "ubuntu"
password = "WGHbOnn2aD/b9YpveGSEug=="
paas_ip = ["10.170.65.4", "10.170.65.5", "10.170.65.6"]
[annotations.minion]
username = "ubuntu"
password = "WGHbOnn2aD/b9YpveGSEug=="
paas_ip = [""]
[annotations.lld]
dir = "/home/pict/TCFconfig"

### Paas配置

Paas ip配置对应的第一个控制节点SSH访问地址以及对应安装文件路径
---------------配置样例-------------------------
[paas]
[paas.ssh]
ip="10.170.65.4"
port="22"
[paas.lld]
ini_config_file="/home/pict/TCFconfig/seed_cmd_config.ini"
daisy_seed_config_file="/home/pict/TCFconfig/zxvmax_tcf_daisyseed.xlsx"
paas_config_file="/home/pict/TCFconfig/zxvmax_tcf_paas.xlsm"
tecs_config_file = ""

### Cloud配置

Cloud配置对应的timezone和对应的VIP的IP 地址
-----------------------配置----------------------
[cloud]
caas_type = "TCF"
runtime_class = ""
timezone = "Africa/Kampala" 项目时区
cluster_root_domain = "cluster.local"
is_not_cluster_admin = false
[cloud.auth]
auth_url = "10.170.65.7:5000" VIP浮动地址（登录TCFngportal的地址）
username = "admin"
password = "04031edb1b6899f35ec8e1a18c2545d73cb5a8fb65988569b270eb50"
api_url = ""
ca_file = ""
cert_file = ""
key_file = ""
[cloud.tsm]
rlogmgt_switch = true
logspace_size = "50Gi"
fmadaptor_switch = true
role_type = ""
[cloud.tsm.ts_depended_components]
ts_net_lcm = false
[cloud.registry]
repo_external = "10.170.65.7:443" VIP浮动地址（联创中移443端口不开放，根据情况修改）
repo = "swr:2512"
user_name = "admin"
password = "04031edb1b6899f35ec8e1a18c2545d73cb5a8fb65988569b270eb50"
certs_ca_path = ""
certs_trust_path = ""
[cloud.namespace]
[cloud.namespace.app_ns]
name = "zenap"
[[cloud.storage_class]]
name = "gluster-csi-sc"
type = "fileStorage"
[cloud.security]
common_security_context_constraints = ""
tsm_security_context_constraints = ""
aiolcm_security_context_constraints = ""
[cloud.xlb]
type = ""
cluster_cidr_v4 = ""
cluster_cidr_v6 = ""
default_cidr_v4 = ""
default_cidr_v6 = ""
other_cidr_v4 = ""
other_cidr_v6 = ""

### lcm配置

lcm配置，可以不修改
-----------------------------配置样例-----------------------
[lcm]
storage_class = "hostPath"
host_path = "/paasdata/docker/aio-lcm"
root_start = false
is_tcf_zartcli = true
[[lcm.labels]]
key = "aio_lcm_label"
values = ["true"]
operator = "In"

### app配置

App配置对应的timezone和对应的IP地址（涉及地址说明见样例备注）
-----------------------------配置样例-----------------------
[app]
timezone = "Africa/Kampala" 项目时区
domain = "idn"
is_multiple_instance = true
id = "zte.otaf"
[[app.extend]]
key = "tecs_ip"
value = "10.170.65.7" VIP浮动地址（登录TCFngportal的地址）
[[app.extend]]
key = "k8s_dns"
value = ""
[[app.extend]]
key = "tecs_password"
value = "gGE29lsfiZJ2baAoSjuSRzsZ9USyvjtGrGqfxyf2z50o96fdea1c2f50b07552f83b6fa72255e3"--登录TCF密码默认为【PaaS1!2@3#4$】,不建议修改
[[app.extend]]
key = "tecs_username"
value = "admin"
[[app.extend]]
key = "localpv_enable"
value = false --单节点部署必须配置，且值为true；多节点部署可以不配置这部分，或者配置为false
[[app.extend]]
key = "localpv_scope"
value = "hostpath" --单节点部署必须配置为pvc, 多节点为hostpath
[[app.extend]]
key = "storage_cluster_name"
value = "gluster-csi-sc" --单节点不配置，多节点保留
[[app.extend]]
key = "xlb_ext_ipv4"
value = "10.170.65.8" 业务uportal地址,即ulb地址
[[app.extend]]
key = "xlb_ext_ipv6"
value = ""
[[app.extend]]
key = "primary_tenant_name"
value = "zenap"
[[app.extend]]
key = "xlb_ext_gw_addrv4"
value = "10.170.65.1" 业务网关
[[app.extend]]
key = "xlb_ext_gw_addrv6"
value = ""
[[app.extend]]
key = "xlb_ext_cidr_v4"
value = "10.170.65.0/26" 业务网段
[[app.extend]]
key = "xlb_ext_cidr_v6"
value = ""
[[app.extend]]
key = "net_iapi_network_cidr_v4"
value = "10.170.65.0/26" 业务网段
[[app.extend]]
key = "net_iapi_network_start_ip"
value = "10.170.65.8" 业务uportal地址，即ulb地址
[[app.extend]]
key = "net_iapi_network_end_ip"
value = "10.170.65.8" 业务uportal地址，即ulb地址
[[app.extend]]
key = "xlb_caas_type"
value = "tcf"
[[app.extend]]
key = "xlb_inner_network_cidrV4"
value = "100.101.0.0/16"
[[app.extend]]
key = "xlb_inner_network_cidrV6"
value = "100:101::/96"
[[app.extend]]
key = "XLB_INNER_GW_V4"
value = "100.101.0.1"
[[app.extend]]
key = "XLB_INNER_GW_V6"
value = "100:101::1"
[[app.extend]]
key = "net_api_attach_network"
value = "net-api"
[[app.extend]]
key = "net_iapi_physicalnetwork_name"
value = "net-iapi"
[[app.extend]]
key = "host_network_enabled"
value = "false"
[[app.extend]]
key = "ipv6_enabled"
value = "false" ---如果是IPV6访问uportal的环境，这段必须有，且value为true；如果是IPV4，这段可选，或者配置为false

## AIOUX安装工具部署

控制节点1上操作下载好对应的AIOUX版本：iDN_Kit_SI_AIO-V3.26.20.06.n2606231414.tar.gz
- 创建目录AIOUX在/home/pict下面$ mkdir -p /home/pict/AIOUX
- 上传文件到/home/pict/AIOUX
- 上传文件名参考：iDN_Kit_SI_AIO-V3.26.20.06.n2606231414.tar.gz
- 解压文件 tar -zxvf iDN_Kit_SI_AIO-V3.26.20.06.n2606231414.tar.gz
- 进入路径/home/pict/AIOUX/iDN_Kit_SI_AIO/idn-aio/aioux
- 启动AIOUX命令：$ nohup ./aioux --host :32001 --multiple-instance-enable true > aioux.log 2>&1 &
- 登录AIOUX web端：
https://10.170.65.6:32001/iui/aioux (IP根据实际部署AIOUX服务地址)
初始登录信息：admin/Zenap_123!@#
[图]

# iMind安装部署

## 初始化参数

登录AIOUX的登录地址 https://ip:32001/iui/aioux/
用户名密码： admin/Zenap_123!@#
初次登录需要修改密码 ，默认修改为：admin/Zenap_123

## 版本上传

在控制一节点新建目录并上传版本（注意修改对应版本号）
$ mkdir -p /paasdata/iMindV6.26.30.F30B3/TSM
$ mkdir -p /paasdata/iMindV6.26.30.F30B3/iMind
上传TSM版本到/paasdata/iMindV6.26.30.F30B3/TSM目录下；
上传iMind版本到/paasdata/iMindV6.26.30.F30B3/iMind目录下。
刷新权限
cd /paasdata/iMindV6.26.30.F30B3
chown -R ubuntu:ubuntu iMindV6.26.30.F30B3

## 版本包导入

选择对应的版本导入软件仓库
[图]

### 导入参数设置

全新开局安装，需要导入iMind与TSM版本：
【名称】建议命名实际安装的产品名称或者环境信息，区分正式环境和测试床；
【类型】自定义版本包
【导入位置】AIO服务器即安装AIOUX服务的服务器；第三方服务器即其他远程机器，需要输入对应的用户名和密码等。
【路径】需要导入的文件的实际路径
[图]

### 导入完成检查

导入成功后可以再页面看到对应的软件名称和版本信息，重点关注版本大小。
[图]

## 实例安装

### 实例创建

1. 实例管理，点击【新建】
[图]
2. 实例参数设置
开局需要选择：【技术服务】【应用】。
(与实际业务保持一致，可独立选择需要的安装包)
[图]
安装配置参数
【版本包】选择上一步导入成功的版本包
【安装模块】技术服务+应用 （与版本包对应）
【上传toml文件】根据现场实际更改的toml文件
【堡垒机地址】 第一台控制节点的地址
【堡垒机登录用户】ubuntu （必须选这个默认用户）
【堡垒机密码】UbuntU1!2@3#4$
[图]
继续选择资源和场景：
【资源resources】:根据需要选择（native开头表示云原生，可选择small，medium，large，hyper）
【场景scenes】 ：根据项目实际场景包名称 例如 Uganda-MTN
[图]

### 参数预览

参数设置检测正确后启动安装
[图]

### 安装前检查

[图]

### 执行安装

正常安装过程不会出现报错安装过程中遇到已知的无关的检测报错可以点击忽略\继续\重试，无法确认的报错联系研发处理 [图]

### 安装完成

安装后检查后系统部署完成
[图]

### 安装后检查

1.登录web: https://ulbip:28001/uportal
初次安装默认密码为admin/Zenap_123!@#第一次安装必须修改密码，请按页面提示修改密码。
2.检查业务数据是否正常，有无缺失。
3.检查业务数据是否正确。检查各模块功能是否正常。
[图]
[图]

## 应用卸载操作

卸载选择
实例管理选择需要卸载的实例名称（一般以版本号命名）点击更多-卸载
[图]
确认卸载验证码后选择卸载即可。
[图]

### 执行卸载

等待系统自动执行卸载前检查
[图]
自动卸载前检查完成后启动卸载
[图]
卸载时间预计25-30分钟左右。
[图]
卸载后系统会自动执行检查。
[图]
