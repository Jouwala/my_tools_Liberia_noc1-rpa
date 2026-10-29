iMind

eFlow Function Operation Guide

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

1 Configuration.......................................................................................................... 1

1.1 System User........................................................................................................................ 1
1.2 Configuring CMDB Personnel............................................................................................. 6
1.3 Event Configuration Procedure........................................................................................... 9
1.4 Configuring Preventive Maintenance Items.......................................................................12
1.5 SMS Notification Configuration for Major Faults............................................................... 14

2 User Group........................................................................................................... 15

2.1 Creating A User Group..................................................................................................... 15
2.2 Modifying A User Group....................................................................................................16
2.3 Delete A User Group.........................................................................................................17
2.4 Querying User Groups...................................................................................................... 18
2.5 User Group Management..................................................................................................19

3 Roles and Processes...........................................................................................23

3.1 Fault Ticket Roles and Processes.................................................................................... 25
3.1.1 Role.......................................................................................................................25
3.1.2 Procedure..............................................................................................................25

3.2 Work Order Roles and Processes.................................................................................... 26
3.2.1 Role.......................................................................................................................26
3.2.2 Procedure..............................................................................................................27

3.3 Scenario.............................................................................................................................28
3.3.1 Simple Troubleshooting Scenarios....................................................................... 28
3.3.2 Complicated Troubleshooting Scenarios.............................................................. 28

4 Trouble Ticket(Product).......................................................................................30

4.1 Creating A Trouble Ticket................................................................................................. 30
4.2 Terminating A Trouble Ticket............................................................................................ 32
4.3 Refresh The Trouble Ticket List........................................................................................33
4.4 Querying Trouble Tickets.................................................................................................. 34
4.5 Exporting Trouble Tickets..................................................................................................35
4.6 Handliong A Trouble Ticket...............................................................................................37
4.7 Workflow History................................................................................................................39
4.8 Site Alarm.......................................................................................................................... 40
4.9 TT Dashboard....................................................................................................................41

5 Work Order(Product)............................................................................................42
5.1 Creating A Work Order..................................................................................................... 42
5.2 Terminating A Work Order................................................................................................ 43
5.3 Refresh The Work Order List............................................................................................44
5.4 Querying Work Orders...................................................................................................... 45
5.5 Exporting Work Orders......................................................................................................46
5.6 Handling A Work Order.....................................................................................................49
5.7 Workflow History................................................................................................................52
5.8 FLM Dashboard................................................................................................................. 53

6 Trouble Ticket&&Work Ticket............................................................................. 55

6.1 Trouble Ticket....................................................................................................................55
6.1.1 Creating A Trouble Ticket.................................................................................... 55
6.1.2 Terminating A Trouble Ticket............................................................................... 57
6.1.3 Discarding A Trouble Ticket................................................................................. 58
6.1.4 Refresh The Trouble Ticket List........................................................................... 60
6.1.5 Updating A Trouble Ticket....................................................................................61
6.1.6 Querying Fault Tickets..........................................................................................62
6.1.7 Exporting A Trouble Ticket................................................................................... 64
6.1.8 Handling A Trouble Ticket.................................................................................... 64
6.1.9 Workflow History...................................................................................................72
6.1.10 Site Alarm........................................................................................................... 73

6.2 Work Order........................................................................................................................ 74
6.2.1 Creating A Work Order.........................................................................................74
6.2.2 Refresh The Work Order List............................................................................... 76
6.2.3 Work Order Statistics List.....................................................................................77
6.2.4 Discarded Work Order..........................................................................................78
6.2.5 Querying Work Orders..........................................................................................79
6.2.6 Exporting A Work Order....................................................................................... 82
6.2.7 Terminating A Work Order................................................................................... 82
6.2.8 Exporting A Work Order Template....................................................................... 83
6.2.9 Handling A Work Order........................................................................................ 84
6.2.10 Updating A Work Order......................................................................................87
6.2.11 Workflow History.................................................................................................88

7 Spare Parts........................................................................................................... 90

7.1 Material Management........................................................................................................ 90
7.1.1 New Materials....................................................................................................... 90
7.1.2 Import Materials.................................................................................................... 91
7.1.3 Export Materials....................................................................................................92
7.1.4 Waste Materials.................................................................................................... 93
7.1.5 Delete Materials....................................................................................................93
7.1.6 Modify Materials....................................................................................................94
7.1.7 Query Materials.................................................................................................... 95
7.2 Warehouse Management.................................................................................................. 95
7.2.1 Adding A Warehouse............................................................................................95
7.2.2 Adding A Warehouse............................................................................................96
7.2.3 Query Warehouse/Warehouse Location...............................................................98
7.2.4 Modify A Warehouse/storage Location.................................................................98
7.2.5 Delete A Warehouse/storage Location...............................................................100
7.2.6 Abandoned Warehouse/Warehouse Location.................................................... 102
7.3 Inventory Management.................................................................................................... 103
7.3.1 Set Inventory.......................................................................................................103
7.4 Spare Parts Warehousing............................................................................................... 104
7.4.1 New Spare Parts Warehousing.......................................................................... 105
7.4.2 Handle Warehousing Orders.............................................................................. 106
7.4.3 Query Warehousing Orders................................................................................109
7.4.4 Discarded Warehousing Receipt........................................................................ 110
7.4.5 Terminate The Warehousing Receipt.................................................................111
7.5 Spare Parts Exiting The Warehouse...............................................................................112
7.5.1 Adding An Outbound Task................................................................................. 112
7.5.2 Handle Outbound Tasks.....................................................................................113
7.6 Material Transfer..............................................................................................................117
7.6.1 Add A Transfer Task.......................................................................................... 117
7.6.2 Process The Transfer Task................................................................................ 119
7.7 Transfer and Return........................................................................................................ 122
7.7.1 Add A Transfer Return Task.............................................................................. 122
7.7.2 Handle The Transfer and Return Task...............................................................124
7.8 Warehouse Check........................................................................................................... 127
7.8.1 Adding A Check Task.........................................................................................128
7.8.2 Handling A Check Task......................................................................................130

8 DashBoard.......................................................................................................... 133

8.1 WO DashBoard............................................................................................................... 133
8.2 FLM WO Dashboard....................................................................................................... 134
8.3 BO WO Dashboard......................................................................................................... 135

9 Preventive Maintenance Management............................................................. 136

9.1 PM Template................................................................................................................... 136
9.1.1 Creating A Template...........................................................................................136
9.1.2 Modify A Template............................................................................................. 137
9.1.3 Discarded Template............................................................................................138
9.2 PM Plan........................................................................................................................... 139
9.2.1 Adding A Preventive Maintenance Plan............................................................. 139
9.2.2 Abandoning The Preventive Maintenance Plan................................................. 142
9.2.3 Terminate A Preventive Maintenance Plan........................................................ 143
9.2.4 Exporting A Preventive Maintenance Plan......................................................... 144
9.2.5 Process The Preventive Maintenance Plan........................................................145
9.3 PM Task.......................................................................................................................... 148
9.3.1 Adding A Preventive Maintenance Task............................................................ 148
9.3.2 Discarding A Preventive Maintenance Task.......................................................149
9.3.3 Terminate A Preventive Maintenance Task........................................................150
9.3.4 Creating A Preventive Maintenance Report....................................................... 151
9.3.5 Processing Preventive Maintenance Tasks........................................................152
9.4 Punch List........................................................................................................................157

10 My Task............................................................................................................. 159

10.1 Task Statistics............................................................................................................... 159
10.2 Task Details...................................................................................................................160
10.3 Processing Task............................................................................................................ 161
10.4 Workflow History............................................................................................................162

11 Message............................................................................................................ 163

11.1 SMS Sending Record....................................................................................................163
11.2 Message Template........................................................................................................ 164

12 Change Management....................................................................................... 167

12.1 Adding A Change Order................................................................................................167
12.2 Termination Change Order............................................................................................168
12.3 Modify A Change Order................................................................................................ 170
12.4 Abandonment Change Order........................................................................................ 171
12.5 Handling Change Orders...............................................................................................172

13 Asset Change Order........................................................................................ 178

13.1 Asset Change Order......................................................................................................178
13.1.1 New Asset Change Order................................................................................ 178
13.1.2 Exporting An Asset Change Order................................................................... 179
13.1.3 Handling Asset Change Orders........................................................................180

13.2 Asset Audit.................................................................................................................... 182
13.2.1 Audit of New Assets......................................................................................... 182
13.2.2 Handling Asset Audit Forms.............................................................................183

14 SLA Management............................................................................................. 185

14.1 Creating An SLA Task.................................................................................................. 185
14.2 Modifying An SLA Task.................................................................................................187
14.3 Delete An SLA Task......................................................................................................188

15 GIS..................................................................................................................... 190

15.1 Site View........................................................................................................................190
15.2 Person View.................................................................................................................. 192
15.3 Tickets View.................................................................................................................. 194

16 App Management............................................................................................. 196

16.1 Release Record............................................................................................................. 196
16.2 App Download............................................................................................................... 197

17 Leave Ticket Management...............................................................................198

17.1 Add A Leave Ticket.......................................................................................................198
17.2 Cancel The Leave Application...................................................................................... 200
17.3 Refresh The Leave List................................................................................................. 200
17.4 Export Leave Application Form..................................................................................... 201
17.5 Query Leave Tickets..................................................................................................... 203
17.6 Handle Leave Application Forms.................................................................................. 204
17.7 Workflow History............................................................................................................206

18 Message Center................................................................................................208

18.1 Message Template Configuration..................................................................................208
18.2 Message Sending Records........................................................................................... 211

19 SP Management................................................................................................213

19.1 Material Mgmt................................................................................................................ 213
19.1.1 Add Material......................................................................................................213
19.1.2 Import Material..................................................................................................214
19.1.3 Export Material..................................................................................................215
19.1.4 Discard Material................................................................................................216
19.1.5 Delete Material..................................................................................................217
19.1.6 Modify Material................................................................................................. 218
19.1.7 Query Material.................................................................................................. 219

19.2 Storage Mgmt................................................................................................................ 220
19.2.1 Set Inventory.....................................................................................................220
19.2.2 Export Warehouse Statistics/Material Details...................................................221

19.3 Warehouse Mgmt.......................................................................................................... 222
19.3.1 Add Warehouse................................................................................................ 222
19.3.2 Add Storage Location....................................................................................... 223
19.3.3 Query Warehouse/Storage Location................................................................ 224
19.3.4 Modify Warehouse/Storage Location................................................................225
19.3.5 Delete Warehouse/Storage Location................................................................ 227
19.3.6 Discard Warehouse/Storage Location.............................................................. 229
19.3.7 Recover Warehouse/Storage Location............................................................. 231
19.4 W.H. Inbound.................................................................................................................233
19.4.1 Add A W.H. Inbound Task............................................................................... 233
19.4.2 Handle W.H. Inbound Task.............................................................................. 234
19.4.3 Query W.H. Inbound Orders.............................................................................236
19.4.4 Discarded W.H. Inbound Task......................................................................... 237
19.4.5 Terminate The W.H. Inbound Task.................................................................. 238
19.5 W.H. Outbound.............................................................................................................. 238
19.5.1 Adding A W.H. Outbound Task........................................................................ 239
19.5.2 Handle W.H. Outbound Task........................................................................... 240
19.6 W.H. Transfer................................................................................................................ 244
19.6.1 Add A W.H. Transfer Task............................................................................... 244
19.6.2 Process The W.H. Transfer Task.....................................................................245
19.7 Safety Stock Warning....................................................................................................247
19.7.1 Safety Inventory Warning Query...................................................................... 247
19.7.2 Avg Monthly Borrowing Query..........................................................................248
19.7.3 Storage Statistics Query...................................................................................248
19.8 W.H. Storage Check......................................................................................................249
19.8.1 Add Inventory Check Task............................................................................... 249
19.8.2 Process Check Task.........................................................................................251
19.9 SP Dashboard............................................................................................................... 253
19.9.1 Query In/Out Records.......................................................................................253
19.9.2 Export In/Out Records...................................................................................... 254
19.10 W.H. Transfer Return.................................................................................................. 255
19.10.1 Create W.H. Transfer Return Task.................................................................256
19.10.2 Process W.H. Transfer Return Task.............................................................. 258

# Configuration

Table of Contents

System User................................................................................................................................. 1
Configuring CMDB Personnel...................................................................................................... 6
Event Configuration Procedure.................................................................................................... 9
Configuring Preventive Maintenance Items............................................................................... 12
SMS Notification Configuration for Major Faults........................................................................14

Use the admin account to create an account for eFlow maintenance personnel. This account
has the operation permission only for the eFlow module.
This chapter includes the following topics:
 System User
 Configuring CMDB Personnel
 Event Configuration Procedure
 Configuring Preventive Maintenance Items
 SMS Notification Configuration for Major Faults

## System User

Create a role with the operation permissions of the eFlow module, which is assigned to the
eFlow user.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
Operation Path
Workspace > System Configuration > Security Management
Operation Steps
1. Log in to the system as the admin user. Select System Configuration > Security

Management > Role Management. The User Role Management page is displayed, see the
following figure.
eFlow Function Operation Guide

1. Click Operation Set > Create Operation Set to create the operation set required by the
eFlow role, see the following figure.

1. Select the operation set permission corresponding to eFlow, and click Create. The operation
set is created successfully, see the following figure.
1 Configuration

1. Click Role > Create Role to create the role required by the eFlow administrator, see the
following figure.

1. Select No for Area Security Administrator, and click OK, see the following figure.
eFlow Function Operation Guide

1. Select resources as required, and select "eFlow" created in the above step for the operation
set, see the following figure.

Note: Select a resource object on the left, and set the operation set on the right to change the
permissions of the resource object. You can press and hold the ctrl key to continuously select
or invert resource objects, or press and hold the shift key to select or invert resource objects at
the same layer in batches.
1. Click Create to create a eFlow role, see the following figure.
1 Configuration

1. Click User Management > +Create User to create the eFlow administrator.
1. Enter the user information, see the following figure.

Parameter     Value
Account Rule  Selecting the Default Rule
eFlow Function Operation Guide

Maximum number of concurrent logins          Depending on the actual situation
User group                                   Depending on the actual situation

1. Click Next. The role selection page is displayed. Select the created eFlow role, see the
following figure.

1. Click Create. The eFlow user is created.

## Configuring CMDB Personnel

The personnel information here provides maintenance personnel for different event process
processing of the e→flow module. The information must be the same as the account registered
in the personnel system.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
Operation Path
1 Configuration

Workspace > System Configuration > Configuration Data
Operation Steps
1. Log in to the system as the admin user. Select System Configuration > Configuration Data.

The configuration data page is displayed, see the following figure.

1. Click person > +Add to add a new person, see the following figure.

After editing the personnel information, click OK to add the personnel.
1. Click More > Export All. The exported excel file can be used as the backup of personnel

information. It is recommended that you copy and save the file before each operation, see
the following figure.
eFlow Function Operation Guide

1. Modify the Excel information. You can modify the original data or add new data, see the
following figure.

1. Click More > Import Management to import the excel file, as shown in the figure below.

1. Click Browse, select a file, and click Import. The file is imported successfully, see the
following figure.
1 Configuration

## Event Configuration Procedure

Event process: Defines the process of event processing. For example, TT, WO, and SP are
restricted by this process. This procedure uses TT as an example.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
Operation Path
Workspace > Capability Operation Center > Workflow Engine > Incident Flow Modeling
Operation Steps
1. On the event process modeling page, click eflow→tt. The TT process editing page is

displayed, see the following figure.
eFlow Function Operation Guide

1. Click FOA ccept to add or delete a person with the FO permission, see the following figure.

1. Click Select Task Handlers to grant the FO role permissions to the group or personnel, see
the following figure.

Note:
1 Configuration

Fo role: Maintenance personnel analyze and handle fault reports in the following four ways:
1. If a fault can be handled directly, the maintenance personnel shall handle it directly. The

maintenance personnel shall fill in the root cause and handling steps of the fault, and close
the fault ticket directly.
2. If a fault needs to be handled on site, a WO work order needs to be dispatched. The
maintenance personnel select to generate a work order. The system automatically
generates a work order. After all work orders are processed, the maintenance personnel
determine whether the fault is solved.
3. The maintenance personnel cannot handle the fault, and need to escalate the fault to the
O&M personnel of the BO role. The O&M personnel of the BO role handle the fault. After
the fault is handled completely, the maintenance personnel determine whether the fault is
solved.
4. The maintenance personnel cannot handle the fault directly. The fault needs to be handled
by a third-party device vendor. If the fault is to be handled by a third-party device vendor,
the fault ticket task still stays with the maintenance personnel. The maintenance personnel
need to fill in the third-party vendor's feedback information, and confirm whether the fault is
solved.
5. Click BOA ccept (the BO role is used as an example here) to grant the rights of the BO role
to the personnel or groups, see the following figure.
eFlow Function Operation Guide

## Configuring Preventive Maintenance Items

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
Operation Path
Workspace > System Configuration > Configuration Data
Operation Steps
1. Log in to the system as the admin user. Select System Configuration > Configuration Data.

The configuration data page is displayed, see the following figure.

1. Search for "PM", see the following figure.
1 Configuration

Parameter          Definition
PMContent          Specific preventive maintenance items, including the
network type, preventive maintenance sub-type, and
PMResultType       preventive maintenance category.
PMMaintainingType  Preventive Maintenance Result Dimension
PMContentSeverity  Preventive Maintenance Category
PMContentType      Preventive Maintenance Level
Preventive maintenance sub-category, which can be
PMNetworkType      mounted on the preventive maintenance category.
PMPeriod           Network type of the preventive maintenance item.
Preventive Maintenance Period

1. Other parameters are the same as the above parameters. This procedure uses PMM
aintainingType as an example. You can configure them as required.

2. Click PMM aintainingType, and then click +Add. The preventive maintenance page is
displayed, see the following figure.

1. Set the parameters as required, and click OK. The preventive maintenance category is
customized successfully.
eFlow Function Operation Guide

1.5 SMS Notification Configuration for Major Faults

SMS notification configuration for major faults uses the keyword (NE Name&&Severity) to
restrict the flow of sending SMS messages.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
Operation Path
Workspace > System Configuration > Configuration Data
Operation Steps
1. Log in to the system. Select System Configuration > Configuration Data. The configuration

data page is displayed. Search for SMS, see the following figure.

1. Click +Add. The Edit dialog box is displayed, see the following figure.

Note:
This configuration restricts the trouble tickets with the NE Nname and Severity fields.
1. Click OK. SMS notifications are configured successfully.

# User Group

Table of Contents

Creating A User Group.............................................................................................................. 15
Modifying A User Group.............................................................................................................16
Delete A User Group................................................................................................................. 17
Querying User Groups............................................................................................................... 18
User Group Management...........................................................................................................19
A user group is a group of personnel. Different event process roles can be assigned to
the group. For example, if the FO role in the TT is assigned to the group, the group and its
members have the permissions of the FO role, which can be assigned to the group in Chapter
1.3.
This chapter includes the following topics:
 Creating a User Group
 Modifying a User Group
 Delete a user group
 Querying User Groups
 User Group Management

## Creating A User Group

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > Capability Operation Center > Workflow Engine > User Group
Operation Steps
1. On the User Group tab, click +New to add a user group, see the following figure.
eFlow Function Operation Guide

**Parameter                   Value**
**Member**
Only the users that exist in the person table (Security
Management > User Management > Configuration
Data > Data Management) can be displayed here.
You can add members to the user group or add
members in the 2.5 section.

1. After the new information is completed, click Create. The user group is created successfully,
see the following figure.

## Modifying A User Group

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > Capability Operation Center > Workflow Engine > User Group
2 User Group

**Operation Steps**
1. Click Modify. The Edit dialog box is displayed, see the following figure.

1. After modifying the information, click Modify. The user group is modified successfully, see
the following figure.

## Delete A User Group

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > Capability Operation Center > Workflow Engine > User Group
Operation Steps
1. Click Delete. A confirmation dialog box is displayed, see the following figure.
eFlow Function Operation Guide

1. Click Delete. The user group is deleted successfully, see the following figure.

## Querying User Groups

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > Capability Operation Center > Workflow Engine > User Group
Operation Steps
1. Click Advanced Query. The query list is displayed, see the following figure.
# User Group

1. After editing the query conditions, click Query to query user groups, see the following figure.

## User Group Management

User group. This module enables you to add a user to a group. You can see the groups that a
user belongs to.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > User Group Management
Operation Steps
1. Log in to the system, and click User Group Management. The user group management

page is displayed, see the following figure.
eFlow Function Operation Guide

1. Click +Add. The Edit dialog box is displayed, see the following figure.

**Parameter  Value**
**User ID**
Only the users that exist in the person table of
Group      Security Management > User Management >
Configuration Data > Data Management can be
displayed here.

Select Capability Operation Center > Workflow
Engine > User Group.

1. After editing the new information, click Submit. The user is added to the group successfully,
see the following figure.
2 User Group

1. Click Modify. The Edit dialog box is displayed, see the following figure.
eFlow Function Operation Guide

1. After modifying the information, click Submit. The modification is successful, see the
following figure.

# Roles and Processes

Table of Contents

Fault Ticket Roles and Processes............................................................................................. 25
Work Order Roles and Processes............................................................................................. 26
Scenario...................................................................................................................................... 28

The O&M personnel perform different service tasks in accordance with their roles in the O&M
system. You can find the operations required by the roles in accordance with the role categories
provided by the O&M system, and support the actual work in accordance with the operations
corresponding to multiple roles in the system.
The roles and organizations of the O&M system are as follows:

For a description of the roles in the O&M system, refer to the following table.

Fo O&M engineer  The main responsibility is to use the NMS
and integrated NMS provided by each device
manufacturer to monitor the device alarms of each
device manufacturer, discover and confirm the device
alarms of each device manufacturer in an area in a
timely manner, and handle the alarms in accordance
with the urgency. For a fault alarm or complaint,
you need to create a work order through the O&
M system and trace the troubleshooting situation
of the troubleshooting personnel. After the fault is
solved, you can confirm the alarm status on the
corresponding NMS, so that the fault can be tracked,
eFlow Function Operation Guide                      handled, and solved in a timely manner to ensure
Customer Service Engineer         normal service operation. In most cases, teams are
(HelpDesk Engineer (HDE)          on duty in turn. Each team has a shift leader.
**Bo O&M Engineer**
Handles consultation and complaint work orders from
NOC Manager                       the customer care center and customer maintenance
NOC Manager                       departments, and checks
Fe (Field Engineer) O&M engineer  Causes and solutions.
In most cases, teams are on duty in turn. Each team
FM Manager                        has a shift leader.
**FM Manager**
Technical expert in each field, responsible for
locating and handling critical faults and alarms, and
performing performance, configuration, and backup
Component management, providing technical support
for FLE (for example, making decisions on problems,
submitting difficult problems of products to the
supplier
Solution by suppliers and network performance
analysis).

As a member of the management layer of the NOC
Center, the NOC manager pays attention to the
operational status of the entire network and customer
satisfaction.
Degree.

The O&M personnel in each region are mainly
responsible for receiving fault maintenance requests
from the NOC center.
Ask for (usually issued through work orders) to
organize the pre-recovery of services on site (for
example, in important services).
Fault location, troubleshooting, and service recovery
to control the impact of the fault on services.
In the minimum range.

As a member of the management layer of the onsite
maintenance team, organizes and schedules the
FME, and tracks onsite maintenance tasks for
confirmation.
Ensure that the network is operating properly.
3 Roles and Processes

3.1 Fault Ticket Roles and Processes

When a fault occurs, the generated fault alarm is automatically sent to the e→flow module, and
the corresponding fault ticket is automatically generated. You can also manually create trouble
tickets for faults that are not automatically generated.

## Role

Troubleshooting involves the following roles:
Eflow O&M engineer: Creates, upgrades, handles, and confirms trouble tickets, and assigns
trouble tickets to the O&M engineer of the FO role.
O&M personnel of the FO role: They can create, upgrade, handle, and confirm trouble tickets.
When a trouble ticket needs to be handled on site, the corresponding work order shall be
dispatched.
O&M personnel as BO: They can process trouble tickets. When a trouble ticket needs to be
handled on site, the corresponding work order is dispatched.
Fe role: Acts as the O&M personnel to handle the work orders dispatched for trouble tickets,
and does not directly participate in the trouble ticket handling process.

## Procedure

The troubleshooting flow is as follows:

1. The FO role is used to analyze and handle fault tickets. There are four options:
2. For the faults that can be handled directly by the O&M personnel of the FO role, the faults

shall be handled directly. The O&M personnel of the FO role shall fill in the fault root cause
and handling steps, and the fault ticket shall be closed directly.
3. If a fault needs to be handled on site, a task work order needs to be dispatched. The O&
M personnel of the FO role select to generate a work order, and the system automatically
generates a work order. The work order is still handled by the FO. The FO can escalate the
work order to the BO or a third party for handling. However, the work order can be closed
only after all work orders are handled and closed.
eFlow Function Operation Guide

4. Fo O&M personnel cannot handle the fault. The fault must be escalated to BO O&M
personnel, who shall handle the fault.

5. The O&M personnel of the FO role cannot directly handle the fault. The fault needs to be
handled by a third-party device vendor. Wait for the third party to handle the fault, and fill in
the information of the third-party vendor. The fault ticket task is transferred to the third-party
claiming step, and the third-party claiming step is performed.

6. Bo role O&M personnel Role O&M personnel has three options for analyzing and handling
fault tickets:

7. If the O&M personnel of the BO role can directly handle the fault, the O&M personnel of the
BO role shall fill in the root cause and handling steps of the fault, and submit them to the FO
for confirmation.

8. A fault needs to be handled on site, and a task work order needs to be dispatched. The O&
M personnel of the BO select to generate a work order. The work order is still processed by
the BO, and the BO can continue to process the work order. However, the work order can
be closed only after all work orders are processed and closed.

9. The O&M personnel of the BO role cannot directly handle the fault. The fault needs to be
handled by a third-party device vendor. Wait for the third party to handle the fault, and enter
the information of the third-party vendor. The trouble ticket task is transferred to the third-
party claiming step, and the third-party claiming step is performed.

3.2 Work Order Roles and Processes

A work order refers to a work order that requires field engineers to handle temporary tasks
on a site, for example, a work order task assigned by a trouble ticket. The system needs to
standardize and track the entire work of field engineers, and provide the function of recording
the work progress on the Web client.

## Role

A work order involves the following roles:
# FO Role of O&M personnel: Creates work orders in accordance with the handling of fault
orders, and assigns work orders to the FE (Field Engineer).
After the FE completes the processing, the work order is finally confirmed.
# FE Role of O&M personnel: Determines whether to accept or transfer the work orders created
by the FO or automatically generated by the system. After accepting the work orders, the O&M
personnel process the work orders.
# FM Role O&M personnel: Field management manager, who manages the O&M team, creates
and reviews work orders in accordance with the handling of fault orders.
3 Roles and Processes

## Procedure

Process Design Steps
Work orders are divided into FL work orders and AT work orders based on sub-work order
types. The AT work order operation flow is divided into five phases: Create, Accept, Process,
Confirm, and Closed. The Start Trip, Arrive Site, and Leave Site phases are added to the FL
work order flow. The work order flow is as follows:

Procedure:
1. Create: A work order can be manually created by the FO or automatically created by the

system due to service information.
2. Accept: When accepting a work order task, you must determine whether to directly process

the task, transfer the work order, and go to the site in accordance with the task site and the
current task execution status. After the corresponding judgment is made, there are three
processing options:
# processing: After the work order is accepted, the next-step work order is processed.
# transfer: After the work order is transferred, another FE determines whether to process the
work order.
Departure: Executes a departure task before a work order leaves the site.
1. Start Trip Departing from the site: Before going to the site, you need to perform the "
Departing" operation. It takes some time during the departure process. You can feed back
the progress information regularly through the phase.
2. Arrive Site Check-in: There are two options:
Check-in: When entering the site, fill in the arrival time to complete the check-in. After the
check-in is completed, you can enter the site to process the work order.
Direct handling without entering the site: For a work order that does not need to be handled
directly, enter the reason and then submit the work order.
1. Process Work order processing:
When processing a work order, you can select whether to suspend the work order in
accordance with the task conditions. If the task conditions are not met, you can suspend the
eFlow Function Operation Guide

work order. If the task conditions are met, you can unsuspend the work order and continue
processing the work order task. After the work order is handled, submit the work order for
confirmation.
1. Leave Site Check-in after departure: After the work order is handled, fill in the departure

time to complete the check-in after departure, and then enter the next confirmation step.
2. Confirm Confirm the processing of the work order:
When confirming the processing of a work order, determine whether to close or reject the work
order in accordance with the processing of the work order. After the corresponding judgment is
made, there are two processing options:
# Close: After the work order is closed, the next work order is closed.
# Reject: After the work order is rejected, the work order is returned to the work order
processing step, and the FE that accepts the work order continues to complete the processing
task.
1. Closed Work order closure:
After a work order is closed, the entire work order service flow ends.

## Scenario

This section describes several troubleshooting scenarios, including simple troubleshooting
scenarios and complicated troubleshooting scenarios.

## Simple Troubleshooting Scenarios

1. Creating a Trouble Ticket
When a fault occurs, the O&M personnel manually creates a trouble ticket, fills in the basic
information of the trouble ticket, and submits the trouble ticket to the FO O&M personnel.
1. Fo O&M personnel handle trouble tickets.
After receiving the fault report, the FO O&M personnel found that the fault was within the scope
of handling, and handled the 3.This fault ticket.
1. Fo O&M personnel handle trouble tickets
After handling the fault, the FO O&M personnel fill in the root cause of the fault and close the
fault ticket.

## Complicated Troubleshooting Scenarios

1. Creating a Trouble Ticket
When a fault occurs, the O&M personnel manually create a trouble ticket, fill in the basic
information of the trouble ticket, and submit the trouble ticket.
Sent to FO O&M personnel.
1. Fo O&M personnel handle trouble tickets
3 Roles and Processes

After receiving the trouble ticket, the FO O&M personnel found that the trouble ticket was not
handled by the FO O&M personnel. The FO O&M personnel escalated the trouble ticket to the
BO O&M personnel.
1. Troubleshooting Ticket Handling by BO O&M Personnel
When handling a fault, the O&M personnel found that the fault was difficult. Therefore, they
dispatched a task work order to the O&M personnel of the FE.
1. Fe O&M personnel handle work orders.
The FE O&M personnel handle the fault and fill in the root cause of the fault.
1. The FO O&M personnel confirm the fault ticket.
The FO O&M personnel confirmed the root cause of the fault in the fault ticket, and found that
there was no problem and the fault had been fixed. The FO O&M personnel closed the fault
ticket.

# Trouble Ticket(Product)

Table of Contents

Creating A Trouble Ticket.......................................................................................................... 30
Terminating A Trouble Ticket.....................................................................................................32
Refresh The Trouble Ticket List.................................................................................................33
Querying Trouble Tickets........................................................................................................... 34
Exporting Trouble Tickets.......................................................................................................... 35
Handliong A Trouble Ticket........................................................................................................37
Workflow History.........................................................................................................................39
Site Alarm................................................................................................................................... 40
TT Dashboard.............................................................................................................................41

This chapter includes the following topics:
 Creating A Trouble Ticket
 Terminating A Trouble Ticket
 Refresh The Trouble Ticket List
 Querying Trouble Tickets
 Exporting Trouble Tickets
 Handling A Trouble Ticket
 Workflow History
 Site Alarm
 TT Dashboard

## Creating A Trouble Ticket

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
4 Trouble Ticket(Product)

1. Click the Create button on the Trouble Ticket page to go to the New Trouble Ticket page, as
shown in the figure.

Note: In the new trouble ticket creation page, parameter values must be filled in according to
actual conditions.
2. After editing the newly created information, clicking the [Submit] button will successfully
create a trouble ticket, as shown in the figure below:
eFlow Function Operation Guide

## Terminating A Trouble Ticket

After entering the trouble ticket list page, you can forcibly terminate the unnecessary trouble
tickets. The status of the terminated trouble tickets is closed, which can be queried through
conditions.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Select the fault tickets to be terminated, click the [More] → [Terminate] button to terminate

the fault tickets, as shown in the figure below:

2. After entering the Remark, click the [Confirm] button to successfully terminate the trouble
ticket, as shown in the figure below:
4 Trouble Ticket(Product)

## Refresh The Trouble Ticket List

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click the [Refresh] button to manually refresh the fault ticket page, as shown in the figure

below:

Click the [Auto Refresh] toggle button to configure the auto-refresh interval; once configured,
the page will refresh according to the default settings as shown in the figure below:
eFlow Function Operation Guide

## Querying Trouble Tickets

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Quick query:

On the trouble ticket list interface, enter the ticket number for a quick search, as shown in
the figure:

2. Advanced query:
On the trouble ticket list interface, click the [Advanced Query] button as shown in the figure:
4 Trouble Ticket(Product)

## Exporting Trouble Tickets

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click the [Export-Export Setting] button to open the Export Configuration page, as shown in

the figure below:

2. After completing the export settings, click the [Confirm] button to start the export, as shown
in the figure below:
eFlow Function Operation Guide

3. Click the [Export-My Export] button to open the export configuration page and view the
export records, as shown in the figure below:
4 Trouble Ticket(Product)

4. Click the [Download] button to download the exported file, as shown in the figure:

## Handliong A Trouble Ticket

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The login account has the permission to handle trouble tickets.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click the [FO Accept] button in the operation bar to navigate to the fault ticket claim operation
page, with the operation description shown in the figure below:
eFlow Function Operation Guide

2. Click the [FO Process] button to navigate to the fault ticket processing operation page, with
the operation description illustrated as shown in the figure:

3. Click the [Confirm] button to navigate to the trouble ticket confirmation operation page, with
the operation description shown in the figure below:
# Trouble Ticket(Product)

## Workflow History

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
Click the [More] → [Workflow History] button to navigate to the work order workflow history
interface, as shown in the figure below:
eFlow Function Operation Guide

## Site Alarm

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click the [More] → [Site Alarm] button to navigate to the site alarm display interface, as

shown in the figure below:
4 Trouble Ticket(Product)

## TT Dashboard

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
The number of fault tickets by region is statistically categorized according to document level, as
shown in the figure below:

# Work Order(Product)

Table of Contents

Creating A Work Order.............................................................................................................. 42
Terminating A Work Order......................................................................................................... 43
Refresh The Work Order List.....................................................................................................44
Querying Work Orders............................................................................................................... 45
Exporting Work Orders...............................................................................................................46
Handling A Work Order..............................................................................................................49
Workflow History.........................................................................................................................52
FLM Dashboard..........................................................................................................................53

This chapter includes the following topics:
 Creating A Work Order
 Terminating A Work Order
 Refresh The Work Order List
 Querying Work Orders
 Exporting Work Orders
 Handling A Work Order
 Workflow History
 FLM Dashboard

## Creating A Work Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Work Order > Work Order
Operation Steps
Click the [Create] button on the work order page to enter the work order creation and editing
page, as shown in the figure:
5 Work Order(Product)

Clicking the [Submit] button successfully creates a work order, as shown in the figure below.

## Terminating A Work Order

Prerequisite
eFlow Function Operation Guide

1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Work Order > Work Order
Operation Steps
In the work order list interface, select the work orders to be terminated, then click the [More] → [
Terminate] button, as shown in the figure below:

Fill in the Remark field and click the [Confirm] button to successfully terminate the work order,
as shown in the figure below:

## Refresh The Work Order List

Prerequisite
1. The system is deployed successfully.
5 Work Order(Product)

2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Work Order > Work Order
Operation Steps
1. Clicking the refresh button on the work order page allows you to manually refresh the work

order page, as shown in the figure below:

2. Click the [Auto Refresh] toggle button to configure the auto-refresh interval; once configured,
the page will refresh according to the default settings as shown in the figure below:

## Querying Work Orders

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
eFlow Function Operation Guide

Operation Path
Workspace > e-flow > Work Order > Work Order
Operation Steps
1. Quick query:

In the work order list interface, enter the work order number for a quick query, as shown in
the figure

below:
2. Advanced Qurey:

On the work order list interface, click the [Advanced Query] button as shown in the figure:

## Exporting Work Orders

Prerequisite
1. The system is deployed successfully.
5 Work Order(Product)

2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Work Order > Work Order
Operation Steps
1. Click the [Export-Export Setting] button to open the Export Configuration page, as shown in

the figure below:

2. After completing the export settings, click the [Confirm] button to start the export, as shown
in the figure below:
eFlow Function Operation Guide

3. Click the [Export-My Export] button to open the export configuration page and view the
export records, as shown in the figure below:

4. Click the [Download] button to download the exported file, as shown in the figure:
5 Work Order(Product)

## Handling A Work Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Work Order > Work Order
Operation Steps
1. Click the [Accept] button in the action bar to navigate to the work order claim operation

page, with the operation description shown in the figure below:
eFlow Function Operation Guide

2. Click the [Departure] button in the operation bar to navigate to the work order departure
station operation page, with the operation description shown in the figure below:
5 Work Order(Product)

3. Click the [Process] button in the operation bar to navigate to the work order processing
page, as illustrated in the figure below:
eFlow Function Operation Guide

4. Click the [Confirm] button in the action bar to navigate to the work order confirmation page;
the operation description is shown in the figure below.

## Workflow History

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Work Order > Work Order
Operation Steps
Click the [More] → [Workflow History] button to navigate to the work order workflow history
interface as shown in the figure.
# Work Order(Product)

## FLM Dashboard

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Work Order > Work Order
Operation Steps
The number of work orders in each region is statistically classified by document level, as shown
in the figure below:
eFlow Function Operation Guide

**Trouble Ticket&&Work**
**Ticket**

Table of Contents

Trouble Ticket.............................................................................................................................55
Work Order................................................................................................................................. 74

There are different types of tickets in the system, such as trouble tickets and work orders.
These tickets involve different aspects of O&M management and have different service
processes, but have some common operations. Describes how to create, query, discard,
terminate, and export documents. For the troubleshooting flow and maintenance personnel,
refer to Section 3.3. For the configuration, refer to Section 1.3.

## Trouble Ticket

This chapter includes the following topics:
 Creating a Trouble Ticket
 Terminating a trouble ticket
 Discarding a trouble ticket
 Refresh the trouble ticket list
 Updating a Trouble Ticket
 Exporting a Trouble Ticket
 Handling a Trouble Ticket
 Workflow History
 Site alarm

## Creating A Trouble Ticket

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
eFlow Function Operation Guide

Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. On the trouble ticket page, click +Add. The page for editing the new trouble ticket is

displayed, see the following figure.

Note: On the page for creating a fault ticket, set the parameters as required.
6 Trouble Ticket&&Work Ticket

1. After editing the new information, click Submit. The trouble ticket is created successfully,
see the following figure.

Note: After the trouble ticket is created, only the "Operator" assigned when the trouble ticket is
created has the operation permission for the follow-up process of the trouble ticket.

## Terminating A Trouble Ticket

After entering the trouble ticket list page, you can forcibly terminate the unnecessary trouble
tickets. The status of the terminated trouble tickets is closed, which can be queried through
conditions.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Select the trouble ticket to be terminated, and click More > Terminate to terminate the

trouble ticket, see the following figure.
eFlow Function Operation Guide

1. Click Confirm. The trouble ticket is terminated successfully, see the following figure.
1. Search for the terminated trouble tickets. The status is close, see the following figure.

## Discarding A Trouble Ticket

After entering the trouble ticket list page, you can discard unnecessary trouble tickets. If a
trouble ticket is discarded, it cannot be found on the page.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
6 Trouble Ticket&&Work Ticket

1. Select the trouble tickets to be discarded, and click More > Discard. The trouble tickets can
be discarded, see the following figure.

1. Click Confirm. The trouble ticket is discarded successfully, see the following figure.

1. The discarded trouble tickets cannot be found on the page, see the following figure.
eFlow Function Operation Guide

## Refresh The Trouble Ticket List

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click Refresh to manually refresh the trouble ticket page, see the following figure.

1. Click Auto Refresh to set the automatic refresh time. After the time is set, the page is
refreshed in accordance with the default setting, see the following figure.
6 Trouble Ticket&&Work Ticket

## Updating A Trouble Ticket

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click Update. The page for updating the trouble ticket is displayed, see the following figure.

1. Click Submit to submit the update information, see the following figure.
eFlow Function Operation Guide

## Querying Fault Tickets

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click Condition Query to configure the query conditions, see the following figure.

1. After configuring the query conditions, click Query to query the corresponding trouble
tickets, see the following figure.

1. Click Save As Template to save the query template, see the following figure.
6 Trouble Ticket&&Work Ticket

1. Fill in the template information and click Confrim. The template is saved successfully, see
the following figure.

1. Click Condition Template. The saved query template is displayed, see the following figure.
1. Click the template name. A new query window is displayed, see the following figure.
1. Click the column search icon to search for some columns, see the following figure.
eFlow Function Operation Guide

## Exporting A Trouble Ticket

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click the Export icon to export the trouble ticket successfully, see the following figure.

## Handling A Trouble Ticket

Faults that can be handled directly after maintenance personnel claim the work order. The
fault is handled directly. The maintenance personnel fill in the root cause and handling steps
of the fault, and the fault ticket is closed directly. A task work order needs to be dispatched
for a fault. The maintenance personnel select to generate a work order, and the system
6 Trouble Ticket&&Work Ticket

automatically generates the work order. The work order stays in the current processing step.
The maintenance personnel can continue to escalate the work order, but can close the work
order only after all work orders are processed and closed.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The login account has the permission to handle trouble tickets.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click Fo Accept in the Operation column. The Trouble Ticket Claim page is displayed, see
the following figure.

There are two Fo Accept processing modes, see the following figure.
eFlow Function Operation Guide

1. If Claim is selected, click Accept, and select whether the ticket processing permission
is shared by the group. Click YES, and the selected Operator operator group has the
processing permission for this ticket. If you click NO, you can select Operator only.

1. Select the rejection ticket and click Reject. Select the Operator confirmation person and
enter the confirmation step to confirm whether the rejection ticket is allowed.

2. Click Fo Process in the Operation column. The Trouble Ticket page is displayed, see the
following figure.

3. The O&M user can edit the trouble ticket information or start the next step of the trouble
ticket, see the following figure.
6 Trouble Ticket&&Work Ticket

4. In Step FO Process, there are multiple handling modes for fault tickets, see the following
figure.

1. Select a work order to be assigned to the WO, and click Create WO. Select the sub-type of
the WO work order to be created, see the following figure.

Click Operator to select the O&M personnel of the WO, see the following figure.

Click Confirm, see the following figure.
eFlow Function Operation Guide

Click Submit. The FO instruction is issued successfully. The corresponding WO is generated in
the TT form, see the following figure.
1. In Step FO Process, close the trouble ticket, and click Confirm to fill in the root cause

information, see the following figure.
6 Trouble Ticket&&Work Ticket

Name                    Value
RC Main Category        Level-1 root cause
RC Sub Category         Subcategory root cause
RC Description          Description
Alarm Clear Time        Alarm clearing time
Processing Description  Handling Procedure Description

After editing the trouble ticket submission information, click OP erator to enter the confirmation
step, see the following figure.
eFlow Function Operation Guide

In the work order confirmation phase, you can close the trouble ticket or reject the FO.

1. In step FO Process, click Transfer. The Operator selects another FO for processing.

1. In Step FO Process, click Phased Reply to fill in the work order processing progress in this
phase.
6 Trouble Ticket&&Work Ticket

1. In Step FO Process, click BO Process. The operator assigns it to the BO personnel. After
the submission, the BO personnel claim it and process it.

1. In Step FO Process, click Third Process. The operator selects a third-party person to be
assigned. After the submission, the third-party person will claim the application and process

it.
eFlow Function Operation Guide

## Workflow History

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
6 Trouble Ticket&&Work Ticket

**Operation Steps**
1. Click More > Workflow History. The workflow history window of the trouble ticket is

displayed, see the following figure.

1. On the workflow history page, you can see the ticket processing process, current status, and
handler, see the following figure.

## Site Alarm

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click More > Site Alarm. The site alarm window is displayed, see the following figure.
eFlow Function Operation Guide

## Work Order

This chapter includes the following topics:
 Creating a Work Order

## Creating A Work Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
Click +Add. The page for creating and editing a work order is displayed, see the following
figure.
6 Trouble Ticket&&Work Ticket

Note: Set the parameters on the new work order page as required.
Click Operator to add a work order handler, see the following figure.

Note: The work order handler is configured in the work order process in Chapter 1.3.
eFlow Function Operation Guide

After adding a ticket handler, click Submit. The ticket is created successfully, see the following
figure.

## Refresh The Work Order List

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
1. On the ticket page, click Refresh to manually refresh the ticket page, see the following

figure.

1. Click Auto Refresh to set the automatic refresh time. After the time is set, the page is
refreshed in accordance with the default setting, see the following figure.
6 Trouble Ticket&&Work Ticket

## Work Order Statistics List

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the work order page, click Count to count the number of work orders in each status, see the
following figure.
eFlow Function Operation Guide

## Discarded Work Order

After entering the ticket list page, you can discard unnecessary tickets. If a ticket is discarded, it
cannot be queried on the page.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the Work Order page, select the work orders to be discarded, and click Discard, see the
following figure.

Click Confirm to cancel the work order, see the following figure.
# Trouble Ticket&&Work Ticket

To cancel this work order, click Cancel.

## Querying Work Orders

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
1. Quick query:
On the work order list page, enter the work order number to query the work order quickly, see
the following figure.

1. Condition query:
On the ticket list page, click Condition Query, see the following figure.

Set the query conditions, for example, WO No., TT No., ticket status, and Create Time. You can
combine the query conditions with each other or query a single condition. Click Query, see the
following figure.
eFlow Function Operation Guide

1. The following example shows how to query template configurations:
After the query conditions are configured, click Save As Template, see the following figure.

Enter the template name, and click Confirm to save the query template for use next time, see
the following figure.

On the ticket list page, click Condition Templates to view the saved query template, see the
following figure.
6 Trouble Ticket&&Work Ticket

Click a template name to query the work orders that meet the template conditions, see the
following figure.

1. Filter query:
On the work order list page, click Column Search, see the following figure.

Enter the query conditions to quickly search for the data that meets the query conditions, see
the following figure.
eFlow Function Operation Guide

## Exporting A Work Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the work order list page, select multiple or all the work orders to be exported, and click
Export to export the data of the work order list, see the following figure.

## Terminating A Work Order

After entering the ticket list page, you can forcibly terminate the process of stopping
unnecessary tickets. The status of the terminated ticket is closed. You can query the status
through conditions.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
6 Trouble Ticket&&Work Ticket

**Operation Steps**
On the ticket list page, select the ticket to be terminated, and click More > Terminate, see the
following figure.

Click Confirm. The work order is terminated successfully, see the following figure.

Search for the work order whose status is close, see the following figure.

## Exporting A Work Order Template

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the work order list page, click More > Export Template to export the work order template,
see the following figure.
eFlow Function Operation Guide

## Handling A Work Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the work order list page, select the work order to be handled, and click Accept, see the
following figure.

Options:
6 Trouble Ticket&&Work Ticket

1) To receive the work order, select Process and click Submit.

After entering this flow, there are three options:
(1) In the work order list, find the received work order, and click Process. The process page is
displayed, see the following figure.
eFlow Function Operation Guide

Fill in the root cause of the fault. Select Submit to Confirm and Operator. Select the next
operator. Click Submit. The work order enters the phase to be confirmed, see the following
figure.

(2) In the work order list, find the received work order, and click Process. The process page is
displayed, see the following figure.

Select Transfer, select the person to be transferred, and click Submit to transfer the work order
to another person, see the following figure.
6 Trouble Ticket&&Work Ticket

(3) In the work order list, find the received work order, and click Process. The process page is
displayed, see the following figure.

Select Phased Reply, fill in the phase progress, and click Submit. The ticket stays in the
Process phase. See the following figure.

## Updating A Work Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the work order list page, select the work order to be updated, and click Update, see the
following figure.
eFlow Function Operation Guide

Enter the information to be updated, and click Submit to update the work order information, see
the following figure.

## Workflow History

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the ticket list page, select a ticket, and click More > Workflow History to view the workflow
history of the ticket, see the following figure.
6 Trouble Ticket&&Work Ticket

# Spare Parts

Table of Contents

Material Management.................................................................................................................90
Warehouse Management........................................................................................................... 95
Inventory Management.............................................................................................................103
Spare Parts Warehousing........................................................................................................ 104
Spare Parts Exiting The Warehouse....................................................................................... 112
Material Transfer...................................................................................................................... 117
Transfer and Return................................................................................................................. 122
Warehouse Check.................................................................................................................... 127

This chapter includes the following topics:
 Material Management
 Warehouse Management
 Inventory Management
 Warehousing Management
 Outbound Management
 Material transfer
 Transfer and Return
 Warehouse Check

## Material Management

## New Materials

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
7 Spare Parts

1. Enter the material management interface, and click +Add, see the following figure.

1. Enter the information of the material to be added, and click Submit, see the following figure.

1. The new material is displayed on the material management page, see the following figure.

## Import Materials

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
eFlow Function Operation Guide

Workspace > e-flow > SP Management > Material Manage
Operation Steps
1. On the material management page, click Import, see the following figure.

1. Select the prepared material information file, and click Upload to import the material
information, see the following figure.

## Export Materials

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
1. On the material management page, select the materials to be exported, and click Export,

see the following figure.

1. The materials in the system can be exported successfully, see the following figure.
7 Spare Parts

## Waste Materials

Material scrapping refers to deleting materials on the GUI, but they can be restored in the
database and can be used after being restored. Material deletion cannot be restored from the
database.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
1. On the material management page, select the materials to be discarded, and click Discard,

see the following figure.

1. Click Confirm to discard the material, see the following figure.

1. To cancel the discarded material, click Cancel.

## Delete Materials

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
1. On the material management page, select the material to be deleted, and click Delete, see

the following figure.
eFlow Function Operation Guide

1. Click Confirm to delete the material, see the following figure.

## Modify Materials

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
1. On the material management page, select the material to be modified, and click Modify, see

the following figure.

1. Modify the corresponding material information, and click Submit, see the following figure.
7 Spare Parts

## Query Materials

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
1. On the material management page, enter Material No or Material Name to query material

information, see the following figure.

## Warehouse Management

## Adding A Warehouse

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
eFlow Function Operation Guide

Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
1. On the Warehouse Management page, click Add Warehouse, see the following figure.

1. Enter the warehouse information, and click Submit, see the following figure.

1. The new warehouse information is displayed on the warehouse list page, see the following
figure.

## Adding A Warehouse

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
7 Spare Parts

3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
1. On the Warehouse Management page, select a warehouse, and click Add Location, see the

following figure.

1. Enter the storage location name and number, and click Confirm, see the following figure.
eFlow Function Operation Guide

## Query Warehouse/Warehouse Location

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
1. On the Warehouse Management page, enter the warehouse name to quickly query the

warehouse, see the following figure.

1. On the Warehouse Management page, enter the warehousing position name to quickly
query the warehousing position, see the following figure.

## Modify A Warehouse/storage Location

Prerequisite
1. The system is deployed successfully.
7 Spare Parts

2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
1. On the Warehouse Management page, select the warehouse to be modified, and click

Modify, see the following figure.

1. After modifying the warehouse information, click Submit to modify the warehouse
information, see the following figure.

1. On the Warehouse Management page, select the storage location to be modified, and click
Modify, see the following figure.
eFlow Function Operation Guide

1. After modifying the location information, click Confirm to modify the location information, see
the following figure.

## Delete A Warehouse/storage Location

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
1. On the Warehouse Management page, select the warehouse to be deleted, and click

Delete, see the following figure.
7 Spare Parts

1. Click Delete again. The repository is deleted successfully, see the following figure.

1. On the warehouse management page, select the storage location to be deleted, and click
Delete, see the following figure.

1. Click Delete again. The storage location is deleted successfully, see the following figure.
eFlow Function Operation Guide

## Abandoned Warehouse/Warehouse Location

To discard a warehouse or storage location is to delete the warehouse or storage location on
the page, but it can be restored in the database. After restoration, the warehouse or storage
location can still be used. If a warehouse/storage location is deleted, it cannot be restored from
the database.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
1. On the Warehouse Management page, select the warehouse to be discarded, and click

Discard, see the following figure.

1. Click Discard again. The warehouse is discarded successfully, see the following figure.
7 Spare Parts

1. On the warehouse management page, select the storage location to be discarded, and click
Discard, see the following figure.

1. Click Discard again. The storage location is discarded successfully, see the following figure.

## Inventory Management

## Set Inventory

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
eFlow Function Operation Guide

Operation Path
Workspace > e-flow > SP Management > Storage Manage
Operation Steps
1. On the Inventory Management page, click Set Storage, see the following figure.

1. Set the maximum and minimum inventory quantity, and click Confirm, see the following
figure.

## Spare Parts Warehousing

The spare parts warehousing flow is as follows. For the specific flow and O&M personnel, refer
to Chapter 1.3, see the following figure.
# Spare Parts

## New Spare Parts Warehousing

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > In Stock
Operation Steps
On the spare parts warehousing page, click +Add, see the following figure.

Fill in the information to be warehoused, and click Submit, as shown in the figure below.
eFlow Function Operation Guide

## Handle Warehousing Orders

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
7 Spare Parts

Workspace > e-flow > SP Management > In Stock
Operation Steps
On the warehousing list page, select the new warehousing order, and click Verify, see the
following figure.

There are two procedures:

(1) If there is no problem with the warehousing order, select Agree and click Submit, see the
following figure.

After entering the next procedure, ask others to confirm it. Click Confirm, see the following
figure.
eFlow Function Operation Guide

There are two flows:

(1) If there is no problem with the warehousing order, select Agree and click Submit. The
warehousing process ends and the warehousing order is closed, see the following figure.

You can see that the warehousing order is closed in the warehousing order list, see the
following figure.

(2) If you have any questions about the warehousing order, select Reject and click Submit
to return the warehousing order. The warehousing order needs to be updated again, see the
following figure.
7 Spare Parts

Click Update, see the following figure.

Update the warehousing order, and click Submit to return to the original process, see the
following figure.

1. If you have any questions about the warehousing order, select Reject and click Submit. The
warehousing order needs to be updated. After the update is completed, submit it again.
After the submission is completed, return to the original process and verify it again.

## Query Warehousing Orders

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > In Stock
Operation Steps
(1) In the warehousing list, click Condition Query, see the following figure.
eFlow Function Operation Guide

Enter the query conditions and click Query. The corresponding warehousing order is displayed,
see the following figure.

(2) In the warehousing list, enter the warehousing number to quickly find the warehousing
order, see the following figure.

## Discarded Warehousing Receipt

Prerequisite
1. The system is deployed successfully.
7 Spare Parts

2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
**Operation Path**
Workspace > e-flow > SP Management > In Stock
**Operation Steps**
In the warehousing order list, select the warehousing order to be discarded, and click Discard.
The warehousing order can be discarded, see the following figure.

## Terminate The Warehousing Receipt

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > In Stock
Operation Steps
In the list of warehousing documents, select the warehousing document to be terminated, and
click Terminate, see the following figure.

The terminated warehousing document becomes closed, see the following figure.
eFlow Function Operation Guide

## Spare Parts Exiting The Warehouse

The spare parts exit-warehouse flow is as follows. For the specific flow and O&M personnel,
refer to Chapter 1.3, see the following figure.

## Adding An Outbound Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Out Stock
Operation Steps
1. On the Ex-Warehousing page, click +Add. The Add Ex-Warehousing page is displayed, see

the following figure.
7 Spare Parts

1. After editing the outbound information, click Submit, see the following figure.

## Handle Outbound Tasks

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Out Stock
Operation Steps
1. Click Verify. The Verify flow page is displayed, see the following figure.
eFlow Function Operation Guide

1. The Verify O&M personnel determine that there is a problem with the delivery note, and
select Rject.

The outbound order enters the Update process.

Re-submit the delivery note after the O&M personnel update it.
7 Spare Parts

After the Verify O&M personnel review the application, the Verify O&M personnel determine
that there is no problem. Select Agree to enter the Confirm process, see the following figure.

1. Click Confirm. The Confirm page is displayed, see the following figure.
eFlow Function Operation Guide

1. The Confirm O&M personnel determine that there is a problem with the outbound order,
and select Rject. The outbound order enters the Update process and repeats the above
process. The Confirm O&M personnel determine that there is no problem, and select Agree.
The items are lent successfully, and the stock-out ticket enters the Return process, see the
following figure.

1. Click Return. The Return page is displayed, see the following figure.
7 Spare Parts

1. Click Submit. The items are returned successfully. The lending ticket flow ends, see the
following figure.

## Material Transfer

The material transfer process is as follows. The specific process and O&M personnel can be
configured in Chapter 1.3, see the following figure.

## Add A Transfer Task

Prerequisite
1. The system is deployed successfully.
eFlow Function Operation Guide

2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Transfer W.H.
Operation Steps
1. On the transfer page, click +Add. The Add Edit page is displayed, see the following figure.

Note: By default, the next process handler is the warehouse keeper added when the warehouse
is created.
1. After editing the new information, click Submit, see the following figure.
7 Spare Parts

## Process The Transfer Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Transfer W.H.
Operation Steps
1. After the transfer task is created, click Verify. The Verify page is displayed, see the following

figure.

1. If the Verify O&M personnel determine that the transfer conditions are not met, they can
click Reject to reject the transfer and end the transfer task process. When the Verify O&M
personnel determine that the transfer is qualified, click Agree and click Submit. The transfer
task enters the next process, see the following figure.
eFlow Function Operation Guide

1. Click Transfer Outbound Operate. The Transfer Outbound Operate page is displayed, see
the following figure.

1. If the Transfer Outbound Operate O&M personnel determine that the transfer conditions
are not met, they can click Reject to reject the transfer and return the transfer task to the
Verify O&M personnel. When the Transfer Outbound Operate O&M personnel determine
that the transfer is qualified, they select Agree and click Submit. The transfer task enters the
Transfer Inbound Operate flow, see the following figure.
7 Spare Parts

1. Click Transfer Inbound Operate. The Transfer Inbound Operate page is displayed, see the
following figure.

1. If the Transfer Inbound Operate O&M personnel determine that the transfer conditions
are not met, they can click Reject to reject the transfer and return the transfer task to the
Verify O&M personnel. When the Transfer Inbound Operate O&M personnel determine that
the transfer is qualified, click Agree and click Submit. The transfer task flow ends, see the
following figure.
eFlow Function Operation Guide

7.7 Transfer and Return

The transfer return flow is as follows. The specific flow and O&M personnel can be configured
in Chapter 1.3, see the following figure.

## Add A Transfer Return Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Return W.H.
Operation Steps
1. On the Transfer Return page, click +Add. The Create Transfer Return page is displayed,

see the following figure.
7 Spare Parts

Note:
Return Material No.It should be consistent with the following figure.

The Return Material SN must be the same as the following:

1. Click Submit to submit the task, see the following figure.
eFlow Function Operation Guide

7.7.2 Handle The Transfer and Return Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Return W.H.
Operation Steps
1. Click Verify. The Verify page is displayed, see the following figure.
7 Spare Parts

1. If the Verify O&M personnel determine that the return conditions are not met, they can click
Reject to reject the return and end the return task process. When the Verify O&M personnel
determine that the warehouse transfer and return are qualified, they select Agree and click
Submit. The warehouse transfer and return task enters the next process, see the following
figure.

1. Click Return Outbound Operate. The Return Outbound Operate page is displayed, see the
following figure.
eFlow Function Operation Guide

1. If the Return Outbound Operate O&M personnel determine that the return conditions are
not met, they can click Reject to reject the return and return the task to the Verify O&
M personnel. When the Return Outbound Operate O&M personnel determine that the
warehouse transfer and return are qualified, they select Agree and click Submit. The
warehouse transfer and return task enters the Return Inbound Operate process, see the
following figure.

1. Click Return Inbound Operate. The Return Inbound Operate page is displayed, see the
following figure.
7 Spare Parts

1. If the Return Inbound Operate O&M personnel determine that the transfer conditions
are not met, they can click Reject to reject the transfer and return the task to the Verify
O&M personnel. When the Return Inbound Operate O&M personnel determine that the
warehouse transfer and return are qualified, they select Agree and click Submit. The
warehouse transfer and return task flow ends, see the following figure.

## Warehouse Check

The warehouse check flow is as follows. For details, refer to Section 1.3.
eFlow Function Operation Guide

## Adding A Check Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Check W.H.
Operation Steps
1. On the Warehouse Check page, click +Add. The Add Task page is displayed, see the

following figure.
7 Spare Parts

1. Add material information, see the following figure.
1. Click Submit. A new task is created, see the following figure.
eFlow Function Operation Guide

## Handling A Check Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Check W.H.
Operation Steps
1. On the Warehouse Check page, click Upload. The Upload page is displayed, see the

following figure.

1. Click Operation to update the material check status, see the following figure.
7 Spare Parts

1. When the Upload O&M personnel select the Finished status, the check procedure ends.
When the Upload O&M personnel select the Not Finished status and click Submit, the task
order enters the Confirm O&M personnel confirmation flow, see the following figure.

1. Click Confirm. The Confirm flow page is displayed, see the following figure.
eFlow Function Operation Guide

1. When the Confirm O&M personnel determine that the check task is not completed, click
Wait ReUpload. The check task is returned to the Upload O&M personnel and the process
is restarted. When the Confirm O&M personnel determine that the check task ends, click
Close and click Submit. The flow ends, see the following figure.

# DashBoard

Table of Contents

WO DashBoard........................................................................................................................ 133
FLM WO Dashboard................................................................................................................ 134
BO WO Dashboard.................................................................................................................. 135

The data of work orders can be collected and displayed in a dashboard, so that O&M personnel
can learn more about work orders.
This chapter includes the following topics:
 WO DashBoard
 FLM WO Dashboard
 BO WO Dashboard

## WO DashBoard

Displays work order data in different dimensions and graphs.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > DashBoard > WO DashBoard
Operation Steps
1. Log in to the system and enter the DashBoard interface, see the following figure.
eFlow Function Operation Guide

1. You can select combination conditions from different dimensions and click Query to query
data, see the following figure.

1. Click Customer Complaint Dashboard to view the work order data of customer complaints,
see the following figure.

## FLM WO Dashboard

Work order data to be handled by field O&M personnel
8 DashBoard

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > DashBoard > FLM WO Dashboard
Operation Steps
1. Click FLM WO Dashboard to view the work orders to be handled by the O&M personnel,

see the following figure.

## BO WO Dashboard

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > DashBoard > BO WO Dashboard
Operation Steps
Click BO WO Dashboard to view the work orders to be handled by BO O&M personnel, see the
following figure.

**Preventive Maintenance**
**Management**

Table of Contents

PM Template............................................................................................................................ 136
PM Plan.................................................................................................................................... 139
PM Task................................................................................................................................... 148
Punch List.................................................................................................................................157

Perform preventive maintenance on devices or resources to ensure stable system operation.
Set preventive maintenance items as required. The preventive maintenance flow and O&M
personnel can be configured in Chapter 1.3.
This chapter includes the following topics:
 PM Template
 PM Plan
 PM Task
 Punch List

## PM Template

## Creating A Template

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Template
Operation Steps
1. On the Inspection Template page, click +Add. The Edit page is displayed, see the following

figure.
9 Preventive Maintenance Management

1. After editing the template, click Submit. The template is created successfully, see the
following figure.

Note: For preventive maintenance items, refer to Section 1.4 Configurable.

## Modify A Template

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Template
Operation Steps
1. Click Modify. The Modify dialog box is displayed, see the following figure.
eFlow Function Operation Guide

1. Click Submit to submit the modification.

## Discarded Template

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Template
Operation Steps
1. Select a template and click Discard. The selected template is discarded, see the following

figure.
# Preventive Maintenance Management

1. Click Confirm.

## PM Plan

## Adding A Preventive Maintenance Plan

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Plan
Operation Steps
1. On the Inspection Plan page, click +Create. The Edit page is displayed, see the following

figure.
eFlow Function Operation Guide

Parameter                  Definition
Plan Begin Date            Planned Start Time
Plan End Date              Planned End Time
PM Template                Preventive Maintenance Template
Site                       Site information to be inspected. One site
corresponds to one inspection task.

1. After the site is added, click Set Executor to modify the site information, see the following
figure.
9 Preventive Maintenance Management

Note:
Actual Patrol Inspector: Direct handler of the preventive maintenance task, see the following
figure.

1. On the Add Edit page, you can import a plan and export a template, see the following figure.

1. Select the O&M personnel to receive the preventive maintenance plan, see the following
figure.
eFlow Function Operation Guide

1. After editing the information, click Submit. The preventive maintenance plan is created
successfully, see the following figure.

## Abandoning The Preventive Maintenance Plan

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Plan
Operation Steps
Select a preventive maintenance plan and click Discard. The preventive maintenance plan can
be discarded, see the following figure.
9 Preventive Maintenance Management

Note: Discarded tickets are not in the search list.

## Terminate A Preventive Maintenance Plan

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Plan
Operation Steps
1. Select a preventive maintenance plan, and click Terminate to terminate the plan, see the

following figure.
eFlow Function Operation Guide

## Exporting A Preventive Maintenance Plan

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Plan
Operation Steps
1. Click Export to export the preventive maintenance plan, see the following figure.
9 Preventive Maintenance Management

## Process The Preventive Maintenance Plan

When creating a preventive maintenance plan, O&M personnel can specify an inspection plan
approver (configured in the 1.3). After the plan is approved by the inspection plan approver,
the plan is assigned to the corresponding inspection task according to the inspection site and
assigned to the default site handler (the handler can be modified when the inspection site is
added in the new plan). The inspection plan can be confirmed by the inspection plan approver
only after the inspection task handler of all sites completes the inspection task.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the permission to operate preventive maintenance plans.
Operation Path
Workspace > e-flow > PM Management > PM Plan
Operation Steps
1. Click Approve to approve the new preventive maintenance plan, see the following figure.
eFlow Function Operation Guide

1. The O&M personnel can approve or reject the preventive maintenance plan, see the
following figure.

2. Click Reject. The O&M personnel can reject the preventive maintenance plan, see the
following figure.

Click Submit. The plan is rejected, see the following figure.
9 Preventive Maintenance Management

Note: Rejected tickets are in closed status and can be found in Condition Query.
1. Click Agree to agree to the plan, see the following figure.

The agreed preventive maintenance plan is displayed in the preventive maintenance task list,
see the following figure.

1. The O&M personnel can obtain the completion progress of the preventive maintenance
tasks corresponding to the preventive maintenance plan from "Completed/Total". When
the tasks of all sites are completed, the O&M personnel who approve the preventive
maintenance plan can confirm whether the preventive maintenance plan is completed, see
the following figure.

the uncompleted "0/1" cannot be confirmed.

1. After the preventive maintenance task is completed, Automatic closing of the preventive
maintenance plan
eFlow Function Operation Guide

## PM Task

## Adding A Preventive Maintenance Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Task
Operation Steps
1. On the preventive maintenance task page, click +Add. The Edit page is displayed, see the

following figure.
9 Preventive Maintenance Management

1. After editing the new information, click Submit to create a preventive maintenance task, see
the following figure.

## Discarding A Preventive Maintenance Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
eFlow Function Operation Guide

Workspace > e-flow > PM Management > PM Task
Operation Steps
1. Select a preventive maintenance task and click Discard. The preventive maintenance task is

discarded, see the following figure.

## Terminate A Preventive Maintenance Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Task
Operation Steps
9 Preventive Maintenance Management

1. Select a preventive maintenance task and click Terminate to terminate the task, see the
following figure.

1. The terminated task is in Closed status, see the following figure.

## Creating A Preventive Maintenance Report

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
eFlow Function Operation Guide

3. The user has the eFlow service operation permission.
4. The preventive maintenance task has been processed.
Operation Path
Workspace > e-flow > PM Management > PM Task
Operation Steps
1. Select a preventive maintenance task that has been processed. A preventive maintenance

report is generated, see the following figure.

1. Click Inspection Report to download the report to the local PC, see the following figure.

## Processing Preventive Maintenance Tasks

After receiving the preventive maintenance task, the O&M personnel (accept) determine
whether to forward the task to others or continue the next step in accordance with the task
content (process). After inspecting each item, the process O&M personnel send it to the PM
manager for confirmation. The PM manager rejects to return the data to the process or assigns
the data to the FLM Leader O&M personnel. FLM Leader Verify that there is no problem in the
preventive maintenance, and select Close. If there is any problem, return to the peocess and go
back to the process.
See the following figure.
9 Preventive Maintenance Management

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
4. Has the permission to receive and process preventive maintenance tasks.
Operation Path
Workspace > e-flow > PM Management > PM Task
Operation Steps
1. Click Accept to receive the preventive maintenance task, see the following figure.

1. There are two processing modes for preventive maintenance tasks: Wait Process and
Transfer, see the following figure.

Note:
Wait Process: Enables the task to enter the processing flow.
Transfer: Assign to another handler
1. Click Re-assign . The task is transferred to another person, see the following figure.
eFlow Function Operation Guide

1. Click Wait Process, see the following figure.
1. Click Submit. The command is executed successfully, see the following figure.
1. Click Process. The task processing page is displayed, see the following figure.

1. Click Operation. The preventive maintenance items are completed, see the following figure.
9 Preventive Maintenance Management

1. Click Submit to confirm the inspection items, see the following figure.
eFlow Function Operation Guide

1. After the inspection items are completed, select the inspection manager and click Submit
to submit the processing result and wait for the inspection manager to confirm, see the
following figure.

1. Click FLM Leader Approve. The approval page is displayed, see the following figure.

1. According to the preventive maintenance result, the PM Manager O&M personnel can select
FLM Leader or reject it, see the following figure.

1. The PM Manager O&M personnel reject the flow, and the flow returns process, see the
following figure.
9 Preventive Maintenance Management

1. FLM Leader approves and moves to Closed status.

1.



## Punch List

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Snag Management > Snag Management
Operation Steps
1. On the Punch List page, click +Add. The Edit page is displayed, see the following figure.
eFlow Function Operation Guide

1. After editing the information, click Submit. The list is created successfully, see the following
figure.

# My Task

Table of Contents

Task Statistics.......................................................................................................................... 159
Task Details..............................................................................................................................160
Processing Task....................................................................................................................... 161
Workflow History.......................................................................................................................162

All tasks assigned to the login account
This chapter includes the following topics:
 My Task

## Task Statistics

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > My Task
Operation Steps
1. On the My Tasks page, click Count. The number of tasks is displayed, see the following

figure.
eFlow Function Operation Guide

## Task Details

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > My Task
Operation Steps
1. On the My Task page, click Order Number. The details of the task are displayed, see the

following figure.
10 My Task

## Processing Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > My Task
Operation Steps
1. Click Execute in the Operation column to process the current task, see the following figure.

Note:
For details, refer to the corresponding chapter of each task.
eFlow Function Operation Guide

## Workflow History

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > My Task
Operation Steps
1. Click Workflow History in the Operation column to view the historical processing information

of the current task, see the following figure.

# Message

Table of Contents

SMS Sending Record...............................................................................................................163
Message Template................................................................................................................... 164

Each step in the procedure is sent to the corresponding O&M personnel through SMS
messages.
This chapter includes the following topics:
 SMS sending record
 Message template

## SMS Sending Record

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Message > SMS Send Records
Operation Steps
1. The SMS sending record page displays the SMS messages sent in all flows. You can filter

and export SMS messages, see the following figure.
eFlow Function Operation Guide

## Message Template

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Message > Message Template
Operation Steps
1. Click +New. The Edit dialog box is displayed, see the following figure.
11 Message

Parameter        Definition
Ticket           Module that the SMS message to be sent belongs to.
Operation Steps  Operation Steps of the Module for Sending SMS
Messages

1. Click OK. The template is created successfully, see the following figure.

1. Click Modify to modify the message template, see the following figure.

1. Click Delete to delete the message template, see the following figure.
eFlow Function Operation Guide

# Change Management

Table of Contents

Adding A Change Order...........................................................................................................167
Termination Change Order.......................................................................................................168
Modify A Change Order........................................................................................................... 170
Abandonment Change Order................................................................................................... 171
Handling Change Orders......................................................................................................... 172

This module provides the change task application and change task tracking functions. For
example, an upgrade task needs to be applied for version upgrade, and a resource change task
needs to be applied for device faults.
This chapter includes the following topics:
 Change Order

## Adding A Change Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Change Management > Change Request
Operation Steps
1. On the Change Order page, click +Create. The page for editing the change order is

displayed, see the following figure.
eFlow Function Operation Guide

1. After editing the new information, click Submit. The new information is created successfully,
see the following figure.

## Termination Change Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
12 Change Management

Workspace > e-flow > Change Management > Change Request
Operation Steps
1. Select a change order and click Terminate to terminate the change order, see the following

figure.

1. Click Confirm. The change order is terminated successfully, see the following figure.

1. The terminated ticket is closed, see the following figure.
eFlow Function Operation Guide

## Modify A Change Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Change Management > Change Request
Operation Steps
1. Select a change order, and select More > Modify. The Modify page is displayed, see the

following figure.

1. After the modification, click Modify . The change order is Saved successfully, see the
following figure.
12 Change Management

## Abandonment Change Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Change Management > Change Request
Operation Steps
1. Select a change order, and click Discard, see the following figure.
eFlow Function Operation Guide

1. Click Confirm. The change order can be discarded, see the following figure.

## Handling Change Orders

According to the actual situation, the specific process and operation personnel can be
configured in Chapter 1.3, see the following figure.

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Change Management > Change Request
Operation Steps
12 Change Management

1. The new change order is approved by the domain maintenance personnel in accordance
with the procedure. Click Domain Approve. The approval page is displayed, see the
following figure.

1. Click Reject. The change order is transferred to the following flow, see the following figure.
eFlow Function Operation Guide

1. Click Agree, and click Submit. The NOC O&M personnel approval flow goes to the next
step, see the following figure.

1. Click Approve. The approval page is displayed, see the following figure.
12 Change Management

1. Click Reject to go to the previous step. Click Agree to go to the next step (Start
Implementing), see the following figure.

1. Click Start Implementing. The Implementing page is displayed, see the following figure.
eFlow Function Operation Guide

1. Click Rject to return to the previous step. Click Agree to go to the next step, see the
following figure.

1. Click Result Feedback. The result feedback page is displayed, see the following figure.
1. After selecting the execution result, click Submit to close the ticket, see the following figure.
12 Change Management

# Asset Change Order

Table of Contents

Asset Change Order................................................................................................................ 178
Asset Audit............................................................................................................................... 182

If resources need to be changed in the TT, WO, preventive maintenance, and asset change
processes, you can apply for a resource change form in this module.
This chapter includes the following topics:
 Asset Change Order
 Asset Audit

## Asset Change Order

## New Asset Change Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Asset Change Order > Asset Change Order
Operation Steps
1. Click +Add. The page for adding an asset change order is displayed, see the following

figure.
# Asset Change Order

1. After editing the information, click Submit. The asset change order is created successfully,
see the following figure.

## Exporting An Asset Change Order

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Asset Change Order > Asset Change Order
Operation Steps
1. Click Export Detail to export the asset change order, see the following figure.
eFlow Function Operation Guide

## Handling Asset Change Orders

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Asset Change Order > Asset Change Order
Operation Steps
1. Click Confirm. The Confirm page is displayed, see the following figure.

1. Click the Rject button. The change order is returned to the Update button. The Confirm
needs to be redistributed. Click the Agree button. The change order enters the Approve
flow, see the following figure.
13 Asset Change Order

1. Click Approve. The Approve page is displayed, see the following figure.

1. Click Rject to return to Update and Confirm again. Click Closed. The change order flow
ends, see the following figure.
eFlow Function Operation Guide

## Asset Audit

13.2.1 Audit of New Assets

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Asset Change Order > Asset Audit
Operation Steps
1. Click +Add. The New Asset Audit tab is displayed, see the following figure.
13 Asset Change Order

1. Click Submit to enter the Accept flow, see the following figure.

## Handling Asset Audit Forms

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Asset Change Order > Asset Audit
Operation Steps
1. Click Accept. The accept flow page is displayed, see the following figure.
eFlow Function Operation Guide

1. When the Accept O&M personnel determine that the ticket task is not processed by
themselves, they can click Transfer to transfer the task to other O&M personnel. Accept
O&M personnel select the Wait Process button to enter the Process flow, see the following
figure.

Note:
The subsequent procedure needs to be performed on the APP side.

# SLA Management

Table of Contents

Creating An SLA Task............................................................................................................. 185
Modifying An SLA Task............................................................................................................187
Delete An SLA Task................................................................................................................ 188

Assign different colors to the corresponding tickets in accordance with the TT and WO sql
commands to display the urgency and completion progress of the tickets.
This chapter includes the following topics:
 SLA Management

## Creating An SLA Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SLA Management > SLA Management
Operation Steps
1. Click +Add. The page for creating an SLA task is displayed, see the following figure.
eFlow Function Operation Guide

Parameter                  Definition
Name                       Self-defined
Type                       Eflow→tt or eflow→wo, which must be the same as
that in the event flow.
SLA Level                  Controls the color display of TT or WO single SLA by
level.
Triggering percentage      Task triggering percentage
SLQ Content                TT or WO that needs to be managed by the SLA.

1. Click Submit. The SLA task is created successfully, see the following figure.
14 SLA Management

Note:
This task corresponds to the SLA column of the TT sheet and WO sheet, see the following
figure.

## Modifying An SLA Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SLA Management > SLA Management
Operation Steps
1. Click Modify. The Modify page is displayed, see the following figure.
eFlow Function Operation Guide

1. After the modification, click Submit. The modification is successful, see the following figure.

## Delete An SLA Task

Prerequisite
14 SLA Management

1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SLA Management > SLA Management
Operation Steps
1. Click Delete. The task is deleted successfully, see the following figure.

# GIS

Table of Contents

Site View...................................................................................................................................190
Person View............................................................................................................................. 192
Tickets View............................................................................................................................. 194

This chapter includes the following topics:
 Gis

## Site View

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > GIS
Operation Steps
1. On the gis page, click Site View. The site map is displayed, see the following figure.
15 GIS

1. On the Site View page, select level-1 and level-2 areas, sites, and organizations, and then
click Query. The histogram on the right shows the TT and WO orders of each day in the
recent week, see the following figure.

1. Click a site. The site information and the corresponding TT and WO are displayed, see the
following figure.
eFlow Function Operation Guide

## Person View

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > GIS
Operation Steps
1. On the gis page, click Person View, see the following figure.

1. On the Person View page, select a location type, a person, and a quick query to query the
person tracks within the range, see the following figure.
15 GIS

1. Select WO to view the WO tickets to be processed and different alarm statistics, see the
following figure.

1. Select PM to view the PM tickets to be processed.
eFlow Function Operation Guide

## Tickets View

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > GIS
Operation Steps
1. On the gis page, click Tickets View, see the following figure.

1. On the Tickets View page, select a level-1 area, a level-2 area, and a site disconnection
area, see the following figure.

1. Click a site. The site information and the corresponding TT are displayed, see the following
figure.
15 GIS

1. Click TT to view the details, see the following figure.

# App Management

Table of Contents

Release Record........................................................................................................................196
App Download.......................................................................................................................... 197

This chapter includes the following topics:
 Release Record
 App Download

## Release Record

The APP version can be released on this module.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > App Management > Release Record
Operation Steps
1. Click +Add. The version release editing page is displayed, see the following figure.
16 App Management

1. After editing the information, click Submit. The version is released successfully.

## App Download

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > App Management > APP Download
Operation Steps
1. After the version is released, the APP can be downloaded on this page, see the following

figure.

Leave Ticket
Management

Table of Contents

Add A Leave Ticket..................................................................................................................198
Cancel The Leave Application................................................................................................. 200
Refresh The Leave List............................................................................................................200
Export Leave Application Form................................................................................................201
Query Leave Tickets................................................................................................................ 203
Handle Leave Application Forms............................................................................................. 204
Workflow History.......................................................................................................................206

This chapter includes the following topics:
 Create a leave ticket
 Cancel the leave application
 Refresh the leave list
 Export leave application form
 Query leave tickets
 Handle leave application forms
 Workflow History

## Add A Leave Ticket

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
1. Click +Add. The page for editing the leave ticket is displayed, see the following figure.
17 Leave Ticket Management

1. After editing the information, click Submit. The leave ticket is created successfully, see the
following figure.
eFlow Function Operation Guide

## Cancel The Leave Application

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
1. Click More-> Revoke to cancel the leave ticket, see the following figure.

## Refresh The Leave List

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
17 Leave Ticket Management

1. Click Refresh to manually refresh the trouble ticket page, see the following figure.

## Export Leave Application Form

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
Click Export > Export Setting, and select the names of the exported excel tables and the
columns of the fields to be displayed. By default, the excel tables are exported offline, see the
following figure.

1. On the Export Settings page, click Confirm. The my Export page is displayed, where you
can view the export progress and download documents.
eFlow Function Operation Guide

1. View the exported document
# Leave Ticket Management

## Query Leave Tickets

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
1. Click Advanced Query to configure the query conditions, see the following figure.

2. After configuring the query conditions, click Query. The corresponding leave ticket is
displayed, see the following figure.
eFlow Function Operation Guide

## Handle Leave Application Forms

If a leave applicant submits a leave application, the leave application shall be reviewed at
different levels in accordance with the leave type. If the leave application type is Long-Term
Leave or Resign, the leave application shall be reviewed at level 2. If the leave application
type is Short-Term Leave, the leave application shall be reviewed at level 1 only. If the leave
application is approved and the leave application time expires, the leave applicant's status shall
be updated to Leave.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
1. Click Approve. The page for reviewing the leave application is displayed, see the following

figure.
17 Leave Ticket Management

1. The following figure shows the multi-processing mode of leave tickets in step Approve.

1. Select Reject, enter the rejection reason, and submit it. The ticket enters the step to be
modified. You can modify the submitted application data.
eFlow Function Operation Guide

1. Select Agree. The ticket is automatically closed after being approved.

## Workflow History

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
On the ticket list page, select a leave ticket, and click More > Workflow History to view the
workflow history of the leave ticket, see the following figure.
17 Leave Ticket Management

# Message Center

Table of Contents

Message Template Configuration............................................................................................ 208
Message Sending Records...................................................................................................... 211

Content Summary
Each step of process handling will be sent to the corresponding operations personnel via SMS/
Email.
This chapter contains the following topics:
1.Message Template Configuration
 Used to configure message templates sent by the system
 Supports SMS and email notification methods
2.Message Sending Records
 Records all sent messages
 Facilitates tracking and querying historical notification

## Message Template Configuration

Prerequisites
 The system has been successfully deployed
 Normal system login is available
 The user has eFlow business operation permissions
Operation Path
【Workspace】→【e-flow】→【Message Center】→【Message Template
Configuration】
Operation Steps
1. Click the [Create] button to enter the new/edit page, as shown below:
18 Message Center

Parameter     Definition
Product       The product to which the SMS/email belongs
Service       The business service to which the SMS/email belongs
Scenario      The business operation scenario for SMS/email
sending
Sub-scenario  The sub-step of the business operation scenario
Send Channel  Select whether to send email or SMS to operations
personnel
eFlow Function Operation Guide

1. Click the【Save】button to successfully create the template, as shown below:
1. Click the【Edit】button to edit the message template, as shown below:

1. Click the【Delete】button to remove the message template, as shown below:
18 Message Center

1.Click the 【Start】button to enable the message template and make it effective, as shown
below:

1.Click the 【Stop】 button to disable the message template, as shown below:

## Message Sending Records

Prerequisites
 The system has been successfully deployed
 Normal system login is available
 The user has eFlow business operation permissions
Operation Path
【Workspace】→【e-flow】→【Message Center】→【Message Sending Records】
eFlow Function Operation Guide

Operation Steps
1. The message sending log interface displays all messages sent by various processes

and supports operations such as conditional filtering and export, as shown below:

# SP Management

Table of Contents

Material Mgmt...........................................................................................................................213
Storage Mgmt........................................................................................................................... 220
Warehouse Mgmt..................................................................................................................... 222
W.H. Inbound............................................................................................................................233
W.H. Outbound.........................................................................................................................238
W.H. Transfer........................................................................................................................... 244
Safety Stock Warning...............................................................................................................247
W.H. Storage Check................................................................................................................ 249
SP Dashboard.......................................................................................................................... 253
W.H. Transfer Return............................................................................................................... 255

## Material Mgmt

 Material Mgmt is used to maintain basic information for all spare parts and materials,
including material code, name, manufacturer, category, unit of measure, parameters,
specifications, etc. It supports multi-criteria querying, saving query templates, exporting
material lists, and adding or modifying material records.

## Add Material

Prerequisites
1. The system has been successfully deployed
2. Can log in normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】 → 【e-flow】 → 【SP Management】 → 【Material Mgmt】
Operation Steps
1. Enter the Material Management interface and click the 【Add】 button, as shown in the

figure:
eFlow Function Operation Guide

1. Fill in the required material information and click the 【Submit】 button, as shown in the
figure:

1. The newly added material can be viewed in the Material Management interface, as shown in
the figure:

## Import Material

Prerequisites
1. The system has been successfully deployed
2. Can log in normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】 → 【e-flow】 → 【SP Management】 → 【Material Mgmt】
Operation Steps
19 SP Management

1. In the Material Management interface, click 【More】 → 【Import】 button:

1.

Download  the  import  template  by  clicking                            【Download

:

1. Select the prepared material information file and click 【Import】 button to import
material

**Template】**

data:

## Export Material

rerequisites
1. The system has been successfully deployed
2. Can log in normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】 → 【e-flow】 → 【SP Management】 → 【Material Mgmt】
Operation Steps
eFlow Function Operation Guide

1. In the Material Management interface, select the materials to be exported, click the 【
Export】 button, and download the exported data from "My Exports", as shown in the
figures:

1. The system's materials can be successfully exported, as shown in the figure:

## Discard Material

Material obsoletion means deleting the material from the interface, but it can be restored from
the database and continue to be used after restoration; material deletion cannot be recovered
from the database.
Prerequisites
1. The system has been successfully deployed
2. Can log in normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】 → 【e-flow】 → 【SP Management】 → 【Material Mgmt】
19 SP Management

**Operation Steps**
1. In the Material Management interface, select the material to be obsoleted, click 【More】 →

【Discard】 button, as shown in the figure:

1. Click 【Confirm】 button to obsolete the material, as shown in the figure:

1. If you need to cancel the obsoletion of this material, you can click 【Close】 button.

## Delete Material

Prerequisites
1. The system has been successfully deployed
2. Can log in normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】 → 【e-flow】 → 【SP Management】 → 【Material Mgmt】
Operation Steps
1. In the Material Management interface, select the material to be deleted, click 【More】 →

【Delete】 button, as shown in the figure:
eFlow Function Operation Guide

1. Click 【Confirm】 button to delete the material, as shown in the figure:

## Modify Material

Prerequisites
1. The system has been successfully deployed
2. Can log in normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】 → 【e-flow】 → 【SP Management】 → 【Material Mgmt】
Operation Steps
1. In the Material Management interface, select the material to be modified, click the 【

Modify】 button, as shown below:
19 SP Management

1. Modify the corresponding material information and click the 【Submit】 button, as shown
below:

## Query Material

Prerequisites
1. The system has been successfully deployed
2. Can log in normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】 → 【e-flow】 → 【SP Management】 → 【Material Mgmt】
Operation Steps
1. In the Material Management interface, enter the Material No or Material Name to query

material information, as shown below:

1.In the Material Management interface, use the Advanced Query to search for material
information, as shown below:
eFlow Function Operation Guide

## Storage Mgmt

Storage Mgmt is used to view and manage the current inventory status of materials in various
warehouses, including viewing inventory details, setting inventory thresholds, exporting
warehouse statistics and material details.

## Set Inventory

Prerequisites

1. System has been successfully deployed
2. Can log into the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-flow】→【SP Management】→【Storage Mgmt】
Operation Steps
1. In the Inventory Management interface, click the 【Inventory Threshold Settings】 button,

as shown in the figure:

2. Set the maximum and minimum inventory quantities, click the 【Confirm】 button, as
shown in the figure:
19 SP Management

## Export Warehouse Statistics/Material Details

Prerequisites
1. System has been successfully deployed
2. Can log into the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-flow】→【SP Management】→【Storage Mgmt】
Operation Steps
1. In the Inventory Management interface, select "Warehouse Statistics Details", click the 【

Export】 button, then download the exported data in "My Exports", as shown in the figure:

1. In the Inventory Management interface, select "Export Material Details", click the 【Export】
button, then download the exported data in "My Exports", as shown in the figure:
eFlow Function Operation Guide

## Warehouse Mgmt

## Add Warehouse

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【Spare Parts】→【Warehouse Management】
Operation Steps
1. In the warehouse management interface, click 【Add】 button, as shown in the figure:

1. Fill in the warehouse information, click 【Add】 button, as shown in the figure:
# SP Management

1. You can see the newly created warehouse information in the warehouse list interface, as
shown in the figure:

## Add Storage Location

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【Spare Parts】→【Warehouse Management】
Operation Steps
1. In the warehouse management interface, select a warehouse, click 【Add】, as shown in

the figure:
eFlow Function Operation Guide

1. Fill in the location name and number, click 【Confirm】 button, as shown in the figure:

## Query Warehouse/Storage Location

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【Spare Parts】→【Warehouse Management】
Operation Steps
1. In the warehouse management interface, enter the warehouse name to quickly search for

the warehouse, as shown in the figure:
19 SP Management

1. In the warehouse management interface, enter the location name to quickly search for the
location, as shown in the figure:

## Modify Warehouse/Storage Location

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【Spare Parts】→【Warehouse Management】
Operation Steps
1. In the warehouse management interface, select the warehouse to edit, click 【Modify】

button, as shown in the figure:
eFlow Function Operation Guide

1. After modifying the warehouse information, click 【Submit】 button to save the changes, as
shown in the figure:

1. In the warehouse management interface, select the storage location to edit, click 【
Modify】 button, as shown in the figure:
19 SP Management

1. After modifying the storage location information, click 【Confirm】 button to save the
changes, as shown in the figure:

## Delete Warehouse/Storage Location

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
eFlow Function Operation Guide

【Workbench】→【e-Flow】→【Spare Parts】→【Warehouse Management】
Operation Steps
1. In the warehouse management interface, select the warehouse to delete, click 【Delete】

button, as shown in the figure:

1. Click 【Confirm】 button again to successfully delete the warehouse, as shown in the
figure:

1. In the warehouse management interface, select the storage location to delete, click 【
Delete】 button, as shown in the figure:

1. Click 【Confirm】 button again to successfully delete the storage location, as shown in the
figure:
19 SP Management

## Discard Warehouse/Storage Location

Note: Discarding a warehouse/storage location removes it from the interface but it can be
recovered from the database and continue to be used after recovery; Deleting a warehouse/
storage location cannot be recovered from the database.
Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【Spare Parts】→【Warehouse Management】
Operation Steps
1. In the warehouse management interface, select the warehouse to discard, click 【Discard】

button, as shown in the figure:
eFlow Function Operation Guide

1. Click 【Confirm】 button again to successfully discard the warehouse, as shown in the
figure:

1. In the warehouse management interface, select the storage location to discard, click 【
Discard】 button, as shown in the figure:

1. Click 【Confirm】 button again to successfully discard the storage location, as shown in the
figure:
19 SP Management

## Recover Warehouse/Storage Location

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【Spare Parts】→【Warehouse Management】
Operation Steps
1. In the warehouse management interface, select the warehouse to restore, click 【

Recover】 button, as shown in the figure:

1. Click 【Confirm】 button again to successfully restore the warehouse, as shown in the
figure:
eFlow Function Operation Guide

1. In the warehouse management interface, select the storage location to restore, click 【
Recover】 button, as shown in the figure:

1. Click 【Confirm】 button again to successfully restore the storage location, as shown in the
figure:
19 SP Management

## W.H. Inbound

The spare parts warehousing flow is as follows. For the specific flow and O&M personnel, refer
to Chapter 1.3, see the following figure.

## Add A W.H. Inbound Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-Flow> SP Management> W.H. Inbound
Operation Steps
eFlow Function Operation Guide

On the spare parts warehousing page, click +Add, see the following figure.

Fill in the information to be warehoused, and click Submit, as shown in the figure below.

## Handle W.H. Inbound Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-Flow> SP Management> W.H. Inbound
Operation Steps
On the warehousing list page, select the new warehousing order, and click Verify, see the
following figure.

There are two procedures:
19 SP Management

Note: If you have any questions about the warehousing order, select Reject and click Submit
to return the warehousing order. The warehousing order needs to be updated. After the update
is completed, submit it again. After the submission is completed, return to the original process
and verify it again.
If there is no problem with the warehousing order, select Approve and click Submit, see the
following figure.

After entering the next procedure, ask others to confirm it. Click Confirm, see the following
figure.

There are two flows:

Note: If you have any questions about the warehousing order, select Reject and click Submit
to return the warehousing order. The warehousing order needs to be updated. After the update
is completed, submit it again. After the submission is completed, return to the original process
and verify it again.
eFlow Function Operation Guide

If there is no problem with the warehousing order, select Confirm to Close and click Submit.
The warehousing process ends and the warehousing order is closed, see the following figure.

You can see that the warehousing order is closed in the warehousing order list, see the
following figure.

## Query W.H. Inbound Orders

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-Flow> SP Management> W.H. Inbound
Operation Steps
(1) In the warehousing list, click Condition Query, see the following figure.

Enter the query conditions and click Query. The corresponding warehousing order is displayed,
see the following figure.
19 SP Management

(2) In the warehousing list, enter the warehousing number to quickly find the warehousing
order, see the following figure.

(3 In the warehousing list, click Filter by Column to quickly find the warehousing order, see the
following figure.

## Discarded W.H. Inbound Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-Flow> SP Management> W.H. Inbound
Operation Steps
In the warehousing order list, select the warehousing order to be discarded, and click Discard.
The warehousing order can be discarded, see the following figure.
eFlow Function Operation Guide

## Terminate The W.H. Inbound Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-Flow> SP Management> W.H. Inbound
Operation Steps
In the list of warehousing documents, select the warehousing document to be terminated, and
click Terminate, see the following figure.

The terminated warehousing document becomes closed.

## W.H. Outbound

The spare parts exit-warehouse flow is as follows. For the specific flow and O&M personnel,
refer to Chapter 1.3, see the following figure.
19 SP Management

## Adding A W.H. Outbound Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-Flow> SP Management> W.H. Outbound
Operation Steps
1. On the Ex-Warehousing page, click +Add. The Add Ex-Warehousing page is displayed, see

the following figure.

1. After editing the outbound information, click Submit, see the following figure.
eFlow Function Operation Guide

## Handle W.H. Outbound Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-Flow> SP Management> W.H. Outbound
Operation Steps
1. Click Verify. The Verify flow page is displayed, see the following figure.
19 SP Management

1. The Verify O&M personnel determine that there is a problem with the delivery note, and
select Reject.

The outbound order enters the Update process.

Re-submit the delivery note after the O&M personnel update it.
eFlow Function Operation Guide

After the Verify O&M personnel review the application, the Verify O&M personnel determine
that there is no problem. Select Agree to enter the Confirm process, see the following figure.

1. Click Confirm. The Confirm page is displayed, see the following figure.

1. The Confirm O&M personnel determine that there is a problem with the outbound order,
and select Rject. The outbound order enters the Update process and repeats the above
process. The Confirm O&M personnel determine that there is no problem, and select Agree.
The items are lent successfully, and the stock-out ticket enters the Return process, see the
following figure.
19 SP Management

1. Click Return. The Return page is displayed, see the following figure.
1. Click Submit. The items are returned successfully. The lending ticket flow ends, see the

following figure.
eFlow Function Operation Guide

## W.H. Transfer

The material transfer process is as follows. The specific process and O&M personnel can be
configured in Chapter 1.3, see the following figure.

## Add A W.H. Transfer Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-Flow> SP Management> W.H. Transfer
Operation Steps
1. On the transfer page, click +Add. The Add Edit page is displayed, see the following figure.
19 SP Management

Note: By default, the next process handler is the warehouse keeper added when the warehouse
is created.
1. After editing the new information, click Submit, see the following figure.

## Process The W.H. Transfer Task

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-Flow> SP Management> W.H. Transfer
Operation Steps
1. After the transfer task is created, click Verify. The Verify page is displayed, see the following

figure.

1. If the Verify O&M personnel determine that the transfer conditions are not met, they can
click Reject to reject the transfer and end the transfer task process. When the Verify O&
M personnel determine that the transfer is qualified, click Approve and click Submit. The
transfer task enters the next process, see the following figure.
eFlow Function Operation Guide

1. Click Transfer Outbound Operate. The Transfer Outbound Operate page is displayed, see
the following figure.

1. If the Transfer Outbound Operate O&M personnel determine that the transfer conditions
are not met, they can click Reject to reject the transfer and return the transfer task to the
Verify O&M personnel. When the Transfer Outbound Operate O&M personnel determine
that the transfer is qualified, they select Approve and click Submit. The transfer task enters
the Transfer Inbound Operate flow, see the following figure.

1. Click Transfer Inbound Operate. The Transfer Inbound Operate page is displayed, see the
following figure.
19 SP Management

1. If the Transfer Inbound Operate O&M personnel determine that the transfer conditions are
not met, they can click Reject to reject the transfer and return the transfer task to the Verify
O&M personnel. When the Transfer Inbound Operate O&M personnel determine that the
transfer is qualified, click Approve and click Submit. The transfer task flow ends, see the
following figure.

## Safety Stock Warning

## Safety Inventory Warning Query

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【SP Management】→【Spare Dashboard】→【Safety
Stock Warning】
Operation Steps
1. In the Inventory Warning Statistics query interface, enter query criteria to search quickly, as

shown in the figure:

1. In the Inventory Warning Details query interface, enter query criteria to search quickly, as
shown in the figure:
eFlow Function Operation Guide

## Avg Monthly Borrowing Query

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【SP Management】→【Spare Dashboard】→【Safety
Stock Warning】
Operation Steps
1. In the Monthly Average Borrowing query interface, enter query criteria to search quickly, as

shown in the figure:

## Storage Statistics Query

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
19 SP Management

Operation Path
【Workbench】→【e-Flow】→【SP Management】→【Spare Dashboard】→【Safety
Stock Warning】
Operation Steps
1. In the Inventory Statistics Query interface, enter query criteria to search quickly, as shown in

the figure:

## W.H. Storage Check

The warehouse check flow is as follows. For details, refer to Section 1.3.

## Add Inventory Check Task

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
eFlow Function Operation Guide

Operation Path
【Workbench】→【e-Flow】→【SP Management】→【SP Process Ticket】→【W.H.
Storage Check】
Operation Steps
1. In the Inventory Check interface, click 【Add】 button to enter the new task interface, as

shown in the figure:

1. Add material information, as shown in the figure:
19 SP Management

1. Click 【Submit】 button to create a new task, as shown in the figure:

## Process Check Task

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【SP Management】→【SP Process Ticket】→【W.H.
Storage Check】
Operation Steps
1. In the warehouse check page, click 【Process】 button to enter the Upload page, as shown

in the figure:
eFlow Function Operation Guide

2. Click 【Check】 to update the material check status, as shown in the figure:

1. When the operations staff selects Manual Check status, the check process ends; When the
operations staff selects to click 【Submit】 button, the task enters the confirmation process,
as shown in the figure:

1. Click 【Confirm】 button to enter the Confirmation process interface, as shown in the
figure:
19 SP Management

1. When the operations staff determines that the check task is not completed, select 【
Reject】 button to send the check task back to the Processing staff to re-run the process;
When the Confirming staff determines that the check task is completed, select 【Confirm to
Close】 button, click 【Submit】 button to end the process, as shown in the figure:

## SP Dashboard

## Query In/Out Records

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【SP Management】→【SP Dashboard】→【In/Out
Records】
eFlow Function Operation Guide

Operation Steps
1. In the In/Out Records interface, enter query criteria to search quickly, as shown in the

figure:

1. In the In/Out Records interface, enter the work order number to quickly search for records,
as shown in the figure:

## Export In/Out Records

Prerequisites
1. System has been successfully deployed
2. Can log in to the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【SP Management】→【SP Dashboard】→【In/Out
Records】
Operation Steps
19 SP Management

1. In the Material Management interface, select materials to export, click 【Export 】 button,
then download the exported data in My Exports, as shown in the figure:

## W.H. Transfer Return

The W.H. Transfer Return process is as follows. The specific process and operations personnel
can be configured in section 1.3, as shown in the figure：
eFlow Function Operation Guide

## Create W.H. Transfer Return Task

Prerequisites
1. System has been successfully deployed
2. Can log into the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【SPManagement】→【W.H. TransferReturn】
Operation Steps
1. Click the【+Add】button on the W.H. Transfer Return interface to enter the W.H. Transfer

Return creation page，as shown in the figure:
19 SP Management

Note:
Return Material Code、Return Serial Numbermust match the figure as shown：

1. Click the【Submit】button to submit the task，as shown in the figure:
eFlow Function Operation Guide

## Process W.H. Transfer Return Task

Prerequisites
1. System has been successfully deployed
2. Can log into the system normally
3. User has eFlow business operation permissions
Operation Path
【Workbench】→【e-Flow】→【SPManagement】→【W.H. TransferReturn】
Operation Steps
1. Click the【Verify】button to enter the review page, as shown in the figure：

1. When the review operations personnel determines the W.H. Transfer Return conditions
are not met, you can select thebutton, to reject the W.H. Transfer Return and end the W.
H. Transfer Return task process; When the review operations personnel determines the W.
H. Transfer Return conditions are met, select the【Approve】button, Click the【Submit】
button. The W.H. Transfer Return task enters the next process, as shown in the figure：
19 SP Management

1. Click the【W.H. Transfer Return Outbound Confirmation】button to enter the W.H.
Transfer Return Outbound Confirmation page, as shown in the figure：

1. When the outbound confirmation operations personnel determines the W.H. Transfer Return
conditions are not met, you can select the【Reject】. The W.H. Transfer Return task will
be returned to the review operations personnel; When the outbound confirmation operations
personnel determines the W.H. Transfer Return conditions are met, select the【Approve】
button, Click the【Submit】button, as shown in the figure：
eFlow Function Operation Guide

1. Click the【W.H. Transfer Return Inbound Confirmation】button to enter the W.H.
Transfer Return Inbound Confirmation page, as shown in the figure：

1. When the inbound confirmation operations personnel determines the W.H. Transfer Return
conditions are not met, you can select the【Reject】, The task will be returned to the review
operations personnel; When the inbound confirmation operations personnel determines
the W.H. Transfer Return conditions are met, select the【Approve】button, Click the【
Submit】button. The W.H. Transfer Return task process ends, as shown in the figure：
