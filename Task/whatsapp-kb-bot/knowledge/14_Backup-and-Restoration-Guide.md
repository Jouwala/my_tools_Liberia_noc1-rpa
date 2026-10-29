iMind

Backup and Restoration Operation Guide

V6.26.30.F30B3

**ZTE CORPORATION**
ZTE Plaza, Keji Road South, Hi-Tech Industrial Park,
Nanshan District, Shenzhen, P.R.China
Postcode: 518057
Tel: +86-755-26771900
URL: https://support.zte.com.cn
E-mail: support@zte.com.cn
**LEGAL INFORMATION**

Copyright 2026 ZTE CORPORATION.
The contents of this document are protected by copyright laws and international treaties. Any reproduction or
distribution of this document or any portion of this document, in any form by any means, without the prior written
consent of ZTE CORPORATION is prohibited. Additionally, the contents of this document are protected by
contractual confidentiality obligations.
All company, brand and product names are trade or service marks, or registered trade or service marks, of ZTE
CORPORATION or of their respective owners.
This document is provided as is, and all express, implied, or statutory warranties, representations or conditions are
disclaimed, including without limitation any implied warranty of merchantability, fitness for a particular purpose,
title or non-infringement. ZTE CORPORATION and its licensors shall not be liable for damages resulting from the
use of or reliance on the information contained herein.
ZTE CORPORATION or its licensors may have current or pending intellectual property rights or applications
covering the subject matter of this document. Except as expressly provided in any written license between ZTE
CORPORATION and its licensee, the user of this document shall not acquire any license to the subject matter
herein.
ZTE CORPORATION reserves the right to upgrade or make technical change to this product without further notice.
Users may visit the ZTE technical support website https://support.zte.com.cn to inquire for related information.
The ultimate right to interpret this product resides in ZTE CORPORATION.

Statement on the Use of Third-Party Embedded Software:
If third-party embedded software such as Oracle, Sybase/SAP, Veritas, Microsoft, VMware, and Redhat is
delivered together with this product of ZTE, the embedded software must be used as only a component of this
product. If this product is discarded, the licenses for the embedded software must be void either and must not be
transferred. ZTE will provide technical support for the embedded software of this product.

**Revision History**
**Contents**

1 Backup and Restoration Overview.......................................................................1
2 Setting Backup Option Parameters......................................................................3
3 Backup data statistics of each product (task time, period, and retention

period).......................................................................................................................7

3.1 eFlow................................................................................................................................... 7
3.2 UPM..................................................................................................................................... 8
3.3 NIOS.................................................................................................................................... 8
3.4 UFM..................................................................................................................................... 9
3.5 UEM................................................................................................................................... 10

4 Manual Backup..................................................................................................... 12

4.1 Backing Up Basic Data Manually......................................................................................12
4.2 Backing Up Service Data Manually...................................................................................14

5 Automatic Backup................................................................................................17

5.1 Backing Up Basic Data Automatically............................................................................... 17
5.2 Backing Up Service Data Automatically............................................................................19

6 Data Restoration...................................................................................................22

6.1 Recovering Basic Data......................................................................................................22
6.2 Restoring Service Data..................................................................................................... 24

7 Querying Backup and Recovery Logs............................................................... 26
8 Acronyms.............................................................................................................. 28

Backup and Restoration
# Overview

Overview：
Backup and restoration refers to the backup of basic data and service data required for the
proper operation of the AIMind system. If the system is faulty, you can restore the current
AIMind system as much as possible based on the backup files
Backup：
Backup refers to the process of storing data in a specified path in accordance with the
requirements of the AIMind system maintainer.The backup data can be used to restore data in
the AIMind system if the data is damaged or lost.The backup file is saved as a. Zip package
The backup data consists of basic data and service data.All basic data is backed up together,
and all service data is backed up separately
●Basic Data：Data required for system operation, including database table structures and
model data, such as resource models, security operation codes, and data generated by
services during operation
●Service data：Service data with a large amount of data, including log data, historical
alarm and notification data, backup and restoration log data, and operation and maintenance
data. Because there is a large amount of service data and backup and restoration are time-
consuming, the policies (such as the scheduling policy and backup scope) used are not exactly
the same as the basic data.
There are two backup modes: Manual backup and automatic backup
●Manual Backup：Back up basic data and service data manually or at the scheduled time
●Automatic Backup：Periodically back up basic data and service data at the time set by the
AIMind system maintainer
Restore：
Restoration consists of basic data restoration and service data restoration. All basic data is
restored together, and each type of service data is restored independently. Allows the AIMind
system maintainer to restore the backup files
Backup and Restoration Operation Guide

Caution
The restoration process is irreversible, that is, the restored data cannot be rolled back. Exercise

！
caution when restoring AIMind system data
●Basic Data Restoration：Restore the basic data backed up previously.
●Service Data Restoration：Restore the service data backed up previously.

Setting Backup Option
Parameters

Abstract：
Describes how to set the task execution time, backup file clearing, and file server information
involved in AIMind data backup and restoration。
You can back up and restore services from the default server, self-defined server, and remote
server。
Prerequisite：
You have obtained the information about the third-party FTP/SFTP server where the AIMind
backup file is stored, including the protocol, IP address, port, username, and password.
Steps：
From the navigation tree in the left pane, select [Data Backup and Recovery Backup Options].
The Backup Options window is displayed, see Figure 2-1 and Figure 2-2
Figure 2-1 Backup Options

Figure 2-2 File Server Configuration
Backup and Restoration Operation Guide

Description：
When you set the user-defined server, you cannot set the data backup path. The backup
directory (relative path under the home directory of the user) will be created automatically. For
example, when you manually back up basic data, the directory created is basic/manual。

Parameter Name                       Execution Time  Details
**Taskexecution time**
24-hour system, accurate to
Clearing Backup Files                                minutes. The execution time is the
execution time of automatic backup
of basic data. The execution time
of automatic backup of service
data is 1~2 hours later than the
execution time.
For the automatic backup task,
refer to "4 Automatic Backup". It is
recommended to set the backup
time to 1: 00 a.m. local time or
other idle time that does not affect
system use.

Sets the file clearance threshold
for basic data and service data.
When the size of a file reaches the
upper limit, the file is cleared from
the earliest to the lower limit.
The upper limit, lower limit, upper
limit of manual backup files, and
2 Setting Backup Option Parameters

Customized Service         Protocol                       lower limit of manual backup files
Device Information/Remote                                 can be set.。
Server Information         IP Adress
Port                           Select the protocol type of the
Username                       server in accordance with the
Password                       backup policy and actual backup
Backing Up the Root Directory  environment. Options: SFTP and
ftp.

Enter the IPV4 or IPV6 address of
the server path.。

Set it in accordance with the actual
setting of the operating system.

Username and password with read
and write permissions。

This parameter is applicable to
remote servers only. This path is
a relative path under the directory
where the FTP/SFTP server user is
located.

2. Click Modify.。
3. In the Task Execution Time area, set the global execution time for automatic backup.。
4. In the Backup File Clearing area, set the automatic clearing time for basic data and service
data, and the upper and lower limits of the file size for automatic or manual clearing。
5. (Optional) In the Custom Server Information and Remote Server Information areas, select
Enable to configure the FTP/SFTP server information. Click Test to test whether the AIMind
server is successfully connected to the FTP/SFTP server, see Figure 2-4。
Description：
If the customized server is enabled, you can select the default FTP server or customized FTP
server to back up and restore data.
If the remote server is enabled, you can back up data to the default FTP server or a user-
defined FTP server, and back up data to the remote FTP server at the same time.。
The user-defined server/remote server connection test is successful. If the FTP account
does not have the read/write access to the backup directory of the server, a message box is
displayed, see Figure 2-3. The server configuration information cannot be saved.。
Figure 2-3 Server configuration failure
Backup and Restoration Operation Guide

Figure 2-4 Customizing Server Information

6. Click OK.。

Backup data statistics of
each product (task time,
period, and retention
period)

Table of Contents

eFlow............................................................................................................................................ 7
UPM.............................................................................................................................................. 8
NIOS............................................................................................................................................. 8
UFM.............................................................................................................................................. 9
UEM............................................................................................................................................ 10

Note: The task time, period, and retention period of the following products are the
default configurations of the system. They can be used in accordance with this solution
or modified in accordance with the actual project situation.。

3.1 eFlow                              Task Time  Period  Retention duration
01：00      Daily
Service data       01：00      Daily   Thirty days or more than
CMDB               01：00      Daily   80 G days
eFlow am Data      01：00      Daily
eFlow Gis Data     01：00      Daily   Ten days or more than 80
eFlow mytask Data                     G days
eFlow sp Data
Ten days or more than 80
G days

Ten days or more than 80
G days

Ten days or more than 80
G days
Backup and Restoration Operation Guide

eFlow pm Data                        01：00      Daily   Ten days or more than 80
eFlow Ticket Data                    01：00      Daily   G days
eFlow Leave Data                     01：00      Daily
eFlow Asset Data                     01：00      Daily   Ten days or more than 80
eFlow Problem Data                   01：00      Daily   G days
Flow API Engine                      01：00      Daily
Ten days or more than 80
G days

Ten days or more than 80
G days

Ten days or more than 80
G days

Clearing 20 G 90%

Basic data: None
1. The APP data of the eFlow is not backed up, and only the query is performed. The data
source is web
The attachments and pictures of eFlow are compressed and backed up under mytask.

## UPM

Caution：There is only basic data and no service data for UPM data backup and restoration. In
addition, the AP database does not support service data backup and restoration due to a large
amount of data

Basic Data                           Task Time  Period  Retention duration
Daily   30 days or more than 8
gp_batch Script Data                 01：00      Daily   GB
Backup and Restoration                          Daily   30 days or more than 8
GB
OSSPM Model Data                     01：00      Daily   30 days or more than 8
Backup and Restoration                                  GB

QUICKRPT Model                       01：00              30 days or more than 8
Database Backup and                                     GB
Restoration

UPS Model Data Backup                01：00
and Restoration

3.3 NIOS                                Task Time  Period  Retention duration

Basic Data：None

Service Data
3 Backup data statistics of each product (task time, period, and retention period)

Work Order Voltage          01：00      Daily   180 days or more than 80
Drop-AI Order                          Daily   G days
Daily
Work Order Voltage          01：00      Daily   180 days or more than 80
Drop-Automated QC                              G days
Daily
Work Order Voltage          01：00      Daily   180 days or more than 80
Drop-Automatic Return                  Daily   G days
Daily
Work Order Voltage          01：00      Daily   180 days or more than 80
Drop-Dispatch                          Daily   G days
Suppression                            Daily
180 days or more than 80
Work Order Voltage          01：00              G days

Drop-Intelligent Diagnosis                     180 days or more than 80
G days
Work Order Voltage          01：00
Drop-Order Management                          180 days or more than 80
G days
Work Order Voltage          01：00
Drop-Repeat TT Analysis                        180 days or more than 80
G days
UNIA Asset Analyzer         01：00
180 days or more than 80
UNIA Openapi                01：00              G days

UNIA Prediction             01：00              180 days or more than 80
G days
UNIA Ticket Handler         01：00
180 days or more than 80
G days

## UFM

Basic Data                  Task Time  Period  Retention duration
Daily   30 days or more than 8
Alarm Association           01：00      Daily   GB
Daily   30 days or more than 8
Analysis-Rule Association                      GB
Daily   30 days or more than 8
Alarm-Basic Data            01：00              GB

Alarm Code Standar          01：00              30 days or more than 8
dization-Alarm Code         01：00              GB
Management

Alarm Dispatch-Alarm
Cache
Backup and Restoration Operation Guide

Access Management                   01：00      Daily   30 days or more than 8
Daily   GB
Access Management                   01：00      Daily   30 days or more than 8
Service                                                GB
Period  30 days or more than 8
Resource-resource data,             01：00      Daily   GB
including the RES data of
the UFM                                        Daily   Retention duration
Daily   180 days or more than 80
Service Data                        Task Time          G days
01：00      Period
Alarms (including                              Daily   30 days or more than 80
historical alarms and               01：00      Daily   G days
notifications)                                 Daily   360 days or more than 80
Daily   G days
Access Management                              Daily
Period  Retention duration
UFM data, including                 01：00      Daily   30 days
alarm statistics, alarm                        Daily
GIS, engineering alarm                                 30 days
management, and
dispatch service                                       30 days

3.5 UEM                                                    30 days

Basic Data                          Task Time          30 days

Event Analysis-Intelligent          01：00              Retention duration
Identification                                         180 days or more than 80
G days
Event Analysis-Intelligent          01：00              180 days or more than 80
Perception                                             G days

Intelligent Model                   01：00                                               |
Management

Event Analysis-Intelligent          01：00
Delimiting

Fault monitoring robot              01：00

Service Data                        Task Time
UNIA Event View                     01：00

Fault monitoring robot (            01：00
session and message
3 Backup data statistics of each product (task time, period, and retention period)

data and voice broadcast
records)

Event Monitoring-Current   01：00  Daily  180 days or more than 80
Event                             Daily  G days
Daily
Event Monitoring-Historic  01：00         180 days or more than 80
al Events                                G days

Event Monitoring-Event     01：00         180 days or more than 80
Dashboard                                G days

**Manual Backup**

Table of Contents

Backing Up Basic Data Manually...............................................................................................12
Backing Up Service Data Manually........................................................................................... 14

## Backing Up Basic Data Manually

Abstract：
This procedure describes how to manually back up basic data.
Only data records are backed up, excluding table structures, historical alarms, notifications,
logs, and original performance data。
Description：
The backup operation may take a long time.
File for manual backup of basic data:/basic/manual/manual_basic_ timestamp. Zip, where/
basic/manual is the default path.。
Steps：
1. On the Backup&Restore page, select [Data Backup&Restore > Manual Backup] from the
navigation tree in the left pane. The Basic Data Backup tab is displayed by default, see Figure
4-1.。
Figure 4-1 Manual Backup of Basic Data

2. Configure the manual backup of basic data. For a description of the parameters, refer to
Table 4-1.。
Table 4-1 Parameter Descriptions for Manual Basic Data Backup
4 Manual Backup

Parameter Name                                 Parameter Descriptions
**Backup server**
Synchronizing Uploads to a Remote Server       If there are multiple backup servers, select the IP
address of the server where the backup data is
Server Path                                    stored. For how to set the FTP/SFTP server, refer
Remote Server Path                             to Setting the File Server in Setting Backup Option
Timeout time                                   Parameters.。

Customized label                               The server path determines the storage location of
backup files. By default, a path is provided. The path
can also be modified as needed.。

When the backup execution time exceeds the
configured timeout time, the system automatically
stops the backup. The maximum timeout time is 60
minutes.

Only lowercase letters, digits, and underscores are
allowed. A maximum of 10 characters are allowed.
The name is displayed in the name of the final backup
file.。

3. Perform the following operations as required.。

If...                                          Then...
Executing a Backup Task Immediately
Execute the backup task at the scheduled time  Click Execute. A dialog box is displayed. Click OK。

a. Click Set Scheduled Task.。
b. In the displayed dialog box, set the scheduled time,
and click OK.
After the scheduled time is set, a red dot is
displayed in the upper right corner of the button.

（   ）。

The manual backup result and the generated backup file name are displayed in the basic

data backup list, see Figure 4-2.。
Description：
Before basic data is backed up, you cannot back up basic data. Otherwise, a task conflict

occurs.。
**Figure 4-2 Basic Data Backup List**
Backup and Restoration Operation Guide

Description：
As long as one item fails to be backed up, no compressed file will be generated and stored
under the server path. The backup files of all items are finally stored on the server.。

## Backing Up Service Data Manually

Abstract:
This procedure describes how to manually back up service data.。

ServicCeaduattiaonca！nnot be backed up before it is completed. Otherwise, a task conflict occurs.
Steps:
1. In the left navigation tree of the Backup&Restore Management window, select [Data
Backup&Restore > Manual Backup]. The Service Data Backup tab is displayed, see Figure 4-3.
Figure 4-3 Backing Up Service Data Manually

2. Click Config for the service data to be backed up. The parameter setting page is displayed.
This manual uses manual backup of historical alarms and notifications as an example. Figure
4-4 shows the parameter setting page.
Figure 4-4 Manual Backup of Historical Alarms and Notifications
4 Manual Backup

Parameter Name                            Description
**Backup Action**
l Backup Only: Only the local service data within the
Backup Filter Mode                        specified period is backed up manually.
T time bar                                l Delete Only: Only the local service data within the
Delete Filter Type                        specified period is deleted manually.
T time bar                                l backup and deletion: Backs up the local data within
Backup Selection                          the specified time to the server, and then deletes the
Backup server                             local service data within the specified time.。
Synchronizing Uploads to a Remote Server
Options: All, T Month Before, Last T Month, T Day
Before, and Last T Day. If All is selected, the T time
bar is not displayed.。

Integer of 1~9999, which is the T value in the backup
filtering mode.

Options: All, T Month Before, Last T Month, T Day
Before, and Last T Day. If All is selected, the T time
bar is not displayed.

Integer that can be set to 1~9999, which is the T
value in the deletion filter mode.。

Select the type of data to be backed up.。

If there are multiple backup servers, select the IP
address of the server where the backup data is
stored. For how to set the FTP/SFTP server, refer
to Setting the File Server in Setting Backup Option
Parameters.。
Backup and Restoration Operation Guide

Server Path                                    Backup path of the data on the backup server. This
Remote Server Path                             path is a relative path under the directory where the
Timeout time                                   FTP server user is located.。

Customized label                               When the backup execution time exceeds the
configured timeout time, the system automatically
stops the backup. The maximum timeout time is 120
minutes.

Only lowercase letters, digits, and underlines are
allowed. A maximum of 10 characters are allowed.
After being entered, the name of the final backup file
is displayed。

3. Perform the following operations as required。

If...                                          Then...
Executing a Backup Task Immediately
Execute the backup task at the scheduled time  Click Execute. A dialog box is displayed. Click OK.

a. Click Set Scheduled Task.。
b. In the displayed dialog box, set the scheduled time,
and click OK.
After the scheduled time is set, a red dot is displayed
in the upper right corner of the button.

The execution result shows the details of manual backup, see Figure 4-5.
Description：
The AIMind system data cannot be restored during the waiting process.
Figure 4-5 Backup Details of Historical Alarms and Notifications

**Automatic Backup**

Table of Contents

Backing Up Basic Data Automatically........................................................................................17
Backing Up Service Data Automatically.....................................................................................19

This chapter includes the following topics:：
●l Backing Up Basic Data Automatically
●l Backing Up Service Data Automatically

## Backing Up Basic Data Automatically

Abstract:
This procedure describes how to set the parameters for automatic backup of basic data,
including the server for saving automatic backup files and the execution period.
Automatic backup of basic data is full backup.
File generated by automatic backup of basic data:/basic/auto/auto_basic_ timestamp .zip
Steps:
1. On the Backup&Restore page, select [Data Backup&Restore > Auto Backup] from the
navigation tree in the left pane. The Basic Data Auto Backup tab is displayed by default.。
2. To modify task parameters, click Modify, see Figure 5-1.。
Backup and Restoration Operation Guide

3. Configure the automatic backup of basic data. For a description of the parameters, refer to
Table 5-1。
Table 5-1 Parameter Descriptions for Automatic Backup of Basic Data

Parameter Name                            Parameter Descriptions
Scheduled backup
Backup server                             Sets whether to enable the scheduled backup task.
Synchronizing Uploads to a Remote Server
If there are multiple backup servers, select the IP
address of the server where the backup data is
stored. For how to set the FTP/SFTP server, refer
5 Automatic Backup

Timeout time      to Setting the File Server in Setting Backup Option
Execution Period  Parameters.。
**Execution Time**
When the backup execution time exceeds the
configured timeout time, the system automatically
stops the backup. The maximum timeout time is 60
minutes.

Options: Day, Week, and Month. Select a time in
accordance with the execution period. Automatic
backup is performed once in each period.

The execution time information comes from the
task execution time set in 2 Setting Backup Option
Parameters.。

Click OK. The automatic backup configuration is completed.。

## Backing Up Service Data Automatically

Abstract:
● Backup and restoration(backup and restoration log data):/large/backup-service/
auto_backup-service_large_timestamp.zip
● Alarm (history alarm and notification data):/large/fm-history/auto/auto_fm-history_large_
timestamp .zip
● Access management (access package file)/large/giga-ams-framework/auto/auto_giga-ams-
framework_large_ timestamp .zip
● Model data (model package model)/large/nemodelmng/auto/auto_nemodelmng_large_
timestamp .zip
● Log (log service data):/large/log-backup/auto/auto_log-backup_large_ timestamp .zip
Steps:
1. On the Backup and Restore Management page, select [Data Backup and Restore] Automatic
Backup from the navigation tree in the left pane. The Automatic Backup tab is displayed, see
Figure 5-2.。
Figure 5-2 Automatic Backup of Service Data
Backup and Restoration Operation Guide

2. Click Configuration Task for the service data to be backed up. The Parameter Settings page
is displayed. Click Modify.
This manual uses automatic backup of historical alarms and notifications as an example. Figure
5-3 shows the parameter setting page.。
Figure 5-3 Automatic Backup of Historical Alarms and Notifications

Table 5-2 Parameter Descriptions for Automatic Service Data Backup

Parameter Name                            Parameter Descriptions
**Backup server**
Synchronizing Uploads to a Remote Server  If there are multiple backup file servers, select the
IP address of the server where the backup data is
Server Path                               stored. For how to set the FTP/SFTP server, refer to
Remote Server Path                        Setting Backup Option Parameters.。
**Timeout time**
Backup path of the data on the backup server. This
path is a relative path under the directory where the
FTP server user is located.。

When the backup execution time exceeds the
configured timeout time, the system automatically
stops the backup. The maximum timeout time is 120
minutes.
5 Automatic Backup

Execution Period                                    Options: Day, Week, and Month. Select a time in
Execution Time                                      accordance with the execution period. Automatic
Backup Item and Clearing Settings                   backup is performed once in each period。

The execution time of automatic backup of service
data is 1~2 hours later than the task execution time
set in "Setting Backup Option Parameters".

Sets data clearing rules. Data can be cleared by time
or by capacity. Only the data that exceeds the upper
limit is cleared. Before clearing data items, back up
the data.

3. Perform the following operations as required.

If...                                               Then...
Click Save.
The configuration data is saved and automatically
backed up each time.                                Click Save and Clear. The configuration is completed
Then, clear the number of backups according to the  and data is cleared immediately.
backup items and cleanup settings.
Data

Save the configuration data and clear the settings
according to the backup items.
Clear backup data immediately

**Data Restoration**

Table of Contents

Recovering Basic Data...............................................................................................................22
Restoring Service Data.............................................................................................................. 24

## Recovering Basic Data

Abstract:
If the basic data of the AIMind is lost, you can manually restore the basic data to the current
system through scheduled backup or manual backup. The period during which data can be
restored depends on the period during which data is backed up in the file.
The system can read backup files from the backup path of its own server or the path of a third-
party FTP/SFTP backup server. In addition, the backup files copied to the backup server can be
read.

DuringCathuetiroens！toration operation, the system clears the current system data and replaces it with
the historical data backed up by the system. Perform this operation with care.
Prerequisite：
The storage address and file name of the basic data backup file are known.
Steps:
1. On the Backup&Restore page, select [Data Backup&Restore > Data Restore] from the
navigation tree in the left pane. The Basic Data Restore tab is displayed by default, see Figure
6-1。
6 Data Restoration

Configure basic data restoration. For a description of the parameters, refer to Table 6-1.
Table 6-1 Parameter Descriptions for Restoring Basic Data

**Parameter Name  Parameter Descriptions**
**Backup server**
If there are multiple backup servers, select the IP
Server Path     address of the backup server where the backup files
Backup File     are located. For how to set the FTP/SFTP server,
Timeout time    refer to Setting Backup Option Parameters。

Select the server path where the data restoration file
is located and the data restoration file.

If the recovery execution time exceeds the configured
timeout time, basic data recovery fails and the
recovery is rolled back to the status before recovery.
The recommended maximum timeout time is 120
minutes.

2. Click Data Restore. The Data Restore dialog box is displayed, see Figure 6-2。
**Figure 6-2 Restore Execution Dialog Box**
Backup and Restoration Operation Guide

3. Click Data Restore. The details of data restoration are displayed in the Basic Data Backup
list.。

## Restoring Service Data

Abstract:
If service data is lost, you can manually restore the service data files that are backed up
periodically or manually to the database. Time period during which data can be restored,
depending on the time period during which data is backed up.

DuringCathuetiroens！toration operation, the system clears the current system data and replaces it with
the historical data backed up by the system. Perform this operation with care
Prerequisite：
The storage address and file name of the basic data backup file are known
Steps:
1. From the navigation tree in the left pane, select [Data Backup and Restore Data Restore].
The Service Data Restore window is displayed, see Figure 6-3.。
Figure 6-3 Service Data Restoration

2. Configure service data restoration. For a description of the parameters, refer to Table 6-2。
Table 6-2 Service Data Restoration Parameter Descriptions

**Parameter Name   Parameter Descriptions**
**Backup server**
If there are multiple backup servers, select the IP
Function Module  address of the backup server where the backup files
are located. For how to set the FTP/SFTP server,
refer to Setting Backup Option Parameters。

Select the type of data to be restored。
Server Path                                                                    6 Data Restoration
Backup File
Timeout time                   Select the server path where the data restoration file
is located and the data restoration file。
Figure 6-4 Select Restore File
When the recovery execution time exceeds the
configured timeout time, service data recovery fails
and the recovery is rolled back to the status before
recovery. The recommended maximum timeout time
is 120 minutes.

3. Click Data Restore. The Data Restore dialog box is displayed, see Figure 6-5.

Click Data Recovery. The data recovery progress is displayed in the service data recovery
list.。

Querying Backup and
Recovery Logs

Abstract:
Backup and recovery logs record the results of system backup and recovery operations,
including automatic system backup operations and manual backup operations
Steps:
1. On the Backup and Recovery Management page, select [Data Backup and Recovery]
Backup and Recovery Log from the navigation tree in the left pane. The Backup and Recovery
Log page is displayed, see Figure 7-1。
Figure 7-1 Backup and Restoration Logs

2. In the Result column, you can query the execution result of the backup and restoration
operation。
3. Click Details to view the details of the backup and restoration operation, see Figure 7-2。
Figure 7-2 Viewing the Details of a Backup and Restoration Operation
7 Querying Backup and Recovery Logs

Acronyms

Abbreviated Name  Full Name                      中文意思
APP               Application                    应用
FTP               File Transfer Protocol         文件传输协议
IP                Internet Protocol              因特网协议
NF                Network Function               网络功能
SFTP              Secure File Transfer Protocol  安全文件传输协议
