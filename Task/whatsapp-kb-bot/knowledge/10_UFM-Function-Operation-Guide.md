iMind

UFM Function Operation Guide

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

2 Alarm Management................................................................................................ 8

2.1 Alarm-Related Concepts......................................................................................................8
2.2 Current Alarms.................................................................................................................. 11

2.2.1 Alarm Monitoring...................................................................................................11
2.2.2 My Export..............................................................................................................25
2.2.3 Alarm Statistics..................................................................................................... 27
2.2.4 Scheduled Export................................................................................................. 28
2.2.5 Alarm Synchronization.......................................................................................... 37
2.2.6 Alarm Prompt........................................................................................................38
2.2.7 KeyAlarms Dashboard.......................................................................................... 39
2.2.8 Alarm Map(Discarded).......................................................................................... 42
2.2.9 Alarm Dashboard..................................................................................................47
2.2.10 Professional Network Alarm Statistics................................................................51
2.2.11 Site Outages Monitor Dashboard....................................................................... 56
2.2.12 Site Outages Monitor Dashboard （South Africa）.......................................... 60
2.2.13 Site Outages Trend Dashboard..........................................................................63
2.2.14 Alarm Trend Dashboard..................................................................................... 64
2.2.15 Provincial Site Disconnection............................................................................. 66
2.2.16 Sprint Dashboard................................................................................................67
2.2.17 Assign Trend Dashboard....................................................................................70
2.2.18 Disaster Time Dashboard...................................................................................80
2.3 Historical Alarms................................................................................................................82
2.3.1 Alarm Query..........................................................................................................82
2.3.2 My Export..............................................................................................................83
2.3.3 Alarm Statistics..................................................................................................... 84
2.3.4 Timed Statistics.................................................................................................... 93
2.3.5 Scheduled Export................................................................................................. 95
2.4 Notification......................................................................................................................... 98
2.4.1 Notification Monitoring.......................................................................................... 99
2.4.2 Notification Query................................................................................................. 99
2.4.3 My Export............................................................................................................100
2.4.4 Scheduled Export............................................................................................... 100
2.5 Alarm Settings................................................................................................................. 101

2.5.1 Rule Setting........................................................................................................ 101
2.5.2 Suppression Plan................................................................................................106
2.5.3 Handling Suggestion Setting.............................................................................. 108
2.5.4 Other Settings.....................................................................................................109
2.5.5 Engineering Alarm Management........................................................................ 123
2.5.6 Map Template(Discarded).................................................................................. 126
2.5.7 Site Break Map Configuration............................................................................ 128
2.5.8 Alarm Code Settings...........................................................................................132
2.6 Correlation Rule Management.........................................................................................135
2.6.1 Rule Operation....................................................................................................135
2.6.2 Rule Package Management............................................................................... 135
2.6.3 RCA Rule Energy Efficiency(Discarded)............................................................ 137

3 Intelligent RCA....................................................................................................138

3.1 Association Rule Mining.................................................................................................. 138
3.1.1 Topic Management............................................................................................. 138
3.1.2 Alarm Analysis.................................................................................................... 145

4 Topology Management...................................................................................... 148

4.1 Logical View.................................................................................................................... 148

5 UNIGIS（Alarm）................................................................................................ 150

5.1 Alarm Map(Group Fault Template)..................................................................................150
5.1.1 Interface Display................................................................................................. 150
5.1.2 Alarm-GIS Configuration.....................................................................................151
5.1.3 UNIGIS Configuration......................................................................................... 152
5.1.4 Map Configuration.............................................................................................. 153
5.1.5 Creating an Alarm Map Template...................................................................... 155
5.1.6 Site and area search.......................................................................................... 156
5.1.7 Site outage Statistics Table................................................................................157
5.1.8 Site Rendering and Details.................................................................................158

5.2 Alarm Map(Basic Template)............................................................................................ 159
5.2.1 Interface Display................................................................................................. 159
5.2.2 Alarm-GIS Configuration.....................................................................................160
5.2.3 UNIGIS Configuration......................................................................................... 161
5.2.4 Map Configuration.............................................................................................. 162
5.2.5 Creating an Alarm Map Template...................................................................... 164
5.2.6 Site and area search.......................................................................................... 165
5.2.7 Site Rendering and Details.................................................................................166

6 Daily Monitoring Dashboard（Alarm）............................................................. 168

6.1 Alarm Status Opening Alarm(Performance).................................................................... 168
6.1.1 Interface Display................................................................................................. 168
6.1.2 Opening Performance Alarm Group Configuration.............................................169
6.1.3 Daily Monitoring Dashboard（Alarm Status Opening Alarm(Performance)）....172

**System User**

Table of Contents

Creating A User............................................................................................................................1

Use the admin account to create an account for the UFM O&M personnel. This account has the
operation permission only for the UFM module.
This chapter includes the following topics:
 Creating a User

## Creating A User

Prerequisite
1. The system is deployed successfully.
2. You can log in to the workbench properly.
Operation Path
Workspace > System Configuration > Security Management > Role Management
Operation Steps
1. Log in to the workbench as the administrator. Select System Configuration > Security

Management > Role Management. The User Role Management page is displayed, see the
following figure.
**UFM Function Operation Guide**

1. Click Operation Set > Create Operation Set to create the operation set required by the UFM
administrator, see the following figure.

1. Select the operation set permission corresponding to UFM, see the following figure.
1 System User

1. Click Role > Create Role to create the role required by the UFM administrator, see the
following figure.
**UFM Function Operation Guide**

1. Select No for Area Security Administrator, and click OK, see the following figure.
1. Select resources as required, and select "UFM" created in the above step for the operation

set, see the following figure.
1 System User

Note: Select a resource object on the left, and set the operation set on the right to change the
permissions of the resource object. You can press and hold the ctrl key to continuously select
or invert resource objects, or press and hold the shift key to select or invert resource objects at
the same layer in batches.
1. Click Create to create a UFM role, see the following figure.

1. Click User Management > +Create User to create the UFM administrator.
**UFM Function Operation Guide**

1. Enter the user information, see the following figure.

Parameter                            Value
Account Rule                         Selecting the Default Rule
Maximum number of concurrent logins  Depending on the actual situation
User group                           Depending on the actual situation

1. Select the created UFM role, see the following figure.
1 System User

1. Click Create. The UFM user is created.

# Alarm Management

Table of Contents

Alarm-Related Concepts.............................................................................................................. 8
Current Alarms........................................................................................................................... 11
Historical Alarms.........................................................................................................................82
Notification.................................................................................................................................. 98
Alarm Settings.......................................................................................................................... 101
Correlation Rule Management................................................................................................. 135
This chapter includes the following topics:
 Alarm-Related Concepts
 Current alarms
 Historical alarms
 Notification
 Alarm Settings
 Correlation Rule Management

## Alarm-Related Concepts

Alarm
Alarms report the exceptions or faults that occur during the operation of the managed NEs
and the EMS, prompting users to handle the alarms. The alarm information usually lasts for a
period of time. When the fault or fault disappears, the alarm information disappears and the
corresponding alarm clearing message is returned.
Notification
A notification prompts some operations or exceptions during the operation of the managed NE
and the EMS, so that the O&M personnel can learn about the operational status of each module
in a timely manner.
Difference Between Alarms and Notifications
# The alarm is usually caused by an error or fault and must be handled. Otherwise, services
may be affected. You can acknowledge and clear alarms.
# The event is usually some prompt information, which does not necessarily affect services. O&
M personnel cannot confirm or clear notifications.
2 Alarm Management

Alarm Level
In accordance with the impact on the system, alarms are divided into four levels: Critical, major,
minor, and warning. For details, refer to.

Alarm Level  Level Description
Critical
Major        Indicates that normal services are seriously affected
Minor        and need to be repaired immediately.

Warning      Indicates that the system has signs of affecting
normal services and requires emergency repair.

Indicates that the system has factors that do not
affect normal services, but corrective measures
should be taken to avoid more serious faults.

Indicates that the system has potential problems or
problems that will affect normal services. Measures
should be taken to diagnose and correct the system
to avoid a more serious fault that affects normal
services.

The default alarm level of each alarm is set during system initialization. You can also adjust
the alarm level in accordance with different service requirements and actual environments. For
details, refer to the Other Settings module.
Alarm Status
Alarms are in the following states:
# Unconfirmed and uncleared
# Confirmed but not cleared
# Unconfirmed and cleared
# Confirmed and cleared
Unacknowledged and uncleared alarms and acknowledged and uncleared alarms are called
current alarms. Unacknowledged and cleared alarms and acknowledged and cleared alarms
are called historical alarms.The following figure shows the alarm status transition relationship.
**UFM Function Operation Guide**

# Acknowledge/unacknowledge the alarm
Acknowledge the alarm, indicating that the O&M personnel are handling the alarm. After an
alarm is acknowledged, it changes from unacknowledged status to acknowledged status. You
can also unacknowledge an acknowledged alarm to an unacknowledged alarm.
# Alarm clearing/clearing
After the fault is cleared, the alarm status changes from uncleared to cleared. This alarm
becomes a historical alarm and is recorded in the alarm database.You can also manually
change the uncleared status of alarms to cleared status. If the fault persists, the alarm becomes
an active alarm after the alarm is synchronized.
Root alarm/derivative alarm
The alarms directly triggered by faults or abnormal events are called root alarms. Other alarms
derived from root alarms are called derived alarms. Root alarms and derivative alarms are
related.
2 Alarm Management

## Current Alarms

This chapter includes the following topics:
 Alarm monitoring
 My Export
 Alarm statistics
 Scheduled Export
 Alarm Synchronization
 Key Alarm Monitoring
 Alarm Map(Discarded)
 Alarm Dashboard
 Professional Network Alarm Statistics
 Site Outages Monitor Dashboard
 Site Outages Monitor Dashboard （South Africa）
 Site Outages Trend Dashboard
 Alarm Trend Dashboard
 Provincial Site Disconnection
 Sprint Dashboard
 Disaster Time Dashboard
 Assign Trend Dashboard

## Alarm Monitoring

Alarm monitoring is used to monitor current alarms. Active alarm monitoring displays active
alarms in the system in a centralized manner.An active alarm refers to an alarm that is being
raised and not cleared in the system.The following describes how to monitor alarm information
in a similar way.

## Interface Display

Prerequisite
1. System Login
2. The user has the alarm monitoring permission.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Active

Alarm > Alarm Monitor. The current alarms are displayed in the alarm monitoring area, see
the following figure.
**UFM Function Operation Guide**

## Alarm Details

Prerequisite
1. System Login
2. The user has the alarm monitoring permission.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the Current Monitor page, click... in the Operation column. ]Click Details or click the

alarm code to view the alarm details and handling suggestions, Detailed Information
Attribute Group Display and Lifecycle Management，see the following figure.
2 Alarm Management
**UFM Function Operation Guide**

## Querying Alarms

If there are many alarms, you can filter them in accordance with the self-defined conditions.If no
condition is selected, all alarms are queried.
Prerequisite
1. System Login
2. The user has the alarm monitoring permission.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the Alarm Monitor page, click Condition Query, see the following figure.

1. As shown in the following figure, you can select query conditions for combined query.

2. Fields marked with the "Exclude" indicator support "NOT" logic queries.
2 Alarm Management

## Multi-window Monitoring

You can save common query conditions to a template. A public template can be used by all
users. A private template can only be used by the currently created template.
Prerequisite
1. System Login
2. The user has the alarm monitoring permission.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the Alarm Monitor page, click Condition Query, see the following figure.
**UFM Function Operation Guide**

1. After editing the query conditions, click Save AS, see the following figure.
1. After editing the template information, click OK, see the following figure.

1. Click OK.
2 Alarm Management

1. When using a condition template to open the tabs of multiple query results, you can click
the Multi-window Monitoring button in the upper right corner to monitor alarms in multiple
windows, see the following figure.
**UFM Function Operation Guide**

1. Click Layout Settings in the upper right corner to adjust the layout style, see the following
figure.
# Alarm Management

## Confirm/Unconfirm

Acknowledging/Unacknowledging Alarms
You can manually acknowledge or unacknowledge alarms.Acknowledging an alarm means
changing the status of an alarm from Unacknowledged to Acknowledged, indicating that the O&
M personnel have learned about the alarm and begin to handle it.You can also unacknowledge
an acknowledged alarm to reset it to unacknowledged status.
O&M personnel can also set automatic alarm acknowledgment rules to automatically set
common alarms to acknowledged status, reducing the workload of O&M personnel and
facilitating the generation of key alarms or new alarms.
Prerequisite
1. System Login
2. The user has the alarm monitoring permission.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the Alarm Monitor page, select one or more alarms, see the following figure.

1. Click Ack in the menu bar to acknowledge alarms in batches, see the following figure.
**UFM Function Operation Guide**

1. Enter the details of the acknowledged alarm. The acknowledgement status of the
alarm changes to Acknowledged. The system records the acknowledgement time and
acknowledger in the alarm data, see the following figure.
2 Alarm Management

1. The operations for unacknowledging alarms are similar.

## Clearing Alarms

In most cases, after a fault is removed, related alarms are automatically cleared and become
historical alarms.If an alarm cannot be automatically cleared or does not exist, you can
manually clear the alarm.
Prerequisite
1. System Login
2. The user has the alarm monitoring permission.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1.

On the Alarm Monitor page, select the alarms to be cleared, see the following figure.

1. Click Clear on the menu bar to clear the alarm, see the following figure.
**UFM Function Operation Guide**

1. After an alarm is manually cleared, it disappears from the current alarm list, automatically
changes to a historical alarm, and automatically changes to Acknowledged status.

## Exporting Alarms

Prerequisite
1. System Login
2. The user has the alarm monitoring permission.
2 Alarm Management

**Operation Path**
Workspace > Maintenance Surveillance > Alarm Management
**Operation Steps**
1. On the Alarm Monitor page, select Export > Export All, see the following figure.

1. When more than 5 W alarms are exported, the exported results are displayed here, and the
contents are kept for 24 hours only, see the following figure.

## Alarm Dispatch

Prerequisite
1. System Login
2. The user has the alarm monitoring permission.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the Alarm Monitor page, select one or more alarms, see the following figure.
**UFM Function Operation Guide**

1. Select More > Marge Assign from the menu bar. The task is dispatched successfully, see
the following figure.

1. Select More > Additional Assign from the menu bar to assign alarms to a TT, see the
following figure.
2 Alarm Management

1. Click... in the Operation column.> Assign: Click this button to dispatch the current
instruction.

## My Export

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
**UFM Function Operation Guide**

Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Active Alarm > My Export. When more than 5 W alarms are exported, the exported results
are displayed here, and the contents are kept for 24 hours only, see the following figure.

1. Export progress: (You need to manually refresh the page to obtain the latest progress.)

2.2.2.2 Download and Export

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the My Export page, click Download. The download command is successfully delivered,

see the following figure.
2 Alarm Management

## Delete Export

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the My Export page, click Delete. The download command is successfully delivered, see

the following figure.

## Alarm Statistics

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Active

Alarm > Statistics, and monitor the NE and NE type alarms in graphic mode, see the
following figure.
**UFM Function Operation Guide**

1. On the Alarm Statistics page, collect alarm statistics by selected NE and NE type. You can
view statistical results in graphs or tables, manually adjust the refresh frequency, or export
the results as a picture, see the following figure.

## Scheduled Export

The scheduled alarm export task can export the current alarms of the system as a file at 00:
00 every day and save the file on the server or a third-party FTP/SFTP server. You can set
the filtering conditions for outputting alarms, for example, alarms at a specified location, at
a specified level, and within a specified period. After a task is created, the task is executed
periodically to output the alarms that meet the conditions to a file and upload the file to the
default FTP. If the FTP is configured, the file is also uploaded to the FTP. You can create a
scheduled task to export data periodically. A maximum of 100000 alarms can be exported at
a time. To avoid too heavy system load due to the concurrent execution of a large number
of tasks at the same time, the actual execution time is not strictly in accordance with the set
period. A scheduled export task can be activated, suspended, deleted, and modified. You can
also view export details and download export results.

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
2 Alarm Management

Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
Log in to the workbench, and select Maintenance Surveillance > Alarm Management > Active
Alarm > Scheduled Export, see the following figure. You can add, delete, or modify a scheduled
task.

## Creating A Task

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click +New, see the following figure.
**UFM Function Operation Guide**

1. Edit New Information

Parameter Descriptions for a Scheduled Output Task

Parameter Name            Parameter Descriptions
Name                      Name of the scheduled export task.
Task Type                 By default, the system outputs current alarms.
Description               Brief description of the scheduled task.
Activate                  Initial status of the scheduled export task. If it is
activated, the task is valid.
Export Format             Select a file format for the task. The following formats
are supported: *.csv *.txt *.xml *.html
2 Alarm Management

1. To export the files exported from the scheduled task to a third-party FTP at the same time,
enable the third-party FTP, and enter the parameters of the peer FTP server, see the
following figure.

Third-Party FTP Parameter Descriptions

Parameter Name                          Parameter Descriptions
Protocol                                Supports the FTP or SFTP protocol.
IP                                      IP address of the peer FTP server.
File Path                               FTP path for storing output files.
Port                                    Port number of the peer FTP server.
Username                                Username for logging in to the peer FTP server. The
user must have the write permission.
Password                                Password of the peer FTP server.
Test Connection                         After configuring FTP server parameters, click
this button to test whether the FTP server can be
connected properly.

To export current alarms in accordance with the specified conditions, you can set the filtering
conditions in the Resource, Alarm Code, Time Condition, Other Conditions, and More
Conditions areas. For a description of the parameters, refer to "1.2.1.Alarm Monitoring If no
alarm condition is set, the system outputs all current alarms by default.
1. Click New. The new scheduled export task is displayed on the Scheduled Export page, see

the following figure.
**UFM Function Operation Guide**

1. When the task execution time arrives, the system automatically exports alarms in
accordance with the conditions set in the task. Click Log to list the task execution status or
download the file to the local client, see the following figure.

## Suspend A Task

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the Scheduled Export tab, select a task, see the following figure.

1. Click Suspend in the menu bar to suspend tasks in batches, see the following figure.
2 Alarm Management

1. Click Suspend in the Operation column to suspend the current task, see the following figure.

## Activate A Task

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the Scheduled Export tab, select a task, see the following figure.

1. Click Activate in the menu bar to activate scheduled tasks in batches, see the following
figure.
**UFM Function Operation Guide**

1. Click Activate in the Operation column to activate the current task.

## Modifying A Task

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
2 Alarm Management

Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the Scheduled Export page, click Modify in the Operation column, see the following

figure.

1. Edit the modification information, see the following figure.

1. Click OK. The task is modified successfully, see the following figure.
**UFM Function Operation Guide**

## Delete A Task

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the Scheduled Export tab, select a task, see the following figure.

1. Click Delete in the menu bar to delete tasks in batches, see the following figure.
2 Alarm Management

1. Click Delete in the Operation column to delete the current task, see the following figure.

## Alarm Synchronization

The alarm information may be different from the actual alarm information of the NE due to
network interruption or NE cutover. You can manually synchronize the alarms of the selected
NEs to the server.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Active

Alarm > Synchronization. The Alarm Synchronization page is displayed, see the following
figure.
**UFM Function Operation Guide**

1. Click Synchronize All MEs or select the NE to be synchronized and click Synchronize, see
the following figure.

## Alarm Prompt

Active alarms are monitored in descending order of alarm occurrence time. Therefore, in
scenarios where there are a large number of alarms, the alarms that you focus on may be
pushed to the next page.The alarm prompt function provides customized policies for users to
customize the alarms to be focused on. After customization, if the alarm is generated, it will be
displayed on the active alarm monitoring page and the alarm prompt page.
Prerequisite
2 Alarm Management

1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. To customize an alarm prompt policy, select Workbench > Maintenance Surveillance >

Alarm Management > Alarm Settings > Others > Prompt Settings, and configure key alarms.
For details, refer to Other Settings.

1. Select Alarm Management > Active Alarm > Alarm Prompt. The Alarm Prompt page is
displayed. You can acknowledge, unacknowledge, and clear the alarm, see the following
figure.

## KeyAlarms Dashboard

Key alarm monitoring In scenarios where there are a large number of alarms, the current key
alarm information may be pushed to the next page, which is inconvenient for users to view.
The key alarm monitoring function provides customized policies for users to customize the
alarm codes corresponding to alarms. After the customization, if the alarm is generated, the
number of alarms will be refreshed in real time on the key alarm monitoring page. Click the
corresponding monitoring task to view the monitored alarms.
**UFM Function Operation Guide**

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. To customize the alarm prompt policy, log in to the workbench, select Maintenance

Surveillance > Alarm Management > Active Alarm > KeyAlarms Dashboard, and configure
the following key alarms:

## Timed Refresh

Select Alarm Management > Active Alarm > Key Alarms Monitor. The Key Alarms Monitor
page is displayed, see the following figure. You can enable or disable alarm monitoring at the
scheduled time.

## Add

Select Alarm Management > Active Alarm > Key Alarms Monitor > Add. On the displayed Key
Alarm Monitor page, add an alarm monitoring task. Set the alarm code name, alarm code, and
public/private type, see the following figure.
2 Alarm Management

## Edit

Select Alarm Management > Active Alarm > Key Alarms Monitor > Edit. The Edit page is
displayed. On the Edit page, you can delete, edit, or cancel an alarm monitoring task, see the
following figure.

## Alarm Monitoring Drill-down

Select Alarm Management > Active Alarm > Key Alarms Monitor. The Key Alarms Monitor page
is displayed. Click the corresponding monitoring task. The monitored alarms are displayed, see
the following figure.
**UFM Function Operation Guide**

## Alarm Map(Discarded)

Based on the wireless gisweb→zgis component, the alarm map filters out the sites with alarms,
and counts the total number of alarms filtered out under the current conditions and the number
of alarms at each level on the gis page. Click a site. A message box is displayed, showing the
alarm details of the site.

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Active Alarm > Alarm GIS. Related alarms are displayed on the map, see the following
figure.

## Return Query

Prerequisite
1. System Login
2 Alarm Management

2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the alarm map page, click the Return to Query Template icon. The map template

management page is displayed, see the following figure.

1. Click Back to Center. The center point of the template is displayed on the map, see the
following figure.

2.2.8.3 Site and Area Search

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
**UFM Function Operation Guide**

1. On the alarm map page, click the Site Search or Area Search icon to search for the alarm
information of the corresponding site or area, see the following figure.

## Reset

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the alarm map page, click reset to reset the conditions, see the following figure.

## Alarm Details

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
2 Alarm Management

Operation Steps
1. The alarm statistics of the sites set in the alarm template are displayed on the right.

2.2.8.6 Site Details and Related Alarms

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the alarm map page, click Related Sites. The site details are displayed in the left pane.

Click Site ID. The related alarm details are displayed, see the following figure.
**UFM Function Operation Guide**

## Map Configuration

The map can be used only after the related map parameters are configured in the configuration
center.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select System Configuration > Configuration Center > Map Project.

1. Select Web GIS > System Parameter Configuration, see the following figure.
2 Alarm Management

Options:

## Alarm Dashboard

The dashboard provides the function of collecting statistics on site disconnection alarms by
dimension (NE, alarm level, and dispatch).

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Active Alarm > Alarm Dashboard. The Alarm Dashboard area is displayed, see the following
figure.
**UFM Function Operation Guide**

1. The panel collects statistics of alarms by dimension.

## Configuring Display Parameters

You can configure the title of the large screen, scheduled refresh time, number of statistical
panels, and statistical type in the configuration center.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Select Configuration Center > System Configuration > Dashboard Title Config, see

the following figure.
2 Alarm Management

1. Configure the large screen title:

1. The following example shows how to configure the scheduled refresh time:
**UFM Function Operation Guide**

1. Configure the number of statistical panels:

1. Configure the statistics type:
2 Alarm Management

## Professional Network Alarm Statistics

The dashboard provides the alarm statistics function by dimension (alarm cause and
site).

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Step
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Active Alarm > [Professional Network Alarm Statistics]. The active alarm is displayed in the
dashboard area, see the following figure.
**UFM Function Operation Guide**
2 Alarm Management

1. The panel collects statistics of alarms by professional network (site and alarm cause).

## Configuring Display Parameters

You can configure the title of the large screen, scheduled refresh time, number of statistical
panels, and statistical type in the configuration center.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Select Configuration Center > System Configuration > Dashboard Title Config, see

the following figure.
**UFM Function Operation Guide**

1. Configure the large screen title:
2 Alarm Management

1. The following example shows how to configure the scheduled refresh time:
1. Configure the number of statistical panels:
**UFM Function Operation Guide**

## Site Outages Monitor Dashboard

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Step
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Active Alarm > [Site Outages Monitor Dashboard].The dashboard area is displayed, see the
following figure.

1. The site disconnection dashboard provides the statistics and histogram display of the
number of site disconnection alarms of 2G, 3G, and 4G sites and cells of different vendors (
such as ZTE and NOKIA) in each area, see the following figure.
2 Alarm Management

1. The details of the alarm are displayed on the dashboard, see the following figure.

## Configuring Display Parameters

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Select Configuration Center > System Configuration > Site Down Dashboard Configuration,

see the following figure.
**UFM Function Operation Guide**

1. The configuration item corresponds to the kanban module, see the following figure.

## SiteDown Config

The site disconnection map configuration is the preset condition of the area-level site
disconnection map. The area-level site disconnection map displays the number of site
disconnection alarms in each area based on the site disconnection map configuration template.
For details, refer to 2.4.8 Site Break Map Configuration.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Select Configuration Center > System Configuration > SiteDown Config,Add, delete, and

edit the alarm, see the following figure.
2 Alarm Management

1. Log in to the system, and select O&M Monitoring > Alarm
Management > Alarm Settings > Broken Site Map Configuration.
The GeoJSON map and Zgis map are displayed, see the following

figure.
**UFM Function Operation Guide**

## Site Outages Monitor Dashboard （South Africa）

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Step
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Active Alarm > [Site Outages Monitor Dashboard].The dashboard area is displayed, see the
following figure.
2. The site disconnection dashboard provides the statistics and histogram display of the
number of site disconnection alarms of 2G, 3G, and 4G sites and cells of different vendors (
such as ZTE and NOKIA) in each area, see the following figure.
2 Alarm Management

1. The details of the alarm are displayed on the dashboard, see the following figure.

## Configuring Display Parameters

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Select Configuration Center > System Configuration > Site Down Dashboard Configuration,

see the following figure.
**UFM Function Operation Guide**

1. The configuration item corresponds to the kanban module, see the following figure.

## SiteDown Config

The site disconnection map configuration is the preset condition of the area-level site
disconnection map. The area-level site disconnection map displays the number of site
disconnection alarms in each area based on the site disconnection map configuration template.
For details, refer to 2.4.8 Site Break Map Configuration.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Select Configuration Center > System Configuration > SiteDown Config,Add, delete, and

edit the alarm, see the following figure.
2 Alarm Management

1. Log in to the system, and select O&M Monitoring > Alarm Management > Alarm Settings >
Broken Site Map Configuration. The GeoJSON map and Zgis map are displayed, see the
following figure.

## Site Outages Trend Dashboard

The number of broken sites within 24 hours is displayed by hour.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
**UFM Function Operation Guide**

Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Active

Alarm > Site Outages Trend Dashboard, see the following figure.

## Alarm Trend Dashboard

On the left side of the page, three line charts are displayed on the hour scales of Today (current
time of the 0~), Yesterday (0~24 hours), and Same Day (0 ~ 24 hours) of the last week, and
two line charts are displayed on the right side of the page.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Active

Alarm > Alarm Trend Dashboard, see the following figure.
2 Alarm Management

2. Select EMS from the drop-down list. You can select the probe to be monitored.
3. Hover the cursor over the scale point of the line chart to display the corresponding value.
**UFM Function Operation Guide**

## Provincial Site Disconnection

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Active Alarmashboard province. The current site disconnection alarm is displayed in the
dashboard area, see the following figure.

1. The site disconnection dashboard collects statistics on the number of 2G, 3G, and 4G site
disconnection alarms of sites and cells in each province, see the following figure.
2 Alarm Management

1. The details of the alarm are displayed on the dashboard, see the following figure.

## Sprint Dashboard

Select a radio site type to monitor and collect statistics on sites by area.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Active

Alarm > Sprint Dashboard, see the following figure.
**UFM Function Operation Guide**
2 Alarm Management

2. Select the radio site type RAN Site type from the drop-down list.

3. The statistical values of the site attribute fields (VIPSites, MailsFail, SiteDown, UmbDown,
TowcoDown, ClassADown, PlatinumDown, AGDown, StrategicDown, VIPSiteDown,
AGRun, BATT ClassA (4hrs), BATT ClassA, and MF ClassA >2hrs) can be drilled down to
display the alarm statistics details.
**UFM Function Operation Guide**

## Assign Trend Dashboard

This function collects and displays the trend of the number of dispatched alarms based on
groups. By default, 26 groups are preset, and the statistics can be displayed by time range. By
default, 24 hours are displayed.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Active

Alarm > Assign Trend Dashboard, see the following figure.
2 Alarm Management

2. Select a statistical time range from the drop-down list. Options: 3 hours, 6 hours, 12 hours,
and 24 hours.

3. Hover the cursor over the scale point of the line chart to display the corresponding value.
**UFM Function Operation Guide**

4. Select, preview, and save the groups to be displayed from the drop-down list, and drag them
to change the group sequence.
Deselect All

**Select All**
2 Alarm Management

**Preview**
**UFM Function Operation Guide**

Save
2 Alarm Management

Drag to change the group display order
5. This module adds, modifies, deletes, and queries alarm code groups.
**UFM Function Operation Guide**

Adding an Alarm Code Group
2 Alarm Management

Modifying an Alarm Code Group
**UFM Function Operation Guide**

Delete an alarm code group
2 Alarm Management

Delete alarm code groups in batches

Querying Alarm Code Groups
**UFM Function Operation Guide**

## Disaster Time Dashboard

Monitor and statistically analyze site conditions and Mains Fail and Battery Disconnected Pre
alarm statuses according to MACRO wireless site types within Circle.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Active

Alarm > Disaster Time Dashboard, see the following figure.
2 Alarm Management
**UFM Function Operation Guide**

## Historical Alarms

This chapter includes the following topics:
 Alarm Query
 Alarm statistics
 Timed statistics
 Scheduled Export

## Alarm Query

Historical alarms are used to display the alarms that have occurred. The system retains the
historical alarms that have occurred during operation.

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > History

Alarm > Alarm Query. Historical alarms are displayed in the alarm monitoring area, see the
following figure.
2 Alarm Management

1. The operations that can be performed on historical alarms are similar to those on current
alarms. You can query historical alarms in accordance with the query conditions, set the
resources, alarm codes, and time, and then export the alarms. For details, refer to 1.2.1
Alarm Monitoring.

## My Export

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select [Maintenance Surveillance] > [Alarm Management] > [

History Alarm] > [My Export], which is the same as the current alarm export function. It is
recommended that you refer to "My Export" on the 1.2.2.
**UFM Function Operation Guide**

## Alarm Statistics

## Interface Display

Supports statistics of historical alarms by dimension.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

History Alarm > Statistics. The statistics of unreachable dimensions are displayed. You can
create and modify the dimension templates, see the following figure.
2 Alarm Management

## Basic Statistics

The supports Top N statistics of historical alarms by dimension. If the default query conditions
cannot meet requirements, you can perform statistics through customized conditions.
Basic statistics refers to a simple summary of the number of times that an alarm is raised based
on a statistical object. You can create or modify statistical conditions, and manually refresh or
export alarm statistical results.

## Interface Display
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the Alarm Statistics page, click Basic Statistics. The basic statistics are displayed, see
the following figure.

## Default

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click Set as Default. The current statistical conditions are used as the default statistical

conditions, see the following figure. The default statistical condition is alarm code Top20.
**UFM Function Operation Guide**

## Statistical Condition

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click Statistics Conditions to switch to the existing statistical condition template, see the

following figure.
2 Alarm Management

1. Click the Delete icon to delete the customized statistics template, see the following figure.
**UFM Function Operation Guide**

## Save Template
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click the Save icon in the upper right corner to save the current template as a statistics
template, see the following figure.
2 Alarm Management

1. Click Statistics Conditions to view and select the saved template, see the following figure.

## Creating A Template
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click +New to create and edit a basic statistics template, see the following figure.

1. Set the parameters, and click New, see the following figure.
**UFM Function Operation Guide**

## Modify A Template
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click Modify to modify the current statistics template, see the following figure.

## Export All
Prerequisite
1. System Login
2 Alarm Management

2. The user has the permission to manage alarms.
**Operation Path**
Workspace > Maintenance Surveillance > Alarm Management
**Operation Steps**
1. Click Export All to export the statistical data of the current template, see the following figure.

## Graphic Switching

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click Table, Donut, or Bar to display the statistical results in a graph, see the following

figure.
**UFM Function Operation Guide**

## Busy-hour Statistics

You can specify a busy-hour period during which historical alarms are collected by frequency
or alarm duration. Busy-hour statistics show the time periods during which alarms occur in a
centralized manner. You can clearly see the occurrence of alarms in a centralized manner. You
can use the alarm frequency or alarm duration to collect statistics. Similar to basic statistics,
you can display statistical results in a table, ring chart, or histogram. For the functions such as
handover statistics conditions and default display, refer to 1.3.3.2 Basic Statistics.

## Major Alarm Code Statistics

You can collect statistics on specified alarm codes and occurrence frequency in a specified time
period.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. On the alarm statistics page, click Important Alarm-Code Statistics to create a query, see

the following figure.

## Fault/Fault Rate Statistics

You can collect the number of times that alarms meet the conditions and the fault rate of each
month in accordance with the location and alarm code.
2 Alarm Management

**Prerequisite**
1. System Login
2. The user has the permission to manage alarms.
**Operation Path**
Workspace > Maintenance Surveillance > Alarm Management
**Operation Steps**
1. On the alarm statistics page, click Fault/Fault Rates Statistics to create a query, see the

following figure.

## Timed Statistics

A scheduled statistics task can periodically execute the alarm statistics template specified by
O&M personnel, and save the alarm statistics results in a file.

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

History Alarm > Scheduled Statistics to create, suspend, or delete a scheduled statistics
task, see the following figure.
**UFM Function Operation Guide**

## Creating A Task

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click +New to create a task, see the following figure.

1. Enter the information of the new task, and click New, see the following figure.

1. To interconnect with a third-party FTP, click FTP, see the following figure.
2 Alarm Management

The parameters are defined as follows:  Parameter Descriptions

Parameter Name                         Name of the scheduled statistics task.
**Name**
Task Time                              Start time and end time of the scheduled statistics
Template Name                          task.
**Parameter Name**
Activate                               Statistical template for the scheduled execution of the
Enabling Third-Party FTP               task. You can customize a statistics template.

Execution Plan                         Parameter Descriptions

Initial status of the scheduled statistics task. If it is
activated, the task is valid.

If the FTP/SFTP server is enabled, you need to
configure the server information, such as the protocol
type, IP address, file path, port, username, and
password.

Set the execution period of the scheduled statistics
task.

## Scheduled Export

The scheduled historical alarm export task can export historical alarms of the system as a file
at 00: 00 every day and save the file on the server or a third-party FTP server. You can set the
filtering conditions for outputting alarms, for example, the alarms of the specified NE, level, and
period.
**UFM Function Operation Guide**

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

History Alarm > Scheduled Export to create, suspend, or delete a scheduled export task,
see the following figure.

## Creating A Task

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click +New, see the following figure.
2 Alarm Management

1. Set the parameters as follows:

Parameter Name                     Parameter Descriptions
Name
Task Type                          Name of the scheduled output task.
Description
Activate                           By default, historical alarms are output.

Export Format                      Brief description of the scheduled task.

Initial status of the scheduled output task. If it is
activated, the task is valid.

Select a file format for the task. The following formats
are supported:
*.csv
*.txt
*.xml
*.html

1. To export the files exported by the scheduled task to a third-party FTP at the same time,
enable the third-party FTP, and enter the parameters of the peer FTP server, see the
following figure.
**UFM Function Operation Guide**

Parameter Name                                           Parameter Descriptions
Protocol                                                 Supports the FTP or SFTP protocol.
IP                                                       IP address of the peer FTP server.
File Path                                                FTP path for storing output files.
Port                                                     Port number of the peer FTP server.
Username                                                 Username for logging in to the peer FTP server. The
user must have the write permission.
Password                                                 Password of the peer FTP server.
Test Connection                                          After configuring FTP server parameters, click
this button to test whether the FTP server can be
connected properly.

## Notification

This chapter includes the following topics:
 # Notification Monitoring
 # Notification Query
 My Export
 # scheduled export
2 Alarm Management

O&M personnel can query system notifications in accordance with existing query conditions or
customized query conditions.

## Notification Monitoring

When the messagetype value in the alarm information received by the system is 100, the
system regards this type of alarm as a notification, and does not report the alarm.
The information is displayed in Notification Monitor.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Notification > Notification Monitor. Clear, refresh, and export the monitoring alarms, see the
following figure.

## Notification Query

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
Log in to the workbench, and select Maintenance Surveillance > Alarm Management >
Notification > Notification Query. You can query notifications in combination, see the following
figure.
**UFM Function Operation Guide**

## My Export

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
Log in to the workbench, and select Maintenance Surveillance > Alarm Management >
Notification > My Export to export notification data. For details, refer to 1.2.2 My Export.

## Scheduled Export

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
Log in to the workbench, and select Maintenance Surveillance > Alarm Management >
Notification > Scheduled Export to export notification data at the scheduled time. For details,
refer to 1.2.4 Scheduled Export.
2 Alarm Management

## Alarm Settings

This chapter includes the following topics:
 # Rule Settings
 # suppression plan
 # Handling Suggestion Setting
 Other # Settings
 # map template
 Engineering Alarm Management

## Rule Setting

Rule: When a specified alarm or notification meets certain conditions, the 1 system
automatically triggers the corresponding operation.

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Alarm Settings > Rule Settings to create, delete, modify, import, and export rules, see the
following figure.

## Creating A Rule

Prerequisite
**UFM Function Operation Guide**

1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. In the Rule Setting window, click +New, see the following figure.

1. (Optional) In the Resource, Alarm Code, Time Condition, Other Conditions, and More
Conditions areas, set alarm filtering conditions. The system performs the corresponding
operations on the alarms that meet the conditions.

Set the parameters as follows:

**Area  Operation**
2 Alarm Management

Resource                                    Filters NE alarms by object or type.
Alarm Code
Filters alarms by specified alarm code. From the
Time Condition                              resource type tree on the left, select an alarm code
Other Conditions                            and add it to the Selected area on the right. If no
More Conditions                             alarm code is selected, all alarms are matched.

Sets the alarm occurrence time range to be filtered. If
this parameter is not set, all time is matched.

Select the alarm level to be filtered. If this parameter
is not selected (or all options are selected), all alarm
levels are matched.

Select the engineering status to be filtered.

Additional description:
Except that the alarm display filtering rule is valid for all the alarm data that meets the
conditions, other alarm rules are valid for the alarm data that meets the conditions and is
reported after the rule is created.
Visible: Whether alarms or notifications are displayed in the list on the Alarm Monitor page or
Notification Monitor page.
In Database: Whether alarms or notifications are stored in the alarm or notification database.
Whether the southbound and northbound alarm consistency is affected.
Alarms are not marked as "Northbound Filter" or "Invisible", and are reported to the northbound
upper-level NMS through the northbound interface. The southbound and northbound alarms are
consistent.
If an alarm is marked as "Northbound Filter" or "Invisible", the northbound interface determines
whether to report the alarm to the northbound upper-level NMS. If yes, the southbound and
northbound alarms are the same. If it is not reported, the southbound and northbound alarms
are inconsistent.

2.5.1.3 Rule Definition                        Application Description

Rule Name                  Filters the alarms that meet the specified conditions.
Displays filtering rules.  By default, the filtered alarms are not displayed on
the client, but can be viewed through the alarm query
function. If an alarm meets both the alarm reporting
filtering rule and the alarm display filtering rule, the
alarm is directly filtered in accordance with the alarm
reporting filtering rule.
UFM Function Operation Guide                          After alarms meeting the conditions are reported,
Alarm Acknowledgement Rule          the alarms are automatically acknowledged in
Alarm Clearing Rules                accordance with the alarm acknowledgment rule.
**Alarm shielding rule**
When alarms meeting the conditions are reported, the
Momentary Interruption Alarm Rules  alarm clearing rule automatically clears these alarms.

Notification Filtering Rule         An alarm masking rule delivers masking conditions
to an NE agent. The NE agent does not report the
Rule Name                           specified alarm data to the EMS. Screening rules
Alarm forwarding rules              can only be set for NE agents and devices managed
Reporting Filtering Rules           by NE agents. When an NE agent is disconnected
Alarm Delay Rule                    or stopped, only suspended screening rules can be
104                                                   created.

If the alarms with the same alarm location and
alarm code are frequently reported within a short
time interval (for example, more than five alarms
are reported within one minute), they are called
momentary interruption alarms. This type of alarms
is combined to generate a new alarm instead of the
original alarm. The purpose is to reduce the number
of alarms displayed on the client, so that users can
focus on key alarms and quickly locate faults. You
can view the original alarm information by opening the
detailed information about the merged alarms.

Filters the notifications that meet the specified
conditions. The filtered notifications are directly
discarded, and are neither displayed on the client nor
stored in the database. This rule is only valid for new
notifications.

Application Description

When an alarm that meets the conditions is reported,
the alarm forwarding rule can send the alarm to the
specified person by email.

Filters the alarms that meet the specified conditions.
The filtered alarms are directly discarded, and are
neither displayed on the client nor saved in the cache.
This rule is only valid for newly reported alarms.

The alarm delay rule is used to process momentary
interruption alarms. The alarms that meet the
conditions are reported after a period of time. If the
alarms that meet the conditions are reported and

|
Alarm Timing Rule                                                                      2 Alarm Management
**Northbound Filtering Rule**
Repeated historical alarm filtering rules  cleared within the specified delay time, you can select
whether to enter the historical alarm database.
Repeated notification filtering rule
The alarm timing rule counts the status of the newly
Alarm merging rule                         reported alarms that meet the conditions. If the
Automatic dispatch rule (103)              duration reaches the specified time, the specified
|                                                            operation is performed. Multiple rules can be created,
but the conditions cannot overlap.

Filters the alarms that meet the specified conditions.
The filtered alarms are not reported to the northbound
upper-level NMS.Note: If this rule is used, the alarms
on the northbound NMS may be different from those
on the EMS. This rule affects the alarm reporting of
the northbound interface.

Filters out the repeated historical alarms (with the
same location and alarm code) reported within a
period of time since the last historical alarm (including
the filtered historical alarms). The filtered historical
alarms are directly discarded. You can query the
number of times that historical alarms are reported.
This rule is only applicable to newly reported historical
alarms. Multiple rules can be created. This rule does
not affect the reporting of alarms on the northbound
interface.

Filters the repeated notifications (occurrence location
and notification code) reported within a period of
time from the last notification (including filtered
notifications).
Same as). Filtered notifications are directly discarded.
You can query notifications to see the number of
times that notifications are reported. This rule is
only valid for new notifications. Multiple rules can
be created. This rule does not affect the reporting of
alarms on the northbound interface.

Combine the alarms caused by the same fault, and
display one alarm to indicate these alarms. This rule
does not affect the alarm reporting of the northbound
interface.

The alarms that meet the automatic dispatch rule are
automatically forwarded to the work order system,
which generates the corresponding Trouble Ticket.
**UFM Function Operation Guide**

Suppress Dispatch Rule (102)                   Suppression rules must be used together with
dispatch rules. Alarms that meet suppression rules
For details, refer to the following documents:  are not involved in dispatch.

## Suppression Plan

A large number of abnormal alarms may be raised when engineering cutover and switchover
tasks are performed on NE devices. The O&M personnel of the system can create a
suppression plan task in accordance with the engineering plan to suppress the alarms
generated during the engineering task.
When suppressed alarms are reported, only the alarms of one suppression plan task are
displayed on the client. Suppressed alarms are not displayed on the system client, but are still
recorded in the alarm database of the system.

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Alarm Settings > Suppress Plan to create, delete, modify, import, and export suppression
plan tasks, see the following figure.

## Creating A Task

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
2 Alarm Management

Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click +New, see the following figure.

1. Fill in the suppression task information and click New. The task is created successfully, see
the following figure.

The parameters are described as follows:  Parameter Descriptions
Name of the suppression plan task.
Parameter Name                           Parameter Descriptions
Name                                     Sets the initial status of the suppression plan task.
Parameter Name                           Options: Activated and Suspended.A task takes effect
Activate                                 only when it is in Activated status.
Description of the suppression plan task.
Remarks                                  Contact person of the engineering task.
Contact                                  Brief description of the engineering task.
Engineering Task Description             Start time and end time of the suppression plan task.
Task Period
**UFM Function Operation Guide**

## Handling Suggestion Setting

You can add handling suggestions for an alarm based on your alarm handling experience.

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Alarm Settings > Suggestion to add handling suggestions and import/export alarms, see the
following figure.

## Adding Suggestions

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Click Modify to add handling suggestions for the alarm, see the following figure.
2 Alarm Management

## Other Settings

You can redefine the following alarm attributes:

## Level Redefinition

Level redefinition: Redefines the level of an alarm code.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Alarm Settings > Others > Redefine Severity Settings to import, export, and reset alarm
levels, see the following figure.
**UFM Function Operation Guide**

1. Click Resource Type, and select the corresponding resource, see the following figure.

1. Click Redefined Severity in the Operation column, and select the alarm level to be defined,
see the following figure.

1. Click Save to save the new level, see the following figure.
2 Alarm Management

1. Click reset to restore the default alarm level, see the following figure.

1. Click Import and Export to export the alarm level definition template.

## Sound Color Setting

Sound color setting: Customizes the colors of prompt sounds and alarm information displayed
on the EMS client when alarms of different levels occur.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
**UFM Function Operation Guide**

1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >
Alarm Settings > Others > Sound-Color Settings. You can define colors and sounds for
different levels of alarms, see the following figure.

1. Click Switch to enable or disable the sound prompt of the current alarm level, see the
following figure.

1. Click Replace to replace the prompt sounds of the current alarm category, see the following
figure.
2 Alarm Management

1. Click reset to restore the alarm level sound modification, see the following figure.

1. Click the Play Mode button to select the playing mode of the alarm sound, see the following
figure.

1. Click More > Enable All/Disable All to enable or disable the sound of all alarm levels, see the
following figure.
**UFM Function Operation Guide**

Click Severe Category to define the colors of different alarm levels, see the following figure.
Click reset to restore the default settings, see the following figure.

## Alarm Code Customization

Alarm code customization: Redefines the alarm code name and level.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Alarm

Settings > Others > Alarm-Code Settings. Set the alarm code name and alarm level, see the
following figure.
2 Alarm Management

1. Click Resource Type, and select a resource, see the following figure.
1. Select an alarm code from the list, and select Modify Alarm Code Level from the menu, see

the following figure.
**UFM Function Operation Guide**

1. Select an alarm code and click reset on the menu bar to reset the self-defined alarm code,
see the following figure.

1. Click Import/Export to import and export the alarm codes.

## Prompt Setting

Prompt setting: Customizes the major alarms that you care about in the latest period. When
these alarms are generated or their status is changed, a prompt is displayed.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Alarm Settings > Others > Prompt Settings to create, delete, or modify a prompt task, see
the following figure.
2 Alarm Management

1. Click +New. A prompt task is created, see the following figure.
**UFM Function Operation Guide**

## Forwarding Template Configuration

Forwarding template setting: Sets the content template for forwarding alarms to mailboxes
or mobile phones, that is, the message format for forwarding alarms to mailboxes or mobile
phones.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Alarm Settings > Others > Forwarding Template Settings to create or delete a predefined
template, see the following figure.

1. Click +New to create a template, see the following figure.
2 Alarm Management

1. Click Delete to delete the template, see the following figure.

## Confirming Task Settings

Acknowledgment task setting: An automatic historical alarm acknowledgment task is used to
automatically acknowledge historical alarms generated before the specified number of days,
avoiding manual acknowledgment and improving maintainability. This task is executed once a
day. The number of days for confirmation can be set by the user.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
**UFM Function Operation Guide**

1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Alarm
Settings > Others > Auto-Ack Task Settings, and set the task, see the following figure.

1. Click Settings to set the confirmation task, see the following figure.

## Synchronization Settings

Synchronization setting: Alarms are synchronized periodically and automatically.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Alarm

Settings > Others > Synchronization Settings, and set the synchronization period, see the
following figure.
2 Alarm Management

## Locking Alarm Settings

Locked alarm setting: Unacknowledged alarms in cleared status are called locked alarms.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Alarm

Settings > Others > Lock Alarm Settings, and set the locking alarm, see the following figure.

## Column Customization Template Settings

Column customization template setting: Pre-defined templates for current alarms, historical
alarms, and notification systems.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
**UFM Function Operation Guide**

1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >
Alarm Settings > Others > Column Customization Template Settings to create a column
customization template, see the following figure.

1. You can modify, delete, or set a user-defined template as the default template, see the
following figure.
2 Alarm Management

## Current Alarm Clearing Settings

When the number of current alarms exceeds the alarm pool clearance threshold, the alarms are
cleared in accordance with the following policy. The cleared alarms enter the historical alarms.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Alarm Settings > Others > Clear Settings of Active Alarms to clear alarms, see the following
figure.

## Engineering Alarm Management

Engineering alarms are automatically marked in accordance with engineering reservation
information such as the site name, NE type, project start time, and end time. You can manually
mark engineering alarms for a single alarm or batch alarms.
The system suppresses the dispatch of engineering alarms. If an engineering alarm is not
cleared after the engineering time expires, a semi-automatic or automatic work order can be
dispatched, and the remaining engineering alarms can be specified.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
**UFM Function Operation Guide**

Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Alarm Settings > CR Management to create, delete, activate, and suspend engineering
alarms, see the following figure.

1. Click +Create. The project alarm is created successfully, see the following figure.

The related parameters are as follows:  Alarm Name

**Name**
2 Alarm Management

Engineering Alarm Description                Engineering Alarm Description
Enable                                       Enable Switch
Planned Start Time                           Setting the Scheduled Start Time
Planned End Time                             Setting the End Time
Sites Affected                               Setting Affected Sites
Professional Network                         Select Professional Network
Vendor                                       Selecting a Vendor
Dispatch suppression or not                  Dispatch Suppress Switch
Whether the remaining alarms are dispatched  Whether to Dispatch Remaining Alarms
Whether to shield alarms.                    Whether to shield alarms.

1. Click Delete, Activate, and Suspend to delete the selected engineering alarms in batches,
see the following figure.

1. Click Project Alarm Name to view the alarm details, see the following figure.
**UFM Function Operation Guide**

## Map Template(Discarded)

The map template is the preset condition of the alarm map. The alarm map displays the alarm
statistics and alarm details of related sites based on the map template.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, and select Maintenance Surveillance > Alarm Management >

Alarm Settings > GIS Template to create, delete, modify, and preview a map template, see
the following figure.

1. Click +Create. The map template is created successfully, see the following figure.
2 Alarm Management

The new parameters are as follows:

Name                                Template Name
Filtering Alarm Codes               Filter the alarm codes to be displayed
Filter Probe                        Filter the probes to be displayed
Alarm Level                         Filter alarm levels, critical/major/minor/warning
Alarm Time Type                     Alarm time type, including all time, alarm occurrence
time, and self-defined time.
Refresh Time                        Sets the refresh time. Default: 5 minutes.
Show Site                           Displays all sites and alarm sites.

1. Click Edit to modify the template, see the following figure.
**UFM Function Operation Guide**

1. Click Preview to preview the template, see the following figure.

1. Click Delete to delete the template, see the following figure.

## Site Break Map Configuration

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
1. Log in to the workbench, select Maintenance Surveillance > Alarm Management > Alarm

Settings > SiteDown Config, and add, delete, and edit the data, see the following figure.
2 Alarm Management

1. Click +Add to add configuration items, see the following figure.

The configurable quantity determines the highlight color and Geo JSON map to be displayed.

1. After modifying the time, click preservation to save the refresh time, see the following figure.
1. Switch to the Display button, see the following figure.
1. Click Details to view the corresponding map, see the following figure.
**UFM Function Operation Guide**

Click the Color button in the lower left corner to control the color display of the map, see the
following figure.

1. Click Edit in the Operation column to edit the parameters on the map, see the following
figure.
2 Alarm Management

1. Click Delete to delete the site break map configuration.
**UFM Function Operation Guide**

## Alarm Code Settings

The alarm code configuration function allows you to customize alarm codes, maintain
customized alarm codes, and add, modify, and delete alarm codes.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > Maintenance Surveillance > Alarm Management
Operation Steps
Log in to the workbench, and select Maintenance Surveillance > Alarm Management > Alarm
Settings > Alarm Code Setting to create, modify, and delete alarm codes, see the following
figure.

1. Click +Create. The alarm code is created successfully, see the following figure.

The related parameters are as follows:
2 Alarm Management

Alarm Code Name  New Alarm Code Name
Resource Type
Resource type corresponding to the new alarm
Alarm Code       code. You can select a resource type from the drop-
down list
Alarm Severity
Alarm code corresponding to the new alarm code,
Reason Code      range: [9000,9999] or [9999990000,9999999999]
Reason Name
Alarm Type       Select an alarm level (critical, major, minor, or
Maintenance      warning) from the drop-down list

Reason code corresponding to the new alarm code.

Reason Name

Select an alarm type from the drop-down list

Maintenance

After an alarm code is created, you can find the corresponding new alarm code on the
Resource Alarm Code Filter page.

2. Click Delete to delete the alarm codes, or select the alarm codes to delete them or delete
them in batches, see the following figure.
**UFM Function Operation Guide**

3. Click Modify to modify the alarm code. The resource type and alarm code cannot be
modified, see the following figure.

4. The search box supports fuzzy query of alarm codes, see the following figure.
2 Alarm Management

## Correlation Rule Management

## Rule Operation

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Alarm Management > Correlation Rule Management
Operation Steps
1. Log in to the workbench, select Alarm Management > Correlation Rule Management > Rule

Operation, and Create, Enable,Disable,Delete, and Modify a rule, Log,see the following
figure.

## Rule Package Management

Service-related or similar rules are usually placed in a rule package. Service rules are installed
and uninstalled in accordance with the rule package.
**UFM Function Operation Guide**

For the service package specifications, refer to the unified rule package specifications. This
specification supports two types: Template DRL without parameters and template DRT with
parameters.
Compared with common alarm rules, correlation analysis rules are more service-oriented and
more complicated. To reduce user creation,
The system creates rules based on rule templates, and further views rules.
You can delete, modify, enable, disable, and filter queries.
After the rule takes effect, the system processes various analysis data that meets the rule logic
in real time, and generates fault-related data.
The performance analysis result is sent to the alarm management system for further
processing.
The system records and collects statistics of the rule validation process for subsequent
analysis. For details, refer to the correlation analysis result.
Statistics.
The correlation analysis rule template is imported into the system through the correlation
service package, and the association rules created by the template are tracked and managed.
When a correlation service package or correlation analysis rule template expires, it can be
deleted.
Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Alarm Management > Correlation Rule Management
Operation Steps
1. Log in to the workbench, select Alarm Management > Correlation Rule Management >

Rule Package Management, and create, delete, modify, and import a rule package, see the
following figure.
2 Alarm Management

## RCA Rule Energy Efficiency(Discarded)

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA
Operation Steps
1. Log in to the workbench, select Network Intelligence Automation > Intelligent RCA >

Correlation Rule Management > Rca Energy Efficiency, select a rule, and click Query after
the time range. The validity of the rule is displayed. See the following figure.

**Intelligent RCA**

Table of Contents

Association Rule Mining........................................................................................................... 138
This chapter includes the following topics:
 Association Rule Mining

## Association Rule Mining

## Topic Management

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA
Operation Steps
1. Log in to the workbench, select Network Intelligence Automation > Intelligent RCA >

Correlation Rule Mining > Topic Management, and create, delete, and edit a topic, see the
following figure.

## Create A Topic

Create a topic: You can create two types of topics. Select a rule package to create a topic
containing a built-in validity verification template. If no rule package is selected, a common topic
is created. If you select a rule package during creation, you must select a rule package after
modification. If no rule package is selected during creation, no rule package can be selected
during modification.
3 Intelligent RCA

## Common Topic

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA
Operation Steps
1. Click +New, and select a rule package to create a common topic, see the following figure.

Note:
Common features:
Relationship and node source: Obtained through intelligent mining.
Edit the knowledge map:
You can manually create a relationship by entering the alarm code, resource type, and vendor
information of the primary and secondary nodes. A relationship created manually can be
deleted, the direction can be reversed (the primary and secondary directions are reversed),
and the time window can be modified. The relationship created manually will appear in the
status of "To be confirmed" in validity verification. You can confirm whether the relationship is
**UFM Function Operation Guide**

valid, confirm whether it is invalid, modify the time window, and reverse the direction. A valid
relationship is verified.
The status relationships are as follows:

1. Click Close Editor to manually edit the knowledge map, see the following figure.

1. Click Import to import data, see the following figure.
1. Click Intelligent Miningr to create an intelligent mining relationship, see the following figure.
3 Intelligent RCA

1. You can modify, execute, or delete an intelligent mining task, see the following figure.

Note:
Intelligent Mining (only for common topics)
1. Add a task:
Periodic tasks with the same execution time cannot be set.
Sets the alarm data time range when the task is executed automatically. The default value is 10
days, indicating that the alarms that occur within the last 10 days are analyzed.
Location type and location relation determination mode: Equal, including or not determined.
Location: The system determines the resource relationship based on the location of a layer,
for example, the location of a site or an NE, or the location of the upper and lower layers of the
same bearer or the same bearer service path.
Calculation and analysis type: Analyze all alarms or alarms of a specific NE type or alarm code.
Directional analysis only analyzes the correlation between the alarms of the selected NE type or
alarm code and other alarms, so as to narrow the data scope and make it more targeted.
Pearson algorithm: The Pearson algorithm measures the strength of the alarm association
relationship by calculating the linear relationship coefficient between alarm vectors. The value
range of the correlation coefficient is 0-1. The larger the value, the stronger the relationship.
**UFM Function Operation Guide**

Minimum number of occurrences: Only the alarms with the minimum number of occurrences
are counted.
Coefficient: The value range of the correlation coefficient is 0-1. The larger the value, the
stronger the correlation coefficient.
Time window: Time range for determining association relationships.
FP-Growth algorithm: The FP-Growth is an association analysis algorithm for mining frequent
patterns. It slices data from three dimensions: Resource relationship, time, and alarm code, and
calculates the support and confidence to find the high-confidence relationship.
Confidence: Probability that alarm B also occurs when alarm A occurs in the same time
window.
Support degree: Indicates the probability that alarm A and alarm B occur at the same time in
the same time window.
1. Task Execution
Only one task can be executed at a time. If other tasks are being executed when the periodic
task is executed, skip this task. The task execution time is subject to the server time.
During manual execution, you need to select the alarm time range.
Save the execution records each time, and view the historical records.
The relationships excavated after mining are displayed in the knowledge map in a way to be
determined.
1. Task Flow

1. Click Verification to verify the validity of the selected rules in the list. The verification may
take a long time. After the execution is completed, you can select the required rules to
release them to the production environment, see the following figure.
3 Intelligent RCA

Note:
Validity verification (common feature):
Click Verify to verify the validity of the selected rules in the list. After the execution is completed,
select the required rules to be released to the production environment.
The validity of specific templates can be verified.
Rules can be released through templates and associated rules can be managed. The validity
verification rules are defined by users.
Saves validity verification records and supports the export of historical record details.
You can view the release history of validity verification.

## Built-in Rules
Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA
Operation Steps
1. Click +New, and select a rule package to create a topic with a built-in validity verification
template, see the following figure.
**UFM Function Operation Guide**

Note:
The feature of the built-in rule package is described as follows:
Relationship and node source: Rule in the built-in rule package.
A topic created in accordance with a rule package cannot be edited, imported, or exported.
Click Knowledge Map to perform operations on the map, see the following figure.
On the Knowledge Map page, you can view the selected rule package, see the following figure.

Displays the relationships between nodes in a visual manner. Two display modes are
supported: Mesh diagram and tree diagram.
See the following figure.
3 Intelligent RCA

The related nodes are connected by directed line segments. The nodes include the alarm code,
alarm name, resource type, and vendor.
See the following figure.

You can zoom in, zoom out, or drag the map to view it. Click Reset to return to the middle
position of the map.
1. Click Verification to verify the validity of the selected rules in the list. The verification may

take a long time. After the execution is completed, you can select the required rules to
release them to the production environment, see the following figure.

Validity verification description:
The feature of the built-in rule package is described as follows:
The rules containing the built-in verification template in the selected rule package are displayed
in Validity Verification.
Validity verification can only be performed in accordance with the built-in template. Check the
verification records.

## Alarm Analysis

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA
Operation Steps
**UFM Function Operation Guide**

1. Log in to the workbench, and select Network Intelligence Automation > Intelligent RCA >
Correlation Rule Mining > Alarm Analysis. Analyze the alarms in the system in accordance
with the following three conditions, see the following figure.

Note:
Momentary interruption alarm:
The alarms cleared within the delay time are called momentary interruption alarms. Momentary
interruption alarm analysis refers to analyzing the momentary interruption alarm rules that meet
the specified conditions from the historical alarms in a specific time range to provide reference
for alarm pressure reduction.

Oscillation alarm:
The alarms of the same NE, location, and alarm code or the alarms of the same NE are
frequently generated and cleared within a short time interval (for example, 1 minute
If more than five alarms are generated and cleared within the clock, the alarm is called an
oscillation alarm. The analysis of oscillation alarms is based on the historical alarms within a
specific time range.
In the, analyze the oscillation alarm rules that meet the specified conditions to provide a
reference for alarm voltage reduction.
3 Intelligent RCA

Lifecycle and interval:
This function analyzes the distribution of the life cycle or interval of alarms within a specified
range in each time period.

**Topology Management**

Table of Contents

Logical View............................................................................................................................. 148

## Logical View

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > System Configuration > TOPO Management > NE Model Management
Operation Steps
1. Log in to the workbench, select System Configuration > TOPO Management > NE Model

Management. You can see the resource topology and the meanings of the icons, see the
following figure.

1. Select a resource to view the information overview, see the following figure.
4 Topology Management

1. For more operations on the topology view, refer to the function icon description. For a
description of the mouse floating buttons, see the following figure.

**UNIGIS（Alarm）**

Table of Contents

Alarm Map(Group Fault Template).......................................................................................... 150
Alarm Map(Basic Template).....................................................................................................159

## Alarm Map(Group Fault Template)

The alarm map is based on the wireless UNIGIS and gisweb → zgis component. Select
the template type and country for alarm query through the UNI-GIS configuration in the
configuration center, create an alarm GIS template, filter the alarm sites corresponding to
the template, and render the total number of alarms filtered in accordance with the current
conditions and the number of alarms at each level on the gis page.Click a site. A message box
is displayed, showing the alarm details of the site.You can also query the number of out-of-
service eNodeBs by site outage in a template, and use the icon and the corresponding number
to display them.

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
3. You need to configure the map source in WebGIS.
Operation Path
Workspace > Uniform Gis Operation> UNIGIS
Operation Steps
1. Log in to the workbench, and select Uniform Gis Operation > UNIGIS. The alarm and site

information corresponding to the alarm template is displayed on the map, see the following
figure.
# UNIGIS（Alarm）

## Alarm-GIS Configuration

If Alarm-GIS is configured as the preset condition for creating an alarm map template, you need
to select the template type and country.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > System Configuration > Configuration Center
Operation Steps
1. Log in to the workbench, select Configuration Center > System Configuration>

Alarm-GIS Configuration> The alarm query template type can be configured.In
Bangladesh, the default group fault template is used. Other templates are basic templates,
see the following figure.
**UFM Function Operation Guide**

l

## UNIGIS Configuration

The unified GIS configuration is a preset condition for creating an alarm map template. You
need to configure the national center point, national boundary, regional boundary, and site icon
of the alarm map through the unified GIS.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > System Configuration > Configuration Center
Operation Steps
1. Log in to the workbench, select Configuration Center > Common Configuration>

UNIGIS Configuration>Click Unified GIS Configuration to open the configuration
interface, as shown in the figure below.
5 UNIGIS（Alarm）

Parameter Name        Description                       Remarks
Country Center Point                                    Supports the] format of [longitude
Country Boundary      Configuring Country Center Point  and latitude, for example, [90,90].
Region Boundary       on the Map                        Supports the GeoJson format.
**Site Icon Config**
Configuring Country Boundary on   Supports the GeoJson format.
the Map

Configuring Region Boundary on
the Map

Configuring Site Icon on the Map

## Map Configuration

The map can be used only after the related map parameters are configured in the configuration
center.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > System Configuration > Configuration Center
Operation Steps
1. Log in to the workbench, select System Configuration > Configuration Center > Map Project.
**UFM Function Operation Guide**

1. Select Web GIS > System Parameter Configuration, see the following figure.

Options:
5 UNIGIS（Alarm）

5.1.5 Creating an Alarm Map Template

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
3. You need to configure the map source in WebGIS.
4. After upgrading the components, you need to delete the previous outdated templates.
Operation Path
Workspace > Uniform Gis Operation> UNIGIS
Operation Steps
1. On the map page, select a public template or private template, and click Create Template,

see the following figure.

2. When the configuration center query template is Group Obstacle Template, create an alarm
template.
**UFM Function Operation Guide**

3. Creating an Alarm Template During the Basic Template of a Configuration Center Query
Template

5.1.6 Site and area search

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
3. You need to configure the map source in WebGIS.
Operation Path
Workspace > Uniform Gis Operation> UNIGIS
Operation Steps
1. In the map interface, select an area, and enter the site for query, see the following figure.
5 UNIGIS（Alarm）

## Site outage Statistics Table

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
3. You need to configure the map source in WebGIS.
Operation Path
Workspace > Uniform Gis Operation> UNIGIS
Operation Steps
1. Select the created advanced alarm query template. The site outage statistics table that

collects the number of sites by alarm type is displayed in the upper right corner.

2. Move the cursor to the number of areas to display the number of sites corresponding to the
area.
**UFM Function Operation Guide**

5.1.8 Site Rendering and Details

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
3. You need to configure the map source in WebGIS.
Operation Path
Workspace > Uniform Gis Operation> UNIGIS
Operation Steps
1. The rendered alarm sites are displayed on the map. Site A:2 indicates the number of current

alarms of the site, and the alarm details and site information can be drilled and displayed,
see the following figure.
5 UNIGIS（Alarm）

## Alarm Map(Basic Template)

The alarm map is based on the wireless UNIGIS and gisweb → zgis component. Select
the template type and country for alarm query through the UNI-GIS configuration in the
configuration center, create an alarm GIS template, filter the alarm sites corresponding to
the template, and render the total number of alarms filtered in accordance with the current
conditions and the number of alarms at each level on the gis page.Click a site. A message box
is displayed, showing the alarm details of the site.

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
3. You need to configure the map source in WebGIS.
Operation Path
Workspace > Uniform Gis Operation> UNIGIS
Operation Steps
1. Log in to the workbench, and select Uniform Gis Operation > UNIGIS. The alarm and site

information corresponding to the alarm template is displayed on the map, see the following
figure.
**UFM Function Operation Guide**

## Alarm-GIS Configuration

If Alarm-GIS is configured as the preset condition for creating an alarm map template, you need
to select the template type and country.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > System Configuration > Configuration Center
Operation Steps
1. Log in to the workbench, select Configuration Center > System Configuration>

Alarm-GIS Configuration> The alarm query template type can be configured.In
Bangladesh, the default group fault template is used. Other templates are basic templates,
see the following figure.
5 UNIGIS（Alarm）

l

## UNIGIS Configuration

The unified GIS configuration is a preset condition for creating an alarm map template. You
need to configure the national center point, national boundary, regional boundary, and site icon
of the alarm map through the unified GIS.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > System Configuration > Configuration Center
Operation Steps
1. Log in to the workbench, select Configuration Center > Common Configuration>

UNIGIS Configuration>Click Unified GIS Configuration to open the configuration
interface, as shown in the figure below.
**UFM Function Operation Guide**

Parameter Name           Description                       Remarks
Country Center Point                                       Supports the] format of [longitude
Country Boundary         Configuring Country Center Point  and latitude, for example, [90,90].
Region Boundary          on the Map                        Supports the GeoJson format.
**Site Icon Config**
Configuring Country Boundary on   Supports the GeoJson format.
the Map

Configuring Region Boundary on
the Map

Configuring Site Icon on the Map

## Map Configuration

The map can be used only after the related map parameters are configured in the configuration
center.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
Workspace > System Configuration > Configuration Center
Operation Steps
1. Log in to the workbench, select System Configuration > Configuration Center > Map Project.
5 UNIGIS（Alarm）

1. Select Web GIS > System Parameter Configuration, see the following figure.

Options:
**UFM Function Operation Guide**

5.2.5 Creating an Alarm Map Template

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
3. You need to configure the map source in WebGIS.
Operation Path
Workspace > Uniform Gis Operation> UNIGIS
Operation Steps
1. On the map page, select a public template or private template, and click Create Template,

see the following figure.

2. When the configuration center query template is Basic Template, create an alarm template.
5 UNIGIS（Alarm）

5.2.6 Site and area search

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
3. You need to configure the map source in WebGIS.
Operation Path
Workspace > Uniform Gis Operation> UNIGIS
Operation Steps
1. In the map interface, select an area, and enter the site for query, see the following figure.
**UFM Function Operation Guide**

5.2.7 Site Rendering and Details

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
3. You need to configure the map source in WebGIS.
Operation Path
Workspace > Uniform Gis Operation> UNIGIS
Operation Steps
1. The rendered alarm sites are displayed on the map. Site A:4 indicates the number of current

alarms of the site, and the alarm details and site information can be drilled and displayed,
see the following figure.
5 UNIGIS（Alarm）

**Daily Monitoring**
**Dashboard（Alarm）**

Table of Contents

Alarm Status Opening Alarm(Performance).............................................................................168

## Alarm Status Opening Alarm(Performance)

The daily performance alarm monitoring dashboard can collect statistics on performance alarms
by alarm occurrence time (1-2days, 2-5days, 5-7days, or >7days), customize performance
alarm groups, and display the statistics of selected alarm groups by manufacturer.

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
【e-Flow】→【Daily Monitoring Dashboard】
Operation Steps
Log in to the workbench, and select e-Flow > Daily Monitoring Dashboard. The daily
monitoring dashboard and current performance alarm group configuration are displayed, see
the following figure.
# Daily Monitoring Dashboard（Alarm）

## Opening Performance Alarm Group Configuration

You can create, delete, modify, and query performance alarm groups.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
【e-Flow】→【Daily Monitoring Dashboard】
Operation Steps
Log in to the workbench, and select e-Flow > Daily Monitoring Dashboard >Opening
Performance Alarm Group Configuration.

1. Click New. The alarm group is created successfully, see the following figure.
**UFM Function Operation Guide**

The related parameters are as follows:

Group Name                              Name of the new alarm group

Alarm Codes                             Alarm code corresponding to the new alarm group

2. Click delete to delete alarm groups, or select alarm groups to delete them or delete them
in batches. The seven default groups (cssr, tch_assignment, congestion, datavolume, thp,
traffic, and mpd) cannot be deleted, see the following figure.
6 Daily Monitoring Dashboard（Alarm）

3. Click modify to modify the alarm groups. The default seven groups (cssr, tch_assignment,
congestion, datavolume, thp, traffic, and mpd) cannot be modified, see the following figure.

4. The search box supports fuzzy query of alarm groups, see the following figure.

5. Click the Alarm Codes column to view the selected alarm codes, but do not modify or delete
them.
**UFM Function Operation Guide**

## Daily Monitoring Dashboard（Alarm Status Opening Alarm(
Performance)）

The daily performance alarm monitoring dashboard can collect statistics on performance alarms
by alarm occurrence time (1-2days, 2-5days, 5-7days, or >7days), customize performance
alarm groups, and display the statistics of selected alarm groups by manufacturer.You can
create, delete, modify, and query performance alarm groups.
Prerequisite
1. System Login
2. The user has the permission to manage alarms.
Operation Path
【e-Flow】→【Daily Monitoring Dashboard】
Operation Steps
Log in to the workbench, and select e-Flow > Daily Monitoring Dashboard > Daily
Monitoring Dashboard > Alarm Status Opening Alarm(Performance).
6 Daily Monitoring Dashboard（Alarm）

1. Refresh and automatic refresh configurations are supported. The default value is 30 m, and
automatic refresh is disabled by default, see the following figure.
**UFM Function Operation Guide**

2. The Performance Opening Alarm Period collects performance alarms by alarm occurrence
time (1-2days, 2-5days, 5-7days, or >7days), and supports customizing alarm codes, see
the following figure.

3. The Opening Alarm Count by Vendor displays the selected alarm groups by vendor. Only
seven groups can be displayed. By default, the seven groups (cssr, tch_assignment,
congestion, datavolume, thp, traffic, and mpd) are predefined in the system. You can
configure the seven groups to be displayed, see the following figure.
6 Daily Monitoring Dashboard（Alarm）
