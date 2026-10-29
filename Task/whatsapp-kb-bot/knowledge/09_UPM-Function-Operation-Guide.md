iMind

UPM Function Operation Guide

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

1 Foreword................................................................................................................. 1

1.1 Term.....................................................................................................................................1
1.2 Process Overview................................................................................................................1

2 System User........................................................................................................... 3

2.1 Creating A User...................................................................................................................3

3 Probe..................................................................................................................... 10

3.1 Term...................................................................................................................................10
3.2 Probe Package Management............................................................................................ 10

3.2.1 Installing The Probe Package.............................................................................. 11
3.2.2 Querying Probe Packages....................................................................................13
3.2.3 Upgrading The Probe Package............................................................................ 14
3.2.4 Uninstalling The Probe Package.......................................................................... 15
3.3 Probe Management........................................................................................................... 17
3.3.1 Creating A Probe..................................................................................................17
3.3.2 Select Filter...........................................................................................................25
3.3.3 Viewing Probe Information................................................................................... 27
3.3.4 Probe Modification................................................................................................ 28
3.3.5 Probe Interface Detection.....................................................................................29
3.3.6 Performance File Processing Information Query..................................................31
3.3.7 Advanced Query/Refresh of Collected File Details.............................................. 32
3.3.8 Re-Collect/Download Collected Files................................................................... 33
3.3.9 Advanced Query/refresh of Files to Be Collected................................................ 35
3.3.10 Advanced Query/Refresh of Task History Information....................................... 36
3.3.11 Advanced Query/Refresh of Latest Error Logs.................................................. 37
3.3.12 Starting and Stopping The Probe.......................................................................39
3.3.13 Probe Deletion.................................................................................................... 41
3.3.14 Viewing The Information in The Probe List........................................................ 43

4 Model Management.............................................................................................. 48

4.1 Term...................................................................................................................................48
4.2 Service Package Management..........................................................................................49

4.2.1 Installing A Service Package................................................................................49
4.2.2 Viewing Service Package Information.................................................................. 50
4.2.3 Upgrading A Service Package............................................................................. 52
4.2.4 Uninstalling A Service Package........................................................................... 53
4.3 Resource Model................................................................................................................ 55

4.3.1 Extended Resource Type..................................................................................... 55
4.3.2 Modifying Extended Resources............................................................................ 57
4.3.3 Exporting Extended Resources............................................................................ 59
4.3.4 Viewing Resource Location Information............................................................... 60
4.4 Performance Model........................................................................................................... 61
4.4.1 View The Data of Different NEs in The Performance Model................................ 61
4.4.2 Creating PO Selection KPIs................................................................................. 63
4.4.3 Creating PO Input KPIs........................................................................................65
4.4.4 Search KPI by Input Characters...........................................................................67
4.4.5 Viewing and Modifying The PO............................................................................68
4.4.6 Viewing KPI Details.............................................................................................. 71
4.4.7 KPI Modification....................................................................................................72
4.4.8 KPI Deletion..........................................................................................................74
4.5 Aggregation Management................................................................................................. 75
4.5.1 Filter...................................................................................................................... 75
4.6 Conversion Management...................................................................................................76
4.6.1 Service Package Selection...................................................................................76
4.6.2 Performance Metadata Modification..................................................................... 77
4.6.3 Performance Mapping Modification...................................................................... 78
4.6.4 Performance Rule Modification.............................................................................79
4.7 Service Busy Hour.............................................................................................................81
4.7.1 Creating A Busy Hour.......................................................................................... 81
4.7.2 Querying Busy Hours........................................................................................... 84
4.7.3 Delete A Busy Hour............................................................................................. 85
4.8 Global Configuration.......................................................................................................... 87
4.8.1 General Modification............................................................................................. 87
4.8.2 Conversion Modification........................................................................................89
4.8.3 Database Modification.......................................................................................... 92
4.8.4 Modifying Calculation Information.........................................................................94
4.8.5 Modifying The Monitoring Time............................................................................ 96
4.8.6 Data Source → Add Connection Information....................................................... 98
4.8.7 Data Source → Connection Information Modification...........................................99
4.8.8 Data Source → Delete Connection Information................................................. 100
4.8.9 Data Source → Create Data Source..................................................................101
4.8.10 Data Source → Modify Data Source Information............................................. 103
4.8.11 Data Source → Delete Data Source Information............................................. 104
4.9 GIS KPI............................................................................................................................105

5 Data Display........................................................................................................106

5.1 Performance Query......................................................................................................... 107
5.1.1 Creating A Group............................................................................................... 107
5.1.2 Modifying Group Information.............................................................................. 108
5.1.3 Delete A Group...................................................................................................110
5.1.4 New Query > General Query............................................................................. 110
5.1.5 New Query > Busy-Time Query......................................................................... 112
5.1.6 New Query > Others (Alarm Settings)............................................................... 114
5.1.7 Performance Query Module Information Board Query....................................... 117
5.1.8 Copying A Performance Query Template.......................................................... 118
5.1.9 Modifying A Performance Query Template........................................................ 119
5.1.10 Performance Query Template Deletion............................................................ 120
5.1.11 Performance Query Template Statistics........................................................... 121
5.1.12 Exporting Performance Query Template Data................................................. 122
5.1.13 Query Conditions.............................................................................................. 123
5.1.14 Performance Data Query Page........................................................................ 124

5.2 Threshold Management...................................................................................................126
5.2.1 Creating A Common Threshold..........................................................................126
5.2.2 Creating Historical Statistics Thresholds............................................................ 129
5.2.3 Creating A Complex Threshold.......................................................................... 132
5.2.4 4.2.4 Create Historical Period Comparison Threshold....................................... 135
5.2.5 Viewing Threshold Information........................................................................... 138
5.2.6 Modifying Thresholds..........................................................................................139
5.2.7 Start/Stop Threshold........................................................................................... 140
5.2.8 Threshold............................................................................................................ 141
5.2.9 Delete Threshold................................................................................................ 142

5.3 Performance Monitoring.................................................................................................. 143
5.3.1 Creating A Group............................................................................................... 143
5.3.2 Modifying Group Information.............................................................................. 144
5.3.3 Delete A Group...................................................................................................146
5.3.4 Creating A TopN Monitoring Template...............................................................147
5.3.5 Creating A Trend Monitoring Template.............................................................. 149
5.3.6 Creating A Proportion Monitoring Template....................................................... 151
5.3.7 Creating A Year-on-Year Analysis Template......................................................153
5.3.8 Viewing Performance Monitoring Template Information..................................... 155
5.3.9 Modifying A Performance Monitoring Template................................................. 155
5.3.10 Performance Monitoring Template Data Monitoring......................................... 156
5.3.11 Delete A Performance Monitoring Template.................................................... 157
5.3.12 Downloading Monitoring Figures...................................................................... 158
5.3.13 Year-on-year Analysis Monitoring Data Display Time Setting.......................... 159
5.3.14 Viewing and Downloading The YoY Analysis Monitoring Data List.................. 161
5.4 User-defined Statistics.....................................................................................................162
5.4.1 Creating A Group............................................................................................... 163
5.4.2 Modifying Group Information.............................................................................. 164
5.4.3 Delete A Group...................................................................................................165
5.4.4 New User-defined Statistics Template → General Query.................................. 166
5.4.5 Creating A Customized Statistics Template for →→ Drilling.............................. 168
5.4.6 Customizing A Statistics Template →→ Creating A Graph................................ 171
5.4.7 Viewing Customized Statistics Template Information......................................... 174
5.4.8 Copying A Customized Statistics Template........................................................175
5.4.9 Modifying A Customized Statistics Template..................................................... 176
5.4.10 User-defined Statistics Template Data Statistics..............................................177
5.4.11 Deleting A Customized Statistics Template......................................................179
5.4.12 Exporting Customized Statistics....................................................................... 180
5.4.13 Customizing Statistics Page Graphs................................................................ 181
5.4.14 Modify Condition Dialog Box............................................................................ 182
5.4.15 Modifying Customized Statistical Data Conditions........................................... 183
5.5 Current Alarms................................................................................................................ 184
5.5.1 Advanced Query of Active Alarms..................................................................... 184
5.6 Historical Alarms..............................................................................................................186
5.6.1 Advanced Query of Historical Alarms.................................................................186

6 KPI Dashboard................................................................................................... 188

6.1 Monitoring Template Settings..........................................................................................188
6.2 Scaling of The Monitoring Interface................................................................................ 190
6.3 Viewing Monitoring Details.............................................................................................. 191

7 Support................................................................................................................193

7.1 Data Connection.............................................................................................................. 193
7.1.1 Database.............................................................................................................193
7.1.2 FTP/SFTP Connection Management..................................................................197
7.1.3 SSH Connection Management........................................................................... 200
7.1.4 Email................................................................................................................... 202

7.2 Script................................................................................................................................205
7.2.1 Script Repository................................................................................................ 205
7.2.2 Script Task..........................................................................................................208
7.2.3 File upload.......................................................................................................... 212
7.3 Report.............................................................................................................................. 213
7.3.1 Report Task........................................................................................................ 214
7.3.2 Report View........................................................................................................ 217
7.4 KPI Predict.......................................................................................................................218
7.5 Report Template Management........................................................................................218
7.5.1 Report Management........................................................................................... 218
7.5.2 Element Management.........................................................................................219
7.5.3 Layout Management........................................................................................... 220
7.5.4 SQL Management...............................................................................................221

**Foreword**

Table of Contents

Term..............................................................................................................................................1
Process Overview.........................................................................................................................1

## Term                      Description

Term      Northbound interface, which is provided for the UPM
ems       to collect original resources or performance data.
ups
Collects the original data obtained from the ems
dis       through the customized probe package, and performs
preliminary processing.
pof
res       Process the files processed by UPS again, put them
tlmaster  into the database, and calculate the corresponding
tlsalave  performance data.

Performance file generated after UPS processing

Resource files generated after UPS processing

Scan the files generated by UPS, and send them to
conversion or warehousing.

Converts the pof file transferred from the tlmaster
to the tof file that can be directly warehoused, and
supports multi-copy deployment.

## Process Overview

The main function of the UPM system is to process performance data. The customer uses it to
extract indicators, output reports, and monitor special indicators. The data flow is as follows:
**UPM Function Operation Guide**

1. The original data of each manufacturer provided by ems is saved under the fixed path of the
disk.

2. The ups scans files from the EMS through FTP (SFTP), converts them into a unified
format, converts resource files into RES files, and converts performance files into POF files.
The files are saved in a fixed disk path:/home/tl > data/ups > data/nbi. You can enter the
container to check whether files are generated.

3. The tlmaster service of the dis scans the disk files saved by the UPS, parses the resource
files and stores them in the database through the FTP. The performance files are randomly
forwarded to one of the four tlsalave files. After the files are parsed and converted
successfully, they are sent back to the tlmaster. The tlmaster sends the files to the database
through the FTP. One of the two databases stores performance data, and the other stores
the data processing status.

**System User**

Table of Contents

Creating A User............................................................................................................................3

Use the admin account to create an account for UPM maintenance personnel. This account has
the operation permission only for the UPM module.
This chapter includes the following topics:
 Creating a User

## Creating A User

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
Operation Path
[Workspace]→[System Configuration]→[Security Management]→[Role Management]
Operation Steps
1. Log in to the system as the administrator. Select [System Configuration] > [Security

Management] > [Role Management]. The User Role Management page is displayed, see
the following figure.
**UPM Function Operation Guide**

1. Click [Operation Set] > [Create Operation Set] to create the operation set required by the
UPM administrator, see the following figure.

1. Select the operation set permission corresponding to UPM, see the following figure.
2 System User

1. Click [Role] > [Create Role] to create the role required by the UPM administrator, see the
following figure.
**UPM Function Operation Guide**

1. Select No for Domain Security Administrator, and click OK, see the following figure.

1. Select resources as required, and select "UPM" created in the above step for the operation
set, see the following figure.
2 System User

Note: Select a resource object on the left, and set the operation set on the right to change the
permissions of the resource object. You can press and hold the ctrl key to continuously select
or invert resource objects, or press and hold the shift key to select or invert resource objects at
the same layer in batches.
1. Click [Create] to create a UPM role, see the following figure.

1. Click [User Management] →[+ Create User] to create the UPM administrator user, see the
following figure.
**UPM Function Operation Guide**

1. Enter the user information, see the following figure.

Parameter                            Value
Account Rule                         Selecting the Default Rule
Maximum number of concurrent logins  Depending on the actual situation
User group                           Depending on the actual situation

1. Select the created UPM role, see the following figure.
2 System User

1. Click [Create]. The UPM user is created.

# Probe

Table of Contents

Term............................................................................................................................................10
Probe Package Management.....................................................................................................10
Probe Management.................................................................................................................... 17

The performance data and resource data in UPM are collected from the original file reported
by the lower level according to the specific fields and rules, and then parsed into the data
type stored in UPM. That is, the data is first collected to a path of the current environment in
ftp mode, and then the probe parses the data to generate the pof file. Generally, the data is
customized and does not depend on other components of UPM. The data collected and parsed
by the probe is finally scanned and stored in the database through the dis service. Describes
how to install, upgrade, and uninstall probe packages, how to add, delete, modify, and query
probes, and how to view data collection.
This chapter includes the following topics:
 Probe Package Management
 Probe Management

3.1 Term                     Original performance data, that is, counters.

counter

## Probe Package Management

Probe package: Defines a set of scanning, collection, and data parsing rules in accordance
with the resource data reported by the lower-level EMS, the format of performance data, and
the contents in the file. For example, the command rules for collecting files are defined, that
is, after the probe information is created by referencing the probe package, all data files that
meet the naming rules in the ftp information path of the probe configuration are scanned and
downloaded, and downloaded to the default storage path (/home/tl-data/ups-data/erf/res (pm)/
Probe Package Type/Probe Name/) written in the probe package. Then, the file is parsed in
accordance with the parsing rules carried in the probe package. By default, all resource data
3 Probe

is parsed and stored in the database. The performance file is generated in accordance with
the counter parsing information carried in the probe package to generate a POF file for the dis
component in the UPM to scan and store.

## Installing The Probe Package

Prerequisite
1. System Login
2. The user has the permission to manage probes.
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Package Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed, see the following figure.

1. Click [Probe Package Management]. The probe package management page is displayed.
Click [Install] in the upper left corner of the list to install the probe package, see the following
figure.
**UPM Function Operation Guide**

1. On the Probe Package Management page, click Install. The Select Probe Package page is
displayed. Click Select File. The Upload dialog box is displayed. Find the probe package to
be installed. Select the probe package, and click Open, see the following figure.

1. When using external files, click "Upload" to upload and install the probe package. After the
installation is completed, a message box is displayed, see the following figure.

Installing the External Probe Package
# Probe

## Querying Probe Packages

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Package Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Package Management]. The Probe Package Management page is displayed.

Enter the probe package name in the search box in the upper right corner of the list, see the
following figure.
**UPM Function Operation Guide**

## Upgrading The Probe Package

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Package Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Package Management]. The Probe Package Management page is displayed.

Click [Upgrade] in the list, see the following figure.
3 Probe

1. Upload the probe package to be upgraded, see the following figure.

1. After the upgrade succeeds, the upgrade success message is displayed on the upgrade
page, see the following figure.

## Uninstalling The Probe Package

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Package Management]
Operation Steps
**UPM Function Operation Guide**

1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management
page is displayed.

2. Click [Probe Package Management]. The Probe Package Management page is displayed.
Click [Uninstall] in the list, see the following figure.

1. Click Delete. A confirmation dialog box is displayed. Click Delete, see the following figure.

1. After you confirm the deletion, a message is displayed, indicating that the probe package is
deleted successfully, and the corresponding probe package information is invisible on the
page, see the following figure.
3 Probe

## Probe Management

In the ups module, after a probe package is installed, it only provides maintenance personnel
with available filtering rules and resolution rules, and does not collect data. You need to
reference the probe package rules, configure the data collection interface and collection
time information, that is, the probe package acts as the main body, and create the FTP
information that connects to the collected data, that is, the probe. According to the created
probe information, the probe package collects the data that matches the probe package rules
under the FTP path of the probe. This section describes how to add, modify, view, and delete
probes.

## Creating A Probe

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
Click [Probe Management]. The Probe Management tab is displayed. Click [New Probe] above
the list, see the following figure.
**UPM Function Operation Guide**

1. After selecting a node and a probe type, you can set the basic information of the probe, see
the following figure.

Field                     Introduction
Node
If this node is selected, the current IP port is
Probe Type                automatically obtained. In most cases, 127.0.0.1:
Apps1 :port is displayed locally.

The probe package installed in the current probe
module can be selected as required.

1. After selecting the node and probe type, fill in the basic information. The probe package
name, version, and manufacturer are fixed when the probe type is selected. Therefore, they
cannot be edited or selected, see the following figure.
3 Probe

**Field                    Introduction**
**EMS Version**
The probe package supports multiple versions. By
Probe Name               default, only the latest version can be selected. If you
need to select other versions, contact PM technical
support.

If there are requirements for the project, fill in the
name as required. If there is no requirement, name
the project as required.

1. Select the status and time zone of the new probe. By default, the local time zone and time
are set, see the following figure.

**Field  Introduction**
**UPM Function Operation Guide**

Status                        Select the status here. If it is running, it starts
Time zone                     scanning data according to the FTP information after
it is created. Otherwise, it does not take effect.
**Daylight Saving Time Type**
EMS northbound time           Set this parameter in accordance with the local
time zone. The pof file generated after scanning is
generated in accordance with the time corresponding
to the local time zone.

It can be used if necessary. Otherwise, it is not used
by default.

Set this parameter in accordance with the EMS time
zone. In most cases, set this parameter to the local
time.

1. Fill in the FTP information of the probe resource data and performance data. The FTP
address information reported by the northbound interface should be known in advance, as
shown in the figure below.

**Field       Introduction**
**FTP Type**
Select the FTP type of the resources reported by the
IP          EMS northbound interface. Currently, both FTP and
Slave IP    SFTP are supported. Confirm with the northbound
Port        interface in advance.
FTP service IPs for northbound performance/resource
data connection

Not used in most cases

FTP service port for the northbound interface to
provide performance/resource data connection

|
3 Probe

Username                       FTP service login name for northbound performance/
Password                       resource data connection
**Path**
FTP service login password for northbound
performance/resource data connection

Path for storing the FTP service data of the
northbound performance/resource data connection.

1. For the configuration of normal performance data scanning tasks and performance data
recollection tasks, see the following figure.

**Field        Introduction**
**Start Time**
Interval     Sets the start time of the scanning task.

Granularity  This parameter sets the interval at which the scanning
and downloading tasks are executed based on the
|                              start time. The normal scanning task is usually set to
60. that is, the scanning and downloading tasks are
executed every hour. The recollection task is usually
set to 1440, that is, the recollection task is executed
once a day.

The granularity set here determines the scanning
range. For example, the default value of normal
scanning is 60, that is, the current scanning data
period includes the period within one hour. For
example, the default value is 10080, which means
that the system scans and downloads the data that
is missing within seven days. Set this parameter as
required.
**UPM Function Operation Guide**

Delay                                   The time configured here is the start time of scanning
pm-normal-scan-task2.scancachecapacity  and downloading delayed. For example, five minutes
are set, and the first scanning is changed from
00:00:00 to 00:05:00, and so on. In most cases, the
default value 0 is used without any delay.

Number of cached files. The processed files are
stored in the cache to avoid repeated processing.

1. Configure the performance data download task and performance data processing task, see
the following figure.

Field                                   Introduction
Download task: Interval
After a scanning task is executed for performance
Processing task: Interval               data collection or re-collection, the download task
starts to be executed. Therefore, this parameter sets
pm-erfs-combine.erfSplitScheduleP       the interval at which the download task is executed
pm-erfs-combine.erfSplitBatch           after the scanning task is executed. If there is no
special requirement, use the default value 0, that
is, the download task is executed immediately after
scanning.

After the performance data is downloaded, the
processing task is executed. Therefore, the interval
setting here refers to how long the conversion
processing task is executed after the download task is
executed. If there is no special requirement, use the
default value 0, that is, execute the processing task
immediately after the download is executed.

Number of processing threads

Number of files processed at a time

1. Configure the resource data synchronization task, see the following figure.
3 Probe

Field                              Introduction
**Parsing Northbound Resource Files**
Start Time                         Set this parameter in accordance with whether to
Interval                           obtain resources from the unified resource probe.
To obtain resources from the northbound interface,
Filter duplicate data              select Yes.

Sets the start time of the scanning task.

This parameter sets the interval at which the scanning
and downloading tasks are performed based on the
start time. By default, the scanning task is set to
60. that is, the scanning and downloading tasks are
performed every hour. Resource data is not updated
frequently. It is recommended that you perform the
scanning and downloading tasks once a day, that is,
1440.

There are many repeated reky in the original resource
file reported by the northbound interface. The
configuration item here determines whether to filter
out the repeated data. Generally, the default value
"Yes" is used to keep the data in the generated
resource pof file unique.

1. Configure the probe clearing task, see the following figure.
**UPM Function Operation Guide**

**Field                     Introduction**
**Start Time**
Interval                  Sets the start time of the task.

Data Retention Time       This parameter indicates the number of minutes
before the start time. By default, this parameter is set
to 1440, that is, the task is executed once a day.

The time here refers to the data retention period. For
example, if this parameter is set to 168, the data to
be cleared is the old data seven days before the data
clearing time. The specific setting time depends on
the office requirements.

1. Click OK. The new probe is displayed, and its status is the same as that when it is created,
see the following figure.
3 Probe

## Select Filter

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Management]. The Probe Management tab is displayed. Click [Status] above

the list, see the following figure.
**UPM Function Operation Guide**

1. Select a status to implement filtering, see the following figure.

1. Select a probe package and filter by probe type, see the following figure.
3 Probe

## Viewing Probe Information

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Management]. The Probe Management tab is displayed. Click [Probe Name]

in the Probe Name column. The detailed probe information page is displayed, see the
following figure.
**UPM Function Operation Guide**

1. Click. The page for viewing the details of the probe is displayed, see the following figure.

## Probe Modification

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
3 Probe

1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management
page is displayed.

2. Click [Probe Management]. The Probe Management page is displayed. Click [Probe name]
in the Probe Name column. The page for viewing probe details is displayed. On this page,
click [Edit] in Probe Configuration.

1. The probe type and basic information cannot be modified, and other information can be
modified. After modifying the information, click OK. The information is displayed on the
Modify Success page, see the following figure.

## Probe Interface Detection

Prerequisite
1. System Login
**UPM Function Operation Guide**

2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Management]. The Probe Management page is displayed. Click [Probe name]

in the Probe Name column. The page for viewing probe details is displayed. On this page,
click [Interface Detect] in probe configuration.

1. Click [Detect] in the upper left corner of the page. The probe displays the configured ftp
connection information, see the following figure.
3 Probe

The performance FTP path set for the probe does not exist. Check the FTP path of the
collected performance data.
In addition, performance files can be collected through the path inside the container, and are
also unreachable here.

## Performance File Processing Information Query

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Management]. The Probe Management page is displayed. Click [Probe

name] in the Probe Name column. The page for viewing probe details is displayed. Click [
Performance File Processing Information] in the time dimension of probe analysis statistics,
see the following figure.

Note: There are two processing modes for the probe: One is to convert the original file into the
POF file, and the conversion quantity can be viewed in the conversion phase; the other is to
split the fragment file, and the result cannot be viewed in the conversion phase. You can view
the number of files that fail to be processed and the causes through the latest error logs.
**UPM Function Operation Guide**

1. After setting the time, click OK to view the file processing status within the fixed period, see
the following figure.

3.3.7 Advanced Query/Refresh of Collected File Details

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Management]. The Probe Management page is displayed. Click [Probe name]

in the Probe Name column. Click [File Details] in the file dimension of Probe Analysis
Statistics, see the following figure.
3 Probe

1. Click Advanced Query in the upper right corner of the Collected File Details page. After
setting the query conditions, click Query. The query results are displayed in the list, see the
following figure.

## Re-Collect/Download Collected Files

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
**UPM Function Operation Guide**

Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Management]. The Probe Management tab is displayed. Click [Probe Name] in

the Probe Name column. The page for viewing probe details is displayed. On this page, click
[File Details] in the file dimension of probe analysis statistics. Click Advanced Query. The
data that you want to re-collect or download is displayed, see the following figure.

1. Select the file to be re-collected, and click [Recapture Files] in the upper right corner of the
page, see the following figure.

To recollect all the files within a period of time, set the data time to the period during which the
files need to be recollected, select all the data status, and click Recollect File.
1. In, click [Download] to download the file, see the following figure.
3 Probe

3.3.9 Advanced Query/refresh of Files to Be Collected

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Management]. The Probe Management tab is displayed. Click [Probe Name]

in the Probe Name column. The page for viewing probe details is displayed. Click [File
Information To Be Collected] in the file dimension of probe analysis statistics, see the
following figure.
**UPM Function Operation Guide**

1. Click Advanced Query in the upper right corner of the page, select the date and erf file
name, and click Search. The data is displayed, see the following figure.

3.3.10 Advanced Query/Refresh of Task History Information

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
3 Probe

1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management
page is displayed.

2. Click [Probe Management]. The Probe Management tab is displayed. Click [Probe Name] in
the Probe Name column. Click [Mission History Information] in the task dimension of Probe
Analysis Statistics, see the following figure.

1. Click Advanced Query in the upper right corner of the page, select the date, name, and type,
and click Search. The data is displayed, see the following figure.

3.3.11 Advanced Query/Refresh of Latest Error Logs

Prerequisite
1. System Login
2. The user has the permission to manage probes.
**UPM Function Operation Guide**

3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Management]. The Probe Management tab is displayed. Click [Probe Name] in

the Probe Name column. The page for viewing the detailed probe information is displayed.
In this page, click the [Recent Error Log] button in the error log of probe analysis statistics,
see the following figure.

1. Click Advanced Query in the upper right corner of the page, select the date and error type,
and then click Query. The data is displayed, see the following figure.
3 Probe

3.3.12 Starting and Stopping The Probe

Prerequisite
1.System Login
2.The user has the permission to manage probes.
3.The existing probe package is installed successfully.
4.Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1.Log in to the system. On the home page of the system, click [UPS]. The Probe Management
page is displayed.
2.Click [Probe]. The Probe Management page is displayed. Click Start/Stop in the Operation
column. Start and stop the probe, see the following figure.
**UPM Function Operation Guide**

1.Click Stop or Start. A confirmation dialog box is displayed. Click [Confirm], see the following
figure.

1.Click OK. The status in the list changes, see the following figure.
3 Probe

## Probe Deletion

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Management]. The Probe Management page is displayed. Click [delete] in the

Operation column. The following figure shows how to delete a probe.
**UPM Function Operation Guide**

1. Click [delete]. The Confirm dialog box is displayed, see the following figure.

1. Click Delete. The probe is deleted. The probe information cannot be queried, see the
following figure.
3 Probe

3.3.14 Viewing The Information in The Probe List

Prerequisite
1. System Login
2. The user has the permission to manage probes.
3. The existing probe package is installed successfully.
4. Probe Created
Operation Path
[Workspace]→[Performance]→[UPS]→[Probe Management]
Operation Steps
1. Log in to the system. On the home page of the system, click [UPS]. The Probe Management

page is displayed.
2. Click [Probe Management]. The Probe Management page is displayed. Click Value in the

Recent Error Number column, see the following figure.
**UPM Function Operation Guide**

1. The Latest Error Log page is displayed, see the following figure.

1. Click [Probe Management]. The Probe Management tab is displayed. Click Value in the
Remaining Files column, see the following figure.
3 Probe

1. The collected file details are displayed, see the following figure.

1. Click [Probe Management]. The Probe Management tab is displayed. Click Value in the
Remaining Time column, see the following figure.
**UPM Function Operation Guide**

1. The collected file details are displayed, see the following figure.

1. Click [Probe Management]. The Probe Management tab is displayed. Click Value in the
Latest Data Processing Time column, see the following figure.
3 Probe

1. The page jumps to the performance file processing information page, where you can view
the detailed data conversion information, see the following figure.

**Model Management**

Table of Contents

Term............................................................................................................................................48
Service Package Management.................................................................................................. 49
Resource Model......................................................................................................................... 55
Performance Model.................................................................................................................... 61
Aggregation Management.......................................................................................................... 75
Conversion Management........................................................................................................... 76
Service Busy Hour..................................................................................................................... 81
Global Configuration...................................................................................................................87
GIS KPI.....................................................................................................................................105

In the system, data warehousing, analysis, and calculation depend on basic data models. For
example, resource data and performance data are warehoused only when the UPM database
has the corresponding storage table that provides the basic conditions for warehousing, and
the corresponding indicators are output during performance indicator query. Different model
packages play different roles. This chapter describes the basic operations of model packages
that the system depends on.
This chapter includes the following topics:
 Service Package Management
 Resource Model
 Performance Model
 Service busy hour
 Aggregation Management
 Conversion Management
 Global Configuration

## Term                  Description
Original PO: In accordance with the original
Term  performance files, different types of original
Po
|
kpi                                                  4 Model Management
**Counter**
performance data are split into multiple or single POF
files in accordance with specific rules, and then stored
in the data table. Each PO group consists of multiple
Counter, and its name is related to the Counter.
PO calculation: Different types of KPI are divided into
multiple PO groups, and one PO is calculated into
one data table. When most of the associated Counter
in this PO is complete, the UPM will participate in the
calculation and put the calculated result into this data
table.

It consists of multiple or a single Counter based on a
specific formula, which is usually formulated by users.

Basic performance data, which is provided by the
northbound interface.

## Service Package Management

The performance data and resource data in the UPM are stored through the framework
structure table provided by the service package. The system can operate properly to query
statistical data. The service package status is the most basic prerequisite. This procedure
describes how to install, upgrade, uninstall, and view a service package.

## Installing A Service Package

Prerequisite
1. The system can be logged in properly.
2. The user has the UPM service package management permission.
Operation Path
[Workspace]→[Performance]→[Model]→[Access Package]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Access Package] to switch to the service package list tab. Click [Install] to enter the

installation steps, see the following figure.
**UPM Function Operation Guide**

1. Click OK. Wait until the installation is completed. The page cannot be refreshed.

Note: During the installation process, the page cannot be refreshed or closed. Otherwise, the
installation fails.
1. After the service package is installed successfully, a message is displayed, indicating that

the service package is installed successfully.

## Viewing Service Package Information

Prerequisite
1. The system can be logged in properly.
2. The service package is installed and available.
Operation Path
[Workspace]→[Performance]→[Model]→[Access Package]
Operation Steps
4 Model Management

1. Log in to the system. On the home page of the system, click [Model]. The page for model
management is displayed.

2. Click [Access Package]. The service package list page is displayed. Click the service
package name. The information view page is displayed, see the following figure.

1. On the Details page, click a service name to view its details, see the following figure.

1. To return to the service package management page, click [Access Package] in the
navigation tree or click Service Package in the upper right corner of the service package
details to return to the service package management page, see the following figure.
**UPM Function Operation Guide**

## Upgrading A Service Package

Prerequisite
1. UPM Login
2. The service package is installed properly.
3. The user has the permission to operate service packages.
Operation Path
[Workspace]→[Performance]→[Model]→[Access Package]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Access Package] to switch to the service package list tab. Click [Upgrade] to enter the

upgrade step, see the following figure.

1. After selecting the upgrade package, click Open. A confirmation dialog box is displayed.
Click [Upgrade], see the following figure.
4 Model Management

1. Click Upgrade. Wait until the upgrade is completed. The page cannot be refreshed. Wait
until the upgrade is completed.

Note: During the installation process, you cannot refresh the page or close the upgrade page.
Otherwise, the upgrade fails.
1. After the upgrade succeeds, a prompt is returned, indicating that the upgrade succeeds. The

service package list page is displayed.
2. Click [Model Overload]. Wait until the system is restarted and reloaded.

## Uninstalling A Service Package

Prerequisite
1. UPM Login
2. The service package is installed properly.
3. The user has the permission to operate service packages.
**UPM Function Operation Guide**

Operation Path
[Workspace]→[Performance]→[Model]→[Access Package]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Access Package] to switch to the service package list tab. Click [Uninstall] to enter the

uninstallation step, see the following figure.

1. Click Uninstall. A message box is displayed, prompting you to enter the verification code.
You can click Uninstall only after entering the verification code, see the following figure.

1. Check the unloading status, see the following figure.
# Model Management

1. After the service is uninstalled successfully, a message box is displayed, indicating that the
service is uninstalled successfully. There is no corresponding information in the list.

## Resource Model

When querying performance data, the system matches performance data with resource data.
Performance data is available only when resources exist in the database. This procedure
describes how to view information about existing resources and how to expand resources.

## Extended Resource Type

Prerequisite
1. System Login
2. The user has the resource model operation permission.
3. Related service packages are installed properly.
Operation Path
[Workspace]→[Performance]→[Model]→[Resource Model]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Resource Model]. The Resource Model tab is displayed. Click [Extend]. The extension

steps are displayed, see the following figure.
**UPM Function Operation Guide**

1. Click the Extended Resource Type button. The page for filling in the information is
displayed, see the following figure. Set the name and click Add.
4 Model Management

1. Click the Extension button. The extension success information is displayed. Return to
the Resource Model page. You can search for extended resources and view the detailed
information, see the following figure.

## Modifying Extended Resources

Prerequisite
1. System Login
2. The user has the resource model operation permission.
3. Related service packages are installed properly.
4. Existing extended resources in the resource model
Operation Path
[Workspace]→[Performance]→[Model]→[Resource Model]
**UPM Function Operation Guide**

Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Resource Model]. The Resource Model tab is displayed. Enter the extended resource

name in the search box, see the following figure.

1. Click a resource name, and click [Add Resource Type] in the associated resource type list.
The associated resource model selection box is displayed, see the following figure.

1. Click [Add Resource Properties] in the resource attribute list. The Add Resource Attribute
dialog box is displayed. Enter the basic information, and click OK, see the following figure.
4 Model Management

1. After resource attributes are added and associated successfully, a success prompt is
displayed, see the following figure.

## Exporting Extended Resources

Prerequisite
1. System Login
2. The user has the resource model operation permission.
3. Related service packages are installed properly.
4. Existing extended resources in the resource model
Operation Path
[Workspace]→[Performance]→[Model]→[Resource Model]
Operation Steps
**UPM Function Operation Guide**

1. Log in to the system. On the home page of the system, click [Model]. The page for model
management is displayed.

2. Click [Resource Model]. The Resource Model tab is displayed. Enter the extended resource
name in the search box, and click the resource name. The location information list is
displayed. Click Export, see the following figure.

1. The exported data is downloaded successfully.

## Viewing Resource Location Information

Prerequisite
1. System Login
2. The user has the resource model operation permission.
4 Model Management

3. Related service packages are installed properly.
4. The existing resource data in the resource model package is stored in the database.
Operation Path
[Workspace]→[Performance]→[Model]→[Resource Model]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Resource Model]. The Resource Model tab is displayed. Enter the resource type

name in the search box, and click the resource name. The location information list is
displayed. View the details.
3. The information in the resource location can be queried in the database. The database table
name can be queried in the basic information table name, see the following figure.

## Performance Model

The data query statistics in the system is obtained according to the KPI formula and
aggregation mode. The data in the performance query is persistent. Therefore, the data is
calculated according to the KPI formula and stored in the database. During the query, the
calculated data in the table is searched directly. This section describes the basic operations
of adding, modifying, deleting, and viewing the performance KPI. It is not recommended to
manually add the KPI, which will automatically delete it when the service package is upgraded.

4.4.1 View The Data of Different NEs in The Performance Model

Prerequisite
1. System Login
**UPM Function Operation Guide**

2. The user has the permission to operate performance models.
3. Related service packages are installed properly.
Operation Path
[Workspace]→[Performance]→[Model]→[Performance Model]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Performance Model]. The Performance Model tab is displayed. Enter the performance

model name in the search box, and click to view all the KPI/PO information of the specific
RAT model of the vendor, see the following figure.

1. Click a professional network to view the performance KPI information of all manufacturers in
different systems, see the following figure.
4 Model Management

## Creating PO Selection KPIs

Prerequisite
1. System Login
2. The user has the permission to operate performance models.
3. Related service packages are installed properly.
Operation Path
[Workspace]→[Performance]→[Model]→[Performance Model]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Performance Model]. The performance model page is displayed. Click a professional

network. In the upper right corner of the data display page on the right, click [New KPI]. The
Add page is displayed, see the following figure.

1. On the Add page, select the resource type and the service package. After selecting the
granularity for creating a service package, click [Select] in the PO area. The KPI saves the
existing PO in the model package. Select the model package, see the following figure.
**UPM Function Operation Guide**

1. Set the basic information, edit and check the formula, and click New, see the following
figure.

1. After the creation succeeds, the page returns.
4 Model Management

## Creating PO Input KPIs

Prerequisite
1. System Login
2. The user has the permission to operate performance models.
3. Related service packages are installed properly.
Operation Path
[Workspace]→[Performance]→[Model]→[Performance Model]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Performance Model] to switch to the performance model page. Click a professional

network, and click [New KPI] in the upper right corner of the data display page on the right.
3. On the Add page, select the resource type and service package. Select the granularity for

creating a service package, and click [Input] in the PO selection area. A new PO is created
to store the new KPI. After filling in the basic information of the new PO, you need to select
a reference PO, see the following figure.
**UPM Function Operation Guide**

1. After filling in the basic information of KPI, edit and verify the formula, and click New.

1. After the creation succeeds, search for the KPI just created in the upper right corner of the
list. Both the PO and KPI can be queried, see the following figure.
4 Model Management

4.4.4 Search KPI by Input Characters

Prerequisite
1. System Login
2. The user has the permission to operate performance models.
3. Related service packages are installed properly.
Operation Path
[Workspace]→[Performance]→[Model]→[Performance Model]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Performance Model]. The performance model page is displayed. Click a professional

network, and filter conditions in the upper right corner of the data display page, see the
following figure.
**UPM Function Operation Guide**

4.4.5 Viewing and Modifying The PO

Prerequisite
1. System Login
2. The user has the permission to operate performance models.
3. Related service packages are installed properly.
Operation Path
[Workspace]→[Performance]→[Model]→[Performance Model]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Performance Model] to switch to the performance model page. Click a professional

network.
3. Click the name of the PO in the right list. The page for viewing the information is displayed,

see the following figure.
4 Model Management

1. Click the Modify button in the upper right corner of the PO Details page to modify the PO,
see the following figure.

1. In the displayed dialog box, modify the name, description, and status, and click OK. The
modification is successful, see the following figure.
**UPM Function Operation Guide**

1. After the modification is successful, a success prompt is displayed. The modified information
is displayed on the information page, see the following figure.

1. On the Performance Model page, you can search for and view the modified PO name, see
the following figure.
4 Model Management

## Viewing KPI Details

Prerequisite
1. System Login
2. The user has the permission to operate performance models.
3. Related service packages are installed properly.
Operation Path
[Workspace]→[Performance]→[Model]→[Performance Model]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Performance Model] to switch to the performance model page. Click a professional

network.
3. Click the Unfold button before the PO name in the right list. The KPI list is displayed. Click

the KPI name. The details are displayed, see the following figure.
**UPM Function Operation Guide**

1. View the basic KPI information, see the following figure.

## KPI Modification

Prerequisite
1. System Login
2. The user has the permission to operate performance models.
3. Related service packages are installed properly.
Operation Path
[Workspace]→[Performance]→[Model]→[Performance Model]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
4 Model Management

2. Click [Performance Model] to switch to the performance model page. Click a professional
network.

Click the Expand button before the PO name in the right list. The KPI list is displayed.
1. Click the [modify] button in the detailed information list to perform KPI modification, see the

following figure.

1. On the Modify tab, modify the basic information and formula, and click Confirm, see the
following figure.

1. The modified data is the same as that in the detailed KPI information.
Note: After the KPI is modified, the historical data will not be changed. The data generated
after the modification will be calculated according to the new rule. It is not recommended to
manually modify or create a new KPI. The modified KPI will reset back to the original rule when
the service package is upgraded.
**UPM Function Operation Guide**

## KPI Deletion

Prerequisite
1. System Login
2. The user has the permission to operate performance models.
3. Related service packages are installed properly.
4. KPIs already exist under the PO that the performance model belongs to.
Operation Path
[Workspace]→[Performance]→[Model]→[Performance Model]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Performance Model] to switch to the performance model page. Click a professional

network.
3. Click the Expand button before the PO name in the right list. The KPI list page is displayed.
4. Slide the bar in the lower part of the page. Find the Operation column in the list, and click

the [Delete] button for the corresponding KPI, see the following figure.

1. Click OK in the Delete dialog box.

1. After the KPI is deleted, it is displayed on the KPI page.
4 Model Management

## Aggregation Management

During data statistics on the UPM, resource data is aggregated from lower-level data to upper-
level data in accordance with a rule, such as summation, averaging, maximum value, and
minimum value. In addition, original data is collected from lower-level data through probes
at a small granularity. Therefore, there are different aggregation modes in time aggregation.
If the same KPI and the same formula are used between the lower-level data and the UPM,
the resource aggregation mode and time aggregation mode must be the same. This section
describes how to view resource aggregation and time aggregation.

## Filter

Prerequisite
1. System Login
2. Related service packages are installed properly.
3. The user has the operation permission of aggregation management.
4. The POs related to time aggregation and resource aggregation exist under aggregation

management.
Operation Path
[Workspace]→[Performance]→[Model]→[Aggregation]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Aggregation] to switch to the aggregation management page. Select the resource type

and filtering mode, and then click PO, see the following figure.

1. On the PO selection page, you can filter and search by condition name, and then click [
confirm], see the following figure.
**UPM Function Operation Guide**

1. After selecting a PO, click [Filter]. The PO data is displayed, see the following figure.

## Conversion Management

The data stored in the UPM is converted and stored in accordance with specific rules through
customized service packages. Here, the rules for converting the excel model into the po table
are displayed, from the original granularity to the time/resource convergence description.

## Service Package Selection

Prerequisite
1. System Login
2. Related service packages are installed properly.
3. The user has the conversion management permission.
4 Model Management

**Operation Path**
[Workspace]→[Performance]→[Model]→[Transform]
**Operation Steps**
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Transform]. The Conversion Management tab is displayed. Select the service

package to be modified, see the following figure.

1. After the service package is selected, the corresponding information is displayed in the list.

## Performance Metadata Modification

Prerequisite
1. System Login
2. Related service packages are installed properly.
3. The user has the conversion management permission.
Operation Path
[Workspace]→[Performance]→[Model]→[Transform]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
**UPM Function Operation Guide**

2. Click [Transform]. The Conversion Management tab is displayed. Select the service
package that you want to modify. Click [PM source data] in the upper right corner, see the
following figure.

1. In the Operation column of the performance metadata list, click Modify, see the following
figure.

1. After modifying the corresponding fields, click OK. The modification is successful, see the
following figure.

## Performance Mapping Modification

Prerequisite
1. System Login
2. Related service packages are installed properly.
3. The user has the conversion management permission.
Operation Path
4 Model Management

[Workspace]→[Performance]→[Model]→[Transform]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Transform]. The Conversion Management tab is displayed. Select the service

package that you want to modify. Click Performance Mapping in the upper right corner, see
the following figure.

1. In the Operation column of the performance mapping data list, click Modify, see the
following figure.

1. On the Information tab, modify the corresponding fields, and click OK. The modification is
successful, see the following figure.

## Performance Rule Modification

Prerequisite
1. System Login
**UPM Function Operation Guide**

2. Related service packages are installed properly.
3. The user has the conversion management permission.
Operation Path
[Workspace]→[Performance]→[Model]→[Transform]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Transform]. The Conversion Management tab is displayed. Select the service

package that you want to modify. Click Performance Rule in the upper right corner, see the
following figure.

n
1. In the Operation column of the performance rule data list, click Modify, see the following

figure.

1. After modifying the corresponding fields, click OK. The modification is successful, see the
following figure.
4 Model Management

## Service Busy Hour

When querying statistical data, the UPM queries the maximum and minimum values of
indicators in a day, and even queries the values of other indicators at the corresponding time
points in accordance with the maximum or minimum value of an indicator in a day, that is, the
relationship between the driver and the associated indicators. This query depends on the query
rules created in advance. After the query rules are created, the UPM calculates the values in
accordance with the created rules and stores them in a specific table for subsequent query.
This section describes the prerequisites for busy-hour service query, and basic operations such
as adding, deleting, and querying busy-hour service rules.

## Creating A Busy Hour

Prerequisite
1. System Login
2. Related service packages are installed properly.
3. There are available performance indicators under the performance model.
4. The user has the operation permission in busy hours.
Operation Path
[Workspace]→[Performance]→[Model]→[Busy Hour]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Busy Hour] to switch to the Busy Time tab.
3. Click [Create] in the upper right corner of the list. The Add page is displayed, see the

following figure.
**UPM Function Operation Guide**

1. On the Add page, enter the basic information, and click [Add Key Index]. The Select KPI
dialog box is displayed, see the following figure.

1. In the displayed driver selection box, select an indicator and click OK. Only one driver
indicator can be selected, see the following figure.
4 Model Management

1. Click [Add Related Index]. The associated indicator selection page is displayed, see the
following figure.

1. In the associated indicator selection box, select an indicator and click [confirm]. Multiple
associated indicators can be selected, but the KPI selected as the driving indicator cannot
be selected as the associated indicator, see the following figure.
**UPM Function Operation Guide**

1. After all indicators are added, click [confirm]. A success message is displayed, see the
following figure.

## Querying Busy Hours

Prerequisite
1. System Login
2. Related service packages are installed properly.
3. There are available performance indicators under the performance model.
4. The user has the operation permission in busy hours.
5. Create busy-hour rules for existing services in a professional network.
Operation Path
[Workspace]→[Performance]→[Model]→[Busy Hour]
Operation Steps
4 Model Management

1. Log in to the system. On the home page of the system, click [Model]. The page for model
management is displayed.

2. Click [Busy Hour] to switch to the Busy Hour tab. Click an existing busy-hour rule.
3. Through the busy-hour data granularity and busy-hour name search, find the busy-hour rule,

and click the name of the service busy-hour task. The page for viewing the information is
displayed, see the following figure.

1. Click a rule name. The basic information, drive indicators, and associated indicators of the
rule are displayed, see the following figure.

## Delete A Busy Hour

Prerequisite
1. System Login
**UPM Function Operation Guide**

2. Related service packages are installed properly.
3. There are available performance indicators under the performance model.
4. The user has the operation permission in busy hours.
5. Create busy-hour rules for existing services in a professional network.
Operation Path
[Workspace]→[Performance]→[Model]→[Busy Hour]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Busy Hour] to switch to the Busy Hour tab. Click an existing busy-hour rule.
3. Through the busy-hour data granularity and busy-hour name search, find the busy-hour rule.

Find the operation example and click [Delete] to delete it, see the following figure.

1. Click OK in the confirmation dialog box. The deletion is successful, see the following figure.
4 Model Management

## Global Configuration

A large amount of data is stored in the database every day, and a large amount of data
is processed and a large amount of space is required. Therefore, if the data is stored in
the database for calculation for a long time, a global configuration is required. This section
describes how to set the performance data retention time, data conversion time interval,
database connection information, calculation time interval, monitoring setting, and data source
information configuration.

## General Modification

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Global configuration] to switch to the Global Management tab. Click [General] to view

the setting of the performance data retention period, see the following figure.
**UPM Function Operation Guide**

Field Name                        Field Description                 Configuration Suggestions

Start Day of Week                 Sets the start time of each week. Monday

15-minute granularity data (day)  Number of days that the 15-minute 7
granularity data is saved in the
database.

Hourly granularity data (day)     Number of days that the hourly    30

data is stored in the database.

Daily granularity data (day)      Number of days for storing daily 90
data in the database.

Weekly Granularity Data (Weekly) Number of weeks for storing        12

weekly data in the database.

Monthly Granularity Data (Monthly) Number of months in which the    36

granularity data is saved in the

database.

1. Click [Modify] to modify the configuration, see the following figure.
4 Model Management

1. Click OK. A success message is displayed, see the following figure.

## Conversion Modification

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
**UPM Function Operation Guide**

2. Click [Global configuration] to switch to the global management page. Click [conversion] to
view the settings of the conversion thread and interval, see the following figure.

Field Name                  Field Description                     Recommended Configuration
**File Scanning Scope**
Time range for the DIS to scan        7
**Thread Pool**
RES File Scan Interval      pof and res files. The storage time
**POF File Scan Interval**
POF File Dispatch Interval  of pof and res files is configured

when the probe is created. It is

recommended that the storage

time be the same as that set for the

probe.

The number of threads used by         5

the DIS to load and convert data

depends on the actual hardware

configuration and data volume.

Interval at which the DIS scans       60

files in the path where the res is

located, unit: Seconds.

Interval at which the DIS scans       300

files in the path where the pof is

located, unit: Seconds.

Interval (in seconds) for converting 10
dispatch to tof after the DIS scans
the pof.
4 Model Management

TOF File Scan Interval              Interval at which the DIS scans     5
TOF file description dump interval
files in the path where the tof is

located, unit: Seconds.

Interval (in seconds) for converting 8
the data type to storage data after
the DIS scans the tof.

1. Click [modify] to modify the configuration, see the following figure.

1. Click [confirm]. A success message box is displayed, see the following figure.
**UPM Function Operation Guide**

## Database Modification

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Global configuration] to switch to the Global Management tab. Click [database] to view

the performance data calculation thread and time interval, see the following figure.
4 Model Management

Field Name          Field Description
IP Address          IP address of the FTP for data upload.
Port                Port corresponding to the data upload ftp.
Username            Username used to upload data to the ftp.
Password            Password used by the ftp user to upload data.
Upload Directory    Path used to upload the tof.
FTP HOME Directory  It is recommended to be the same as the uploaded
directory.

1. Click [modify] to modify the configuration, see the following figure.

1. Click Expand. A message box is displayed, see the following figure.
**UPM Function Operation Guide**

## Modifying Calculation Information

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Global configuration] to switch to the Global Management tab. Click [calculation] to

view the performance data calculation thread and time interval, see the following figure.

Field Name                          Field Description                 Recommended Configuration
Normal Data Calculation Interval (  In most cases, the data that is
s)                                  stored in the database one or
two hours before the current
time is used as the normal data.
4 Model Management

This configuration refers to the
time interval from the time when
the normal data is stored in the
database to the time when the
KPIs involved in the calculation are
triggered.

Recollect/Late Data Calculation  In most cases, the data that arrives 300
Interval (s)                     two hours before the current time
is used. The data that is stored in
Number of data analysis threads  the database through the probe
Number of data aggregation       re-collection function is used
threads                          as the re-collected data. This
Number of indicator calculation  configuration refers to the time
threads                          interval from the time when the
data is stored in the database to
the time when the indicator-related
calculation is triggered.

Used by the threads involved in       10

data warehousing analysis.

After the original data is            5

warehoused, the threads involved

in data aggregation are used.

After the original data is stored in 5
the database, the threads involved
in KPI calculation are used.

1. Click [modify] to modify the configuration, see the following figure.

1. Click Expand. A message box is displayed, see the following figure.
**UPM Function Operation Guide**

## Modifying The Monitoring Time

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Global configuration] to switch to the global management page. Click [Monitor] to

view the maximum number of monitors, monitoring delay, and monitoring interval, see the
following figure.
4 Model Management

Field Name                                        Field Description
Number of trend monitoring data displayed on the
page.                                             Number of granularities displayed in the trend
graph at different granularities. For example, if the
Delay time for monitoring data.                   granularity is 24 hours or below, the granularity is 24
hours in a day, and the granularity is 6 hours in a 15-
Monitoring Interval                               minute period.

1. Click [modify] to modify the configuration.     Interval between the latest monitoring time and the
current time. For example, if Day is set to 1, the latest
data is the current time of yesterday.

This configuration controls how often the monitored
data on the trend chart is refreshed.

1. Click [confirm]. A success message box is displayed, see the following figure.
**UPM Function Operation Guide**

## Data Source → Add Connection Information

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Global configuration]. The Global Management page is displayed. Expand [Data

Source] and click [Connection Information]. The Connection Information page is displayed.
3. Click [New connection] in the upper left corner. The connection information is added, see

the following figure.

1. On the Add page, enter the data, and click [confirm], see the following figure.
4 Model Management

1. After the creation succeeds, a message is displayed, indicating that the creation succeeds,
see the following figure.

## Data Source → Connection Information Modification

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
3. The created connection information already exists on the Connection Information page.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Global configuration]. The Global Management tab is displayed. Expand [Data

Source], and click [Connection Information].
3. In the connection information list, click [modify] in the Operation column to modify the

configuration, see the following figure.
**UPM Function Operation Guide**

1. Modify the data, and click [confirm], see the following figure.

1. Click [modify]. If the modification is successful, a message box is displayed, see the
following figure.

## Data Source → Delete Connection Information

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
3. The created connection information already exists on the Connection Information page.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Global configuration]. The Global Management tab is displayed. Expand [Data

Source], and click [Connection Information].
4 Model Management

3. In the connection information list, click [Delete] in the Operation column to delete the
information, see the following figure.

1. Click [Delete].

1. After the data is deleted successfully, it is not displayed on the page, see the following
figure.

## Data Source → Create Data Source

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
**UPM Function Operation Guide**

2. Click [Global configuration]. The Global Management page is displayed. Expand [Data
Source], and click [Data source information]. The Data Source Information page is
displayed.

3. Click [New data source] in the upper left corner to add a connection, see the following figure.

1. On the Add page, enter the data, and click [New], see the following figure.

Field Name                    Field Descriptions                Recommended Value
Basic Information: Policy                                       Resource data preferred
Setting the Priority of Scanning
POF file setting: Path        Data                              /home/tl→data/ups→data/nbi/pof
POF file setting: Scan type                                     Recursion
Dis Scanning POF File Path
POF file setting: Write type                                    Direct
Dis Scanning POF File Scanning
RES file setting: Path        Type                              /home/tl→data/ups→data/nbi/res
RES file setting: Scan type                                     Recursive and latest
RES file setting: Write type  Dis Write Type After Scanning     Direct
POF Files

Dis path for scanning RES files.

Dis Scan RES File Scan Type

Dis Write Type After Scanning
RES Files
4 Model Management

1. After the creation succeeds, a message is displayed, indicating that the creation succeeds,
see the following figure.

## Data Source → Modify Data Source Information

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
3. The created connection information already exists on the Data Source Information page.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Global configuration]. The Global Management tab is displayed. Expand [Data

Source], and click [Data source information].
3. In the data source information list, click [modify] in the Operation column to modify the

configuration, see the following figure.

1. Modify the data, and click [modify], see the following figure.
**UPM Function Operation Guide**

1. Click OK. A success message is displayed.

## Data Source → Delete Data Source Information

Prerequisite
1. System Login
2. The user has the operation permission of global configuration.
3. The created connection information already exists on the Data Source Information page.
Operation Path
[Workspace]→[Performance]→[Model]→[Global configuration]
Operation Steps
1. Log in to the system. On the home page of the system, click [Model]. The page for model

management is displayed.
2. Click [Global configuration]. The Global Management tab is displayed. Expand [Data

Source], and click [Data source information].
3. In the data source information list, click [Delete] in the Operation column to delete the

information, see the following figure.
4 Model Management

1. Click [Delete].
1. After the data is deleted successfully, it is not displayed on the page.

## GIS KPI

In development...

Data Display

Table of Contents

Performance Query.................................................................................................................. 107
Threshold Management............................................................................................................126
Performance Monitoring........................................................................................................... 143
User-defined Statistics..............................................................................................................162
Current Alarms......................................................................................................................... 184
Historical Alarms.......................................................................................................................186

Describes how to query performance data through the web, monitor KPI errors, and generate
alarms when KPIs exceed the threshold.
Comprehensive Process
During performance data query, first create various indicator tables in the database for data
storage when the service package is installed. (2) After the probe package corresponding to
the collection rules in the table provided in the service package is installed through the UPS
module, the probe package is referenced in accordance with the address reported by the data
source to create a probe. The probe collects data in FTP or SFTP mode. (3) After collecting
data, the probe parses the collected data into a pof file that can be warehoused and stores it in
the specified path in accordance with the parsing rules carried in the probe package. (4) The
third-party dis service periodically scans the path where the POF file is stored, obtains the data
in this path, converts the data, stores the data in the table provided when the service package
is installed, calculates the data in accordance with the performance index calculation mode
and aggregation mode, and stores the data in the table as persistent data. The ⑤web client
obtains performance data by creating a specified query template. The server generates the
corresponding SQL statement in accordance with the query template, and obtains the data in
the data table. The data is displayed on the web page.
This chapter includes the following topics:
 Performance Query
 Threshold Management
 Performance Monitoring
 User-defined statistics
5 Data Display

 Current alarms
 Historical alarms

## Performance Query

The performance query data is stored in the database after being processed by the system.
The KPIs in this module do not support real-time calculation or aggregation. Therefore, when
the KPI formula or aggregation mode is changed, or even when a new busy-hour rule is added
to the busy-hour module of model management, the previous data is unavailable. You need
to wait for one or two days after the new data is reported again, and then the queried KPIs
are modified or added correctly. This section describes how to create persistent data query
templates and how to view and export results.

## Creating A Group

Prerequisite
1. System Login
2. The user has the permission to display data.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query]. The Performance Query tab is displayed. Click [New group] in

the upper left corner of the list to fill in the information of the new group, see the following
figure.

1. Enter the information on the Group tab, and click [Create]. The group is created
successfully, see the following figure.
**UPM Function Operation Guide**

1. After the group is created successfully, the group information is displayed on the page, and
a message indicating that the group is created successfully is displayed, see the following
figure.

## Modifying Group Information

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A group is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query] to switch to the Performance Query tab. Select a group, and

click [modify] in the Operation column of the group to modify the group information, see the
following figure.
5 Data Display

1. On the Group Information Modify page, you can modify the basic information and query
template. Modify the information, and click [modify], see the following figure.

1. After the group information is modified, the information in the list is changed, and a success
prompt is displayed, see the following figure.
**UPM Function Operation Guide**

## Delete A Group

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A group is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query] to switch to the Performance Query tab. Select a group, and click

[Delete] in the Operation column of the group to delete the group, see the following figure.

1. Click Delete. A confirmation dialog box is displayed. Click [Delete] in the confirmation dialog
box. The deletion function is performed properly, see the following figure.

1. After the group information is deleted, the information in the list is changed, and a prompt is
displayed, see the following figure.

## New Query > General Query

Prerequisite
1. System Login
5 Data Display

2. The user has the permission to display data.
3. The corresponding service package is installed successfully.
4. The probe is operating properly, and the existing resource data and performance data are

stored in the database.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query]. The Performance Query tab is displayed. Click [New Query] in

the upper left corner of the list, see the following figure.

1. In the Select Resource Type dialog box, enter the template name and select the resource
type. After the PO granularity, select No for busy-hour query. Select one or more indicators,
and click [Next], see the following figure.

1. Click Next. In the Location area, select All NEs by default. If you need to query the data
of a specific NE or a batch of NEs, You can manually select NEs, or export all the current
NEs and edit them to keep the NEs to be queried. After NE data is imported, the maximum
number of NEs to be queried is 1500. Click [Next], see the following figure.
**UPM Function Operation Guide**

1. Click Next. In the Time Setting area, do not select Busy Hour. In most cases, the query time
is the last day by default. You can modify the query time as required. After setting a valid
time period, click [Query], see the following figure.

1. After the query is saved, the Data Statistics page is displayed, see the following figure.

## New Query > Busy-Time Query

Prerequisite
1. System Login
2. The user has the permission to display data.
3. The corresponding service package is installed successfully.
5 Data Display

4. The probe is operating properly, and the existing resource data and performance data are
stored in the database.

5. A busy-hour rule is already created on the service busy-hour side of the model management
module.

Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query]. The Performance Query tab is displayed. Click [New Query] in

the upper left corner of the list, see the following figure.

1. In the Select Resource Type dialog box, enter the template name and select the resource
type. After the PO granularity, select one or more indexes for busy-hour query, and click [
Next], see the following figure.

1. Click Next. In the Location area, select All NEs by default. If you need to query the data
of a specific NE or a batch of NEs, You can manually select NEs, or export all the current
NEs and edit them to keep the NEs to be queried. After NE data is imported, the maximum
number of NEs to be queried is 1500. Click [Next], see the following figure.
**UPM Function Operation Guide**

1. Click Next. The Busy Hour parameter is unavailable (the button is grayed out). The query
time is set to the latest day by default. You can modify the query time as required. After
setting a valid time period, click Save and Execute, see the following figure.

1. After the query is saved, the Data Statistics page is displayed.

## New Query > Others (Alarm Settings)

Prerequisite
1. System Login
2. The user has the permission to display data.
3. The corresponding service package is installed successfully.
4. The probe is operating properly, and the existing resource data and performance data are

stored in the database.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
5 Data Display

2. Click [Performance Query]. The Performance Query tab is displayed. Click [New Query] in
the upper left corner of the list, see the following figure.

1. In the Select Resource Type dialog box, enter the template name, select the resource type,
PO granularity, and busy hour, select one or more KPIs, and click [Next], see the following
figure.

1. Click Next. In the Location area, select All NEs by default. If you need to query the data
of a specific NE or a batch of NEs, You can manually select NEs, or export all the current
NEs and edit them to keep the NEs to be queried. After NE data is imported, the maximum
number of NEs to be queried is 1500. Click [Next], see the following figure.
**UPM Function Operation Guide**

1. Click Next. The Busy Hour tab is displayed. By default, the query time is set to the latest
day. You can modify the query time as required. After setting a valid time period, click [
Next], see the following figure.

1. Click Next. On the Others tab, select Sort by KPI or Time, set the alarm level threshold,
enter the KPI condition expression, verify the formula successfully, and click [Query], see
the following figure.

1. After the query is saved, the Data Statistics page is displayed, see the following figure.
# Data Display

## Performance Query Module Information Board Query

Prerequisite
1. System Login
2. The user has the permission to display data.
3. An existing query template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query] to switch to the Performance Query tab. Select a query template,

and click the name in the Template Name column, see the following figure.

1. The template information page is displayed, including the basic KPI information, location
information, and query time, see the following figure.
**UPM Function Operation Guide**

## Copying A Performance Query Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. An existing query template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query]. The Performance Query tab is displayed. Select a query

template, and click [copy] in the Operation column of the template, see the following figure.

1. Click Copy. The page for modifying information is displayed, see the following figure. The
modification is the same as that when the template is created. The template name needs to
be modified.
5 Data Display

1. Except that the template name must be modified to be different, other parameters can be
modified or use the default values.

## Modifying A Performance Query Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. An existing query template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query] to switch to the Performance Query tab. Select a query template,

and click [modify] in the Operation column of the template, see the following figure.

1. After you click Modify, the page for filling in information is displayed. On the page for
modifying information, you can keep the default settings or modify the information. Click [
Save And Execute] after the modification, see the following figure.
**UPM Function Operation Guide**

## Performance Query Template Deletion

Prerequisite
1. System Login
2. The user has the permission to display data.
3. An existing query template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query] to switch to the Performance Query tab. Select a query template,

and click [Delete] in the Operation column of the template, see the following figure.

1. Click Delete. A confirmation dialog box is displayed. Click [Delete], see the following figure.
5 Data Display

1. After you confirm the deletion, the template is deleted successfully. The template is not
displayed on the page, but a prompt is displayed, see the following figure.

## Performance Query Template Statistics

Prerequisite
1. System Login
2. The user has the permission to display data.
3. An existing query template is created.
4. The probe is operating properly, and the existing resource data and performance data are

stored in the database.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query]. The Performance Query tab is displayed. Select a query

template, and click [copy] in the Operation column of the template, see the following figure.
**UPM Function Operation Guide**

1. Click Statistics. The data is displayed in accordance with the conditions in the template, see
the following figure.

## Exporting Performance Query Template Data

Prerequisite
1. System Login
2. The user has the permission to display data.
3. An existing query template is created.
4. The probe is operating properly, and the existing resource data and performance data are

stored in the database.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query] to switch to the Performance Query tab. Select a query template,

and click [query] in the Operation column of the template, see the following figure.
Figure 3→ Statistical Query39
5 Data Display

1. On the displayed page, click Export in the upper left corner, select the file format for saving
the exported data, and click [confirm] to export the data, see the following figure.

## Query Conditions

Prerequisite
1. System Login
2. The user has the permission to display data.
3. An existing query template is created.
4. The probe is operating properly, and the existing resource data and performance data are

stored in the database.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query]. The Performance Query tab is displayed. Select a query

template, and click [Query] in the Operation column of the template, see the following figure.
**UPM Function Operation Guide**

1. On the displayed page, click [show Conditions] in the upper left corner, see the following
figure.

1. The condition information of the statistics is displayed, see the following figure.

## Performance Data Query Page

Prerequisite
1. System Login
2. The user has the permission to display data.
3. An existing query template is created.
4. The probe is operating properly, and the existing resource data and performance data are

stored in the database.
Operation Path
5 Data Display

[Workspace]→[Performance]→[Data Demonstration]→[Performance Query]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Query]. The Performance Query tab is displayed. Select a query

template, and click [Query] in the Operation column of the template, see the following figure.

1. On the displayed page, click [] in the upper left corner. The page for modifying the query
conditions is displayed, see the following figure.

1. On the Condition Modify page, the data entered is the same as that added, see the following
figure.
**UPM Function Operation Guide**

## Threshold Management

In the performance data reported by the lower-level system, the values of many monitored
indicators may be abnormal. Common problems are as follows: The indicator value is too large
or is not reported. Abnormal indicators are usually accompanied by device errors or faults,
which require troubleshooting and conclusions. In a large amount of performance data, it is
difficult to identify abnormal indicators manually. In this case, you need to set thresholds for
indicators in the system to automatically determine and report alarms. This section describes
how to add, delete, modify, query, start, stop, export thresholds, and view reported alarms.
Function Description

Threshold Type                                   Function Description
**Normal Threshold**
Historical statistics threshold                  The real-time data should trigger an alarm by defining
a threshold formula.
**Complex threshold**
The threshold formula is defined to determine real-
Historical Synchronization Comparison Threshold  time data. When the number of times that data
continuously crosses the line meets the defined
requirements, an alarm is triggered.

Define a formula to compare the data occurrence time
with the average value within a period of time and the
data of the previous day. When the conditions are
met, an alarm is triggered.

Define a formula to compare the data occurrence time
with the average value within a period of time. When
the conditions are met, an alarm is triggered.

## Creating A Common Threshold

Prerequisite
5 Data Display

1. System Login
2. The user has the permission to display data.
3. The service package is installed properly.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Threshold Definition]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Threshold Definition]. The Threshold Management tab is displayed. Click [+Add

Threshold] in the upper left corner of the list, see the following figure.

1. Click New. The page for filling in the basic threshold information is displayed. The
verification with * is required. Click [Next], see the following figure.

1. Click Next. On the Threshold Alarm Formula Setting tab, click Formula Edit. The Formula
Setting tab is displayed, see the following figure.
**UPM Function Operation Guide**

1. On the Formula Edit page, after editing the formula, click Check to verify that the formula is
correctly expressed. Click [confirm], see the following figure.

1. After the formula is edited, click [Next] to select the effective period of the threshold alarm.
After the selection, click OK to directly save the configuration and exit the editing page.
By default, all NEs generate alarm information in accordance with the formula set for the
threshold alarm. Click Next to select some NEs to generate alarm information, see the
following figure.
5 Data Display

1. Click [Next] to select a specified NE, see the following figure.
1. Click [confirm]. The created threshold information is displayed, see the following figure.

## Creating Historical Statistics Thresholds

Prerequisite
**UPM Function Operation Guide**

1. System Login
2. The user has the permission to display data.
3. The service package is installed properly.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Threshold Definition]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Threshold Definition]. The Threshold Management tab is displayed. Click [+Add

Definition] in the upper left corner of the list, see the following figure.

1. Click New. The page for filling in the basic threshold information is displayed. The
verification with * is required. Click [Next], see the following figure.

1. Click Next. On the Threshold Alarm Formula Setting tab, click Formula Edit. The Formula
Setting tab is displayed, see the following figure.
5 Data Display

1. On the Formula Edit page, after editing the formula, click Check to verify that the formula is
correctly expressed. Click [confirm], see the following figure.

1. After the formula is edited, click [Next] to select the effective period of the threshold alarm.
After the selection, click OK to directly save the configuration and exit the editing page.
By default, all NEs generate alarm information in accordance with the formula set for the
threshold alarm. Click Next to select some NEs to generate alarm information, see the
following figure.
**UPM Function Operation Guide**

1. Click [Next] to select a specified NE, see the following figure.

1. Click [confirm]. The created threshold information is displayed, see the following figure.

## Creating A Complex Threshold

Prerequisite
1. System Login
2. The user has the permission to display data.
3. The service package is installed properly.
Operation Path
5 Data Display

[Workspace]→[Performance]→[Data Demonstration]→[Threshold Definition]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Threshold Definition]. The Threshold Management tab is displayed. Click [Add

Threshold] in the upper left corner of the list, see the following figure.

1. Click New. The page for filling in the basic threshold information is displayed. Set Threshold
Type to Complicated Operation. The verification with * is required. Click [Next], see the
following figure.

1. Click Next. On the Threshold Setting tab, select KPIs, set the basic information and upper
and lower alarm thresholds, and click [Next], see the following figure.
**UPM Function Operation Guide**

1. Click [Next] to select the validity period of the threshold alarm. After the selection, click [
confirm] to save the setting and exit the editing page. By default, all NEs generate alarm
information in accordance with the formula set for the threshold alarm. Select [Next] to
generate alarm information for some NEs, see the following figure.

1. Click Next to select the specified NE, see the following figure.

1. Click [confirm]. The created threshold information is displayed, see the following figure.
5 Data Display

## 4.2.4 Create Historical Period Comparison Threshold

Prerequisite
1. System Login
2. The user has the permission to display data.
3. The service package is installed properly.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Threshold Definition]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Threshold Definition]. The Threshold Management tab is displayed. Click [Add

Threshold] in the upper left corner of the list, see the following figure.
**UPM Function Operation Guide**

1. Click New. The page for filling in the basic information of the threshold is displayed. Set
Threshold Type to New Historical Period Comparison. The verification with * is required.
Click [Next], see the following figure.

1. Click Next. On the Threshold Setting tab, select KPIs, set the basic information and upper
and lower alarm thresholds, and click [Next], see the following figure.

1. Click [Next] to select the validity period of the threshold alarm. After the selection, click [
confirm] to save the setting and exit the editing page. By default, all NEs generate alarm
information in accordance with the formula set for the threshold alarm. Select [Next] to
generate alarm information for some NEs, see the following figure.
5 Data Display

1. Click Next to select the specified NE, see the following figure.
1. Click [confirm]. The created threshold information is displayed, see the following figure.
**UPM Function Operation Guide**

## Viewing Threshold Information

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Threshold Monitoring Template
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Threshold Definition]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Threshold Definition]. The Threshold Management tab is displayed. Select a threshold

management template, and click Template Name in the Template Name column, see the
following figure.

1. All the input information during creation is displayed, see the following figure.
5 Data Display

## Modifying Thresholds

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Threshold Monitoring Template
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Threshold Definition]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Threshold Definition]. The Threshold Management tab is displayed. Select a threshold

management template, and click [modify] in the Operation column of the template, see the
following figure.
**UPM Function Operation Guide**

After you click Modify, except the Basic Information tab, you can modify other parameters as
required.

## Start/Stop Threshold

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Threshold Monitoring Template
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Threshold Definition]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Threshold Definition]. The Threshold Management tab is displayed. Select a threshold

management template, and click the Slide button in the Threshold Status column of the
template, see the following figure.

1. The Start button is green, and the Stop button is white. You will be prompted to stop the
operation, see the following figure.
5 Data Display

## Threshold

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Threshold Monitoring Template
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Threshold Definition]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Threshold Definition]. The Threshold Management tab is displayed. Select a threshold

management template. Above the displayed list, enter a threshold name, select a threshold
status, and click [Filter], see the following figure.

1. Click Filter. The information is displayed, see the following figure.
**UPM Function Operation Guide**

## Delete Threshold

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Threshold Monitoring Template
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Threshold Definition]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Threshold Definition]. The Threshold Management tab is displayed. Select a threshold

management template, and click [Delete] in the Operation column of the template, see the
following figure.

1. Click Delete. A confirmation dialog box is displayed. Click OK, see the following figure.

1. After the deletion, the information on the page is updated, indicating that the deletion is
successful, see the following figure.
5 Data Display

## Performance Monitoring

When performance data is reported, the involved performance indicators usually have a certain
data range. When abnormal indicators exist in data reporting, for example, the data increases
suddenly, the data decreases sharply, or even the data is not reported yet. These abnormal
situations need to be visually displayed in real time for the monitoring personnel to check. This
procedure describes how to create, delete, view, and modify monitoring templates, and how to
view monitoring indicators.

## Creating A Group

Prerequisite
1. System Login
2. The user has the permission to display data.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Click [New group]

in the upper left corner of the list to fill in the information of the new group, see the following
figure.
**UPM Function Operation Guide**

1. Enter the information on the Group tab, and click [Create]. The group is created
successfully, see the following figure.

1. After the group is created successfully, the group information is displayed on the page, and
a message indicating that the group is created successfully is displayed, see the following
figure.

## Modifying Group Information

Prerequisite
1. System Login
2. The user has the permission to display data.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
5 Data Display

2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Select a group, and
click [modify] in the Operation column of the group, see the following figure.

1. On the Group Information Modify page, you can modify the basic information and query
template. Modify the information, and click [modify], see the following figure.

1. After the group information is modified, the information in the list is changed, and a success
prompt is displayed, see the following figure.
**UPM Function Operation Guide**

## Delete A Group

Prerequisite
1. System Login
2. The user has the permission to display data.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Select a group, and

click [Delete] in the Operation column of the group to delete the group, see the following
figure.

1. Click Delete. A confirmation dialog box is displayed. Click [Delete] in the confirmation dialog
box. The deletion function is performed properly, see the following figure.
5 Data Display

1. After the group information is deleted, the information in the list is changed, and a prompt is
displayed, see the following figure.

## Creating A TopN Monitoring Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. The probe is operating properly, and the existing resource data and performance data are

stored in the database.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Click [New Monitor]

in the upper left corner of the list, see the following figure.
**UPM Function Operation Guide**

1. Set Type to [TopN Monitor], see the following figure.

1. Select other information, and click [Monitor], see the following figure.

1. Click [Monitor]. The Data Monitor page is displayed, see the following figure.
5 Data Display

## Creating A Trend Monitoring Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. The probe is operating properly, and the existing resource data and performance data are

stored in the database.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Click [New Monitor]

in the upper left corner of the list, see the following figure.
**UPM Function Operation Guide**

1. Set Type to [Trend Monitor], see the following figure.
1. Select a location, and click New and Monitor, see the following figure.
5 Data Display

1. Click [Build And Monitor]. The Data Monitor page is displayed, see the following figure.

## Creating A Proportion Monitoring Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. The probe is operating properly, and the existing resource data and performance data are

stored in the database.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Click [New Monitor]

in the upper left corner of the list, see the following figure.

1. Set Type to [Proportion Monitor], see the following figure.
**UPM Function Operation Guide**

1. Select other information, and click New and Monitor. The location can be set as required,
see the following figure.

1. Click New Monitor. The Data Monitor page is displayed, see the following figure.
5 Data Display

## Creating A Year-on-Year Analysis Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. The probe is operating properly, and the existing resource data and performance data are

stored in the database.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Click [New Monitor]

in the upper left corner of the list, see the following figure.
**UPM Function Operation Guide**

1. Set Type to [Compare Analysis], see the following figure.

1. After selecting other information, click [Monitor]. You can only select one location, see the
following figure.

1. Click [Monitor]. The Data Monitor page is displayed, see the following figure.
5 Data Display

## Viewing Performance Monitoring Template Information

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Performance Monitoring Template
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Click Monitor Name

in the Name column, see the following figure.

1. The basic information and location information are displayed, see the following figure.

## Modifying A Performance Monitoring Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Performance Monitoring Template
Operation Path
**UPM Function Operation Guide**

[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Click [modify] in the

Operation column, see the following figure.

1. After modifying the information, click [Save], see the following figure.

## Performance Monitoring Template Data Monitoring

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Performance Monitoring Template
Operation Path
5 Data Display

[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
**Operation Steps**
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Click [Monitor] in

the Operation column, see the following figure.

1. The monitoring data is displayed, see the following figure.

## Delete A Performance Monitoring Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Performance Monitoring Template
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Click [Delete] in the

Operation column, see the following figure.
**UPM Function Operation Guide**

1. Click Delete. A confirmation dialog box is displayed. Click OK, see the following figure.
1. After the deletion succeeds, a prompt is displayed, see the following figure.

## Downloading Monitoring Figures

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Performance Monitoring Template
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The Performance Monitor tab is displayed. Click [Monitor] in

the Operation column, see the following figure.
5 Data Display

1. Click the Download button in the upper right corner of the data page to download the image,
see the following figure.

5.3.13 Year-on-year Analysis Monitoring Data Display Time Setting

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Performance Monitoring Template
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The performance monitoring page is displayed. Select a

monitoring template for year-on-year analysis, and click [Monitor] in the Operation column,
see the following figure.
**UPM Function Operation Guide**

1. Click the Setting button in the upper right corner of the Monitor Display Data page to set the
time, see the following figure.

1. In the displayed Modify Time dialog box, select the data to be compared and analyzed, and
click [confirm], see the following figure.

1. After the time setting is modified, the page is displayed, see the following figure.
5 Data Display

5.3.14 Viewing and Downloading The YoY Analysis Monitoring Data List

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Creating an Existing Performance Monitoring Template
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Performance Monitor]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Performance Monitor]. The performance monitoring page is displayed. Select a

monitoring template for year-on-year analysis, and click [Monitor] in the Operation column,
see the following figure.

1. Click Table in the upper right corner of the Monitor Display Data page, see the following
figure.
**UPM Function Operation Guide**

1. After you click the icon, a table is displayed, see the following figure.

## User-defined Statistics

Like performance query, this module is used by the web to query and display performance
data. Different from performance query, busy-hour data cannot be queried in this module. The
created templates are queried in real-time calculation and aggregation mode in accordance
with the query template conditions. That is, when the formula or aggregation mode of a
performance indicator is modified, the self-defined statistics function can be used to verify the
correctness of the modification in real time. It supports aggregation from small granularities
to large granularities, and real-time aggregation from lower-layer NEs to upper-layer NEs.
5 Data Display

This section describes how to add, delete, modify, and query user-defined statistical query
templates, aggregate data, drill data, and view statistical data.

## Creating A Group

Prerequisite
1.System Login
2.The user has the permission to display data.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1.Log in to the system. On the home page of the system, click [Data Demonstration]. The data
display page is displayed.
2.Click [Custom Statistics]. The user-defined statistics page is displayed. Click [New group] in
the upper left corner of the list to fill in the information of the new group, see the following figure.

1.Enter the information on the Group tab, and click [New]. The group is created successfully,
see the following figure.

1.After the group is created successfully, the group information is displayed on the page, and a
message indicating that the group is created successfully is displayed, see the following figure.
**UPM Function Operation Guide**

## Modifying Group Information

Prerequisite
1. System Login
2. The user has the permission to display data.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The Custom Statistics tab is displayed. Select a group, and click

[modify] in the Operation column of the group to modify the group information, see the
following figure.

1. On the Group Information Modify page, you can modify the basic information and query
template. Modify the information, and click [modify], see the following figure.
5 Data Display

1. After the group information is modified, the information in the list is changed, and a success
prompt is displayed, see the following figure.

## Delete A Group

Prerequisite
1. System Login
2. The user has the permission to display data.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The Custom Statistics tab is displayed. Select a group, and click [

Delete] in the Operation column of the group to delete the group, see the following figure.
**UPM Function Operation Guide**

1. Click Delete. A confirmation dialog box is displayed. Click [Delete] in the confirmation dialog
box. The deletion function is performed properly, see the following figure.

1. After the group information is deleted, the information in the list is changed, and a prompt is
displayed, see the following figure.

## New User-defined Statistics Template → General Query

Prerequisite
1. System Login
5 Data Display

2. The user has the permission to display data.
3. The service package is installed properly and can be used.
4. System with resources and performance data
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics page is displayed. Click [New Query] in

the upper left corner of the page to add a query template, see the following figure.

1. On the Select Resource Type tab of the New Query window, enter the template name and
select a resource type. After the PO granularity, select one or more indicators, and click [
Next], see the following figure.

1. Click Next. The time resource aggregation is not aggregated by default. The query time is
set to the last day by default. You can modify the query time as required. After setting the
valid time period, click [Next], see the following figure.
**UPM Function Operation Guide**

1. Click Next. In the Location area, select All NEs by default. If you need to query the data
of a specific NE or a batch of NEs, You can manually select NEs, or export all the current
NEs and edit them to keep the NEs to be queried. After NE data is imported, the maximum
number of NEs to be queried is 1500. Click [statistics], see the following figure.

1. The following figure shows the common data statistics page.

5.4.5 Creating A Customized Statistics Template for →→ Drilling

Prerequisite
5 Data Display

1. System Login
2. The user has the permission to display data.
3. The service package is installed properly and can be used.
4. System with resources and performance data
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics page is displayed. Click [New Query] in

the upper left corner of the page to add a query template, see the following figure.

1. On the Select Resource Type tab of the New Query window, enter the template name and
select a resource type. After the PO granularity, select one or more indicators, and click [
Next], see the following figure.

1. Click Next. The time resource aggregation is not aggregated by default. In this step,
resources are aggregated to the upper layer, and the time is aggregated to a large
granularity. The query time is usually the last day by default. You can modify the query time
as required. After setting the valid time period, click [Next], see the following figure.
**UPM Function Operation Guide**

1. Click Next. In the Location area, select All NEs by default. If you need to query the data
of a specific NE or a batch of NEs, You can manually select NEs, or export all the current
NEs and edit them to keep the NEs to be queried. After NE data is imported, the maximum
number of NEs to be queried is 1500. Click [Save And Statistics], see the following figure.

1. On the data statistics page, you can drill the resource time to the lower layer, see the
following figure.
5 Data Display

## Customizing A Statistics Template →→ Creating A Graph

Prerequisite
1. System Login
2. The user has the permission to display data.
3. The service package is installed properly and can be used.
4. System with resources and performance data
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics page is displayed. Click [New Query] in

the upper left corner of the page to add a query template, see the following figure.
Figure → Create Query4139

1. On the Select Resource Type tab of the New Query window, enter the template name and
select the resource type. After the PO granularity, select one or more indicators, and click
Next, see the following figure.
**UPM Function Operation Guide**

1. Click Next. The time resource aggregation is not aggregated by default. The query time is
set to the last day by default. You can modify the query time as required. After setting the
valid time period, click [Next], see the following figure.

1. Click Next. In the Location area, select All NEs by default. If you need to query the data
of a specific NE or a batch of NEs, You can manually select NEs, or export all the current
NEs and edit them to keep the NEs to be queried. After NE data is imported, the maximum
number of NEs to be queried is 1500. Click [Next], see the following figure.

1. Click [Save And Statistics] to query the data. If you save the data as a template in Step 1, it
is [Save And Statistics], see the following figure.

1. Click Statistics. The queried data is displayed. Select Display Graph > Create Graph. The
Graph page is displayed, see the following figure.
5 Data Display

1. Create a graph, and click OK to generate a graph in accordance with the design, see the
following figure.

1. Data Statistics Tab with Graphs
**UPM Function Operation Guide**

## Viewing Customized Statistics Template Information

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A customized statistics template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics query page is displayed. Select a query

template, and click Template Name in the Template Name column, see the following figure.

1. The basic information, time, and location are displayed, see the following figure.
5 Data Display

## Copying A Customized Statistics Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A customized statistics template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics query page is displayed. Select a query

template, and click [copy] in the Operation column of the template, see the following figure.

1. After you click Copy, the same page flow is displayed. The difference is that the basic
information is already selected, but the name needs to be modified. After you click Save, it is
equivalent to adding a new page, see the following figure.
**UPM Function Operation Guide**

## Modifying A Customized Statistics Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A customized statistics template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The Custom Statistics Query page is displayed. Select a query

template, and click [modify] in the Operation column of the template, see the following
figure.
5 Data Display

1. After you click Modify, the same page flow is displayed. The difference is that the query
template is not added even if the query template and basic information are selected and
modified, see the following figure.

## User-defined Statistics Template Data Statistics

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A customized statistics template is created.
**UPM Function Operation Guide**

Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics query page is displayed. Select a query

template, and click [statistics] in the Operation column of the template, see the following
figure.

1. After you click Statistics, data is queried in accordance with the conditions set in the
template, see the following figure.
5 Data Display

## Deleting A Customized Statistics Template

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A customized statistics template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics query page is displayed. Select a query

template, and click [Delete] in the Operation column of the template, see the following figure.

1. Click Delete. A confirmation dialog box is displayed. Click Delete again. The template is
deleted, see the following figure.
**UPM Function Operation Guide**

1. After the deletion succeeds, a prompt is displayed, see the following figure.

## Exporting Customized Statistics

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A customized statistics template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics query page is displayed. Select a query

template, and click [statistics] in the Operation column of the template, see the following
figure.
5 Data Display

1. On the displayed page, click Export in the upper right corner, that is, the icon under the
arrow in the following figure. Select the format of the exported data storage file, and click [
confirm] to export the data, see the following figure.

## Customizing Statistics Page Graphs

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A user-defined statistics template with graphs is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics query page is displayed. Select a query

template with a graph, and click [Statistics] in the Operation column of the template, see the
following figure.
**UPM Function Operation Guide**

1. Click the chart button in the upper right corner of the queried data display page. If multiple
graphs are created, you can drag them with the left mouse button to move the graph, see
the following figure.

## Modify Condition Dialog Box

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A customized statistics template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics query page is displayed. Select a query

template, and click [statistics] in the Operation column of the template, see the following
figure.

1. On the displayed page, click [show conditions] in the upper left corner, see the following
figure.
5 Data Display

1. The basic information, time, and location are displayed, see the following figure.

## Modifying Customized Statistical Data Conditions

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A customized statistics template is created.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Custom Statistics]
Operation Steps
1. Log in to the system. On the home page of the system, click [Data Demonstration]. The data

display page is displayed.
2. Click [Custom Statistics]. The user-defined statistics query page is displayed. Select a query

template, and click [statistics] in the Operation column of the template, see the following
figure.
**UPM Function Operation Guide**

1. On the displayed page, click [Modify Conditions] in the upper left corner, see the following
figure.

1. After you click the button, the same page flow is displayed. The difference is that the query
template is not added even if the basic information is selected and modified.

## Current Alarms

When the UPM performance data is collected into the database, for the abnormal KPIs reported
by the lower level, the alarm information of the corresponding level is generated through the
threshold crossing condition set in the threshold alarm area. For the alarm generation time and
the number of involved NEs, the corresponding information can be viewed here, and can be
compared with the UFM interconnected with the alarm information. For an NE with a threshold
alarm, only the latest alarm information is recorded.

5.5.1 Advanced Query of Active Alarms

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Collection and warehousing of performance data and resource data
4. A threshold alarm rule is created.
Operation Path
5 Data Display

[Workspace]→[Performance]→[Data Demonstration]→[Current Alarm]
Operation Steps
1. Log in to the system. On the home page of the system, click [Current Alarm]. The Current

Alarm page is displayed, see the following figure.

1. Click Advanced Query in the upper right corner of the Current Alarm window. Set the query
conditions in Advanced Query, and click Query. The current alarms are filtered, see the
following figure.
**UPM Function Operation Guide**

## Historical Alarms

For the alarms generated when the threshold exceeds the threshold in the UPM, if the
conditions for clearing alarms are set in the threshold setting, when the indicator reaches the
set value, the alarm information in the current alarm will be processed as a history alarm, which
cannot be found on the current alarm page, and the clearing reason can be found in the history
alarm. If no alarm clearing condition is set for the threshold, the alarm is handled in accordance
with the alarm handling rules of the UFM. After the alarm is handled by the maintenance
personnel, the UFM returns a message indicating that the alarm is handled, and generates
historical alarms.

5.6.1 Advanced Query of Historical Alarms

Prerequisite
1. System Login
2. The user has the permission to display data.
3. Collection and warehousing of performance data and resource data
4. A threshold alarm rule has been created, and an alarm is cleared.
Operation Path
[Workspace]→[Performance]→[Data Demonstration]→[Current Alarm]
Operation Steps
1. Log in to the system. On the home page of the system, click [History Alarm]. The historical

alarm page is displayed, see the following figure.
5 Data Display

1. Click Advanced Query in the upper right corner of a historical alarm, set query conditions
in the Advanced Query window, and click Query. The historical alarms are filtered, see the
following figure.

KPI Dashboard

Table of Contents

Monitoring Template Settings...................................................................................................188
Scaling of The Monitoring Interface......................................................................................... 190
Viewing Monitoring Details....................................................................................................... 191
During the performance data reporting process, if there is no large-scale power outage or
fault on the involved NEs, the indicator data generally does not fluctuate greatly. Under the
corresponding monitored NEs and indicators, the data trend trend within a period of time
generally overlaps. Therefore, when the indicator fluctuates greatly, you need to troubleshoot
it in a timely manner. In addition, you need to use the KPI Dashboard function to calculate
the real-time monitoring of indicators and present them in the form of a curve. This procedure
describes how to use the KPI Dashboard to set KPI monitoring and view KPI details.
This chapter includes the following topics:
 Monitoring Template Settings
 Scaling of the Monitoring Interface
 Viewing Monitoring Details

## Monitoring Template Settings

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A year-on-year analysis monitoring template is created on the performance monitoring side.
4. Collection and warehousing of performance data and resource data
Operation Path
[Workspace]→[Performance]→[KPI Dashboard]
Operation Steps
1. Log in to the system. On the home page of the system, click [KPI Dashboard]. The KPI

Report Monitor page is displayed.
2. Click Network KPI to switch to the KPI monitoring page of the entire network. Click the

button in the upper left corner of the monitoring page to switch to the monitoring page. You
can add a monitoring template for each monitoring page as required. Different monitoring
6 KPI Dashboard

templates on different pages do not affect each other. That is, a single indicator can be used
on multiple pages, see the following figure.

Note: The operations of creating monitoring information on the Network KPI, CN KPI, RAN
KPI, and MBB&WLBB are the same. This procedure uses the Network KPI as an example to
describe how to create and view other monitoring templates.
1. Click Settings in the upper right corner to set the monitoring template as required, see the

following figure.

1. In the displayed dialog box, you can set the time for monitoring comparison and select a
performance monitoring template. Select a template and set the time, and click [Confirm],
see the following figure.
**UPM Function Operation Guide**

1. The monitoring page displays data in accordance with the number of selected templates and
the set time, see the following figure.

6.2 Scaling of The Monitoring Interface

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A year-on-year analysis monitoring template is created on the performance monitoring side.
4. A template is added on the monitoring page.
Operation Path
[Workspace]→[Performance]→[KPI Dashboard]
Operation Steps
1. Log in to the system. On the home page of the system, click [KPI Dashboard]. The KPI

Report Monitor page is displayed.
2. Click Network KPI to switch to the KPI monitoring page of the entire network. Click in the

upper left corner of the monitoring page to switch to the page where you want to monitor
indicators, see the following figure.
6 KPI Dashboard

1. Tap the Zoom button in the upper right corner to switch between full screen or normal
display, see the following figure.

1. On the full-screen monitoring page, tap the Zoom button again. The normal web screen is
displayed, see the following figure.

1. After zooming out, the normal page is displayed when the web is in initial status, see the
following figure.

## Viewing Monitoring Details

Prerequisite
1. System Login
2. The user has the permission to display data.
3. A template is added on the monitoring page.
Operation Path
[Workspace]→[Performance]→[KPI Dashboard]
Operation Steps
**UPM Function Operation Guide**

1. Log in to the system. On the home page of the system, click [KPI Dashboard]. The KPI
Report Monitor page is displayed.

2. Click Network KPI to switch to the Network-wide KPI Monitoring page.Click the top-right
corner of the monitoring page to switch to the bar chart display page; refer to the figure
below.

1. Switch graphics.

Display after switching

Support

Table of Contents

Data Connection.......................................................................................................................193
Script......................................................................................................................................... 205
Report....................................................................................................................................... 213
KPI Predict................................................................................................................................218
Report Template Management.................................................................................................218

This section primarily introduces the routine operations of support tools. Reports provide default
self-monitoring templates for the UPM data storage calculation process, and customized
graphical interfaces can be used to view charts. Additionally, scheduled push notifications
are available by setting customized charts to various formats and sending them periodically
to specified FTP servers or accessible email addresses. It also covers the routine operations
of the script executor, script repository management, and script task management functions,
offering a comprehensive script management interface for customizing scripts and completing
scheduled tasks
This chapter includes the following topics
report
script
KPI predict
Report Template Management
Data Connection

## Data Connection

Provide database, SSH, FTP/SFTP, and email connection methods for report tasks and script
tools

## Database

## Creating A Data Source

Prerequisite
1. System Login
**UPM Function Operation Guide**

2. The user has the operation permission of script connection.
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [Database]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. In the left function module, click the [Data Connection] menu to enter the database display

page. By default, there are two connection entries on the right side. The initial connection for
PMS_AP needs to be modified, as shown in the figure below:

3. Click the [New Data Source] button and fill in the connectable data source information
according to the prompts, as shown in the figure below:

4. Field                   Description
Select different driver modes based on the
Data Source Type  database being used
7 Support

**Field            Description**

IP/Service Name  Connect to the device where the database is
located via IP/service name

Port             The port occupied by the database

Username         The user name for logging into the database

Password         The password for logging into the database

Database Name    The name of the database

5. After filling in all fields, click the [Test] button to verify whether the connection information
is correct. Once the test passes, click the [Confirm] button to automatically return to the
data source home page, where you can see the newly created data source, as shown in the
figure below:

## Modifying A Data Source

Prerequisite
1. System Login
2. The user has the operation permission of script connection.
3. There are data sources that can be connected.
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [Database]
Operation Steps
1. Log in to the system. On the home page of the system, click Script Connector. The script

connection page is displayed.
On the Script Connection page, click [dataBase]. The Database Connection Management page
is displayed, see the following figure.
**UPM Function Operation Guide**

2. Click [modify], see the following figure.

3. Click [test] to verify that the database connection is normal.
4. Click [confirm] to save the database connection.

## Delete A Data Source

Prerequisite
1. System Login
2. The user has the operation permission of script connection.
3. There is a completed data source.
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [Database]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. In the left function module, click the [Data Connection] menu to enter the database page.
3. Click the [Delete] button on the right side of the target data source to delete it, as shown in

the figure below:
7 Support

1. Click [Delete], see the following figure.

## FTP/SFTP Connection Management

## SFTP New

Prerequisite
1. System Login
2. Available FTP/SFTP
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [FTP/SFTP]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. In the left function module, click the [Data Connection ] menu.
3. Click the [FTP/SFTP] button to display the FTP/SFTP configuration page, as shown in the

figure below:
**UPM Function Operation Guide**

4. Click +New FTP/SFTP to create the data source, as shown in the figure below.

5. Click [test]. Verify that the FTP connection is normal.
6. Click [confirm] to save the FTP connection.

## SFTP Modification

Prerequisite
1. System Login
2. The user has the operation permission of script connection.
3. There are data sources that can be connected.
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [FTP/SFTP]
Operation Steps
1. Log in to the system and click on 'Support' on the main page to enter the report viewing

page
2. In the left functional module, select FTP/SFTP and enter the FTP/SFTP page
3. The FTP/SFTP page displays all created FTP/SFTP connections, as shown in the figure:

4. Click [modify], see the following figure.
7 Support

5. Click [test]. Verify that the FTP connection is normal.
6. Click [confirm] to save the FTP connection.

## SFTP Deletion

Prerequisite
1. System Login
2. The user has the operation permission of script connection.
3. There is a completed data source.
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [FTP/SFTP]
Operation Steps
1. Log in to the system and click on 'Support' on the main page to enter the report viewing

page
2. In the left functional module, select FTP/SFTP and enter the FTP/SFTP page
3. Click the [Delete] button on the right side of the target FTP/SFTP to delete the task target.

The scheduled push tasks that have been created in the report task cannot be deleted, as
shown in the figure:

1. Click [Delete], see the following figure.
**UPM Function Operation Guide**

## SSH Connection Management

## Adding An SSH Connection

Prerequisite
1. System Login
2. Available SSH
Operation path
[Workbench] → [Performance] → [Support] → [Data Connection] → [SSH]
operating steps
1. Log in to the system and click on 'Support' on the main page to enter the report viewing page
2. In the left functional module, click on the 'Data Connection Configuration' menu
3. Click the [SSH] button to display the FTP/SFTP configuration page, as shown in the figure:

4. Click +New SSH connection to create the data source, as shown in the figure below.
7 Support

5. Click [test]. Verify that the SSH connection is normal.
6. Click [confirm] to save the SSH connection.

## SSH Connection Modification

Prerequisites
1. System login is normal
2. User has operation permissions
3. SSH connection has been created
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [SSH]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. In the left function module, select SSH to enter the SSH page.
3. The SSH page displays all created SSH connections, as shown in the figure below:

4. Only correct SSH connections can be successfully created. When the information of an
SSH connection changes and causes scheduled tasks to fail, you need to modify the SSH
connection. Click the [Modify] button on the right side of the SSH connection to enter the
modification page. After completing the modification, click the [Test] button. Once the test
passes, click [Confirm] to apply the changes, as shown in the figure below:
**UPM Function Operation Guide**

## SSH Connection Deletion

Prerequisites
 System login is normal
 User has operation permissions
 SSH connection has been created
 No scheduled tasks require the target SSH to be deleted
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [SSH]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. In the left function module, select SSH to enter the SSH page.
3. Click the [Delete] button on the right side of the target SSH connection to delete it. Note that

SSH connections with existing scheduled push tasks in report tasks cannot be deleted, as
shown in the figure below:

4. After confirming the deletion, a success message will appear in the upper right corner, and
the deleted SSH information will no longer be displayed on the page.

## Email

## New Email

Prerequisites
 System login is normal
 An available email account exists
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [Email]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. On the report page, click the [Data Connection Configuration] menu.
3. Click the [Email] button to display the email configuration page, as shown in the figure

below:
7 Support

4. Click the [+ New Email] button to enter the creation page. Fill in the correct email information
according to the prompts, as shown in the figure below:

5. After filling in all information, click the [Confirm] button to automatically return to the email
home page, where you can see the newly created email account.

## Modify Email

Prerequisites
 System login is normal
 User has operation permissions
 An email account has been created
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [Email]
Operation Steps
**UPM Function Operation Guide**

1. Log in to the system. On the main page of the system, click [Support] to enter the report
viewing page.

2. On the report page, click the [Data Connection] menu.
3. Click the [Email] button to display the email configuration page, as shown in the figure

below:

4. When the information of an email account changes, you need to modify it. Click the [Modify]
button on the right side of the email account to enter the modification page. After completing
the modification, click the [Confirm] button. The system will then return to the email display
page, where you can see the updated email account, as shown in the figure below:

## Delete Email

Prerequisites
 System login is normal
 User has operation permissions
 An email account has been created
7 Support

 No scheduled tasks require the target email to be deleted
Operation Path
[Workbench] → [Performance] → [Support] → [Data Connection] → [Email]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. In the left function module, click the [Data Connection] menu, select Email, and enter the

email page.
3. Click the [Delete] button on the right side of the target email account to delete it. Note that

email accounts with existing scheduled push tasks in report tasks cannot be deleted, as
shown in the figure below:

4. After confirming the deletion, a success message will appear in the upper right corner, and
the deleted email information will no longer be displayed on the page.

## Script

This section describes the common operations of the script executor. The script executor
provides script connection management, script repository management, and script task
management functions, and provides a good script management page.Customizes scripts and
completes scheduled tasks.
This chapter includes the following topics:
 Script repository
 Script task
 File upload

## Script Repository

## Script Group Management
## Creating A Group

Prerequisite
1. System Login
**UPM Function Operation Guide**

2. The user has the operation permission of script connection.
Operation Path
[Workbench] → [Performance] → [Support] → [Scripts] → [Script Repository]
Operation Steps
1. Log in to the system. On the home page of the system, click [script_repository]. The Script

Repository Management page is displayed.
2. On the Warehouse Connection page, click [New group]. The page for adding a group is

displayed, see the following figure.

1. Click [confirm].

## Delete A Group

Prerequisite
1. System Login
2. The user has the operation permission of script connection.
3. The script group already exists.
Operation Path
[Workbench] → [Performance] → [Support] → [Scripts] → [Script Repository]
Operation Steps
1. Log in to the system. On the home page of the system, click [script_repository]. The Script

Repository Management page is displayed.
2. In the navigation bar on the left, click....The Operation dialog box is displayed. Click [Delete],

see the following figure.
7 Support

Click [Delete].

## Script File Management

## View Script
Prerequisites
 System login is normal
 User has script connection operation permissions
 The script already exists
Operation Path
[Workbench] → [Performance] → [Support] → [Scripts] → [Script Repository]
Operation Steps
1. Log in to the system. On the main page of the system, click [Script Repository] to enter the
script repository management page.
2. On the script management page, select the [Details] button on the right side of the script you
want to view, as shown in the figure below:

3. View the script information on the pop-up details page, as shown in the figure below:
**UPM Function Operation Guide**

## Script Task

## Script Task Group Management

## Creating A Group
Prerequisite
1. System Login
2. The user has the operation permission of script connection.
Operation Path
[Workbench] → [Performance] → [Support] → [Scripts] → [Script Task]
Operation Steps
1. Log in to the system. On the home page of the system, click [Script task]. The Script Task
Management page is displayed.
2. On the Scheduled Task page, click [New group]. The page for adding a scheduled task
group is displayed, see the following figure.
7 Support

1. Click [confirm].
## Delete A Group

Prerequisite
1. System Login
2. The user has the operation permission of script connection.
3. The script task group already exists.
Operation Path
[Workbench] → [Performance] → [Support] → [Scripts] → [Script Task]
Operation Steps
1. Log in to the system. On the home page of the system, click [Script task]. The Script Task

Management page is displayed.
2. On the Scheduled Task page, click [Delete]. The Delete Scheduled Task Group page is

displayed, see the following figure.
**UPM Function Operation Guide**

1. Click [Delete].

## Script Task Management

## Creating A Script Task
Prerequisite
1. System Login
2. The user has the operation permission of script connection.
3. The connection is configured and available.
4. The script repository is added.
Operation Path
[Workbench] → [Performance] → [Support] → [Scripts] → [Script Task]
Operation Steps
1. Log in to the system. On the home page of the system, click [Script task]. The Script Task
Management page is displayed.
2. On the Scheduled Task page, click [Create]. The page for adding a scheduled task is
displayed, see the following figure.

1. Set the parameters in the dialog box that is displayed, see the following figure.
7 Support

1. Click [confirm].

## Delete A Script Task
Prerequisite
1. System Login
2. The user has the operation permission of script connection.
3. The connection is configured and available.
4. The script repository is added.
5. The script task already exists.
Operation Path
[Workbench] → [Performance] → [Support] → [Scripts] → [Script Task]
Operation Steps
1. Log in to the system. On the home page of the system, click [Script task]. The Script Task
Management page is displayed.
2. On the Scheduled Task page, click [Delete]. The Delete Scheduled Task page is displayed,
see the following figure.

1. In the displayed dialog box, click [Delete].

## Modify Script Task
Prerequisites
 System login is normal
**UPM Function Operation Guide**

 User has script connection operation permissions
 Connection has been configured and is available
 New scripts have been added to the script repository
 Script tasks already exist
Operation Path
[Workbench] → [Performance] → [Support] → [Scripts] → [Script Tasks]
Operation Steps
1. Log in to the system. On the main page of the system, click [Script Tasks] to enter the script

task management page.
2. On the scheduled tasks page, click the [Modify] button to enter the modify scheduled task

page, as shown in the figure below:

3. Click the [Confirm] button to complete the modification.

## File upload

Prerequisites
 System login is normal
 User has script connection operation permissions
Operation Path
[Workbench] → [Performance] → [Support] → [Scripts] → [File Upload Management]
Operation Steps
1. Log in to the system. On the main page of the system, click [File Upload Management] to

enter the file upload management page.
7 Support

2. Click Upload File to transfer local files to the server for use by other services.

## Upload file

Prerequisites
 System login is normal
 User has script connection operation permissions
Operation Path
[Workbench] → [Performance] → [Support] → [Scripts] → [File Upload]
Operation Steps
1. Log in to the system. On the main page of the system, click [File Upload] to enter the file

upload management page.
2. Click Upload File to transfer local files to the server for use by other services.

## Report

This section describes the common operations of ad-hoc reports. By default, ad-hoc reports
provide a self-monitoring template for the calculation flow of storing UPM data into the
database. In addition, ad-hoc reports can also provide GUI-based charts and push them at
scheduled time. By setting customized charts in multiple formats, ad-hoc reports are sent to the
specified FTP or mailboxes that can be accessed at scheduled time.
This chapter includes the following topics:
 Report View
**UPM Function Operation Guide**

 Report Task

## Report Task

## Creating A Scheduled Push Task

Prerequisite
1. System Login
2. Available FTP/SFTP or mailbox
3. Template Created
Operation Path
[Workspace]→[Performance]→[Support]→[report]→[Report Task]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. On the report page, click the [Report Tasks] menu.
3. Click the [+ New Scheduled Push] button to enter the creation page. Fill in the correct

information according to the prompts:Custom Cron Expression:{Seconds} {Minutes} {Hours}
{Day of Month} {Month} {Day of Week} {Year (optional)}Example:0 15 10 ? * * (Executes the
task at 10:15 AM every day), as shown in the figure below:

4. After the configuration, click [confirm] to return to the home page of the scheduled task. The
created scheduled task is displayed.
7 Support

## Manually Executing A Task

Prerequisite
1. System Login
2. Scheduled Task Created
Operation Path
[Workspace]→[Performance]→[Support]→[report]→[Report Task]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. On the report page, click the [Report Tasks] menu.
3. On the expanded report task page, click Execute on the right of the target task. A prompt

is displayed in the upper right corner, indicating whether the task has been sent. Under the
arrow of the target task details, you can expand to check whether the report is exported
normally, see the following figure.

## Modifying A Scheduled Task

Prerequisite
1. System Login
**UPM Function Operation Guide**

2. Scheduled Task Created
Operation Path
Workspace]→[Performance]→[Support]→[report]→[Report Task]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. On the report page, click the [Report Tasks] menu.
3. On the expanded report task page, click [modify] on the right of the target. The page for

modifying the task is displayed. After the modification, the system returns to the homepage
of the scheduled task, see the following figure.

## Deleting A Scheduled Task

Prerequisite
1. System Login
2. Scheduled Task Created
Operation Path
Log in to the system. On the main page of the system, click [Support] to enter the report viewing
page.
On the report page, click the [Report Tasks] menu.
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. On the report page, click the [Report Tasks] menu.
7 Support

3. On the expanded report task page, click [Delete] on the right of the target. After the
modification is successful, the system returns to the homepage of the scheduled task. There
is no information about the deleted scheduled task on this page, see the following figure.

## Report View

Operation Path
[Workbench] → [Performance] → [Support] → [Reports] → [Report View]
Operation Steps
1. Log in to the system. On the main page of the system, click [Support] to enter the report

viewing page.
2. On the report page, click the [Report View] menu.
3. In the expanded report view page, view the data you need. For example, the UPM Data

Processing Status Table shown below, as illustrated in the figure:
**UPM Function Operation Guide**

## KPI Predict

This feature is not yet available for use

## Report Template Management

 Report Management: Manage and configure page reports
 SQL Management: Handle SQL queries for report data
 Element Management: Modify key elements in reports (data, thresholds, etc.)
 Layout Management: Adjust report layout and display
Note: These features are typically predefined by R&D teams for end users to utilize directly
without requiring modifications.

## Report Management

Prerequisites
 System login is successful
 User has permissions to add and modify reports
Operation Path 【Workbench】→【Performance】→【Support】→【Report Template
Management】→【Report Management】
Operation Steps
1. Log in to the system. On the main page, click 【Support】to enter the report viewing page.
2. Click the 【Report Template Management】menu to enter the 【Report Management】

page.
3. Click 【New Template】to enter the creation page. Fill in the correct information according

to the prompts, as shown below:
# Support

4. Modify template: Click the modify button behind the corresponding template to enter the
modification page. Except for the name, all other fields can be modified.

## Element Management

Prerequisites
 System login is successful
 User has permissions to add and modify elements
Operation Path 【Workbench】→【Performance】→【Support】→【Report Template
Management】→【Element Management】
Operation Steps
**UPM Function Operation Guide**

1. Log in to the system. On the main page, click 【Support】to enter the report viewing page.
2. Click the 【Report Template Management】menu to enter the 【Element Management】

page.
3. Click New Element to enter the element creation page for reports, as shown below:

4. After confirmation and returning to the previous page, you can click Modify to view details.

## Layout Management

Prerequisites
 System login is successful
 User has permissions to add and modify report layouts
Operation Path 【Workbench】→【Performance】→【Support】→【Report Template
Management】→【Layout Management】
Operation Steps
1. Log in to the system. On the main page, click 【Support】to enter the report viewing page.
7 Support

2. Click the 【Report Template Management】menu to enter the 【Layout Management】
page.

3. Click New Layout to enter the layout creation page, where you can create your desired
report page layout, as shown below:

## SQL Management

Prerequisites
 System login is successful
 User has permissions to add and modify report layouts (or SQL queries)
Operation Path 【Workbench】→【Performance】→【Support】→【Report Template
Management】→【SQL Management】
Operation Steps
1. Log in to the system. On the main page, click 【Support】to enter the report viewing page.
2. Click the 【Report Template Management】menu to enter the 【SQL Management】page.
**UPM Function Operation Guide**

3. Click New SQL to enter the SQL creation page, where you can create your desired report
data query, as shown below:

4. After clicking Confirm, the system automatically returns to the previous page, where you can
click Modify to view details.
