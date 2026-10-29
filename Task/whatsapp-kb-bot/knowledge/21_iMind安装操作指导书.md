[图]
iMind 安装操作指导书
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

# 安装流程

AIMind安装流程参见表1.1，给出的操作时间仅供参考。
表1.1

| 序号 | 安装步骤 | 安装说明 | 操作时间 |
|---|---|---|---|
| 1 | 安装前准备 | 安装前检查，环境是否满足安装要求。（告警，磁盘空间，时区检查） | 10min |
| 2 | 版本准备 | 下载和上传版本 安装前版本预置处理 安装参数确认 节点标签数确认 | 1h（所内下载时间） |
| 3 | 版本安装 | 安装产品版本 | 1h |
| 4 | 安装后检查 | 安装后功能检查 | 10min |

# 安装说明

## 安装版本

AIMind产品的版本号以及依赖产品的版本号。

| 产品名称 | 安装版本号 |
|---|---|
| AIMind | V6.26.30.F30B3 |
| TCF | TCF-V7.22.30.11F80 |
| OTAF | V3.26.20.06 |
| AIM | V6.26.30B2 |
| NIP | V18.26.20.01 |

## 版本文件

说明需要准备使用的版本文件。
AIMind产品包含如下内容：

| 序号 | 文件名 | 说明 |
|---|---|---|
| 1 | TCF-V7.22.30.11F80 | TCF安装包（必选） |
| 2 | iMind-V6.26.30.F30B3 | AIMind版本包（必选） |

AIMind版本包中包含详细内容：

| 序号 | 文件目录 | 说明 |
|---|---|---|
| 1 | config | 配置产品，租户，端口等信息 |
| 2 | resources | 配置公共服务信息 |
| 3 | scenes | 安装的场景文件（需要安装的分组包集合） |
| 4 | sources | 分组包信息 |
| 5 | images | 版本依赖的镜像 |
| 6 | projects | 场景包 |
| 7 | scripts | 预置和安装脚本 |
| 8 | tools | 工具包 |

## 安装内容

| 序号 | 产品名称 | 安装内容 | 备注 |
|---|---|---|---|
| 1 | TCF | 参照TCF安装手册完成安装。 |  |
| 2 | AIMind | 根据交付模版所有产品应用 |  |

# TCF安装

## 版本获取

[图]

## 安装TCF版本

1.参考文档《TECS-CFV7.22.30.11F80 第三方IaaS融合 场景6 一键式升级参考指导书.docx》安装TCF
2.修改PAAS密码为PaaS1!2@3#4$
3.(可选步骤）安全加固，参考《TECS-CFV7.22.30.11F80_产品安全加固指南.docx》执行

# AIMind安装前准备

## 安装前检查

详细的检查步骤和通过标志。

### PAAS告警检查

登录PAAS，切换租户为admin，在总览页面查看告警统计（如图），正常情况下告警数量为0，若数量不为0，则点击告警数进入告警查看页面，根据告警中提示的处理建议消除告警。
[图]
[图]

### TCF当前时区检查

SSH登录环境控制节点，查看当前TCF时区：
$ timedatectl
[图]
若时区与预期不一致，则需要参考7.1如何修改节点的时区修改时区。

# 正式安装

该章节所有脚本执行期间发现传入参数不正确，不要异常中断，需要等脚本报错退出后再重复执行！

## 版本准备

获取版本
获取到AIMind版本，版本包为iMind-V6.26.30.F30B3.tar.gz，如图：
[图]
上传版本
将版本包上传到控制节点并进入/paasdata/下，解压，并放置到/paasdata/versions/AIMind/versions/V6.26.30.F30B3目录下：
$ cd /paasdata/
$ rm -rf versions && mkdir -p versions/AIMind/versions/V6.26.30.F30B3
$ tar -zvxf iMind-V6.26.30.F30B3.tar.gz
$ mv iMind/* versions/AIMind/versions/V6.26.30.F30B3/
$ ls versions/AIMind/versions/V6.26.30.F30B3/
[图]
[图]
[图]
参数准备
根据外场需要准备好表5.1所有参数
表5.1

| 参数 | 描述 | 来源 | 用途 |
|---|---|---|---|
| tenant | 租户信息 | 默认zenap | AIMind应用安装租户/UTM（中国铁塔项目）场景只支持ranoss |
| ScenarioName | 场景包名前缀 | 表5.2 | 根据场景包前缀来准备场景包 |
| scenes | 场景文件 | 表5.2 | ***.scene根据交付模板安装哪些组件 |
| resources | 资源文件 | 表5.3 | ***.resource 公共服务配置 |

表5.2

| 项目 | 场景文件名（scenes） | 场景包名前缀（ScenarioName） | 备注 |
|---|---|---|---|
| 孟加拉GP | Bengal-GP.scene | Bengal-GP |  |
| 孟加拉POC | Bengal-POC.scene | Bengal-POC |  |
| 利比亚 | Libya-HLC.scene | Libya-HLC |  |
| 山东 | ShanDong-CMCC.scene | ShanDong-CMCC |  |
| 越南 | Vietnam-VNM.scene | Vietnam-VNM |  |
| 印尼SMF | Indonesia-SMF.scene | Indonesia-SMF |  |
| 印尼XLS | Indonesia-XLS.scene | Indonesia-XLS |  |
| NIOS通用 | NIOS-COM.scene | NIOS-COM | NIOS通用 |
| 安徽 | AnHui-CUCC.scene | AnHui-CUCC | NIOS安徽联通 |
| UTM | AIMIND-UTM.scene | imind-general |  |
| 西班牙 | Spain-MO.scene | Spain-MO |  |
| 泰国 | Thailand-AIS.scene | Thailand-AIS |  |
| 陕西延长石油 | ShanXi-YCPetro.scene | ShanXi-YCPetro |  |
| 尼泊尔 | Nepal-Ncell.scene | Nepal-Ncell |  |
| 利比里亚 | Liberia-OLR.scene | Liberia-OLR |  |
| 河南移动 | HeNan-CMCC.scene | HeNan-CMCC- |  |
| 河南移动点金 | HeNan-CMCCEvent.scene | HeNan-CMCCEvent |  |
| 创新中心 | Novation-Center.scene | iMind-COMMON | 仅用于产品化演示 |
| 南非 | SouthAfrica-Comsol.scene | SouthAfrica-Comsol |  |
| 联创 | LianChuang-CMCC.scene | LianChuang-CMCC |  |
| 乌干达 | Uganda-MTN.scene | Uganda-MTN |  |
| 阿尔 | Algeria-ATM.scene | Algeria-ATM |  |

表5.3

| 资源文件名(resources) | 可以使用的场景 | 备注 |
|---|---|---|
| iMind_Vietnam-VNM_resource.resource | Vietnam-VNM场景（越南） |  |
| iMind_small-scale_resource.resource | 通用小规模场景(物理站点数量<=3000) | 根据配置指导书选规模 |
| iMind_medium-scale_resource.resource | 通用中规模场景(物理站点数量>=3000,<=6000) |  |
| iMind_large-scale_resource.resource | 通用大规模场景(物理站点数量>=6000,<=12000) |  |
| iMind_hyper-large-scale_resource.resource | 通用超大规模场景(物理站点数量>=12000,<=24000) |  |
| AIMIND-UTM_resource.resource | AIMIND-UTM场景（中国铁塔项目） |  |
| zxunia_single_resource_template.resource | 通用单节点环境使用 |  |
| ZXVMAX-UTM_single_mini_resource.resource | UTM场景组件单节点环境使用（中国铁塔项目） |  |

执行版本预置脚本
（脚本用于打包场景包，菜单定制）
$ cd /paasdata/versions/AIMind/versions/V6.26.30.F30B3/scripts
$ sh 01_Version_preset.sh 2>&1 | tee -a result.log
根据表5.1准备的参数输入到脚本
[图]
[图]
执行成功(Version_preset Successfully)--（脚本执行时间预计2-3min）
[图]
版本准备全部完成

## 节点标签数确认

检查标签数量
本次安装使用的公共服务副本及对应标签数量如下：
表5.4

| 公共服务类型 | 标签名 | 标签数量（副本数） | 建议所在节点 |
|---|---|---|---|
| redis | otcp_redis-ha_cluster1 | 2 | 8节点及以下，controller节点8节点以上，放在678节点 |
| postgresql | otcp_pg_cluster1 | 3 |  |
| postgresqlcache | otcp_pgcache_cluster1 | 3 |  |
| zookeeper | otcp_zk_cluster1 | 3 |  |
| logstash | otcp_logstash_cluster1 | 3 |  |
| kafka | otcp_kafka_cluster1 | 3 |  |
| elasticsearch | otcp_es_cluster1 | 3 |  |
| ftp | otcp_ftp_cluster1 | 1 |  |
| ap数据库V7 | zaerag_ap_cluster | 大于等于1根据局点规划的每一个ap节点都打上该标签 |  |
| zgis | zxvmax_zgis_zenap | 1 |  |
| 注： 1.若节点数小于2，则标签所有公共服务标签数为1，全部放在控制节点。 2.以上所有标签均为必选。 |  |  |  |

执行脚本检查每个标签数量是否与上面表格的标签数量相同
$ cd /paasdata/versions/AIMind/versions/V6.26.30.F30B3/scripts
$ sh Check_count_labels.sh
[图]
修改标签数量
根据脚本返回的标签个数与表5.4标签个数对比，如果不一致请增加或删除标签，操作参考7.2如何修改标签

## 版本安装（使用root用户执行）

执行安装脚本
$ cd /paasdata/versions/AIMind/versions/V6.26.30.F30B3/scripts
$ sh 02_install_service.sh 2>&1 | tee -a result.log
根据表5.1准备的参数输入到脚本（输入参数仅供参考）
[图]
执行结果查看（脚本执行安装预计1小时左右，具体以项目和环境为准）
[图]
注：若版本安装截图中出现某个组件安装失败，请联系所内研发处理！

# 安装后验证

## PaaS管理界面检查

1.登录TCF https://IP/ngportal admin/PaaS1!2@3#4$
图6-1 TCF管理登录
[图]
2.进入zenap 项目;
图6-2 zenap项目
[图]
3.在应用管理中，查看所有组件是否符合集成版本信息。
图6-3 应用管理
[图]
图6-4 部署应用界面
[图]

## uportal界面检查数据

1.登录web: https://IP:28001/uportal
初次安装默认密码为admin/Zenap_123!@#第一次安装必须修改密码，请按页面提示修改密码。
如图 uportal登录界面
[图]
2.登录成功，如图:
[图]
3.检查业务数据是否正常，有无缺失。
4.检查业务数据是否正确。检查各模块功能是否正常。

## 检查eFlow场景包是否安装成功

如果环境上没有eFlow产品组件，跳过该检查
登录uportal，点击【配置数据】菜单->【场景包】
[图]
检查导入场景包是否成功。如果安装失败，可以点击详情查看或者找开发定位解决。
[图]

## 青海工单管理组件的数据迁移

我这里先准备好了一个脚本待会会用到的 recover.txt（这里只能放文本，下载后把后缀改为 .sh）
- 在把青海环境铲除之前需要把数据库db_unia_ticket_handler_db_zenap备份。备份请使用工具DBeaver进行操作。操作如下截图，对每一张表都进行备份sql文件。 [图]
- 把备份好的sql文件和脚本放在一起并压缩成一个 xxx.tar.gz 文件。并上传到ssh终端里面 [图]
- 登录TCF平台，查询数据库容器实例名称并拷贝编码。 [图]
- 登录到后台终端查找容并把上传的xxx.tar.gz文件拷贝到对应的容器中。并进入容器，但是如果是这种多节点的情况，就要测试那个库才能写，就分别进入节点后执行如下命令第一个是：su - postgres 第二个是：psql -U postgres -d db_unia_ticket_handler_db_zenap -c "SHOW transaction_read_only;"找到节点后就只需要把xxx.tar.gz文件拷贝到对应的容器中去，然后在这个中执行 [图]
- 进入容器后cd /tmp (因为把xxx.tar.gz文件放到了这个目录下)，然后执行 tar -xvf xxx.tar.gz 进行解压操作 [图]
- 再对这个目录下的文件进行赋权 chmod 777 * ，再检查权限是否正确 [图]
- 然后切换用户到 postgres用户下； su - postgres ； 切换完成后再 cd /tmp 目录；再 执行pwd检查是否在 /tmp 目录下了 [图]
- 然后直接执行 sh recover.sh 这个脚本就行。跑起来后需要等45分钟
- 最后结果输出为0条就成功了 [图]
- 到此数据恢复迁移就完成了。

# FAQ

## 如何修改节点的时区

若查询到的时区与预期不一致，则需要修改时区。修改时区属于高危操作，现场操作前需联系所内研发确认后方可操作！！！确认可以操作后，可参考（下图以尼泊尔为例，请按实际修改）：
1.登录daisy系统，进入云配置->配置->系统配置->时钟与时区
[图]
2.修改时区并保存：
[图]
[图]
3.登录TCF，分别重启opcs租户和zenap租户下的全部应用
[图]
4.检查修改是否生效
检查各个节点时区是否正确：
$timedatectl
[图]
检查容器内时间是否正确
使用k8s命令进入容器，并查看时区信息，命令示例：
$kubectl -n opcs exec -it commsrvzgdb-f82ae148-b7d2-40b9-b493-d7470f9ff7d5-0 sh
$date -R
[图]

## 如何修改标签

登录PAAS，切换租户为admin，依次点击云平台管理---资源---业务集群---cluster1---节点。在对应节点删除或者新增标签：点击对应节点后的修改按钮，新增或删除标签。
[图]
[图]
[图]
[图]
修改完后可以再次执行 sh Check_count_labels.sh，直到返回的标签数量与表5.4一致。
