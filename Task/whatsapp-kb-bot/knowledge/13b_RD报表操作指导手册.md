# 报表模版上传指导手册
**步骤简述**
1. 从场景包中找到模板包 2. 登录系统 3. 进入报表管理 4. 进入模版管理 5. 上传模版
**从场景包中提取报表模板**
1. 找到场景将其解压 2. 在rd的路径下找到UFMRD_Vxx.xx.xx.xx.zip 为报表模板

进去模板管理 登录系统---->报表管理---->模版管理 登录系统 浏览器访问：https://IP:28001/uportal/framework/default.html 输入用户名密码---->登入系统 报表管理 点击进入报表管理

**iMind RD报表操作指导手册**

**模版管理**

**上传模版包**
点击+模版包----> +上传模版包 ----> 选择模板包 rd的路径下找到UFMRD_Vxx.xx.xx.xx.zip 为模板包

1 报表模版上传指导手册

# 创建报表实例指导手册
**创建报表步骤简述**
步骤简述，详情请看对应章节 1. 进入TCF查看数据库的端口 2. 创建探针实例 3. 登入到Uportal创建UFM-PG的数据源 4. 创建报表实例
**查看数据库的端口**
登录地址：https://IP/ngportal/login 步骤： 1. 登 录 2. 点击: 公共服务管理 3. 点击: PostgreSQL 4. 点击: 运行实体 5. 记录: 记录数据库的端口(创建数据源时使用)
**点击: 公共服务管理**

2 创建报表实例指导手册

**点击: PostgreSQL**

**点击: 运行实体**

**iMind RD报表操作指导手册**

记录: 记录数据库的端口(创建数据源时使用) 这里获取的是4580，根据实际获取为准

创建探针实例 1. 登入：https://IP:28001/uportal/framework/default.html#/home 输入用户名密码

2. 点击进入接入管理服务 3. 点击新建
**接入管理服务**

2 创建报表实例指导手册

**新建探针**

填写探针参数 按照参数表创建探针，点击确认 探针参数表 一、基础信息
**配置项 接入系统类型 代理名称 业务类型**
**二、公共信息**

配置值 ZTE-UFM ufm-report 报表

**iMind RD报表操作指导手册**

**配置项 接入包类型**

**配置值**
ZTE-UFM-REPORT-ZTE-ZTE-UFM-UFM-01.01 .447

**三、高级配置信息**
配置项 延迟时间 告警周期 当前条件告警间隔时间 历史条件告警执行间隔 历史条件告警补采天数 文件清理天数 历史告警补采天数 历史告警专业网条件
**历史告警补采执行时间 告警条件**

**配置值**

**单位**

**分钟**

**时**

**分钟**

**分钟**

**天**

**天**

**天**

RAN;CS;PS;PERFORMANCE;TR M_DWDM;TRM_IP

**时**

**见告警条件**

-

**告警条件**
zte.ran.nodeb#9990;zte.ran.enodeb#9970;zte.ran.bts#9980;zte.ran.nodeb#9991;zte.ran.enodeb#9971;zte.ran.

2 创建报表实例指导手册

**启动探针**

登入到Uportal创建UFM-PG的数据源

1. 登入：https://IP:28001/uportal/framework/default.html#/home 输入用户名密码 2. 点击进入报表管理 3. 点击进入数据源管理 4. 新建数据源 注意：如果这里已经创建了ufm-pg的数据源，就不需要在重复创建了 填写参数如下：

**字段 数据源名称 ***

**说明 数据源命名**

**示例 ufm-pg**

**iMind RD报表操作指导手册**
**字段 数据源类型 * 数据源地址 ***
数据库端口 * 数据库用户名 数据库密码 数据库名

说明 类型，一般默认 数据库的IP，这里填写浮动IP（ MSB的IP） 使用TCF查看到的PG端口 默认使用postgres 数据库密码 UFM-PG使用db_imind_ufm_pg_ zenap

示例 greenplum 10.89.245.245
4508 postgres XXXXXX db_imind_ufm_pg_zenap

**创建报表实例**
1. 进入报告管理 2. 点击创建报告 3. 基本信息（填写报表名称） 4. 报告生成方式（选择生成方式） 5. 模板文件（选择对应报表的模板文件） 6. 模板参数（默认） 7. 数据源（选择ufm-pg的数据源） 通用报表共6章，这里使用fm-daily-daily_outage_report做演示，6个报表都需要创建，报表列 表如下：

2 创建报表实例指导手册

**模版名**

**描述**

**生成时间**

fm-daily-daily_outage_report

从当前告警和 昨天恢复的历史告 警 2G/3G/4G Site Down和Cell Down告警列表

**每天一次**

fm-daily_3day_worst_recur_site

最近3天历史告警中的频繁退服站点 每天一次 报表

fm-daily-ip_clock_link_failure

当前告警中持续时长超48小时的 特定告警IP Clock Link Failure Alarms 统计

**每天一次**

fm-daily-network_outrage_tren d

基于历史和当前告警计算每天的退 服情况及最近15天趋势情况

**每天一次**

fm-hourly-network-status

基于一级运维区域站点退服和电源 Main Fail/Battery 在整点时的情况 统计

**每小时一次**

fm-hourly_active_site_down

每小时统计2G，3G Site Down的 退服时长

**每小时一次**

**点击创建报告**

基本信息（填写报表名称） 使用fm-daily-daily_outage_report做演示，填写好后点击下一步

**iMind RD报表操作指导手册**

报告生成方式（选择生成方式） 选择定时生成，按照表对应的生成时间列进行选择，选择好后下一步

模板文件（选择对应报表的模板文件） 使用fm-daily-daily_outage_report做演示，选择对应的模版后下一步

2 创建报表实例指导手册

**模板参数（默认） 保持默认，下一步**

**数据源（选择ufm-pg的数据源）**
数据源类型选择数据库，数据库选择ufm-pg，然后点击完成，fm-daily-daily_outage_report 创建完成，其他报表按照相同步骤操作

**iMind RD报表操作指导手册**
