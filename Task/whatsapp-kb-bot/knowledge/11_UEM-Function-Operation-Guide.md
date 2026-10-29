iMind

UEM Function Operation Guide

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

2 Intelligent RCA....................................................................................................... 7

2.1 Association Rule Management............................................................................................7
2.1.1 Rule Operation........................................................................................................7
2.1.2 Rule Package Management................................................................................. 18

3 Intelligent Model Management............................................................................23

3.1 Interface Display................................................................................................................ 23
3.2 Activate A Model............................................................................................................... 24
3.3 Suspend A Model.............................................................................................................. 25
3.4 Training Model...................................................................................................................25
3.5 Configuration Model...........................................................................................................26

4 Closed-Loop Management.................................................................................. 28

4.1 Interface Display................................................................................................................ 28
4.2 Creating A Closed-Loop System.......................................................................................29
4.3 Importing A Closed-Loop System..................................................................................... 30
4.4 Exporting A Closed-Loop System..................................................................................... 31
4.5 Delete A Closed-loop System........................................................................................... 31
4.6 Event GPT Closed-Loop System...................................................................................... 32

4.6.1 Interface Display................................................................................................... 32
4.6.2 Event Definition.....................................................................................................33
4.6.3 Rule Group........................................................................................................... 46
4.6.4 AI Model Group.................................................................................................... 54

5 Event Monitoring.................................................................................................. 63

5.1 Current Event.................................................................................................................... 63
5.1.1 Interface Display................................................................................................... 63
5.1.2 Exporting Events...................................................................................................64
5.1.3 Clearing An Event................................................................................................ 66
5.1.4 Event Dashboard.................................................................................................. 67
5.1.5 Event Supervision.................................................................................................73
5.1.6 Event Dispatch......................................................................................................75
5.1.7 Event Reprocessing..............................................................................................76
5.1.8 Condition Query....................................................................................................77
5.1.9 Event Details.........................................................................................................81
5.2 Historical Events................................................................................................................ 83

5.2.1 Interface Display................................................................................................... 83
5.2.2 Export....................................................................................................................84
5.3 Data Dashboard................................................................................................................ 89
5.3.1 Interface Display................................................................................................... 89

6 Chatboat................................................................................................................ 92

6.1 Interface Control................................................................................................................ 92
6.1.1 Control Scaling..................................................................................................... 92
6.1.2 Sidebar Display.....................................................................................................94

6.2 Session.............................................................................................................................. 95
6.2.1 Session Window................................................................................................... 95
6.2.2 Common Query.................................................................................................... 96
6.2.3 Creating A Session...............................................................................................97
6.2.4 Message Response.............................................................................................. 99

6.3 Task Center..................................................................................................................... 101
6.3.1 Activity Event...................................................................................................... 101

6.4 Setting..............................................................................................................................107
6.4.1 Large Model Parameter Configuration............................................................... 107
6.4.2 Knowledge Base Parameter Configuration.........................................................108
6.4.3 Enabling Platform Parameter Configuration....................................................... 109
6.4.4 Automatic Return Parameter Configuration........................................................110

**System User**

Table of Contents

Creating A User............................................................................................................................1

Use the admin account to create an account for UEM maintenance personnel. This account has
the operation permission only for the UEM module.
This chapter includes the following topics:
 Creating a User

## Creating A User

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
Operation Path
Workspace > System Configuration > Security Management
Operation Steps
1. Log in to the system as the admin user. Select System Configuration > Security

Management > Role Management. The User Role Management page is displayed, see the
following figure.
**UEM Function Operation Guide**

1. Click Operation Set > Create Operation Set to create the operation set required by the UEM
role, see the following figure.

1. Select the operation set permission corresponding to UEM, and click Create. The operation
set is created successfully, see the following figure.
1 System User

1. Click Role > Create Role to create the role required by the UEM administrator, see the
following figure.

1. Select No for Area Security Administrator, and click OK, see the following figure.
**UEM Function Operation Guide**

1. Select resources as required, and select "UEM" created in the above step for the operation
set, see the following figure.

Note: Select a resource object on the left, and set the operation set on the right to change the
permissions of the resource object. You can press and hold the ctrl key to continuously select
or invert resource objects, or press and hold the shift key to select or invert resource objects at
the same layer in batches.
1. Click Create to create a UEM role, see the following figure.
1 System User

1. Click User Management > +Create User to create the UEM administrator.
1. Enter the user information, see the following figure.

Parameter  Value
**UEM Function Operation Guide**

Account Rule                               Selecting the Default Rule
Maximum number of concurrent logins        Depending on the actual situation
User group                                 Depending on the actual situation

1. Click Next. The Role Selection page is displayed. Select the created UEM role, see the
following figure.

1. Click Create. The UEM user is created.

**Intelligent RCA**

Table of Contents

Association Rule Management.....................................................................................................7

This chapter includes the following topics:
 Association Rule Management
 Associated Rule Package Management

## Association Rule Management

## Rule Operation

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Operation
Operation Steps
1. Log in to the system, and select Network Intelligence Automation > Intelligent RCA >

Correlation Rule Management > Rule Operation. The basic information of the rule is
displayed, including the rule name, rule package, and rule type. You can enable, stop,
modify, or delete a rule, see the following figure.
**UEM Function Operation Guide**

## Creating A Rule

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Operation
Operation Steps
1. On the Rule Running page, click +New, see the following figure.

1. Improve the rule information, see the following figure.
2 Intelligent RCA

1. Click New. The rule is created successfully, see the following figure.

## Enable Rule

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Operation
Operation Steps
1. On the Rule Running tab, select the rule in stopped status, see the following figure.

1. Click the Enable button on the menu bar to enable rules in batches, see the following figure.
**UEM Function Operation Guide**

1. Click Enable in the Operation column to enable the current rule, see the following figure.
1. Click Enable. The rule is enabled successfully, see the following figure.

## Disabling A Rule

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Operation
Operation Steps
1. On the Rule Running page, select the rule in Enabled status, see the following figure.
2 Intelligent RCA

1. Click Disable on the menu bar to disable rules in batches, see the following figure.
1. Click Disable in the Operation column to disable the rule, see the following figure.
1. Click Disable. The rule is disabled successfully, see the following figure.
**UEM Function Operation Guide**

## Modify A Rule

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Operation
Operation Steps
1. In the Rule Operation window, click Modify, see the following figure.

1. Modify the rule information, see the following figure.
2 Intelligent RCA

1. Click OK. The modification is successful, see the following figure.

## Delete A Rule

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Operation
Operation Steps
**UEM Function Operation Guide**

On the Rule Running tab, select the rule in stopped status, see the following figure.

Click Delete in the menu bar to delete rules in batches, see the following figure.
Click Delete in the Operation column to delete the current rule, see the following figure.

Click Delete. The rule is deleted successfully, see the following figure.
2 Intelligent RCA

## Importing Fms Rules

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Operation
Operation Steps
1. On the Rule Running page, select More > fms-rule-Import, see the following figure.

1. Click Select File to import the local fms rule file, see the following figure.

## Exporting Fms Rules

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Operation
Operation Steps
1. On the Rule Running page, select More > fms-rule-Export, see the following figure.
**UEM Function Operation Guide**

1. Select the corresponding template file to export the fms rules successfully, see the following
figure.

## Rule Operation Logs

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Operation
Operation Steps
1. On the Rule Running page, click Log, see the following figure.

1. You can view the details of the rule operation, see the following figure.
2 Intelligent RCA

## Rule Details

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Operation
Operation Steps
1. On the Rule Running page, click the rule name, see the following figure.

1. You can view the details of the rule, see the following figure.
**UEM Function Operation Guide**

## Rule Package Management

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Package Management
Operation Steps
1. Log in to the system. Select Network Intelligence Automation > Intelligent RCA > Correlation

Rule Management > Rule Package Management. The basic information of the rule package
is displayed, including the rule package name and number of included rules. You can delete,
create, and modify the rule package, see the following figure.
2 Intelligent RCA

## Creating A Rule Package

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Package Management
Operation Steps
1. In the Rule Package Management window, click +New, see the following figure.

1. Edit the new information, see the following figure.

1. Click New. The rule package is created successfully, see the following figure.
**UEM Function Operation Guide**

## Importing A Rule Package

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Package Management
Operation Steps
1. In the Rule Package Management window, click Import, see the following figure.

1. Select a local rule package file. The file can be imported successfully.

## Exporting A Rule Package

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Package Management
Operation Steps
1. On the Rule Package Management page, select a rule package, see the following figure.

1. Click Export. The rule package is exported successfully, see the following figure.
2 Intelligent RCA

## Modifying A Rule Package

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Package Management
Operation Steps
1. In the Rule Package Management window, click Modify, see the following figure.

1. Modify the information, see the following figure.

1. Click OK. The modification is successful, see the following figure.

## Delete A Rule Package

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Package Management
Operation Steps
1. In the Rule Package Management window, click Delete, see the following figure.
**UEM Function Operation Guide**

1. Click Delete to delete the rule package, see the following figure.

## Include Rule

Prerequisite
1. System Login
2. The user has the operation permission of the intelligent RCA.
Operation Path
Workspace > Network Intelligence Automation > Intelligent RCA > Correlation Rule
Management > Rule Package Management
Operation Steps
1. On the Rule Package Management page, click the number of rules, see the following figure.

1. You can view the corresponding rules, and enable, delete, and modify the rules, see the
following figure.

**Intelligent Model**
**Management**

Table of Contents

Interface Display.........................................................................................................................23
Activate A Model........................................................................................................................ 24
Suspend A Model.......................................................................................................................25
Training Model............................................................................................................................25
Configuration Model................................................................................................................... 26

This chapter includes the following topics:
 Activate a model
 Suspend a model
 Training Model
 Configuration Model

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Workspace > Network Intelligence Automation > Intelligent Model Management
Operation Steps
1. Log in to the system, select Network Intelligence Automation > Intelligent Model

Management. The information about the intelligent model is displayed, including the model
status and service scenario. You can activate, suspend, and train the model, see the
following figure.
**UEM Function Operation Guide**

## Activate A Model

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Workspace > Network Intelligence Automation > Intelligent Model Management
Operation Steps
1. On the Intelligent Model Management page, click Activate to activate the selected

suspended models in batches, see the following figure.

1. In the Operation column of the Intelligent Model Management page, click Activate to activate
the current model, see the following figure.

1. The activation is successful, see the following figure.
3 Intelligent Model Management

## Suspend A Model

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Workspace > Network Intelligence Automation > Intelligent Model Management
Operation Steps
1. On the Intelligent Management Model page, click Suspend to suspend the selected models

in batches, see the following figure.

1. In the Operation column of the Intelligent Management Model page, click Suspend to
suspend the current model, see the following figure.

1. Suspended successfully, see the following figure.

## Training Model

Prerequisite
1. System Login
**UEM Function Operation Guide**

2. The user has the operation permission of intelligent model management.
Operation Path
Workspace > Network Intelligence Automation > Intelligent Model Management
Operation Steps
1. On the Intelligent Model Management page, click Train to train the model, see the following

figure.

1. During the training process, see the following figure.

1. The training is successful, see the following figure.

## Configuration Model

Prerequisite
1. System Login
2. The user has the operation permission of intelligent model management.
Operation Path
Workspace > Network Intelligence Automation > Intelligent Model Management
Operation Steps
1. On the Intelligent Model Management page, click Configure to modify the configuration of

scheduled model training, see the following figure.
3 Intelligent Model Management

1. Click Confirm. The configuration information can be modified successfully, see the following
figure.

**Closed-Loop**
**Management**

Table of Contents

Interface Display.........................................................................................................................28
Creating A Closed-Loop System................................................................................................29
Importing A Closed-Loop System.............................................................................................. 30
Exporting A Closed-Loop System.............................................................................................. 31
Delete A Closed-loop System.................................................................................................... 31
Event GPT Closed-Loop System............................................................................................... 32

This chapter includes the following topics:
 Closed-Loop System

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management
Operation Steps
1. Select System > Capability Operation Center > Closed Loop Management. By default, there

are two closed-loop management systems: Event GPT and AIM ind. This procedure uses
Event GPT as an example, see the following figure.
4 Closed-Loop Management

## Creating A Closed-Loop System

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management
Operation Steps
1. On the Closed Loop Management page, click +, see the following figure.

1. Edit the new information, see the following figure.

1. Click New, see the following figure.
**UEM Function Operation Guide**

## Importing A Closed-Loop System

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management
Operation Steps
1. On the Closed Loop Management page, click Import, see the following figure.

1. Select a local closed-loop system file to import, see the following figure.
4 Closed-Loop Management

## Exporting A Closed-Loop System

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management
Operation Steps
1. On the Closed-Loop System page, click....Select Export, see the following figure.

## Delete A Closed-loop System

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management
Operation Steps
**UEM Function Operation Guide**

1. In the closed-loop system interface, click....→ Delete, see the following figure.

1. Click Delete, see the following figure.

## Event GPT Closed-Loop System

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT
Operation Steps
1. Log in to the system, and select Capability Operation Center > Closed Loop Management

> Event GPT. The overview of the closed-loop system is displayed, including the Event
Definition, Rule Group, and AI Model Group modules, see the following figure.
# Closed-Loop Management

## Event Definition

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
1. Log in to the system. Select Capability Operation Center > Closed Loop Management >

Event GPT > Incident Definition. The name, type, and type of the event are displayed. You
can add, delete, modify, query, import, and export the event, see the following figure.

## Creating An Event

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
**UEM Function Operation Guide**

1. On the event definition page, click +New, see the following figure.

1. Configure event information, see the following figure.

1. Click New, see the following figure.
4 Closed-Loop Management

## Enable Event

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
1. On the Event Definition page, select Inactive Event, see the following figure.

1. Click the Enable button on the menu bar to enable events in batches, see the following
figure.
**UEM Function Operation Guide**

1. Click Enable in the Operation column to enable the event, see the following figure.
1. Click Enable to enable events in batches, see the following figure.

## Disabling An Event

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
1. On the Event Definition page, select the event in enabled status, see the following figure.
4 Closed-Loop Management

1. Click Disable on the menu bar to disable events in batches, see the following figure.
1. Click Disable in the Operation column to disable the current event, see the following figure.
1. Click Disable.

## Policy Configuration

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
**UEM Function Operation Guide**

Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
1. On the Event Definition page, select an event, see the following figure.

1. Click Policy Configurate, see the following figure.

1. Click OK, see the following figure.
4 Closed-Loop Management

## Importing Events

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
1. On the event definition page, click Import, see the following figure.

1. Select a local event file. The file is imported successfully, see the following figure.
**UEM Function Operation Guide**

## Export All

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
1. On the Event Definition tab, click Export All, see the following figure.

1. The events can be exported successfully, see the following figure.
4 Closed-Loop Management

## Modifying An Event

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
1. On the event definition page, click Modify in the Operation column, see the following figure.

1. Edit the modification information, see the following figure.
**UEM Function Operation Guide**

1. Click OK. The modification is successful, see the following figure.
4 Closed-Loop Management

## Delete An Event

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
1. On the Event Definition page, select an event, see the following figure.

1. Click Delete on the menu bar to delete data in batches, see the following figure.

1. Click Delete in the Operation column to delete the event, see the following figure.

1. Click Delete. The event is deleted successfully, see the following figure.
**UEM Function Operation Guide**

## Event Details

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
1. On the Event Definition page, click Event Name, see the following figure.

1. View the event details, see the following figure.

## Condition Query

Prerequisite
4 Closed-Loop Management

1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Incident Definition
Operation Steps
1. On the Event Definition page, click Condition Query, see the following figure.

1. After the query conditions are improved, click Query, see the following figure.
**UEM Function Operation Guide**

## Rule Group

## Interface Display

There are "event identification rules", "event preprocessing rules", "event definition rules", "
event location rules", "event handling rules", and "event verification rules" in the rule group.
Because the functions of various rules are the same, this section uses "event identification
rules" as an example.
Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Rule Group
Operation Steps
1. Log in to the system, and select Capability Operation Center > Closed Loop Management

> Event GPT > Rule Group. The Rule Group page describes the rules, see the following
figure.

## Event Identification Rule

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
4 Closed-Loop Management

Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
**Rule Group > Incident Identification Rule**
**Operation Steps**
1. Log in to the system. The basic information of the rule is displayed, such as the rule name

and type. You can add, delete, modify, and query the rule, see the following figure.

## Creating A Rule

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Rule Group > Incident Identification Rule
Operation Steps
1. On the Event Identification Rule page, click +New, see the following figure.

1. Complete the new information, see the following figure.
**UEM Function Operation Guide**

1. Click New, see the following figure.

## Enable Rule

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
4 Closed-Loop Management

Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Rule Group > Incident Identification Rule
Operation Steps
1. On the Event Identification Rule tab, select Disable Rule, see the following figure.

1. Click Enable on the menu bar to enable rules in batches, see the following figure.

1. Click Enable in the Operation column to enable the rule, see the following figure.
**UEM Function Operation Guide**

## Disabling A Rule
Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Rule Group > Incident Identification Rule
Operation Steps
1. On the Event Identification Rule tab, select Enabled Rule, see the following figure.

1. Click Disable on the menu bar to disable rules in batches, see the following figure.
4 Closed-Loop Management

1. Click Disable in the Operation column to disable the rule, see the following figure.

## Modify A Rule

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Rule Group > Incident Identification Rule
Operation Steps
1. On the Event Identification Rule page, click Modify in the Operation column, see the

following figure.

1. Edit the modification information, see the following figure.
**UEM Function Operation Guide**

1. Click OK. The modification is successful, see the following figure.

## Rule Details

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Rule Group > Incident Identification Rule
Operation Steps
1. On the Event Identification Rule page, click Rule Name, see the following figure.
4 Closed-Loop Management

1. You can view the details of the rule, see the following figure.

## Delete A Rule
Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT >
Rule Group > Incident Identification Rule
Operation Steps
1. On the Event Identification Rule page, select a disabled rule, see the following figure.

1. Click Delete on the menu bar to delete rules in batches, see the following figure.
**UEM Function Operation Guide**

1. Click Delete in the Operation column to delete the rule, see the following figure.

## AI Model Group

In the AI model group, there are "intelligent perception model", "intelligent identification model",
and "intelligent delimitation model". Because the functions of various rule interfaces are the
same, the "intelligent perception model" is used as an example.

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT > AI
Model Group
Operation Steps
4 Closed-Loop Management

1. Log in to the system. The GUI describes various model designs, see the following figure.

## Intelligent Perception Model

## Interface Display

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT > AI
Model Group > AI Awareness Model
Operation Steps
1. Log in to the system. The basic information of the model is displayed, such as the rule name

and type. You can add, delete, modify, and query rules, see the following figure.

## Creating A Rule

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
**UEM Function Operation Guide**

Workspace > Capability Operation Center > Closed Loop Management > Event GPT > AI
Model Group > AI Awareness Model
Operation Steps
1. On the Intelligence Model Perception page, tap +New, see the following figure.

1. Edit the new information, see the following figure.

1. Click New.

## Enable Model

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
4 Closed-Loop Management

Workspace > Capability Operation Center > Closed Loop Management > Event GPT > AI
Model Group > AI Awareness Model
Operation Steps
1. On the Intelligence Model Perception page, select a rule that is not enabled, see the

following figure.

1. Click Enable on the menu bar, see the following figure.

1. Click OK to enable rules in batches, see the following figure.

1. Click Enable in the Operation column to enable the current rule, see the following figure.
**UEM Function Operation Guide**

## Disable A Model
Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT > AI
Model Group > AI Awareness Model
Operation Steps
1. On the Intelligent Perception Model page, select the rules that are enabled, see the
following figure.

1. Click Disable in the menu bar to disable rules in batches, see the following figure.

1. Click Disable in the Operation column to disable the rule, see the following figure.
4 Closed-Loop Management

## Modify A Model
Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT > AI
Model Group > AI Awareness Model
Operation Steps
1. Click Modify, see the following figure.

1. Edit the modification information, see the following figure.
**UEM Function Operation Guide**

1. Click OK. The modification is successful, see the following figure.

## Model Details

Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT > AI
Model Group > AI Awareness Model
Operation Steps
1. Click Rule Name, see the following figure.

1. View the details of the rule, see the following figure.
4 Closed-Loop Management

## Delete A Model
Prerequisite
1. System Login
2. The user has the operation permission of closed-loop management.
Operation Path
Workspace > Capability Operation Center > Closed Loop Management > Event GPT > AI
Model Group > AI Awareness Model
Operation Steps
1. On the Intelligent Perception Model page, select a rule that is disabled, see the following
figure.

1. Click Delete in the menu bar to delete rules in batches, see the following figure.

1. Click Delete in the Operation column to delete the current rule, see the following figure.
**UEM Function Operation Guide**

**Event Monitoring**

Table of Contents

Current Event............................................................................................................................. 63
Historical Events.........................................................................................................................83
Data Dashboard......................................................................................................................... 89

This chapter includes the following topics:
 Current Event
 Historical events
 Data dashboard

## Current Event

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident
Operation Steps
1. Log in to the system, and select Maintenance Surveillance > Event Monitor > Current

Incident. The basic information of the current event is displayed, including the event title,
event serial number, and event level. You can export, clear, and view the event, see the
following figure.
**UEM Function Operation Guide**

## Exporting Events

## Export Selected

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident
Operation Steps
1. On the Current Event tab, select an event, see the following figure.

1. Select Export > Export Selected, see the following figure.

1. Click OK. The data is exported successfully, see the following figure.
# Event Monitoring

## Export All

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident
Operation Steps
On the Current Event page, select Export > ExportAll, see the following figure.

Click OK to export all data, see the following figure.
**UEM Function Operation Guide**

## Clearing An Event

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident
Operation Steps
1. On the Current Event tab, select an event, see the following figure.

1. Click Clear in the menu bar to clear events in batches, see the following figure.

1. Click More > Clear in the Operation column to clear the current event, see the following
figure.
5 Event Monitoring

## Event Dashboard

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident
Operation Steps
1. On the Current Event page, click Incident Board. The event dashboard is displayed, see

the following figure. The execution results of events in each phase are displayed. In some
phases, you can click Retry to expand and collapse the results of the dashboard, zoom in/
out the results of the dashboard, and refresh the results manually and periodically, see the
following figure.
**UEM Function Operation Guide**

## Expand Kanban

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident > Incident
Board
Operation Steps
1. On the event dashboard page, click the Expand All icon to expand the dashboard, see the

following figure.
5 Event Monitoring

1. Click﹀ to expand the event results of the current phase, see the following figure.

## Collapse A Dashboard

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident > Incident
Board
Operation Steps
**UEM Function Operation Guide**

1. On the event dashboard page, click the Fold All icon to fold the dashboard, see the following
figure.

1. Click︿. The event results of the current phase are displayed, see the following figure.
5 Event Monitoring

## Zoom Dashboard

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident > Incident
Board
Operation Steps
1. On the event dashboard page, click Zoom to control the zooming of the panel, see the

following figure.
**UEM Function Operation Guide**

## Refresh A Dashboard

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident > Incident
Board
Operation Steps
1. On the event dashboard page, click Refresh to manually refresh the dashboard, see the

following figure.

1. Click Timing Refresh to refresh the dashboard at the scheduled time, see the following
figure.

## Retry

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
5 Event Monitoring

Workspace > Maintenance Surveillance > Event Monitor > Current Incident > Incident
Board
Operation Steps
1. On the event dashboard page, click Retry, see the following figure.

1. Click OK. The retry command is delivered successfully, see the following figure.

## Event Supervision

Prerequisite
**UEM Function Operation Guide**

1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident
Operation Steps
1. In the Current Event window, click Supervision, see the following figure.

1. Improve the supervision information, see the following figure.

1. Click OK. The supervision instruction is delivered successfully, see the following figure.
5 Event Monitoring

## Event Dispatch

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident
Operation Steps
1. On the Current Event page, select More > Dispatch, see the following figure.

1. Click OK. The dispatch instruction is delivered successfully, see the following figure.
**UEM Function Operation Guide**

## Event Reprocessing

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident
Operation Steps
1. Click More > Incident Reprocessing, see the following figure.

1. Click OK. The command is delivered successfully, see the following figure.
5 Event Monitoring

## Condition Query

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident
Operation Steps
1. On the Current Event page, click Condition Query, see the following figure.

1. After editing the query conditions, click Query. The query is successful, see the following
figure.
**UEM Function Operation Guide**

1. Click Save As to save the current query conditions as an unqueried template, see the
following figure.

1. After editing the information, click OK. The template is saved successfully, see the following
figure.
5 Event Monitoring

1. Click Condition Template to find the existing template for quick query, see the following
figure.
**UEM Function Operation Guide**

1. Click the multi-window monitoring icon, see the following figure.
1. The query result can be displayed in another window, see the following figure.
5 Event Monitoring

## Event Details

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Current Incident
Operation Steps
1. On the current event page, click the event title. The event details page is displayed, see the

following figure.
**UEM Function Operation Guide**

1. Click Expand All or Shrink All to zoom in or out the details, see the following figure.

1. Click Relative Data to view the data associated with the new time, see the following figure.
5 Event Monitoring

1. Click Incident Processing Detail. The preprocessing details are displayed, see the following
figure.

1. Click WorkOrder Information. The work order information is displayed, see the following
figure.

1. Click Incident Topology. The event topology is displayed, see the following figure.

## Historical Events

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to monitor events.
**UEM Function Operation Guide**

Operation Path
Workspace > Maintenance Surveillance > Event Monitor > History Incident
Operation Steps
1. Log in to the system, and select Maintenance Surveillance > Event Monitor > History

Incident. The basic information about historical events is displayed, including the event
title, event serial number, and event level. You can export and query the events, see the
following figure.

## Export

## Export Selected

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > History Incident
Operation Steps
1. On the History Monitor page, select History Events, see the following figure.

1. Select Export > Export Selected, see the following figure.

1. Click OK. The data is exported successfully, see the following figure.
5 Event Monitoring

## Export All

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > History Incident
Operation Steps
1. On the History Event page, select Export > Export All, see the following figure.

1. Click OK, see the following figure.
**UEM Function Operation Guide**

## Condition Query

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > History Incident
Operation Steps
1. On the History Event page, click Condition Query, see the following figure.

1. After editing the query conditions, click Query. The query is successful, see the following
figure.
5 Event Monitoring

1. Click Save As to save the current query conditions as an unqueried template, see the
following figure.

1. After editing the information, click OK. The template is saved successfully, see the following
figure.
**UEM Function Operation Guide**

1. Click Condition Template to find the existing template for quick query, see the following
figure.
5 Event Monitoring

## Data Dashboard

## Interface Display

Prerequisite
1. System Login
2. The user has the permission to monitor events.
Operation Path
Workspace > Maintenance Surveillance > Event Monitor > Dashboard
Operation Steps
1. Log in to the system, select Maintenance Surveillance > Event Monitor > Dashboard. The

statistical information of each dimension of the event is displayed on the dashboard, see the
following figure.
**UEM Function Operation Guide**

1. Click the time in the dashboard to collect the time range statistics, see the following figure.

1. Click Event Level to control the display of events at different levels, see the following figure.

1. Click Major for an event to control the display of events in different majors, see the following
figure.
5 Event Monitoring

1. Click Serial Number of the latest event in the dashboard to view the event details, see the
following figure.

**Chatboat**

Table of Contents

Interface Control......................................................................................................................... 92
Session....................................................................................................................................... 95
Task Center.............................................................................................................................. 101
Setting....................................................................................................................................... 107

This chapter includes the following topics:
 Session
 Task Center
 Setting

## Interface Control

## Control Scaling

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant
Operation Steps
1. Log in to the system, and click the floating circle icon. The fault monitoring robot page is

displayed, see the following figure.
6 Chatboat

1. Tap the Zoom button in the upper right corner to zoom in or out, see the following figure.
**UEM Function Operation Guide**

## Sidebar Display

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant
Operation Steps
1. On the Fault Monitor Robot page, click the icon in the upper left corner to control whether to

place the fault on the sidebar, see the following figure.
# Chatboat

## Session

## Session Window

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant
Operation Steps
1. Log in to the system, and click the floating circle icon. The fault monitoring robot page is

displayed, see the following figure.
**UEM Function Operation Guide**

1. In the dialog box, enter the content to be queried. The intelligent assistant matches the
corresponding service agent in accordance with the content, see the following figure.

## Common Query

There are recommended common query parameters on the page for quick query.
Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant
Operation Steps
1. Click the recommended common query. The parameters to be clicked are displayed in the

text box, see the following figure.
6 Chatboat

1. Click OK to complete the query, see the following figure.

## Creating A Session

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant
Operation Steps
1. The Intelligent Assistant page is displayed, see the following figure.
**UEM Function Operation Guide**

1. Click New Chat. The session is reset, see the following figure.

1. Click OK. The related query information is added to the session message, see the following
figure.
6 Chatboat

## Message Response

## Edit A Callback

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant
Operation Steps
1. Click Edit, see the following figure.

1. After modifying the callback message name, click OK to modify the name, see the following
figure.
**UEM Function Operation Guide**

## Delete A Callback

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant
Operation Steps
1. Click Delete, see the following figure.

1. Click Delete, see the following figure.

1. The deletion is successful, see the following figure.
6 Chatboat

## Double-click A Call

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant
Operation Steps
1. Log in to the intelligent assistant, see the following figure.

1. Click a call-back message to go to the corresponding call-back record, see the following
figure.

## Task Center

There are "Activity Event", "To Be Scheduled Event", "Scheduled Event", and "Archived Event"
in the task center. Because the event operations displayed on the page are the same, the "
Activity Event" is used as an example.

## Activity Event

## Interface Display

Prerequisite
1. System Login
**UEM Function Operation Guide**

2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Activity Incident
Operation Steps
1. On the Intelligent Assistant page, click Activity Incident. The overview of each activity event

is displayed, including the event name, event serial number, event level, and occurrence
time, see the following figure.

1. The corresponding event is displayed, see the following figure.

## Activity Event Details

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Activity Incident
Operation Steps
6 Chatboat

1. On the Event Overview page, click an event to view its details, see the following figure.

## Activity Event New Session

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Activity Incident
Operation Steps
1. On the Event Overview page, click New Session to generate a new response, see the

following figure.

1. The new session window of the event is displayed, see the following figure.
**UEM Function Operation Guide**

## Activity Event Dashboard

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Activity Incident
Operation Steps
1. On the Event Overview page, click More and click Incident Board. The corresponding event

dashboard is displayed, see the following figure.
6 Chatboat

## Dispatch

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Activity Incident
Operation Steps
1. On the activity event overview page, click the More icon and click Dispatch to dispatch the

event, see the following figure.

1. Click the OK button to distribute the ticket, see the following figure.
**UEM Function Operation Guide**

## Event Reprocessing

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Activity Incident
Operation Steps
1. On the Event Overview page, click More and click Incident Reprocessing, see the following

figure.

1. Click OK to send an event reprocessing instruction, see the following figure.
6 Chatboat

## Clearing An Event

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Activity Incident
Operation Steps
1. On the Event Overview page, click More and click Clear, see the following figure.

1. Click OK to send an event clearing command, see the following figure.

## Setting

## Large Model Parameter Configuration

Prerequisite
1. System Login
**UEM Function Operation Guide**

2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Settings > LLM Config
Operation Steps
1. Select Settings > LLM Config, see the following figure.

1. After editing the configuration information, click OK. The configuration information is
displayed, see the following figure.

## Knowledge Base Parameter Configuration

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Settings > KB Config
Operation Steps
1. Select Settings > KB Config, see the following figure.
6 Chatboat

1. After editing the configuration information, click OK. The configuration information is
displayed, see the following figure.

## Enabling Platform Parameter Configuration

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Settings > LLM Config
Operation Steps
1. On the Intelligent Assistant page, select Settings > Outter Api Config, see the following

figure.

1. After editing the configuration information, click OK. The configuration information is
displayed, see the following figure.
**UEM Function Operation Guide**

## Automatic Return Parameter Configuration

Prerequisite
1. System Login
2. The user has the operation permission of the fault monitoring robot.
3. There is event data.
Operation Path
Workspace > intelligent assistant > Settings > Autofill Params Config
Operation Steps
1. On the Intelligent Assistant page, select Settings > Autofill Params Config, see the following
figure.

2. After editing the configuration information, click OK. The configuration information is
displayed, see the following figure.
6 Chatboat
