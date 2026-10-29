iMind

NIOS Function Operation Guide

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

1 System User........................................................................................................... 1

1.1 Creating A User...................................................................................................................1

2 Cross-Domain Coordination................................................................................. 7

2.1 VMAX Diagnosis Information.............................................................................................. 7
2.1.1 Interface Display..................................................................................................... 7
2.1.2 Delete......................................................................................................................8
2.1.3 Advanced Query..................................................................................................... 8
2.1.4 Details..................................................................................................................... 9
2.1.5 Other Buttons........................................................................................................10

2.2 Task Management............................................................................................................. 11
2.2.1 Interface Display................................................................................................... 11
2.2.2 Activate................................................................................................................. 11
2.2.3 Execution.............................................................................................................. 12
2.2.4 Modification........................................................................................................... 12
2.2.5 History................................................................................................................... 13

3 Cutover Fault Forecast........................................................................................14

3.1 Cutover Fault Forecast......................................................................................................14
3.1.1 Interface Display................................................................................................... 14
3.1.2 Creating A Task....................................................................................................15
3.1.3 Modifying A Task..................................................................................................16
3.1.4 Import Task...........................................................................................................18
3.1.5 Export A Task Template.......................................................................................19
3.1.6 Executing A Task................................................................................................. 19
3.1.7 Stop A Task..........................................................................................................22
3.1.8 Delete A Task.......................................................................................................23
3.1.9 Query Task........................................................................................................... 25
3.1.10 Column Customization........................................................................................25
3.1.11 Operation Log Result..........................................................................................26
3.1.12 Operation Log Result..........................................................................................29

3.2 High-risk operation instruction monitoring......................................................................... 31
3.2.1 High-risk operation monitoring..............................................................................31
3.2.2 Dashboard.............................................................................................................34
3.2.3 Rule Management................................................................................................ 34
3.3 Operation Log Analysis..................................................................................................... 40
3.3.1 Operation Log Query............................................................................................ 40
3.3.2 NE Operation Statistics........................................................................................ 44

3.4 Address Conflict Management.......................................................................................... 48
3.4.1 Address Conflict Detection................................................................................... 48
3.4.2 Interface Address Query.......................................................................................55
3.4.3 Route Distribution Query...................................................................................... 56

3.5 Model Management........................................................................................................... 58
3.5.1 Interface Display................................................................................................... 58
3.5.2 Creating A Model..................................................................................................58
3.5.3 Importing A Model................................................................................................ 59
3.5.4 Delete A Model.....................................................................................................59
3.5.5 Modify A Model.....................................................................................................59
3.5.6 Training Model...................................................................................................... 60

4 Alarm Diagnosis and Self-healing......................................................................61

4.1 Diagnosis List.................................................................................................................... 61
4.1.1 Interface Display................................................................................................... 61
4.1.2 Re-diagnosis......................................................................................................... 62
4.1.3 Export All.............................................................................................................. 63
4.1.4 Diagnosis Details.................................................................................................. 64
4.1.5 Diagnosis Status Filtering.....................................................................................64

4.2 Self-Healing List................................................................................................................ 65
4.2.1 Interface Display................................................................................................... 65
4.2.2 Export All.............................................................................................................. 65

4.3 Rule Management............................................................................................................. 66
4.3.1 Interface Display................................................................................................... 66
4.3.2 Creating A Rule.................................................................................................... 66
4.3.3 Modify A Rule....................................................................................................... 67
4.3.4 Delete A Rule....................................................................................................... 69
4.3.5 Rule Details.......................................................................................................... 69
4.3.6 Rule Activation/Suspension.................................................................................. 70
4.3.7 Rule Export........................................................................................................... 71

5 Automatic Return................................................................................................. 72

5.1 Return A Work Order........................................................................................................ 72
5.1.1 Interface Display................................................................................................... 72
5.1.2 Other Buttons........................................................................................................73

5.2 Return Rules......................................................................................................................73
5.2.1 Interface Display................................................................................................... 73
5.2.2 Creating A Rule.................................................................................................... 74
5.2.3 Exporting/Importing Rules/Rule Templates.......................................................... 75
5.2.4 Rule Disabling/enabling........................................................................................ 76
5.2.5 Delete A Rule....................................................................................................... 77
5.2.6 Rule Modification.................................................................................................. 77

6 Automatic Quality Inspection............................................................................. 79

6.1 Quality Inspection Work Order.......................................................................................... 79
6.1.1 Interface Display................................................................................................... 79
6.1.2 Other Buttons........................................................................................................80

6.2 Quality Inspection Rules....................................................................................................80
6.2.1 Interface Display................................................................................................... 80
6.2.2 Creating A Rule.................................................................................................... 81
6.2.3 Exporting/Importing Rules/Rule Templates.......................................................... 81
6.2.4 Rule Disabling/enabling........................................................................................ 82
6.2.5 Delete A Rule....................................................................................................... 83
6.2.6 Rule Modification.................................................................................................. 83

7 Intelligent Work Order......................................................................................... 85

7.1 Work Order Pressure Reduction Dashboard.................................................................... 85
7.1.1 Interface Display................................................................................................... 85

7.2 Real-time Work Order Association.................................................................................... 86
7.2.1 Interface Display................................................................................................... 86
7.2.2 Refresh/scheduled Refresh.................................................................................. 87
7.2.3 Work Order Filtering............................................................................................. 88
7.2.4 Exporting A Work Order....................................................................................... 89
7.2.5 Work Order Details............................................................................................... 90

8 Work Order Management.................................................................................... 92

8.1 Preprocessing Work Order................................................................................................ 92
8.1.1 Interface Display................................................................................................... 92
8.1.2 Refresh/scheduled Refresh.................................................................................. 93
8.1.3 Preprocessing Work Order Details....................................................................... 94
8.1.4 Work Order Query................................................................................................ 94

8.2 Quality Inspection Work Order.......................................................................................... 95
8.2.1 Interface Display................................................................................................... 95
8.2.2 Refresh/scheduled Refresh.................................................................................. 96
8.2.3 Work Order Filtering............................................................................................. 97
8.2.4 Work Order Details............................................................................................... 98
8.3 Work Order Priority Analysis............................................................................................. 98
8.3.1 Interface Display................................................................................................... 98

9 Repeated Work Order........................................................................................ 100

9.1 Repeated Work Order Analysis.......................................................................................100
9.1.1 Interface Display................................................................................................. 100
9.1.2 Creating A Task..................................................................................................101
9.1.3 Task Details........................................................................................................ 101
9.1.4 Task Start/Stop................................................................................................... 102
9.1.5 Modifying A Task................................................................................................102
9.1.6 Delete A Task.....................................................................................................103
9.1.7 Export Task.........................................................................................................103

10 Complaint Work Order Early Warning........................................................... 105

10.1 Work Order Monitoring.................................................................................................. 105
10.1.1 Interface Display............................................................................................... 105

10.2 Rule Configuration......................................................................................................... 106
10.2.1 Interface Display............................................................................................... 106
10.2.2 Creating A Rule................................................................................................ 106
10.2.3 Rule Details...................................................................................................... 107
10.2.4 Modify A Rule................................................................................................... 108
10.2.5 Delete A Rule................................................................................................... 108

10.3 Warning Result.............................................................................................................. 109
10.3.1 Interface Display............................................................................................... 109

11 Network Risk Identification............................................................................. 110

11.1 Dashboard..................................................................................................................... 110
11.1.1 Interface Display............................................................................................... 110
11.1.2 Details............................................................................................................... 111

11.2 Equipment Failure Prediction........................................................................................ 112
11.2.1 Unlimited Potential Risk Identification.............................................................. 112
11.2.2 Identification of Transmission Potential Risks.................................................. 116
11.2.3 CN Exception Event......................................................................................... 116
11.2.4 Task Management............................................................................................ 117

12 Intelligent Mining of Potential Risk Rules..................................................... 123

12.1 Task Management......................................................................................................... 123
12.1.1 Interface Display............................................................................................... 123
12.1.2 Creating A Task................................................................................................124
12.1.3 Activate A Task................................................................................................ 124
12.1.4 Executing A Task............................................................................................. 125
12.1.5 Suspend A Task............................................................................................... 125
12.1.6 Delete A Task...................................................................................................126
12.1.7 Modifying A Task.............................................................................................. 127
12.1.8 Task History......................................................................................................128
12.2 Mining Result................................................................................................................. 128
12.2.1 Interface Display............................................................................................... 128
12.2.2 Verify That The Result is Valid.........................................................................129
12.2.3 The Confirmation Result is Invalid....................................................................130
12.2.4 Release Result................................................................................................. 131
12.2.5 Sorting Mining Results......................................................................................131
12.2.6 Filtering and Mining Results............................................................................. 132

13 Risk Identify...................................................................................................... 134

13.1 Network Risk................................................................................................................. 134
13.1.1 Task Management............................................................................................ 134
13.1.2 Rule Management............................................................................................ 147

14 Resource Errata................................................................................................152

14.1 Equipment Room Resource Errors............................................................................... 152
14.1.1 Interface Display............................................................................................... 152
14.1.2 Creating A Resource........................................................................................ 153
14.1.3 Intelligent Correction......................................................................................... 154
14.1.4 Modify A Resource........................................................................................... 154
14.1.5 Delete A Resource........................................................................................... 155
14.1.6 Importing Uncorrected Resources.................................................................... 155
14.1.7 Exporting Resources.........................................................................................156
14.1.8 Uploading Complete Resource Files................................................................ 156
14.1.9 Model Training.................................................................................................. 157
14.1.10 Filtering Resources......................................................................................... 157

15 Link Restoration............................................................................................... 158

15.1 Interface Display............................................................................................................ 158
15.2 Creating A Periodic Task.............................................................................................. 159
15.3 Activating A Periodic Task............................................................................................ 160
15.4 Suspending A Periodic Task......................................................................................... 160
15.5 Modifying A Periodic Task.............................................................................................161
15.6 Periodic Task Execution Result.................................................................................... 162
15.7 Deleting A Periodic Task...............................................................................................162
15.8 Filter Periodical Tasks................................................................................................... 163
15.9 Periodic Task Details.....................................................................................................164
15.10 Executing A Manual Task........................................................................................... 164

16 Fault Prediction................................................................................................ 167

16.1 The Base Station is Out of Service...............................................................................167
16.1.1 Out-of-Service Forecast....................................................................................167
16.1.2 Model Management.......................................................................................... 177
16.1.3 Out-of-Service Probability Check......................................................................183

**System User**

Table of Contents

Creating A User............................................................................................................................1

Use the admin account to create an account for maintenance personnel. This account has the
operation permission only for the NIOS module.
This chapter includes the following topics:
 Creating a User

## Creating A User

Prerequisite
1. The system is deployed successfully.
You can log in to the system properly.
Workspace > System Configuration > Security Management > Role Management
Operation steps:
1. Log in to the system as the administrator. Select System Configuration > Security

Management > Role Management. The User Role Management page is displayed, see the
following figure.
**NIOS Function Operation Guide**

1. Click Operation Set > Create Operation Set to create the operation set required by the NIOS
administrator, see the following figure.

1. Select the operation set permission corresponding to NIOS, see the following figure.
1 System User

1. Click Role > Create Role to create the role required by the NIOS administrator, see the
following figure.
**NIOS Function Operation Guide**

1. Select No for Area Security Administrator, and click OK, see the following figure.

1. Select resources as required, and select "NIOS" created in the above step for the operation
set, see the following figure.
1 System User

Note: Select a resource object on the left, and set the operation set on the right to change the
permissions of the resource object. You can press and hold the ctrl key to continuously select
or invert resource objects, or press and hold the shift key to select or invert resource objects at
the same layer in batches.
1. Click Create to create a NIOS role, see the following figure.

1. Click Role Management > Create User to create the NIOS administrator.

1. Enter the user information, see the following figure.
**NIOS Function Operation Guide**

Parameter                                   Value
Account Rule                                Selecting the Default Rule
Maximum number of concurrent logins         Depending on the actual situation
User group                                  Depending on the actual situation

1. Select the created NIOS role, see the following figure.

1. Click Create. The NIOS user is created.

**Cross-Domain**
**Coordination**

Table of Contents

VMAX Diagnosis Information....................................................................................................... 7
Task Management......................................................................................................................11

The provides an interface. Through the delimiting and positioning codes in request parameters,
the can deliver the results to the AAPC, NGI, NQI, EMS DNA, MagicEye, and Big DNA for
positioning analysis and diagnosis analysis, and return the analysis results asynchronously.
You can also query the corresponding current alarms and historical alarms through the site
information and time information.
This chapter includes the following topics:
 VMAX Diagnosis Information
 Task Management

## VMAX Diagnosis Information

## Interface Display

Prerequisite
1. System Login
The user has the operation path of the cross-domain coordination permission.
Login System > Network Intelligence Automation > Cross Domain Collaboration
Operation Steps
1. Login System > Network Intelligence Automation > Cross Domain Collaboration > VMAX

Diagnosis Information. The VMAX diagnosis information is displayed, including the
occurrence time, problem object, and diagnosis details, see the following figure.
**NIOS Function Operation Guide**

## Delete

Prerequisite
1. System Login
The user has the operation path of the cross-domain coordination permission.
Login System > Network Intelligence Automation > Cross Domain Collaboration
Operation Steps
1. On the VMAX Diagnosis Information tab, select one or more diagnosis information items,

see the following figure.

1. On the VMAX Diagnosis Information page, click Delete. The VMAX diagnosis information is
deleted successfully, see the following figure.

## Advanced Query

Prerequisite
2 Cross-Domain Coordination

1. System Login
The user has the operation path of the cross-domain coordination permission.
Login System > Network Intelligence Automation > Cross Domain Collaboration
Operation Steps
1. On the VMAX Diagnosis Information page, click Advanced query to query combined

conditions, see the following figure.

1. After configuring the query conditions, click Query. The query is successful, see the
following figure.

## Details

Prerequisite
1. System Login
The user has the operation path of the cross-domain coordination permission.
Login System > Network Intelligence Automation > Cross Domain Collaboration
Operation Steps
1. On the VMAX Diagnosis Information page, click Detail or click a serial number. The details

page is displayed, see the following figure.
**NIOS Function Operation Guide**

## Other Buttons

Prerequisite
1. System Login
The user has the operation path of the cross-domain coordination permission.
Login System > Network Intelligence Automation > Cross Domain Collaboration
Operation Steps
1. On the VMAX Diagnosis Information page, click a customized image in the figure. The

customized image is displayed, see the following figure.

1. On the VMAX Diagnosis Information page, click the icon to export the information, see the
following figure.

1. On the VMAX Diagnosis Information page, click the refresh icon. The VMAX diagnosis
information is refreshed successfully, see the following figure.
2 Cross-Domain Coordination

## Task Management

Task of collecting data files from the lower-level system at scheduled time, so that the VMAX
can directly invoke the task.

## Interface Display

Prerequisite
1. System Login
The user has the operation path of the cross-domain coordination permission.
Login System > Network Intelligence Automation > Cross Domain Collaboration
Operation Steps
1. Login System > Network Intelligence Automation > Cross Domain Collaboration > Task

Management. Collaborative tasks are displayed, see the following figure.

## Activate

Prerequisite
1. System Login
2. The user has the operation permission of cross-domain coordination.
Operation Path
Login System > Network Intelligence Automation > Cross Domain Collaboration
Operation Steps
1. On the Task Management page, click Activate to control the task status, see the following

figure.
**NIOS Function Operation Guide**

## Execution

Prerequisite
1. System Login
2. The user has the operation permission of cross-domain coordination.
Operation Path
Login System > Network Intelligence Automation > Cross Domain Collaboration
Operation Steps
1. On the Task Management page, click Excute to execute the task, see the following figure.

## Modification

Prerequisite
1. System Login
2. The user has the operation permission of cross-domain coordination.
Operation Path
Login System > Network Intelligence Automation > Cross Domain Collaboration
Operation Steps
1. On the Task Management page, click Modify in the Operation column to modify the task,

see the following figure.

1. Click Submit, see the following figure.

1. The modification is successful, see the following figure.
2 Cross-Domain Coordination

## History

Prerequisite
1. System Login
2. The user has the operation permission of cross-domain coordination.
Operation Path
Login System > Network Intelligence Automation > Cross Domain Collaboration
Operation Steps
1. On the Task Management page, click History. All records of the task are displayed, see the

following figure.

Cutover Fault Forecast

Table of Contents

Cutover Fault Forecast...............................................................................................................14
High-risk operation instruction monitoring..................................................................................31
Operation Log Analysis.............................................................................................................. 40
Address Conflict Management................................................................................................... 48
Model Management....................................................................................................................58

Receives device operation logs and operation logs, makes inference and analysis on the device
operation logs of cutover tasks, and displays the risk log information. The system matches
operation logs with high-risk operation rules, outputs a high-risk operation list, and displays the
results in a list and a dashboard. The system can report high-risk operation information to other
systems.
This chapter includes the following topics:
 Cutover Fault Forecast
 High-Risk Operation Command Monitoring
 Operation Log Analysis
 Address Conflict Management
 Model Management

## Cutover Fault Forecast

## Interface Display

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Select Login System > Network Intelligence Automation > Cutover Fault Forecast. The

information about the cutover task is displayed. The number of abnormal operation logs,
execution results, and execution time of the selected NEs within the execution range can be
3 Cutover Fault Forecast

displayed. The operation log results and operation log results can be viewed in details, see
the following figure.

## Creating A Task

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, click Create Task, see the following figure.

1. After the task information is improved, click New, see the following figure.
**NIOS Function Operation Guide**

1. The task is created successfully, see the following figure.

## Modifying A Task

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, you can modify an unexecuted task. Click Modify, see
the following figure.
3 Cutover Fault Forecast

2. After the task information is improved, click Modify, see the following figure.
3. The task is modified successfully, see the following figure.
**NIOS Function Operation Guide**

## Import Task

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, click Import Task, see the following figure.
3 Cutover Fault Forecast

## Export A Task Template

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, click Export Task Template, see the following figure.

## Executing A Task

Prerequisite
1. System Login
**NIOS Function Operation Guide**

2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, select one or more unexecuted tasks, see the following

figure.

1. Click Excute in the menu bar to execute tasks in batches, see the following figure.

1. Click Excute in the Operation column to execute the current task, see the following figure.
3 Cutover Fault Forecast

1. Click Confirm. The task is executed successfully, see the following figure.
**NIOS Function Operation Guide**

## Stop A Task

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, select a task that is being executed, see the following
figure.

2. Click stop in the Operation column to stop the ongoing task, see the following figure.

3. Click Confirm. The task is stopped successfully, see the following figure.
# Cutover Fault Forecast

## Delete A Task

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, select one or multiple tasks, see the following figure.

1. Click Delete in the menu bar to delete tasks in batches, see the following figure.
**NIOS Function Operation Guide**

1. Click Delete in the Operation column to delete the current task, see the following figure.

4. Click Delete. The task is deleted successfully, see the following figure.
3 Cutover Fault Forecast

## Query Task

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, enter the task name in the search box, see the

following figure.

1. On the Cutover Fault Forecast page, click to query combined conditions, see the following
figure.

## Column Customization

Prerequisite
**NIOS Function Operation Guide**

1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, click the Column Customization icon to customize the

columns of the task list, see the following figure.

## Operation Log Result

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, click Run log results, see the following figure.

1. The operation log analysis information is displayed on the Operation Log Result page.
Including log statistics, error operation log level statistics, error operation event TOP10, error
logs at each level TOP5, and error log proportion at each level. For details, see the following
figure.
3 Cutover Fault Forecast

Exception Log Proportion of Each Level: Select a period of time, see the following figure.

Export: You can export all execution results, see the following figure.

Log level: You can filter results by level, see the following figure.
**NIOS Function Operation Guide**

Search box: Search by NE name, see the following figure.

You can drill down to NEs and view the corresponding log details of the NEs. Including
log statistics, abnormal operation log level statistics, abnormal operation event TOP10,
abnormal logs at all levels TOP5, and abnormal log and operation log list switching. View the
corresponding details.
Drill NE: Click the NE name, see the following figure.
3 Cutover Fault Forecast

## Operation Log Result

Prerequisite
1. System Login
2. The user has the Cutover Fault Fore cast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Cutover Fault Forecast page, click Operation Log Result, see the following figure.

The operation log result page displays the corresponding operation log analysis information,
including log statistics, abnormal NE statistics, NE statistics table, and the corresponding
details, see the following figure.
**NIOS Function Operation Guide**

Export All: You can export all execution results, see the following figure.

You can view the log details of an NE through NE drill-down. Including abnormal log statistics,
abnormal instruction statistics, and list display, see the following figure.

Export All: You can export all execution results, see the following figure.
3 Cutover Fault Forecast

Drill down operation instructions and view details.

3.2 High-risk operation instruction monitoring

The system supports the configuration and management of high-risk operation instruction rules,
generates high-risk operation alarms by analyzing and matching real-time operation logs, and
displays the alarms on the dashboard of each dimension.

## High-risk operation monitoring

## Interface Display

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Login System > Network Intelligence Automation > Cutover Fault Forecast > High-risk

operation instruction monitoring > High-risk operation monitoring, see the following figure.
**NIOS Function Operation Guide**

## Exporting Alarms

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the High-risk operation monitoring page, click Export to export all current alarm data, see

the following figure.

## Querying Alarms

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the High-risk operation monitoring page, click, and set the query conditions, see the

following figure.
3 Cutover Fault Forecast

## Sorting Alarm Fields

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the High-risk operation monitoring page,select the Oder number , NE, title, occurrence

time, operation instruction, specialty, manufacturer, operation account, and operation time to
sort the alarm fields, see the following figure.

## Delete Alarms

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the High-risk operation monitoring page，Select an alarm and click Delete to delete the

corresponding alarm in the system, see the following figure.
**NIOS Function Operation Guide**

## Dashboard

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Login System > Network Intelligence Automation > Cutover Fault Forecast > High-risk

operation instruction monitoring > Dashboard
The high-risk operation data statistics of the last seven days are displayed, see the following
figure.

## Rule Management

New rules can be created to match high-risk operation alarms.

## Interface Display

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
3 Cutover Fault Forecast

**Operation Path**
Login System > Network Intelligence Automation > Cutover Fault Forecast
**Operation Steps**
1. Login System > Network Intelligence Automation > Cutover Fault Forecast > High-risk

operation instruction monitoring > Rule Management
The corresponding high-risk operation alarms are displayed by matching rules, and the alarm
data is displayed in a list, see the following figure.

## Export Rules

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Rule Management page, click Export to export all the current rules, see the following

figure.

## Creating A Rule

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
**NIOS Function Operation Guide**

Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Rule Management page, click Create, see the following figure.

2. After the rule information is improved, click Confirm, see the following figure.

## Query Rules

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Rule Management page, click Advanced query, see the following figure.
3 Cutover Fault Forecast

2. After setting the conditions, click Query. The query is successful, see the following figure.

## Enabling/Stopping A Rule

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Rule Management tab, click start or stop to validate or invalidate the rule, see the

following figure.

## Modify A Rule

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Rule Management page, click Modify, see the following figure.
**NIOS Function Operation Guide**

2. Click Confirm. The rule is modified successfully, see the following figure.

## Delete A Rule

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Rule Management page, click Delete, see the following figure.

2. Click Delete. The rule is deleted successfully, see the following figure.
3 Cutover Fault Forecast

## Download Template

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Rule Management page,Click Template Download to download the rule template,

see the following figure.

## Import Rules

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Rule Management page,Click Import to import rules, see the following figure.
**NIOS Function Operation Guide**

## Operation Log Analysis

Operation logs of all NEs are monitored, and the number of illegal NEs, the number of actually
operated NEs in the cutover plan, and the number of unoperated NEs within the corresponding
time are displayed based on the time dimension. Detailed information can be viewed in drill-
down mode.

## Operation Log Query

The operation logs that match the operation instructions are displayed.

## Interface Display

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
3 Cutover Fault Forecast

**Operation Path**
Login System > Network Intelligence Automation > Cutover Fault Forecast
**Operation Steps**
1. Login System > Network Intelligence Automation > Cutover Fault Forecast > Oplog Analysis

> Oplog Query, see the following figure.

## Export

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Oplog Query page, click Export to export logs, see the following figure.
**NIOS Function Operation Guide**

## Querying Logs

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Oplog Query page, click Advanced query to query logs in combination, see the

following figure.
3 Cutover Fault Forecast

## Column Customization

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Oplog Query page, click the column customization icon to customize the list, see the

following figure.

## Details/Operation Command Name

Prerequisite
**NIOS Function Operation Guide**

1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the Oplog Query page, click Detail, see the following figure.

1. The following figure shows the command details.

## NE Operation Statistics

The NEs that violate the regulations, NEs that are actually operated in the cutover plan, and
NEs that are not operated in the operation log are displayed. You can drill down the NE details
to display the corresponding operation log information.
3 Cutover Fault Forecast

## Interface Display

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Login System > Network Intelligence Automation > Cutover Fault Forecast > Oplog Analysis

> NE Statistics, see the following figure.

## Delete Statistics

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Select one or more data items on the NE Statistics tab, see the following figure.

1. Click Delete to delete data in batches, see the following figure.
**NIOS Function Operation Guide**

## Export Statistics

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click Export to export the current statistics, see the following figure.

## Details

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click Detail. The details page is displayed, see the following figure.

1. You can switch to the tab to switch the failed NEs, or export and display the NE details, see
the following figure.
3 Cutover Fault Forecast

## Other Buttons

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. The search box on the page supports the search of professional names, see the following

figure.

1. Advanced query supports combined query, see the following figure.
**NIOS Function Operation Guide**

1. Column customization supports the display of customized lists, see the following figure.

## Address Conflict Management

## Address Conflict Detection

The route information advertised in the entire network is accessed. If there is network
configuration, network conflict detection is performed, and the conflict configuration information
is displayed in an early warning.

## Interface Display

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Select Login System > Network Intelligence Automation > Cutover Fault Forecast > IP

Conflict Detection > Address Conflict Detection List, see the following figure.
3 Cutover Fault Forecast

## Importing A Scheduling Form

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click Import to import a local dispatch file, see the following figure.

1. You can select Check When Importing or Import Only, and select whether to match the
entire network segment, see the following figure.
**NIOS Function Operation Guide**

## Conflict Detection

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the page, click Conflict Detection. You can check the current scheduling single IP in

batches or by clicking the Conflict Detection button, see the following figure.

1. Click submit. The detection is successful, see the following figure.
3 Cutover Fault Forecast

## Delete

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click the Delete button to delete the current scheduling single IP in batches or delete it, see

the following figure.

1. Click Delete. The data is deleted successfully, see the following figure.
**NIOS Function Operation Guide**

## Search Box

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. In the search box, enter the ID of the dispatch list. The dispatch list can be searched, see

the following figure.

## Advanced Query

Prerequisite
1. System Login
3 Cutover Fault Forecast

2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click Advanced query, and enter the query conditions, see the following figure.

1. Click Query. The query is successful, see the following figure.

## Dispatch List Details

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
**NIOS Function Operation Guide**

Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click the scheduling order number. The scheduling order details are displayed, see the

following figure.

## Viewing The Result

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click Check View. If there is an IP conflict, you can view the detection result and export it. If

there is no IP conflict, this button is unavailable, see the following figure.
3 Cutover Fault Forecast

## Interface Address Query

## Interface Display

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Select Login System > Network Intelligence Automation > Cutover Fault Forecast > IP

Conflict Detection > Network Wide Interface Query. The IP addresses of the entire network
can be displayed, exported, and advanced query and column customization, see the
following figure.

## Export

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
**NIOS Function Operation Guide**

Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click Export. The data is exported successfully, see the following figure.

## Route Distribution Query

 à t 1. Interface Display
Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Login System > Network Intelligence Automation > Cutover Fault Forecast > IP Conflict

Detection > Network Wide Route Query: Displays, exports, advanced queries, column
customization, and details of the routes in the entire network, see the following figure.

 à t 1. Export
**Prerequisite**
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
**Operation Path**
Login System > Network Intelligence Automation > Cutover Fault Forecast
**Operation Steps**
1. Click Export. The data is exported successfully, see the following figure.
3 Cutover Fault Forecast

 à t 1. Details
Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
Click detail to view the details, see the following figure.
**NIOS Function Operation Guide**

## Model Management

## Interface Display

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Select Login System > Network Intelligence Automation > Cutover Fault Forecast > Model

Management. The model information is displayed, such as the status and manufacturer, see
the following figure.

## Creating A Model

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click New Model, see the following figure.

1. After editing the information, click submit.
3 Cutover Fault Forecast

## Importing A Model

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click Import to import a local file, see the following figure.

## Delete A Model

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. On the page, click Delete to delete data in batches or delete data in batches, see the

following figure.

## Modify A Model

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click Modify to edit the current model, see the following figure.
**NIOS Function Operation Guide**

1. After the modification, click submit. The modification is successful, see the following figure.

## Training Model

Prerequisite
1. System Login
2. The user has the Cutover Fault Forecast operation permission.
Operation Path
Login System > Network Intelligence Automation > Cutover Fault Forecast
Operation Steps
1. Click a training model, and select the data within a period of time as the model training

template data, see the following figure.

Alarm Diagnosis and
**Self-healing**

Table of Contents

Diagnosis List............................................................................................................................. 61
Self-Healing List......................................................................................................................... 65
Rule Management...................................................................................................................... 66

Diagnosis self-healing, including diagnosis rule management and diagnosis analysis. Invoke the
aax interface or send instructions through the gp to obtain diagnosis results for the work orders
or alarms that meet the rules.
This chapter includes the following topics:
 Diagnosis List
 Self-Healing List
 Rule Management

## Diagnosis List

## Interface Display

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Select Login System > Network Intelligence Automation > Alarm Diagnosis Recovery

> Diagnosis List, and view the diagnosis task information such as the diagnosis task
number, TT number (if any), diagnosis status, diagnosis result, alarm information, and alarm
occurrence time, see the following figure.
**NIOS Function Operation Guide**

## Re-diagnosis

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Select a diagnosis task, see the following figure.

1. Click Re-diagnosis to diagnose the task again, see the following figure.
4 Alarm Diagnosis and Self-healing

1. Click Submit. The diagnosis is successful, see the following figure.

## Export All

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Click Export All to export all diagnosis tasks, see the following figure.
**NIOS Function Operation Guide**

## Diagnosis Details

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Tap Diagnosis ID. The diagnosis details are displayed, see the following figure.

## Diagnosis Status Filtering

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
4 Alarm Diagnosis and Self-healing

1. Click the Filter button on the page to filter the information in accordance with the diagnosis
status, see the following figure.

## Self-Healing List

## Interface Display

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Select Login System > Network Intelligence Automation > Alarm Diagnosis Recovery >

Recovery List. The details of the self-healing list are displayed, including the self-healing
object, self-healing status, self-healing result, export, and column customization functions,
see the following figure.

## Export All

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
**NIOS Function Operation Guide**

Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Click Export All to export all diagnosis tasks, see the following figure.

## Rule Management

## Interface Display

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Login System > Network Intelligence Automation > Alarm Diagnosis Recovery > Rule

Management, see the following figure. Displays notification rule management information.
You can create, activate, suspend, modify, and delete predefined rules, see the following
figure.

## Creating A Rule

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
4 Alarm Diagnosis and Self-healing

1. Click New, see the following figure.

1. Click Submit, see the following figure.

1. The rule is created successfully, see the following figure.

## Modify A Rule

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Click Modify, see the following figure.
**NIOS Function Operation Guide**

1. Edit the modification information, see the following figure.

1. Click Modify. The modification is successful, see the following figure.
4 Alarm Diagnosis and Self-healing

## Delete A Rule

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Click Delete, see the following figure.

1. Click Delete to delete the rule successfully, see the following figure.

## Rule Details

Prerequisite
**NIOS Function Operation Guide**

1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Click Rule Name to view the details of the rule, see the following figure.

## Rule Activation/Suspension

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Click Suspend or Activate to activate or suspend the rule, see the following figure.
4 Alarm Diagnosis and Self-healing

## Rule Export

Prerequisite
1. System Login
2. The user has the alarm diagnosis and self-healing permission.
Operation Path
Login System > Network Intelligence Automation > Alarm Diagnosis Recovery
Operation Steps
1. Click Export All to export all rules, see the following figure.

**Automatic Return**

Table of Contents

Return A Work Order................................................................................................................. 72
Return Rules...............................................................................................................................73

It provides the return rule management and return analysis functions, receives eFlow) return
requests from external systems, and backfills the return analysis results in accordance with the
definition of return rules.
This chapter includes the following topics:
 Return a work order
 Return Rules

## Return A Work Order

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission to automatically return tickets.
Operation Path
Login System > Network Intelligence Automation > Ticket Auto Reply Rule
Operation Steps
1. Select Login System > Network Intelligence Automation > Ticket Auto Reply Rule > TT List.

The TT List page is displayed, showing the work order information, such as the work order
number, status, and information, see the following figure.
5 Automatic Return

## Other Buttons

Prerequisite
1. System Login
2. The user has the operation permission to automatically return tickets.
Operation Path
Login System > Network Intelligence Automation > Ticket Auto Reply Rule
Operation Steps
1. Click Export All. All work orders are exported successfully, see the following figure.

1. Click Export Selected. The selected work orders are exported successfully, see the following
figure.

1. On the page, click the Regular refresh icon. You can set the time and set it to the default
value, see the following figure.

## Return Rules

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission to automatically return tickets.
Operation Path
Login System > Network Intelligence Automation > Ticket Auto Reply Rule
**NIOS Function Operation Guide**

Operation Steps
1. Select Login System > Network Intelligence Automation > Ticket Auto Reply Rule >

Auto Reply Rule to display the basic information of the rule and export and modify the
information, see the following figure.

## Creating A Rule

Prerequisite
1. System Login
2. The user has the operation permission to automatically return tickets.
Operation Path
Login System > Network Intelligence Automation > Ticket Auto Reply Rule > Auto Reply
Rule
Operation Steps
1. Click Create, see the following figure.

2. After filling in the new information, click OK, as shown in the figure below.
5 Automatic Return

3. The rule can be created successfully, see the following figure.

## Exporting/Importing Rules/Rule Templates

Prerequisite
1. System Login
2. The user has the operation permission to automatically return tickets.
Operation Path
Login System > Network Intelligence Automation > Ticket Auto Reply Rule > Auto Reply
Rule
Operation Steps
1. Click Export Rule. All rules are exported successfully, see the following figure.
**NIOS Function Operation Guide**

2. On the page, click Import Rule to import a local rule file, see the following figure.
3. Click Export Rule Template to export all rule templates, see the following figure.

## Rule Disabling/enabling

Prerequisite
1. System Login
2. The user has the operation permission to automatically return tickets.
Operation Path
Login System > Network Intelligence Automation > Ticket Auto Reply Rule > Auto Reply
Rule
Operation Steps
5 Automatic Return

1. Click Enable/Disable to control the rule status, see the following figure.

## Delete A Rule

Prerequisite
1. System Login
2. The user has the operation permission to automatically return tickets.
Operation Path
Login System > Network Intelligence Automation > Ticket Auto Reply Rule > Auto Reply
Rule
Operation Steps
1. Click Delete. The rule is deleted successfully, see the following figure.

## Rule Modification

Prerequisite
1. System Login
2. The user has the operation permission to automatically return tickets.
Operation Path
Login System > Network Intelligence Automation > Ticket Auto Reply Rule
Operation Steps
1. Click Modify, see the following figure.
**NIOS Function Operation Guide**

2. After editing the information, click OK. The rule is modified successfully, see the following
figure.

**Automatic Quality**
**Inspection**

Table of Contents

Quality Inspection Work Order...................................................................................................79
Quality Inspection Rules............................................................................................................ 80

It provides the return rule management and return analysis functions, receives eFlow) return
requests from external systems, and backfills the return analysis results in accordance with the
definition of return rules.
This chapter includes the following topics:
 Quality Inspection Work Order
 Quality Inspection Rules

## Quality Inspection Work Order

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of automatic quality inspection.
Operation Path
Login System > Network Intelligence Automation > Automated QC
Operation Steps
1. Click Login System > Network Intelligence Automation > Automated QC > QC List to display

the basic information of the work order, such as the status and time, see the following figure.
**NIOS Function Operation Guide**

## Other Buttons

Prerequisite
1. System Login
2. The user has the operation permission of automatic quality inspection.
Operation Path
Login System > Network Intelligence Automation > Automated QC
Operation Steps
1. Click Export All. All work orders are exported successfully, see the following figure.

1. Click Export selected. The selected work orders are exported successfully, see the following
figure.

1. On the page, click the Regular refresh icon. You can set the time and set it to the default
value, see the following figure.

## Quality Inspection Rules

## Interface Display

Prerequisite
6 Automatic Quality Inspection

1. System Login
2. The user has the operation permission of automatic quality inspection.
**Operation Path**
Login System > Network Intelligence Automation > Automated QC
**Operation Steps**
1. Select Login System > Network Intelligence Automation > Automated QC > QC Rule. The

basic information about the rule is displayed, and the export and modification functions are
supported, see the following figure.

## Creating A Rule

Prerequisite
1. System Login
2. The user has the operation permission of automatic quality inspection.
Operation Path
Login System > Network Intelligence Automation > Automated QC
Operation Steps
1. Click Create, see the following figure.

1. After entering the new information, click OK. The rule is created successfully, see the
following figure.

## Exporting/Importing Rules/Rule Templates

Prerequisite
1. System Login
2. The user has the operation permission of automatic quality inspection.
Operation Path
**NIOS Function Operation Guide**

Login System > Network Intelligence Automation > Automated QC
Operation Steps
1. Click Export Rule. All rules are exported successfully, see the following figure.

1. On the page, click Import Rule to import a local rule file, see the following figure.

1. Click Export Rule Tenmplate to export all rule templates, see the following figure.

## Rule Disabling/enabling

Prerequisite
1. System Login
2. The user has the operation permission of automatic quality inspection.
Operation Path
Login System > Network Intelligence Automation > Automated QC
Operation Steps
1. Click Enable/Disable to control the rule status, see the following figure.
6 Automatic Quality Inspection

## Delete A Rule

Prerequisite
1. System Login
2. The user has the operation permission of automatic quality inspection.
Operation Path
Login System > Network Intelligence Automation > Automated QC
Operation Steps
1. Click Delete. The rule is deleted successfully, see the following figure.

## Rule Modification

Prerequisite
1. System Login
2. The user has the operation permission of automatic quality inspection.
Operation Path
Login System > Network Intelligence Automation > Automated QC
Operation Steps
1. Click Modify, see the following figure.
**NIOS Function Operation Guide**

1. After editing the information, click Confirm. The rule is modified successfully, see the
following figure.

**Intelligent Work Order**

Table of Contents

Work Order Pressure Reduction Dashboard............................................................................. 85
Real-time Work Order Association.............................................................................................86

This function collects statistics of real-time work order analysis results, and displays the work
order compression effect in dashboard mode.
This chapter includes the following topics:
 Work order pressure reduction dashboard
 Real-time work order association

## Work Order Pressure Reduction Dashboard

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to operate intelligent work orders.
Operation Path
Login System > Network Intelligence Automation > AI Order
Operation Steps
1. Select Login System > Network Intelligence Automation > AI Order > DashBoard. The

number of work orders is displayed on the GUI. You can filter work orders by time and type,
see the following figure.
**NIOS Function Operation Guide**

## Real-time Work Order Association

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to operate intelligent work orders.
Operation Path
Login System > Network Intelligence Automation > AI Order
Operation Steps
1. Login System > Network Intelligence Automation > AI Order >
2. Ai Order. The associated status of work orders is displayed in a list. You can

manually refresh or filter associated work orders or all work orders. You can search
by header, automatically refresh, export, or customize columns, see the following
figure.
# Intelligent Work Order

## Refresh/scheduled Refresh

Prerequisite
1. System Login
2. The user has the permission to operate intelligent work orders.
Operation Path
Login System > Network Intelligence Automation > AI Order
Operation Steps
1. Click the Refresh icon to manually refresh the work order list, see the following figure.

1. Click the Auto refresh icon. The work order list is refreshed automatically, see the following
figure.
**NIOS Function Operation Guide**

## Work Order Filtering

Prerequisite
1. System Login
2. The user has the permission to operate intelligent work orders.
Operation Path
Login System > Network Intelligence Automation > AI Order
Operation Steps
1. You can select Revelance Order or All Order from the drop-down list, see the following

figure.

1. Click the Revelance Order button from the drop-down list. The associated work order data is
displayed in the list, see the following figure.
7 Intelligent Work Order

1. Click All Order in the drop-down list. All work order data is displayed in the list, see the
following figure.

## Exporting A Work Order

Prerequisite
1. System Login
2. The user has the permission to operate intelligent work orders.
Operation Path
Login System > Network Intelligence Automation > AI Order
Operation Steps
1. Click the Export icon. The work order is exported successfully, see the following figure.
**NIOS Function Operation Guide**

## Work Order Details

Prerequisite
1. System Login
2. The user has the permission to operate intelligent work orders.
Operation Path
Login System > Network Intelligence Automation > AI Order
Operation Steps
1. Click Trouble Ticket No. The details of the trouble ticket are displayed, see the following

figure.
7 Intelligent Work Order

**Work Order Management**

Table of Contents

Preprocessing Work Order.........................................................................................................92
Quality Inspection Work Order...................................................................................................95
Work Order Priority Analysis......................................................................................................98

Displays pre-processed work orders and quality inspection work orders by category.
This chapter includes the following topics:
 Preprocessing Work Order
 Quality Inspection Work Order
 Work Order Priority Analysis

## Preprocessing Work Order

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage work orders.
Operation Path
Login System > Network Intelligence Automation > Order Management
Operation Steps
1. Login System > Network Intelligence Automation > Order Management >
2. Troubleticket. The basic information of pre-processed work orders is displayed, such

as "Tt Id" and "Work Order Subject". You can manually refresh, automatically refresh
at the scheduled time, search by combined conditions, and customize columns, see
the following figure.
# Work Order Management

## Refresh/scheduled Refresh

Prerequisite
1. System Login
2. The user has the permission to manage work orders.
Operation Path
Login System > Network Intelligence Automation > Order Management
Operation Steps
1. Click the Refresh icon to manually refresh the work order list, see the following figure.

1. Click the Auto refresh icon. The work order list is refreshed automatically, see the following
figure.
**NIOS Function Operation Guide**

## Preprocessing Work Order Details

Prerequisite
1. System Login
2. The user has the permission to manage work orders.
Operation Path
Login System > Network Intelligence Automation > Order Management
Operation Steps
1. Click Tt Id to view the work order details, see the following figure.

## Work Order Query

Prerequisite
1. System Login
2. The user has the permission to manage work orders.
Operation Path
Login System > Network Intelligence Automation > Order Management
Operation Steps
1. Click Condition Query, see the following figure.
8 Work Order Management

1. Select the conditions and click Query, see the following figure.
1. The corresponding work order is queried successfully, see the following figure.

## Quality Inspection Work Order

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage work orders.
Operation Path
Login System > Network Intelligence Automation > Order Management
Operation Steps
Select Login System > Network Intelligence Automation > Order Management > Qcticket. The
basic information of the pre-processing work order is displayed, such as "Tt Id" and "Fault
Cause Classification". You can manually refresh, automatically refresh at the scheduled time,
search by combined conditions, and customize columns, see the following figure.
**NIOS Function Operation Guide**

Click Tt Id. The work order details are displayed, see the following figure.

## Refresh/scheduled Refresh

Prerequisite
1. System Login
2. The user has the permission to manage work orders.
Operation Path
Login System > Network Intelligence Automation > Order Management
Operation Steps
1. Click the Refresh icon to manually refresh the work order list, see the following figure.
8 Work Order Management

1. Click the Auto refresh icon. The work order list is refreshed automatically, see the following
figure.

## Work Order Filtering

Prerequisite
1. System Login
2. The user has the permission to manage work orders.
Operation Path
Login System > Network Intelligence Automation > Order Management
Operation Steps
1. Click Condition Query, see the following figure.

1. Select the conditions and click Query, see the following figure.

1. The corresponding work order is queried successfully, see the following figure.
**NIOS Function Operation Guide**

## Work Order Details

Prerequisite
1. System Login
2. The user has the permission to manage work orders.
Operation Path
Login System > Network Intelligence Automation > Order Management
Operation Steps
1. Click Tt Id to view the work order details, see the following figure.

## Work Order Priority Analysis

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage work orders.
Operation Path
Login System > Network Intelligence Automation > Order Management
Operation Steps
Login System > Network Intelligence Automation > Order Management > SLA Ticket Analysis.
The analysis results are displayed, such as id and tt Title, see the following figure.
8 Work Order Management

**Repeated Work Order**

Table of Contents

Repeated Work Order Analysis............................................................................................... 100

Monitors and analyzes work orders in real time. In addition, you can manually create a task to
analyze historical work orders. At present, repeated analysis includes three scenarios: Same
NE, same equipment room, and same link.
This chapter includes the following topics:
 Repeated work order analysis

## Repeated Work Order Analysis

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to repeat work orders.
Operation Path
Login System > Network Intelligence Automation > Repeat TT Analysis
Operation Steps
1. Select Login System > Network Intelligence Automation > Repeat TT Analysis > Repeat TT

Analysis. The basic information of the repeated work order analysis task is displayed. You
can refresh, search, customize columns, and export the task at the scheduled time, see the
following figure.
9 Repeated Work Order

## Creating A Task

Prerequisite
1. System Login
2. The user has the permission to repeat work orders.
Operation Path
Login System > Network Intelligence Automation > Repeat TT Analysis
Operation Steps
1. Click New. Set the parameters, see the following figure.

1. Click submit. The analysis task is created successfully, see the following figure.

## Task Details

Prerequisite
1. System Login
2. The user has the permission to repeat work orders.
Operation Path
Login System > Network Intelligence Automation > Repeat TT Analysis
Operation Steps
1. Click Task Name. The task details are displayed, see the following figure.
**NIOS Function Operation Guide**

## Task Start/Stop

Prerequisite
1. System Login
2. The user has the permission to repeat work orders.
Operation Path
Login System > Network Intelligence Automation > Repeat TT Analysis
Operation Steps
1. Click stop to control the start/stop status of the task, see the following figure.

## Modifying A Task

Prerequisite
9 Repeated Work Order

1. System Login
2. The user has the permission to repeat work orders.
Operation Path
Login System > Network Intelligence Automation > Repeat TT Analysis
Operation Steps
1. Click Update, see the following figure.

1. After the modification, click submit. The task is modified successfully, see the following
figure.

## Delete A Task

Prerequisite
1. System Login
2. The user has the permission to repeat work orders.
Operation Path
Login System > Network Intelligence Automation > Repeat TT Analysis
Operation Steps
1. Click Delete. The task is deleted successfully, see the following figure.

## Export Task

Prerequisite
**NIOS Function Operation Guide**

1. System Login
2. The user has the permission to repeat work orders.
Operation Path
Login System > Network Intelligence Automation > Repeat TT Analysis
Operation Steps
Click the Export icon to export the task successfully, see the following figure.

**Complaint Work Order**
**Early Warning**

Table of Contents

Work Order Monitoring............................................................................................................. 105
Rule Configuration....................................................................................................................106
Warning Result......................................................................................................................... 109

Including complaint work order monitoring, rule configuration, and early warning results. The
system periodically collects complaint work orders from external systems, analyzes them in
accordance with configuration rules, and outputs early warning results.
This chapter includes the following topics:
 Work Order Monitoring
 Rule Configuration
 Warning Result

## Work Order Monitoring

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to raise alerts for complaint work orders.
Operation Path
Login System > Network Intelligence Automation > Complaint Order Warning
Operation Steps
1. Select Login System > Network Intelligence Automation > Complaint Order Warning > Work

Order Monitoring. The basic information of the work order is displayed, such as the work
order number, serial number, and title. You can export, search, customize columns, and
refresh the information, see the following figure.
**NIOS Function Operation Guide**

## Rule Configuration

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to raise alerts for complaint work orders.
Operation Path
Login System > Network Intelligence Automation > Complaint Order Warning
Operation Steps
1. Select Login System > Network Intelligence Automation > Complaint Order Warning > Rule

Management. The basic information of the rule is displayed, including the rule name, rule
level, and location information. You can export, search, customize columns, and refresh the
information, see the following figure.

## Creating A Rule

Prerequisite
1. System Login
2. The user has the permission to raise alerts for complaint work orders.
Operation Path
Login System > Network Intelligence Automation > Complaint Order Warning
Operation Steps
1. Click Create to create a rule, see the following figure.
10 Complaint Work Order Early Warning

1. After editing the new information, click Confirm. The rule is created successfully, see the
following figure.

## Rule Details

Prerequisite
1. System Login
2. The user has the permission to raise alerts for complaint work orders.
Operation Path
Login System > Network Intelligence Automation > Complaint Order Warning
Operation Steps
1. Click the rule name to view the details of the rule, see the following figure.
**NIOS Function Operation Guide**

## Modify A Rule

Prerequisite
1. System Login
2. The user has the permission to raise alerts for complaint work orders.
Operation Path
Login System > Network Intelligence Automation > Complaint Order Warning
Operation Steps
1. On the rule display or details page, click Modify to modify the rule, see the following figure.

1. After editing the information, click Confirm. The rule is modified successfully, see the
following figure.

## Delete A Rule

Prerequisite
1. System Login
2. The user has the permission to raise alerts for complaint work orders.
Operation Path
Login System > Network Intelligence Automation > Complaint Order Warning
Operation Steps
1. Click Delete. The rule is deleted successfully, see the following figure.
10 Complaint Work Order Early Warning

## Warning Result

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to raise alerts for complaint work orders.
Operation Path
Login System > Network Intelligence Automation > Complaint Order Warning
Operation Steps
Login System > Network Intelligence Automation > Complaint Order Warning > Early Warning
Result. The basic information of the early warning result is displayed, such as the occurrence
area, occurrence rule name, and related work order number. You can export, search, and
customize columns, see the following figure.

**Network Risk**
**Identification**

Table of Contents

Dashboard................................................................................................................................ 110
Equipment Failure Prediction................................................................................................... 112

By predefined task pair: Optical module quality evaluation, fronthaul optical link quality
evaluation, RRU environment temperature evaluation, RRU input voltage evaluation, BBU
environment temperature evaluation, and abnormal events of the core network are reported to
different ems to obtain risk information, and the trend is displayed in dashboard mode.
This chapter includes the following topics:
 Dashboard
 Equipment Failure Prediction

## Dashboard

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Login System > Network Intelligence Automation > Potential Problem Identification >

Dashboard. The fault prediction information is displayed on the dashboard, see the following
figure.
11 Network Risk Identification

## Details

Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Click Details in the upper right corner of the page. The details are displayed, see the

following figure.
**NIOS Function Operation Guide**

## Equipment Failure Prediction

## Unlimited Potential Risk Identification

Various evaluation details are displayed in a GUI, and the displayed information is the same as
that on the dashboard.
 à t 1. Optical module quality evaluation
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Login System > Network Intelligence Automation > Potential Problem Identification >

Equipment Failure Prediction > Identifying potential risks of the Wireless network > Optical
Module Quality Evaluation, see the following figure.
11 Network Risk Identification

 à t 1. Fronthaul Optical Link Quality Evaluation
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Login System > Network Intelligence Automation > Potential Problem Identification

> Equipment Failure Prediction > Identifying potential risks of the Wireless network >
Fronthaul Optical Link Quality Evaluation, see the following figure.

 à t 1. RRU Environment Temperature Evaluation
Prerequisite
**NIOS Function Operation Guide**

1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Login System > Network Intelligence Automation > Potential Problem Identification >

Equipment Failure Prediction > Identifying potential risks of the Wireless network > RRU
Environment Temperature Evaluation, see the following figure.

 à t 1. RRU Input Voltage Evaluation
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Login System > Network Intelligence Automation > Potential Problem Identification >

Equipment Failure Prediction > Identifying potential risks of the Wireless network > RRU
Input Voltage Evaluation, see the following figure.
11 Network Risk Identification

 à t 1. BBU Environment Temperature Evaluation
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Login System > Network Intelligence Automation > Potential Problem Identification >

Equipment Failure Prediction > Identifying potential risks of the Wireless network > BBU
Environment Temperature Evaluation, see the following figure.
**NIOS Function Operation Guide**

11.2.2 Identification of Transmission Potential Risks

 à t 1. Interface Display
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Login System > Network Intelligence Automation > Potential Problem Identification >

Equipment Failure Prediction > Identifying potential risks of the transmission network.
The transmission-related alarms are displayed in graphs and lists. The export function is
supported. The alarms are filtered by alarm level and acknowledgment status, see the
following figure.

## CN Exception Event

 à t 1. Interface Display
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Select Login System > Network Intelligence Automation > Potential Problem Identification

> Equipment Failure Prediction > Core network abnormal events. The CN error events are
11 Network Risk Identification

displayed in graphs and lists. The column customization and export functions are supported,
see the following figure.

## Task Management

 à t 1. Interface Display
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Select Login System > Network Intelligence Automation > Potential Problem Identification

> Task Management. The displayed tasks are displayed in a list. You can customize and
refresh the columns displayed on the page, see the following figure.
**NIOS Function Operation Guide**

 à t 1. Activate a task
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Click Activate Status to activate or deactivate the task, see the following figure.

 à t 1. Executing a Task
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
11 Network Risk Identification

1. Click Excute to execute the task manually, see the following figure.

 à t 1. Modifying a Task
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Click Modify to modify an inactive task, see the following figure.

1. After the modification, click submit. The modification is successful, see the following figure.
**NIOS Function Operation Guide**

 à t 1. History
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Click History. The historical records of the task execution are displayed, see the following

figure.
11 Network Risk Identification

 à t 1. Latest Success Record
Prerequisite
1. System Login
2. The user has the operation permission to identify network risks.
Operation Path
Login System > Network Intelligence Automation > Potential Problem Identification
Operation Steps
1. Click History to view the execution history of the task, see the following figure.
**NIOS Function Operation Guide**

Intelligent Mining of
**Potential Risk Rules**

Table of Contents

Task Management....................................................................................................................123
Mining Result............................................................................................................................128

Based on historical alarms, you can mine the relationships between the duration, frequency,
and quantity of alarms and hidden troubles, convert them into hidden troubles rules, and publish
them to the hidden troubles identification rule library.
This chapter includes the following topics:
 Task Management
 Mining Result

## Task Management

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Login System > Network Intelligence Automation > Risk Rule Intelligent Mining > Task

Management. The task list for intelligent mining of hidden danger rules is displayed. You can
create, activate, or suspend a task, see the following figure.
**NIOS Function Operation Guide**

## Creating A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Click New. The New Task page is displayed, see the following figure.

1. Set the parameters, see the following figure.

1. Click Confirm to complete the task creation, see the following figure.

## Activate A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
12 Intelligent Mining of Potential Risk Rules

1. Select one or more suspended tasks, see the following figure.

1. Click Activate to activate the task, see the following figure.

## Executing A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Select an unexecuted task, see the following figure.

2. Click Excute, select the execution time, and click Confirm, see the following figure.

## Suspend A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
**NIOS Function Operation Guide**

Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Select one or more activated tasks, see the following figure.

1. Click Suspend. The task is suspended successfully, see the following figure.

## Delete A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Select one or more suspended tasks, see the following figure.

1. Click Delete. The task is deleted successfully, see the following figure.
12 Intelligent Mining of Potential Risk Rules

## Modifying A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. In the Operation column of the task list, select More > Modify. The Modify Task page is

displayed, see the following figure.

1. After modifying the information, click Confirm. A message box is displayed, indicating that
the modification is successful, see the following figure.
**NIOS Function Operation Guide**

## Task History

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Click History in the Operation column, see the following figure.

1. The History Detail page is displayed, see the following figure.

## Mining Result

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Login System > Network Intelligence Automation > Risk Rule Intelligent Mining > Task

Management. The intelligent mining result of hidden danger rules is displayed. You can
confirm, release, and filter the result, see the following figure.
12 Intelligent Mining of Potential Risk Rules

12.2.2 Verify That The Result is Valid.

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Click Valid in the Operation column to confirm the mining results in Invalid or To Be

Confirmed status, see the following figure.

1. Click Valid in the upper menu bar to confirm the mining results in Invalid and To Be
Confirmed status in batches, see the following figure.
**NIOS Function Operation Guide**

1. After the confirmation, the system prompts "Confirm Valid Success", as shown in the figure
below.

12.2.3 The Confirmation Result is Invalid.

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Click Invalid in the Operation column to confirm the invalid mining results in Valid or To Be

Confirmed status, see the following figure.

1. Click Invalid in the upper menu bar to confirm the mining results in Valid or To Be Confirmed
status in batches, see the following figure.
12 Intelligent Mining of Potential Risk Rules

1. After the confirmation, the system prompts "Confirm Invalid Successfully", as shown in the
figure below.

## Release Result

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. On the page, click Publish to publish the mining results in "valid" status, see the following

figure.

## Sorting Mining Results

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
**NIOS Function Operation Guide**

Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Click the icon in the Cumulative Times column to sort the mining results in ascending or

descending order, see the following figure.

12.2.6 Filtering and Mining Results

Prerequisite
1. System Login
2. The user has the operation permission of intelligent mining of hidden danger rules.
Operation Path
Login System > Network Intelligence Automation > Risk Rule Intelligent Mining
Operation Steps
1. Click the icon in the "Validity" column to filter the mining results of "Validity" and "Release

Status", see the following figure.
12 Intelligent Mining of Potential Risk Rules

**Risk Identify**

Table of Contents

Network Risk............................................................................................................................ 134

By using the discovered hidden danger rules or manually created rules, you can create periodic
tasks or manual tasks to identify hidden danger based on alarm data and resource topology
information.
This chapter includes the following topics:
 Network Risk

## Network Risk

## Task Management

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. In Login System > Network Intelligence Automation > Risk Identify > Network Risk > Task

Management, the periodical task is displayed by default. You can search, suspend, or delete
the periodical task, or switch to a manual task, see the following figure.

## Creating A Periodic Task

Prerequisite
13 Risk Identify

1. System Login
2. The user has the permission to identify potential risks.
**Operation Path**
Login System > Network Intelligence Automation > Risk Identify
**Operation Steps**
1. On the Task Management page, click New, see the following figure.

2. After filling in the information, click New to create the periodical task successfully, as shown
in the figure below.

## Activating A Periodic Task

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. Select the tasks to be suspended, and click Activate on the menu bar to activate them in

batches, see the following figure.
**NIOS Function Operation Guide**

1. Click Activate in the Operation column to activate the current task, see the following figure.

## Suspending A Periodic Task

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. Select multiple activated tasks, and click Suspend to suspend the tasks in batches, see the

following figure.

1. Click Suspend in the Operation column to suspend the current task, see the following figure.
13 Risk Identify

## Deleting A Periodic Task

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. Select multiple suspended tasks, and click Delete to delete the tasks in batches, see the

following figure.

1. Click More > Delete in the Operation column to delete the current task, see the following
figure.

## Modifying A Periodic Task

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
**NIOS Function Operation Guide**

Operation Steps
1. Click Modify in the Operation column to modify the suspended task, see the following figure.

2. Click Confirm. The modification is successful, see the following figure.

## Task Execution Result

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. Click More > Excute Result in the Operation column to view and export the execution result,

see the following figure.
13 Risk Identify

## Task Execution History

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. In the Periodic Task window, select More > Excute History to view the historical records of

task execution, see the following figure.

## Task Details

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. In the Task Management window, click Task Name to view the task details, see the

following figure.
**NIOS Function Operation Guide**

## Executing A Manual Task

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. On the Task Management page, click Manual Task, see the following figure.

1. Select one or more rules, see the following figure.

1. Click Excute. The execution result is displayed, see the following figure.
13 Risk Identify

1. Click Reset to reset the current rule, see the following figure.
1. Click Export to export the execution result, see the following figure.

## Creating A Real Time Task

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. On the Real Time Task Management page, click New, see the following figure.
**NIOS Function Operation Guide**

2. After filling in the information, click New to create the real time real time task successfully, as
shown in the figure below.

## Activating A Real Time Task

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. Select the real time tasks to be suspended, and click Activate on the menu bar to activate

them in batches, see the following figure.
13 Risk Identify

1. Click Activate in the Operation column to activate the current real time task, alarm
derivations that satisfy the rules are generated and attached under the root alarm,see the
following figure.
**NIOS Function Operation Guide**

## Suspending A Real Time Task

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. Select multiple activated real time tasks, and click Suspend to suspend the tasks in batches,

see the following figure.

1. Click Suspend in the Operation column to suspend the current real time task, see the
following figure.

## Deleting A Real Time Task

Prerequisite
13 Risk Identify

1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. Select multiple suspended real time tasks, and click Delete to delete the tasks in batches,

see the following figure.

1. Click Delete in the Operation column to delete the current real time task, see the following
figure.

## Modifying A Real Time Task

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
**NIOS Function Operation Guide**

Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. Click Modify in the Operation column to modify the suspended real time task, see the

following figure.

2. Click Confirm. The modification is successful, see the following figure.

## Real Time Task Details

Prerequisite
1. System Login
13 Risk Identify

2. The user has the permission to identify potential risks.
**Operation Path**
Login System > Network Intelligence Automation > Risk Identify
**Operation Steps**
1. In the Real Time Task Management window, click Task Name to view the task details, see

the following figure.

## Rule Management

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. Click Login System > Network Intelligence Automation > Risk Identify > Network Risk > Rule

Management to create, delete, modify, and search rules, see the following figure.

## Creating A Rule

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
**NIOS Function Operation Guide**

Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. On the Rule Management page, click Create to create a rule, see the following figure.

2. Click New. The rule is created successfully, see the following figure.
# Risk Identify

## Modify A Rule

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. In the Operation column of the Rule Management page, click Modify, see the following

figure.

2. Click Modify to finish the modification, as shown in the figure below.
**NIOS Function Operation Guide**
13 Risk Identify

## Delete A Rule

Prerequisite
1. System Login
2. The user has the permission to identify potential risks.
Operation Path
Login System > Network Intelligence Automation > Risk Identify
Operation Steps
1. On the Rule Management page, select multiple rules and click Delete on the menu bar to

delete the rules in batches, see the following figure.

1. Click Delete in the Operation column to delete the current rule, see the following figure.

**Resource Errata**

Table of Contents

Equipment Room Resource Errors.......................................................................................... 152

Based on the existing information about NEs and devices in the site (equipment room), the
TFIDF algorithm is used to train the model and supplement the information about the NEs
without site (equipment room) information to improve the accuracy of root cause analysis and
the alarm decompression effect of the RCA.
This chapter includes the following topics:
 Equipment Room Resource Errors

## Equipment Room Resource Errors

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to correct resource errors.
Operation Path
Login System > Network Intelligence Automation > Asset Correction
Operation Steps
1. Select Login System > Network Intelligence Automation > Asset Correction > Equipment

Room Correction. The information about the equipment room resources is displayed. You
can add, delete, modify, import, and export resources, see the following figure.
# Resource Errata

## Creating A Resource

Prerequisite
1. System Login
2. The user has the permission to correct resource errors.
Operation Path
Login System > Network Intelligence Automation > Asset Correction
Operation Steps
1. On the equipment room resource correction page, click New, see the following figure.

1. After the information is improved, click New. The resource is created successfully, see the
following figure.
**NIOS Function Operation Guide**

## Intelligent Correction

Prerequisite
1. System Login
2. The user has the permission to correct resource errors.
Operation Path
Login System > Network Intelligence Automation > Asset Correction
Operation Steps
1. On the equipment room resource error correction page, select one or more resources that

are not corrected, and click AIC orrect to correct resources in batches, see the following
figure.

## Modify A Resource

Prerequisite
1. System Login
2. The user has the permission to correct resource errors.
Operation Path
Login System > Network Intelligence Automation > Asset Correction
Operation Steps
1. In the equipment room resource correction window, click Modify to modify the current

resource information, see the following figure.

1. After the modification, click Modify. The modification is successful, see the following figure.
14 Resource Errata

## Delete A Resource

Prerequisite
1. System Login
2. The user has the permission to correct resource errors.
Operation Path
Login System > Network Intelligence Automation > Asset Correction
Operation Steps
1. In the equipment room resource error correction window, select one or more resources, and

click Delete to delete the resources in batches, see the following figure.

1. Click Delete in the Operation column to delete the current resource, see the following figure.

## Importing Uncorrected Resources

Prerequisite
1. System Login
**NIOS Function Operation Guide**

2. The user has the permission to correct resource errors.
Operation Path
Login System > Network Intelligence Automation > Asset Correction
Operation Steps
1. Click Import to import the local resource file, see the following figure.

## Exporting Resources

Prerequisite
1. System Login
2. The user has the permission to correct resource errors.
Operation Path
Login System > Network Intelligence Automation > Asset Correction
Operation Steps
1. In the equipment room resource error correction window, click Export Resource to export

the current resource, see the following figure.

## Uploading Complete Resource Files

Prerequisite
1. System Login
2. The user has the permission to correct resource errors.
Operation Path
Login System > Network Intelligence Automation > Asset Correction
Operation Steps
1. Click Upload Complete Resource File to upload complete resource data for model training,

see the following figure.
14 Resource Errata

## Model Training

Prerequisite
1. System Login
2. The user has the permission to correct resource errors.
Operation Path
Login System > Network Intelligence Automation > Asset Correction
Operation Steps
1. In the equipment room resource error correction window, click model_train to train the error

correction model in accordance with the latest resource file, see the following figure.

## Filtering Resources

Prerequisite
1. System Login
2. The user has the permission to correct resource errors.
Operation Path
Login System > Network Intelligence Automation > Asset Correction
Operation Steps
1. In the equipment room resource error correction list, click the error correction status icon to

filter resources by status, see the following figure.

Link Restoration

Table of Contents

Interface Display.......................................................................................................................158
Creating A Periodic Task......................................................................................................... 159
Activating A Periodic Task....................................................................................................... 160
Suspending A Periodic Task....................................................................................................160
Modifying A Periodic Task....................................................................................................... 161
Periodic Task Execution Result............................................................................................... 162
Deleting A Periodic Task..........................................................................................................162
Filter Periodical Tasks.............................................................................................................. 163
Periodic Task Details............................................................................................................... 164
Executing A Manual Task........................................................................................................ 164

Massive alarm data is used to mine the influence relationship between transmission NEs and
data NEs, and form an end-to-end and cross-professional resource topology relationship in
accordance with the link resource data in a professional network, to support accurate location of
cross-domain faults and reduce repeated ticket allocation.
This chapter includes the following topics:
 Link restoration

## Interface Display

Prerequisite
1. System Login
2. You have the permission to restore links.
Operation Path
Login System > Network Intelligence Automation > Link Discovery
Operation Steps
1. Click Login System > Network Intelligence Automation > Link Discovery, and the tasks are

divided into periodic tasks and manual tasks. You can add, delete, modify, activate, and
suspend tasks, see the following figure.
15 Link Restoration

## Creating A Periodic Task

Prerequisite
1. System Login
2. You have the permission to restore links.
Operation Path
Login System > Network Intelligence Automation > Link Discovery
Operation Steps
1. Click Create to create a new task, see the following figure.

1. Improve the related information, see the following figure.

1. Click New. The periodic task is created successfully, see the following figure.
**NIOS Function Operation Guide**

## Activating A Periodic Task

Prerequisite
1. System Login
2. You have the permission to restore links.
Operation Path
Login System > Network Intelligence Automation > Link Discovery
Operation Steps
1. Click Activate to activate the current periodical task, see the following figure.

## Suspending A Periodic Task

Prerequisite
1. System Login
2. You have the permission to restore links.
Operation Path
Login System > Network Intelligence Automation > Link Discovery
Operation Steps
1. In the Operation column of the Link Restoration window, click Suspend to suspend the

current periodic task, see the following figure.
15 Link Restoration

## Modifying A Periodic Task

Prerequisite
1. System Login
2. You have the permission to restore links.
Operation Path
Login System > Network Intelligence Automation > Link Discovery
Operation Steps
1. On the Link Restore page, click Modify, see the following figure.

1. On the Modify page, complete the modification and click OK. The periodic task is modified
successfully, see the following figure.
**NIOS Function Operation Guide**

## Periodic Task Execution Result

Prerequisite
1. System Login
2. You have the permission to restore links.
Operation Path
Login System > Network Intelligence Automation > Link Discovery
Operation Steps
Click Results to view and export the task execution result, see the following figure.

## Deleting A Periodic Task

Prerequisite
1. System Login
2. You have the permission to restore links.
Operation Path
15 Link Restoration

Login System > Network Intelligence Automation > Link Discovery
**Operation Steps**
1. In the Link Restoration window, click Delete to select periodic tasks in batches, see the

following figure.

1. In the Operation column of the Link Restoration window, click Delete to delete the current
periodical task, see the following figure.

## Filter Periodical Tasks

Prerequisite
1. System Login
2. You have the permission to restore links.
Operation Path
Login System > Network Intelligence Automation > Link Discovery
Operation Steps
1. On the Link Restore page, click the Filter icon in the list to filter periodic tasks, see the

following figure.
**NIOS Function Operation Guide**

## Periodic Task Details

Prerequisite
1. System Login
2. You have the permission to restore links.
Operation Path
Login System > Network Intelligence Automation > Link Discovery
Operation Steps
1. On the Link Restoration page, click the task name to view the task details, see the following

figure.

## Executing A Manual Task

Prerequisite
1. System Login
15 Link Restoration

2. You have the permission to restore links.
Operation Path
Login System > Network Intelligence Automation > Link Discovery
Operation Steps
1. On the Link Restoration page, click Manual Task. The Manual Task page is displayed, see

the following figure.

1. After configuring the manual task information, click Excute. The task execution result is
displayed, see the following figure.
**NIOS Function Operation Guide**

1. Click Export to export the execution result of the manual task, see the following figure.
1. Click Reset to reset the manual task configuration, see the following figure.

**Fault Prediction**

Table of Contents

The Base Station is Out of Service......................................................................................... 167

The algorithm is used to learn historical alarms and resource topology data to predict network
alarms and indicator trends, so as to predict potential faults. The main scenarios are cell out-of-
service and gNodeB out-of-service.
This chapter includes the following topics:
 The base station is out of service.

16.1 The Base Station is Out of Service.

## Out-of-Service Forecast

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. Login System > Network Intelligence Automation > Alarm Fault Predict > Out-of-Service of

Base Station > Out-of-Service Prediction. The basic information about the out-of-service
prediction task is displayed. You can activate, suspend, or delete the task, see the following
figure.
**NIOS Function Operation Guide**

## Creating A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. Click New Task, see the following figure.

1. Set the task information, see the following figure.

1. Click New. The task is created successfully, see the following figure.

## Activate A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
16 Fault Prediction

Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the Out-of-Service Prediction tab, select a suspended periodic task, see the following

figure.

1. Click Activate to activate the task, see the following figure.

1. The activation is successful, see the following figure.

## Suspend A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
**NIOS Function Operation Guide**

Operation Steps
1. On the Out-of-Service Prediction tab, select an activated periodic task, see the following

figure.

1. Click Suspend to suspend the task, see the following figure.

1. Suspended successfully, see the following figure.

## Delete A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
16 Fault Prediction

1. On the Out-of-Service Prediction tab, select an inactive task, see the following figure.

1. Click Delete in the menu bar to delete tasks in batches, see the following figure.

1. The file is deleted successfully, see the following figure.
**NIOS Function Operation Guide**

## Task Details

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the Out-of-Service Prediction page, click Task Name. The task details are displayed, see

the following figure.

## Executing A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. Click Excute, see the following figure.
16 Fault Prediction

1. The command is executed successfully, see the following figure.

## Viewing Execution Records

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. In the Operation column of the Out-of-Service Prediction window, select More > Historical

Records. The execution records are displayed, see the following figure.

1. In the details list, click Details to view the details of each execution record, see the following
figure.
**NIOS Function Operation Guide**

1. On the Execution Details page, click Export to export the execution result details, see the
following figure.

## Viewing The Execution Result

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. In the Operation column of the Out-of-Service Prediction window, select More > Excution

Result. The execution result is displayed, see the following figure.
16 Fault Prediction

1. On the Execution Result page, click Export to export the execution result details, see the
following figure.

## Modifying A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. In the Operation column of the Out-of-Service Prediction window, select More > Modify to

modify the task, see the following figure.
**NIOS Function Operation Guide**

1. Modify the configuration information and click Confirm. The modification is successful, see
the following figure.

## Importing An Expansion File

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the out-of-service prediction page, click Import Extend File. The file is imported

successfully, see the following figure.
16 Fault Prediction

## Model Management

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. Login System > Network Intelligence Automation > Alarm Fault Predict > Out-of-Service of

Base Station > Model Management. The basic information about the out-of-service model of
the base station is displayed. You can create, import, export, and delete the model, see the
following figure.

## Creating A Model

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the model management page, click New Model, see the following figure.
**NIOS Function Operation Guide**

1. After the model information is improved, click New. The model is created successfully, see
the following figure.

## Importing A Model

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the Model Management page, click Import, see the following figure.

1. Select a local file, see the following figure.
16 Fault Prediction

## Exporting A Model

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the Model Management page, click Export, see the following figure.

1. The available model can be exported successfully, see the following figure.

## Delete A Model

Prerequisite
1. System Login
**NIOS Function Operation Guide**

2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the menu bar of the Model Management page, click Delete to delete the selected models

in batches, see the following figure.

1. In the Operation column of the Model Management page, click Delete to delete the current
model, see the following figure.

1. The deletion is successful, see the following figure.

## Training Model

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. In the Operation column of the Model Management page, click Train, see the following

figure.
16 Fault Prediction

1. After configuring the sample data period, click Confirm, see the following figure.
1. You can start training, see the following figure.

## Modify A Model

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. In the Operation column of the Model Management page, click Modify, see the following

figure.

1. After modifying the configuration information, click Confirm. The modification is successful,
see the following figure.
**NIOS Function Operation Guide**

## Model Details

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the Model Management page, click a model name. The details of the model are

displayed, see the following figure.
16 Fault Prediction

## Out-of-Service Probability Check

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. Click Login System > Network Intelligence Automation > Alarm Fault Predict > Out-of-

Service of Base Station > Out-of-Service Verification to synchronize the out-of-service
prediction task and display the basic information of the out-of-service prediction task. You
can export and view the out-of-service inspection results, see the following figure.

## Delete A Task

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
**NIOS Function Operation Guide**

Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the Out-of-Service Probability Check page, you can delete an out-of-service prediction

task that you do not care about. Select a task name and click Delete Task, see the following
figure.

1. Click Delete Task.

## Synchronize Forecast Data

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the Probability Check tab, click Sync Execution Data to synchronize the prediction task

and execution data, see the following figure.
16 Fault Prediction

## Drilling Down The Alarm List

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the Probability Check tab, click Alarms List to view the alarm information of the

prediction task, see the following figure.

## Execution History

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Login System > Network Intelligence Automation > Alarm Fault Predict
Operation Steps
1. On the Out-of-Service Probability Check page, select a task and click Excution History to

view the execution status of the forecast task, see the following figure.

1. Click Verify to synchronize the execution result again, see the following figure.
**NIOS Function Operation Guide**

1. Click Execution Result to check whether the associated site is out of service, see the
following figure.
