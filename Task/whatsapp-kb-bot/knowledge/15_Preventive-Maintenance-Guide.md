iMind

Preventive Maintenance Guide (V6.25.40.
F20 and higher version)

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

1 SSM Inspection...................................................................................................... 1

1.1 Northbound Alarm Subscription...........................................................................................2
1.2 Task Management............................................................................................................... 2
1.3 Viewing and Downloading Reports..................................................................................... 3

2 Hardware Inspection.............................................................................................. 5
3 Log Inspection........................................................................................................7
4 Backup Status Inspection..................................................................................... 8

4.1 Check The Backup Installation Status of The TCF Platform...............................................8
4.2 Checking The Backup Status of Applications..................................................................... 9
4.3 Checking Backup Files......................................................................................................10

4.3.1 Local Server..........................................................................................................10
4.3.2 Remote Server......................................................................................................15

5 TCF Inspection..................................................................................................... 17

5.1 Preventive Inspection of The Inspector Tool (installed in Advance in Each Field).............17
5.1.1 How to Obtain The Inspector Tool....................................................................... 17
5.1.2 Inspector Installation Method................................................................................17
5.1.3 How to Execute The Inspector Tool.....................................................................18

5.2 Alarms (current Alarms, Historical Alarms, and Notifications)........................................... 19

6 Application Inspection.........................................................................................22

6.1 UFM Application Preventive Inspection.............................................................................22
6.1.1 Check Current Alarms and Historical Alarms....................................................... 23
6.1.2 Checking The Operational Status of The UFM Access Agent..............................24
6.1.3 Checking UFM Real-Time Alarm Monitoring Status.............................................25
6.1.4 Checking The Operational Status of UFM RCA Rules.........................................26
6.1.5 UFM Alarm Dispatch Check................................................................................. 27
6.1.6 UFM Alarm GIS Check.........................................................................................28

6.2 UPM Application Preventive Inspection............................................................................ 30
6.2.1 Check Items for UPM Data Collection................................................................. 30
6.2.2 Check Items for UPM Data Warehousing, Convergence, and Calculation........... 31
6.2.3 Check Items for UPM Data Presentation............................................................. 31

6.3 NIOS Application Preventive Inspection............................................................................33
6.3.1 Alarm Diagnosis Check Items.............................................................................. 33
6.3.2 RCA Mining Check Items..................................................................................... 33
6.3.3 Work Order Quality Inspection Items................................................................... 34
6.3.4 Check Items for The Automatic Return Status.....................................................35
6.3.5 Fault Prediction Check Items............................................................................... 35
6.4 EFlow Application Preventive Inspection.......................................................................... 36
6.4.1 Fault Ticket and Work Order Check Items...........................................................36
6.4.2 Check Items of My Task...................................................................................... 37
6.4.3 PM Management Check Items............................................................................. 37
6.4.4 SP Management Check Items..............................................................................38
6.4.5 CR Check Items................................................................................................... 38
6.4.6 DashBoard Check Items.......................................................................................39
6.4.7 CMDB Check Items.............................................................................................. 39
6.4.8 Check Items on The Daily Monitoring Dashboard................................................40
6.4.9 Service Request Check Items.............................................................................. 41

7 Server Resource Usage.......................................................................................42

7.1 CPU Usage........................................................................................................................42
7.2 Memory Usage.................................................................................................................. 43
7.3 Disk Usage........................................................................................................................ 43

8 Preventive Maintenance Report..........................................................................45

SSM Inspection

Table of Contents

Northbound Alarm Subscription................................................................................................... 2
Task Management........................................................................................................................2
Viewing and Downloading Reports.............................................................................................. 3

In the address bar of a browser, enter the uportal front-end address: Https ://IP address:28001.
The login information is obtained from the environment deployment personnel.

Entering the Preventive Maintenance Page
The Scene Management and Threshold Management menus are configuration items of
the preventive maintenance function. The system has default configurations, which can be
configured as required.
The "Task Management" menu includes the execution of preventive maintenance tasks and the
download of preventive maintenance reports.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

## Northbound Alarm Subscription

Entering the Northbound Alarm Page
Check alarm subscription. If there are unsubscribed items, refer to the following figure to ensure
that all alarms are subscribed.
Record the preventive maintenance results in the report.

## Task Management

After the scenario and threshold are configured, perform preventive maintenance on the Task
Management page.
Creating a Preventive Maintenance Task
Select the full preventive maintenance scenario for preventive maintenance.
1 SSM Inspection

You can enable the automatic FTP upload function for periodic automatic preventive
maintenance tasks and reports as required.
Before creating a new task, if the Activate button is turned on, the task will be executed
immediately after it is created.
Preventive maintenance tasks can be manually or automatically executed for multiple times.
You can view and download preventive maintenance reports generated after execution in More
> View Details.

1.3 Viewing and Downloading Reports

After the preventive maintenance is completed, download the report and check the abnormal
situation.
Open the downloaded report document, and directly open the summary page to view the
preventive maintenance results.
View the details on the corresponding sheet page in accordance with the abnormal result.
The table highlights abnormal contents.
Record the preventive maintenance results in the report.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

Hardware Inspection

Because the self-inspection function of the SSM system does not include hardware alarm
inspection, manual inspection is required.
In the browser, enter the IP address of the BMC management page of the server https ://IP.
Note that there is no port on the BMC management port page. The login page is displayed.
Enter your username and password to log in.

Enables the alarm and log functions.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

Click Active Alarms to check whether any alarms exist.
If there is any alarm, collect the information and contact ZTE technical support immediately.

Log Inspection

Unzip the file to obtain the bash script, place it on any node of paas, and use the root account
to adjust the file permission.
chmod 777 logInspection.sh
Execute the following script:
./logInspection.sh
After the script is executed, collect the compressed zip files in the Inspection_Tasks/directory
under the directory where the script is located.
Bash script file:

**Backup Status Inspection**

Table of Contents

Check The Backup Installation Status of The TCF Platform....................................................... 8
Checking The Backup Status of Applications.............................................................................. 9
Checking Backup Files...............................................................................................................10

4.1 Check The Backup Installation Status of The TCF Platform.

Log in to the daisy management page (obtain the login information from the environment
deployment personnel).
In the address bar of a browser, enter the daisy front-end address (https://paas_vip address:
18080/) to access the daisy front-end page. Log in as the admin user.

Enter the daisy page to check backup data management. Take a screenshot of the check result
and fill it in the preventive maintenance report.
4 Backup Status Inspection

4.2 Checking The Backup Status of Applications

Log in to the application page (the login information is obtained from the environment
deployment personnel).

Check whether the backup is successful. If you need to learn about the detailed backup and
restoration operations, refer to the corresponding backup and restoration guide.
Check whether the backup task of the last month fails. Take a screenshot of the check result
and fill it in the preventive maintenance report.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

## Checking Backup Files

Check method:
1. Check the backup path. Click Backup&Restore-> Auto Backup to view the server and server

path for automatic backup. If the server to be backed up is defaultftp, it is the main node
server of the current environment. For a remote server, the IP address is displayed on the
page.
Note: To synchronize the backup files to the remote server, select the check box.

## Local Server

Enter the check result in the preventive maintenance report.
The corresponding SSH address and IP of the login environment can be obtained from the
environment deployment personnel. Connect to the server through the SSH tool. Switch to the
root user, and run the following command:
kubectl get pod -nopcs | grep ftp
4 Backup Status Inspection

Kubectl exec-it ftp container ID-nopcs sh

cd ftpsever/datas/data/data/ict/
Basic is the basic data backup directory.
Large is the service data backup directory.

Basic data: Run the following command to check whether the backup files are backed up
properly every day:
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

Select the backup file of the latest day. Enter this directory to check whether the backup items
of basic data are complete. The file size is not 0.
4 Backup Status Inspection

Service data: Run the following command to check the backup data files:
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

Run the following command to check whether the backup files of each service data are backed
up properly every day:
# Backup Status Inspection

## Remote Server

Take a screenshot of the check result and fill it in the preventive maintenance report.
If the backup file is backed up to a remote server, the check method is the same as that of
the local server. The login information such as IP can be obtained from the environment
deployment personnel. The IP and backup path can also be viewed on the backup page. Use
the SSH tool to connect to the corresponding server for checking.
If no backup remote server is configured, you need to configure it. The configuration method is
as follows:
Select Backup&Restore-> Backup Options. Click Modify and configure the parameters in the
Remote Server area.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

**TCF Inspection**

Table of Contents

Preventive Inspection of The Inspector Tool (installed in Advance in Each Field).....................17
Alarms (current Alarms, Historical Alarms, and Notifications)................................................... 19

5.1 Preventive Inspection of The Inspector Tool (installed in
Advance in Each Field)

Note: The Inspector tool is only applicable to TCF6 and later versions and scenarios.

5.1.1 How to Obtain The Inspector Tool

1. The tool needs to be obtained from the software package released by the TECS OpenPalette
or the Support website of ZTE.
2. Use the hardening tool required in this manual.
3. The tool versions listed in the table are for reference only. During security hardening, use the
tools in the corresponding version.

Tool Version                   Tool Path                          Version release number (Support
inspector_V07.23.10.06_230306                                     website)

In the software package released
by the TECS OpenPalette, an
example is as follows:
TCFV7.23.20.03_tools.tar!/Inspect
or/inspector_V07.23.10.06_23030
6.bin

## Inspector Installation Method

Installation Location
When the TECS OpenPalette product uses the TECS Inspector tool, you need to manually
install it on the PaaS controller node first.
The following uses scenario 6 as an example to describe how to install the tool (the example
version is:
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

Inspector_v07.22.10.16_221112. bin. For other versions, the operation steps are the same.)
Step 1: Ssh to the PaaS controller node of the environment, and switch the su root to the root
user.
Upload the tool installation package inspector_v07.22.10.16_221112. bin to the node, for
example, the/home/vtu directory.

Step 3: Run the following command to start the installation.
sh inspector_v07.22.10.16_221112.bin install

Description of tool installation:
1. If the TECS Inspector tool is already installed on the node, it will be automatically uninstalled

and reinstalled during the installation.
2. The tool does not support HA. If the active node is switched over due to restart, you need to

reinstall it on the new active node.
3. If the node where the tool is installed is recovered, you need to reinstall the tool on the

recovered node.

5.1.3 How to Execute The Inspector Tool

It is recommended that you use the Chrome browser to log in to the ip :8001 of the node where
the https ://tool is installed.
The username and password are used to log in to the OpenPalette portal. The login information
is obtained from the environment deployment personnel.
Check method:
5 TCF Inspection

Inspector Inspection Result  Inspector Inspection Result

**TCF Cluster**

5.2 Alarms (current Alarms, Historical Alarms, and Notifications)

Log in to the tcf management page (obtain the login information from the environment
deployment personnel).
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

1. Current alarm: All
1. Historical alarms: Last seven days
5 TCF Inspection

1. Notification: Last 7

days
If there are alarms, export the alarm data to the preventive maintenance report.

**Application Inspection**

Table of Contents

UFM Application Preventive Inspection..................................................................................... 22
UPM Application Preventive Inspection..................................................................................... 30
NIOS Application Preventive Inspection.................................................................................... 33
EFlow Application Preventive Inspection................................................................................... 36

## UFM Application Preventive Inspection

Log in to the application page (the login information is obtained from the environment
deployment personnel).
In the address bar of a browser, enter the address of the uportal front-end: Https ://IP
address :28001. The usmartNet login page is displayed. Enter the user password to log in.
6 Application Inspection

6.1.1 Check Current Alarms and Historical Alarms

Check items:
1. Active alarm monitoring
2. Historical alarm monitoring
Check Method
Path: Alarm Management----> Active Alarm----> Alarm Monitor
Check method:
1. Active alarm monitoring: Check whether there is the latest active alarm within 30 minutes.
2. Historical alarm monitoring: Check whether there are latest historical alarms within 30

minutes.
Note: The check time depends on the project size. For example, if there are few alarms in some
small projects, increase the check time period.
Criteria:
1. Active alarm monitoring: If there are new alarms within 30 minutes, the alarms are regarded

as normal. Otherwise, the alarms are regarded as abnormal.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

1. Historical alarm monitoring: If an alarm is cleared within 30 minutes, it is considered normal.
Otherwise, it is considered abnormal.

6.1.2 Checking The Operational Status of The UFM Access Agent

Check items:
Checking Whether Each Access Is Normal
Check Method
6 Application Inspection

Path: Application page----> Access management service----> Reception management
Checking method: Check whether the "Number of Broken Agents", "Number of Agents with
Abnormal Modules", and "Number of Agents with Abnormal Channels" values are 0. If they are
0, the access agents are operating properly.
Criteria:
1. Check whether the value of the disconnected agent is 0. If it is 0, the access agent is

operating properly. Otherwise, the access agent is abnormal.
2. Check whether the number of abnormal agents of the module is 0. If it is 0, the access

agents are operating properly. Otherwise, the access agent is abnormal.
3. Check whether the number of agents with abnormal channels is 0. If yes, the access

agents operate properly. Otherwise, the access agents operate improperly.
Normal operation status:

Abnormal operation status:

## Checking UFM Real-Time Alarm Monitoring Status

Check items:
Real-time alarm monitoring status
Check Method
The Refresh button on the real-time monitoring page is opened and operates properly (the
current monitoring alarm page is refreshed automatically every time an alarm is reported).
Criteria:
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

Select Alarm Management > Alarm Monitor. Verify that real-time alarms are refreshed every
minute, see the following figure. If it is not refreshed automatically within one minute, the alarm
monitoring is abnormal.

6.1.4 Checking The Operational Status of UFM RCA Rules

Check items:
RCA Rule Running Status
Check Method
Select Intelligent RCA > Associated Rule Management > Rule Running. Check the status of all
RCA compression rules.
Criteria:
Verify that all RCA rules operate properly and there is no new rule that is disabled abnormally.
# Application Inspection

## UFM Alarm Dispatch Check

Check items:
Check whether the alarms that meet the dispatch rules are dispatched.
Check Method
Path: Alarm Management----> Active Alarm----> Alarm Monitor
Check method: Filter out the alarms that need to be dispatched. If there are some condition
templates (2G, 3G, and RAN), check whether the alarms that are not sub-alarms are
dispatched within forty-eight hours, and generate TT tickets normally. (Which dispatch rules
need to be checked on site)
Criteria:
Based on the operating system time, if an alarm is dispatched for a non-child alarm within 48 h
and a TT is generated properly, it is determined that the alarm is in normal status. Otherwise, if
a ticket is not dispatched or a TT ticket is not generated after 48 h, it is considered abnormal.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

## UFM Alarm GIS Check

Check items:
Alarm Map Check
Check Method
Path: Alarm Management----Current Alarms----Alarm Map. Check whether the number of
alarms at each level on the right of the alarm map is normal and whether the alarm map is
displayed properly.
Criteria:
1. Check whether the number of critical, major, minor, and warning alarms displayed in the

alarm statistics column on the upper right corner of the alarm map can correspond to the
actual number of critical, major, minor, and warning alarms. If they are consistent, it is
normal. If they are inconsistent, it is abnormal. When the number of alarms is large, there
may be a 3% error due to incomplete synchronization of the refresh time, which is a normal
phenomenon.
2. The alarm map is displayed clearly, and the green alarm points on the map are displayed as
normal.
6 Application Inspection

UFM Site Disconnection Dashboard Check
Note: If both the number of disconnected sites and the number of disconnected cells are 0, it is
abnormal. Check the feedback.
Screenshots of the new system and old system
Check items:
Site interruption Dashboard check
Check Method
Path: Alarm Management----Site Break Monitor. Check whether the number of disconnected
sites and cells on the dashboard is normal, and whether the monitoring result is displayed
properly.
Criteria:
If both the number of disconnected sites and the number of disconnected cells are 0, it is
abnormal.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

## UPM Application Preventive Inspection

6.2.1 Check Items for UPM Data Collection

1. Probe running status
2. Number of collected abnormal files
Check Method
Select Probe----> Probe Management. The Probe Management page is displayed. The query
result shows the operational status of all probes. Observe the probe status and startup status.
Number of collected abnormal files
1. Check the probe status. Key probes, such as wireless probe, microwave probe, and core

network probe, are enabled.
2. Check the activated probe and the number of abnormal files. If it is not 0, check the

abnormal files..Observe the data processing time. It should be close to the current time. If
the processing time is too long, check whether the ftp connection is normal. The Ftp check
result is all green.

FTP:
6 Application Inspection

6.2.2 Check Items for UPM Data Warehousing, Convergence, and
**Calculation**

Check the warehousing, aggregation, and calculation of the system.
Check Method
Select Report > Report View to view the system status report. View the system warehousing,
aggregation, and calculation results.
Criteria:
If the waiting value is too large, it is abnormal (vl_calc_data_desc ignore it; otherwise, it is too
large. If the number of Error is abnormal, it is normal.

6.2.3 Check Items for UPM Data Presentation

Check whether there is any breakpoint in the data.
Check Method
Select KPI Dashboard. The data is displayed properly. There is no abnormal value at the
breakpoint. The data update time is within two hours.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

Dashboard In normal cases, it should be a continuous curve. The mark in the following figure is
a breakpoint, which is abnormal.

1. Check whether there is any abnormal value.
In normal cases, the Dashboard data should be a smooth curve.
The following figure shows a sudden data increase or decrease, which is abnormal.
6 Application Inspection

1. Checking the Data Delay Time
For the AP data bottleneck, the delay does not exceed two hours.
"Delay" = "Operating system time"-"Latest data time of the day"
As a result, the ≤2h is normal, and the >2h is abnormal.
If the data delay is within 2 hours, it is considered normal.

## NIOS Application Preventive Inspection

## Alarm Diagnosis Check Items

Check the level-2 menus of alarm diagnosis and self-healing.
Check Method
Select Alarm Diagnosis Self-Healing, and check whether the level-2 menus are operating
properly.
Criteria:
In the level-2 menu, click View. If there is no error or abnormal alarm, it is normal.
Check whether the diagnosis status and self-healing result are successful.

## RCA Mining Check Items

Level-2 Menus of the Intelligent RCA
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

Check Method
Select Intelligent RCA. Check whether the level-2 menus are operating properly.
Criteria:
In the level-2 menu, click View. If there is no error or abnormal alarm, it is normal.
Check whether the execution status or result of each function is normal.

## Work Order Quality Inspection Items

Checking Level-2 Menus of Intelligent Management of Work Orders
Check Method
Click the menu "Work Order Intelligent Management" to check whether the level-2 menus are
operating properly.
Criteria:
In the level-2 menu, click View. If there is no error or abnormal alarm, it is normal.
Check whether the execution status or result of each function is normal.
6 Application Inspection

6.3.4 Check Items for The Automatic Return Status

Checking a Work Order
Check Method
Select----> Automatic Return, and check whether the data and status of the automatic return
are normal.
Criteria:
In the Receipt Status column, if the receipt is successful, it is normal. If the receipt fails, it is
abnormal. You need to check whether the receipt rule is matched. For other reasons, you need
to check the R&D personnel.

## Fault Prediction Check Items

1. Out-of-Service Prediction Check
2. Model Management Check
Check Method
Select Fault Prediction----> Site Out of Service. Check the execution result of the out-of-service
prediction task and the latest training status of model management.
Criteria:
1. Out-of-service prediction: Check the execution result of the related task to see whether

the task is executed successfully. If the task is executed successfully, it is normal. If the
task fails to be executed, it is abnormal. There are several failures, including manual task
termination and task execution failure, which can be viewed under the More button in the
Operation column. Analyze and handle the fault in accordance with the specific failure
cause.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

2. Model management: Checks whether the model training status is available, and performs "
training" for the corresponding model. If the status is available, it is normal; otherwise, it is
abnormal. Click a specific model name to view the training details.

## EFlow Application Preventive Inspection

6.4.1 Fault Ticket and Work Order Check Items

1. Trouble ticket
2. Work Order
Check Method
Click Ticket to check whether the trouble ticket and work order are operating properly.
Criteria:
6 Application Inspection

If no error or alarm is reported when a trouble ticket or work order is opened, and a new trouble
ticket or work order is generated within 24 hours, it is regarded as normal.

6.4.2 Check Items of My Task

Checking My Tasks
Check Method
Select My Task, and check whether the task is operating properly.
Criteria:
Open the My Task and WO Dashboard pages. Verify that there is no error, no abnormal alarm,
and the data is correct.

## PM Management Check Items

Check the level-2 menus of preventive maintenance management.
Check Method
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

Click PM Management/Preventive Maintenance Management to check whether the level-2
menus on the left are operating properly.
Criteria:
Click the level-2 menus on the left in turn. If there is no error or abnormal alarm, it is normal.

## SP Management Check Items

Checking Level-2 Menus of Spare Part Management
Check Method
Click SP Management/Spare Parts Management to check whether the level-2 menus are
operating properly.
Criteria:
Click the level-2 menus on the left in turn. If there is no error or abnormal alarm, it is normal.

## CR Check Items

"Change Request" running status
Check Method
Click Change Request to check whether the system is operating properly.
Criteria:
Click the level-2 menu on the left in turn. If no error or abnormal alarm is reported on the page,
and each statistical graph can be displayed properly, it is regarded as normal.
6 Application Inspection

## DashBoard Check Items

Checking Level-2 Menus of the DashBoard
Check Method
Click DashBoard to enter the menu. Check whether the statistics chart under the menu is
normal, whether there is any error, and whether there is any abnormal alarm.
Criteria:
Open TT Dashboard, and check whether there is any error or abnormal alarm on the three
level-2 labels. If all the statistical graphs can be displayed properly, it is regarded as normal.

## CMDB Check Items

1. Cmdb Data Management
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

2. Cmdb Model Management
Check Method
In the home page, click Configuration Data to enter the CMDB page. Check whether Data
Management and Model Management are normal.

Criteria:
1. Click Data Management. There is no abnormal alarm on the page. If the data of several data

tables can be displayed randomly, it is normal.
2. Click Model Management. There is no abnormal alarm on the page. The following table in

the ROOT column is displayed properly. After you click ROOT, the right table is displayed
properly, indicating that there is no problem.

6.4.8 Check Items on The Daily Monitoring Dashboard

Checking Level-2 Menus on the Daily Monitoring Dashboard
Check Method
6 Application Inspection

Click to enter the menu "Daily Monitoring Dashboard", and check whether each level-2 menu is
operating properly.
Criteria:
Click the three level-2 menus in turn. If no error or abnormal alarm is reported, it is normal.

## Service Request Check Items

Checking the Service Request Menu
Check Method
Click Service Request to enter the menu. Check whether the menu operates properly.
Criteria:
If there is no error or abnormal alarm on the page, it is normal.

**Server Resource Usage**

Table of Contents

CPU Usage.................................................................................................................................42
Memory Usage........................................................................................................................... 43
Disk Usage................................................................................................................................. 43
Check the usage of the RAIS server.

## CPU Usage

1. Log in to the server and run the following command to obtain the current CPU usage.:

2. Run the vmstat 5 5 command to view CPU performance data.

If the CPU usage is higher than 70% or the value of the wa st parameter in the last two columns
in the above figure is higher than 10, feed back the situation.

Category  Item                                               Details
Number of processes to be
Procs     r                                                  executed
Number of processes waiting for I/
b                                                  O
Used swap space (unit: KB)
Memory    swp                                                Available memory (unit: KB)

free
Swap    buff                7 Server Resource Usage
**IO      cache**
System  si     Memory used by the buffer
CPU            Memory used by the cache
so     Memory read from the swap (unit:
KB/s)
bi     Memory written into the switch (
unit: KB/s)
bo     Number of data blocks read from
the disk.
in     Number of data blocks written into
cs     the disk
Number of interrupts per second.
us     Number of context handovers per
sy     second
id     User-mode CPU usage
wa     System CPU usage
st     Idle CPU Time
I/O waiting time
Time when the VM is stolen (in a
virtualized environment)

## Memory Usage

Log in to the server and run the free-h command to obtain the available memory.

If the available memory Mem free is less than 30 G, please feed back.

## Disk Usage

Log in to the server and run the df-h command to obtain the current disk usage.
Preventive Maintenance Guide (V6.25.40.F20 and higher version)

If the usage is higher than 80%, please feed back.

Preventive Maintenance
Report

Fill the inspection result in the Preventive Maintenance Report.
Preventive Maintenance Report.xlsx
