[图]
iMind eFlow Function Operation Guide
Product Version: V6.26.10.F30B3
[图]

LEGAL INFORMATION [图]
ZTE CONFIDENTIAL: This document contains proprietary information of ZTE and is not to be disclosed or used without the prior written permission of ZTE.
Due to update and improvement of ZTE products and technologies, information in this document is subjected to change without notice.
ZTE is a registered trademark of ZTE CORPORATION. All company, brand and product names are trade or service marks, or registered trade or service marks, of ZTE CORPORATION or of their respective owners.
This document is provided as is, and all express, implied, or statutory warranties, representations or conditions are disclaimed. Except as expressly provided in any written license between ZTE CORPRORATION and its licensee, the user of this document shall not acquire any license to any name, logo, mark, etc.
This product complies with the design requirements for environmental protection and personal safety. The storage, use and disposal of the product should comply with the product manual, relevant contracts or the laws and regulations of relevant countries.
The products, services or features you purchase are subject to ZTE's commercial contracts and terms. All or part of the products, services or features described in this document may not be within the scope of your purchase or use. Unless otherwise agreed in the contract, ZTE makes no express or implied representations or warranties regarding the contents of this document.

Statement on the Use of Third-Party Embedded Software:
If the third-party embedded software such as Oracle, Sybase/SAP, Veritas, Microsoft, Vmware, and Redhat is delivered together with this product of ZTE, the embedded software must be used as only a component of this product. If this product is discarded, the licenses for the embedded software must be void and must not be transferred. ZTE will provide technical support for the embedded software of this product.

LEGAL INFORMATION
ZTE CONFIDENTIAL: This document contains proprietary information of ZTE and is not to be disclosed or used without the prior written permission of ZTE.
Due to update and improvement of ZTE products and technologies, information in this document is subjected to change without notice.
ZTE is a registered trademark of ZTE CORPORATION. All company, brand and product names are trade or service marks, or registered trade or service marks, of ZTE CORPORATION or of their respective owners.
This document is provided as is, and all express, implied, or statutory warranties, representations or conditions are disclaimed. Except as expressly provided in any written license between ZTE CORPRORATION and its licensee, the user of this document shall not acquire any license to any name, logo, mark, etc.
This product complies with the design requirements for environmental protection and personal safety. The storage, use and disposal of the product should comply with the product manual, relevant contracts or the laws and regulations of relevant countries.
The products, services or features you purchase are subject to ZTE's commercial contracts and terms. All or part of the products, services or features described in this document may not be within the scope of your purchase or use. Unless otherwise agreed in the contract, ZTE makes no express or implied representations or warranties regarding the contents of this document.

Statement on the Use of Third-Party Embedded Software:
If the third-party embedded software such as Oracle, Sybase/SAP, Veritas, Microsoft, Vmware, and Redhat is delivered together with this product of ZTE, the embedded software must be used as only a component of this product. If this product is discarded, the licenses for the embedded software must be void and must not be transferred. ZTE will provide technical support for the embedded software of this product.

Serial Number:

# Configuration

Use the admin account to create an account for eFlow maintenance personnel. This account has the operation permission only for the eFlow module.
This chapter includes the following topics:
- System User
- Configuring CMDB Personnel
- Event Configuration Procedure
- Configuring Preventive Maintenance Items
- SMS Notification Configuration for Major Faults

## System User

Create a role with the operation permissions of the eFlow module, which is assigned to the eFlow user.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
Operation Path
Workspace > System Configuration > Security Management
Operation Steps
- Log in to the system as the admin user. Select System Configuration > Security Management > Role Management. The User Role Management page is displayed, see the following figure.
[图]
[图]
- Click Operation Set > Create Operation Set to create the operation set required by the eFlow role, see the following figure.
[图]
- Select the operation set permission corresponding to eFlow, and click Create. The operation set is created successfully, see the following figure.
[图]
[图]
- Click Role > Create Role to create the role required by the eFlow administrator, see the following figure.
[图]
- Select No for Area Security Administrator, and click OK, see the following figure.
[图]
- Select resources as required, and select "eFlow" created in the above step for the operation set, see the following figure.
[图]
Note: Select a resource object on the left, and set the operation set on the right to change the permissions of the resource object. You can press and hold the ctrl key to continuously select or invert resource objects, or press and hold the shift key to select or invert resource objects at the same layer in batches.
- Click Create to create a eFlow role, see the following figure.
[图]
- Click User Management > +Create User to create the eFlow administrator.
[图]
- Enter the user information, see the following figure.
[图]

| Parameter | Value |
|---|---|
| Account Rule | Selecting the Default Rule |
| Maximum number of concurrent logins | Depending on the actual situation |
| User group | Depending on the actual situation |

- Click Next. The role selection page is displayed. Select the created eFlow role, see the following figure.
[图]
- Click Create. The eFlow user is created.
[图]

## Configuring CMDB Personnel

The personnel information here provides maintenance personnel for different event process processing of the e→flow module. The information must be the same as the account registered in the personnel system.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
Operation Path
Workspace > System Configuration > Configuration Data
Operation Steps
- Log in to the system as the admin user. Select System Configuration > Configuration Data. The configuration data page is displayed, see the following figure.
[图]
[图]
- Click person > +Add to add a new person, see the following figure.
[图]

| ObjectID | Object ID No space is allowed, and it is the same as the account registered in the personnel system. |
|---|---|
| Phone | Phone number of the person. It is required to send SMS messages. |
| Email | Personnel mailbox, required for sending emails |
| Managed Regions | In the personnel management area, in the TT/WO, the personnel can view all the tickets of the Site in their own management area, but cannot view the tickets of the Site not in their own management area. |
| Status | Select Active |
| ManagedOrganization | Management organization. Select the same configuration as that in the Site. |

[图]
After editing the personnel information, click OK to add the personnel.
- Click More > Export All. The exported excel file can be used as the backup of personnel information. It is recommended that you copy and save the file before each operation, see the following figure.
[图]
- Modify the Excel information. You can modify the original data or add new data, see the following figure.
[图]
- Click More > Import Management to import the excel file, as shown in the figure below.
[图]
- Click Browse, select a file, and click Import. The file is imported successfully, see the following figure.
[图]

## Event Configuration Procedure

Event process: Defines the process of event processing. For example, TT, WO, and SP are restricted by this process. This procedure uses TT as an example.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
Operation Path
Workspace > Capability Operation Center > Workflow Engine > Incident Flow Modeling
Operation Steps
- On the event process modeling page, click eflow→tt. The TT process editing page is displayed, see the following figure.
[图]
[图]
- Click FOA ccept to add or delete a person with the FO permission, see the following figure.
[图]
- Click Select Task Handlers to grant the FO role permissions to the group or personnel, see the following figure.
[图]
Note:
Fo role: Maintenance personnel analyze and handle fault reports in the following four ways:
- If a fault can be handled directly, the maintenance personnel shall handle it directly. The maintenance personnel shall fill in the root cause and handling steps of the fault, and close the fault ticket directly.
- If a fault needs to be handled on site, a WO work order needs to be dispatched. The maintenance personnel select to generate a work order. The system automatically generates a work order. After all work orders are processed, the maintenance personnel determine whether the fault is solved.
- The maintenance personnel cannot handle the fault, and need to escalate the fault to the O&M personnel of the BO role. The O&M personnel of the BO role handle the fault. After the fault is handled completely, the maintenance personnel determine whether the fault is solved.
- The maintenance personnel cannot handle the fault directly. The fault needs to be handled by a third-party device vendor. If the fault is to be handled by a third-party device vendor, the fault ticket task still stays with the maintenance personnel. The maintenance personnel need to fill in the third-party vendor's feedback information, and confirm whether the fault is solved.
- Click BOA ccept (the BO role is used as an example here) to grant the rights of the BO role to the personnel or groups, see the following figure.
[图]
[图]

## Configuring Preventive Maintenance Items

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
Operation Path
Workspace > System Configuration > Configuration Data
Operation Steps
- Log in to the system as the admin user. Select System Configuration > Configuration Data. The configuration data page is displayed, see the following figure.
[图]
- Search for "PM", see the following figure.
[图]

| Parameter | Definition |
|---|---|
| PMContent | Specific preventive maintenance items, including the network type, preventive maintenance sub-type, and preventive maintenance category. |
| PMResultType | Preventive Maintenance Result Dimension |
| PMMaintainingType | Preventive Maintenance Category |
| PMContentSeverity | Preventive Maintenance Level |
| PMContentType | Preventive maintenance sub-category, which can be mounted on the preventive maintenance category. |
| PMNetworkType | Network type of the preventive maintenance item. |
| PMPeriod | Preventive Maintenance Period |

- Other parameters are the same as the above parameters. This procedure uses PMM aintainingType as an example. You can configure them as required.
- Click PMM aintainingType, and then click +Add. The preventive maintenance page is displayed, see the following figure.
[图]
- Set the parameters as required, and click OK. The preventive maintenance category is customized successfully.

## SMS Notification Configuration for Major Faults

SMS notification configuration for major faults uses the keyword (NE Name&&Severity) to restrict the flow of sending SMS messages.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
Operation Path
Workspace > System Configuration > Configuration Data
Operation Steps
- Log in to the system. Select System Configuration > Configuration Data. The configuration data page is displayed. Search for SMS, see the following figure.
[图]
- Click +Add. The Edit dialog box is displayed, see the following figure.
[图]
Note:
This configuration restricts the trouble tickets with the NE Nname and Severity fields.
- Click OK. SMS notifications are configured successfully.

# User Group

A user group is a group of personnel. Different event process roles can be assigned to the group. For example, if the FO role in the TT is assigned to the group, the group and its members have the permissions of the FO role, which can be assigned to the group in Chapter 1.3.
This chapter includes the following topics:
- Creating a User Group
- Modifying a User Group
- Delete a user group
- Querying User Groups
- User Group Management

## Creating A User Group

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > Capability Operation Center > Workflow Engine > User Group
Operation Steps
- On the User Group tab, click +New to add a user group, see the following figure.
[图]
[图]
[图]

| Parameter | Value |
|---|---|
| Member | Only the users that exist in the person table (Security Management > User Management > Configuration Data > Data Management) can be displayed here. You can add members to the user group or add members in the 2.5 section. |

- After the new information is completed, click Create. The user group is created successfully, see the following figure.
[图]

## Modifying A User Group

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > Capability Operation Center > Workflow Engine > User Group
Operation Steps
- Click Modify. The Edit dialog box is displayed, see the following figure.
[图]
- After modifying the information, click Modify. The user group is modified successfully, see the following figure.
[图]
[图]

## Delete A User Group

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > Capability Operation Center > Workflow Engine > User Group
Operation Steps
- Click Delete. A confirmation dialog box is displayed, see the following figure.
[图]
[图]
- Click Delete. The user group is deleted successfully, see the following figure.
[图]

## Querying User Groups

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > Capability Operation Center > Workflow Engine > User Group
Operation Steps
- Click Advanced Query. The query list is displayed, see the following figure.
[图]
[图]
- After editing the query conditions, click Query to query user groups, see the following figure.
[图]

## User Group Management

User group. This module enables you to add a user to a group. You can see the groups that a user belongs to.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > User Group Management
Operation Steps
- Log in to the system, and click User Group Management. The user group management page is displayed, see the following figure.
[图]
[图]
- Click +Add. The Edit dialog box is displayed, see the following figure.
[图]
[图]

| Parameter | Value |
|---|---|
| User ID | Only the users that exist in the person table of Security Management > User Management > Configuration Data > Data Management can be displayed here. |
| Group | Select Capability Operation Center > Workflow Engine > User Group. |

- After editing the new information, click Submit. The user is added to the group successfully, see the following figure.
[图]
[图]
- Click Modify. The Edit dialog box is displayed, see the following figure.
[图]
[图]
- After modifying the information, click Submit. The modification is successful, see the following figure.
[图]

# Roles and Processes

The O&M personnel perform different service tasks in accordance with their roles in the O&M system. You can find the operations required by the roles in accordance with the role categories provided by the O&M system, and support the actual work in accordance with the operations corresponding to multiple roles in the system.
The roles and organizations of the O&M system are as follows:
[图]
For a description of the roles in the O&M system, refer to the following table.

| Fo O&M engineer | The main responsibility is to use the NMS and integrated NMS provided by each device manufacturer to monitor the device alarms of each device manufacturer, discover and confirm the device alarms of each device manufacturer in an area in a timely manner, and handle the alarms in accordance with the urgency. For a fault alarm or complaint, you need to create a work order through the O&M system and trace the troubleshooting situation of the troubleshooting personnel. After the fault is solved, you can confirm the alarm status on the corresponding NMS, so that the fault can be tracked, handled, and solved in a timely manner to ensure normal service operation. In most cases, teams are on duty in turn. Each team has a shift leader. |
|---|---|
| Customer Service Engineer (HelpDesk Engineer (HDE) | Handles consultation and complaint work orders from the customer care center and customer maintenance departments, and checks Causes and solutions. In most cases, teams are on duty in turn. Each team has a shift leader. |
| Bo O&M Engineer | Technical expert in each field, responsible for locating and handling critical faults and alarms, and performing performance, configuration, and backup Component management, providing technical support for FLE (for example, making decisions on problems, submitting difficult problems of products to the supplier Solution by suppliers and network performance analysis). |
| NOC Manager NOC Manager | As a member of the management layer of the NOC Center, the NOC manager pays attention to the operational status of the entire network and customer satisfaction. Degree. |
| Fe (Field Engineer) O&M engineer | The O&M personnel in each region are mainly responsible for receiving fault maintenance requests from the NOC center. Ask for (usually issued through work orders) to organize the pre-recovery of services on site (for example, in important services). Fault location, troubleshooting, and service recovery to control the impact of the fault on services. In the minimum range. |
| FM Manager FM Manager | As a member of the management layer of the onsite maintenance team, organizes and schedules the FME, and tracks onsite maintenance tasks for confirmation. Ensure that the network is operating properly. |

## Fault Ticket Roles and Processes

When a fault occurs, the generated fault alarm is automatically sent to the e→flow module, and the corresponding fault ticket is automatically generated. You can also manually create trouble tickets for faults that are not automatically generated.

### Role

Troubleshooting involves the following roles:
Eflow O&M engineer: Creates, upgrades, handles, and confirms trouble tickets, and assigns trouble tickets to the O&M engineer of the FO role.
O&M personnel of the FO role: They can create, upgrade, handle, and confirm trouble tickets. When a trouble ticket needs to be handled on site, the corresponding work order shall be dispatched.
O&M personnel as BO: They can process trouble tickets. When a trouble ticket needs to be handled on site, the corresponding work order is dispatched.
Fe role: Acts as the O&M personnel to handle the work orders dispatched for trouble tickets, and does not directly participate in the trouble ticket handling process.

### Procedure

The troubleshooting flow is as follows:
[图]
- The FO role is used to analyze and handle fault tickets. There are four options:
- For the faults that can be handled directly by the O&M personnel of the FO role, the faults shall be handled directly. The O&M personnel of the FO role shall fill in the fault root cause and handling steps, and the fault ticket shall be closed directly.
- If a fault needs to be handled on site, a task work order needs to be dispatched. The O&M personnel of the FO role select to generate a work order, and the system automatically generates a work order. The work order is still handled by the FO. The FO can escalate the work order to the BO or a third party for handling. However, the work order can be closed only after all work orders are handled and closed.
- Fo O&M personnel cannot handle the fault. The fault must be escalated to BO O&M personnel, who shall handle the fault.
- The O&M personnel of the FO role cannot directly handle the fault. The fault needs to be handled by a third-party device vendor. Wait for the third party to handle the fault, and fill in the information of the third-party vendor. The fault ticket task is transferred to the third-party claiming step, and the third-party claiming step is performed.
- Bo role O&M personnel Role O&M personnel has three options for analyzing and handling fault tickets:
- If the O&M personnel of the BO role can directly handle the fault, the O&M personnel of the BO role shall fill in the root cause and handling steps of the fault, and submit them to the FO for confirmation.
- A fault needs to be handled on site, and a task work order needs to be dispatched. The O&M personnel of the BO select to generate a work order. The work order is still processed by the BO, and the BO can continue to process the work order. However, the work order can be closed only after all work orders are processed and closed.
- The O&M personnel of the BO role cannot directly handle the fault. The fault needs to be handled by a third-party device vendor. Wait for the third party to handle the fault, and enter the information of the third-party vendor. The trouble ticket task is transferred to the third-party claiming step, and the third-party claiming step is performed.

## Work Order Roles and Processes

A work order refers to a work order that requires field engineers to handle temporary tasks on a site, for example, a work order task assigned by a trouble ticket. The system needs to standardize and track the entire work of field engineers, and provide the function of recording the work progress on the Web client.

### Role

A work order involves the following roles:
 FO Role of O&M personnel: Creates work orders in accordance with the handling of fault orders, and assigns work orders to the FE (Field Engineer).
After the FE completes the processing, the work order is finally confirmed.
 FE Role of O&M personnel: Determines whether to accept or transfer the work orders created by the FO or automatically generated by the system. After accepting the work orders, the O&M personnel process the work orders.
 FM Role O&M personnel: Field management manager, who manages the O&M team, creates and reviews work orders in accordance with the handling of fault orders.

### Procedure

Process Design Steps
Work orders are divided into FL work orders and AT work orders based on sub-work order types. The AT work order operation flow is divided into five phases: Create, Accept, Process, Confirm, and Closed. The Start Trip, Arrive Site, and Leave Site phases are added to the FL work order flow. The work order flow is as follows:
[图]
Procedure:
- Create: A work order can be manually created by the FO or automatically created by the system due to service information.
- Accept: When accepting a work order task, you must determine whether to directly process the task, transfer the work order, and go to the site in accordance with the task site and the current task execution status. After the corresponding judgment is made, there are three processing options:
 processing: After the work order is accepted, the next-step work order is processed.
 transfer: After the work order is transferred, another FE determines whether to process the work order.
Departure: Executes a departure task before a work order leaves the site.
- Start Trip Departing from the site: Before going to the site, you need to perform the "Departing" operation. It takes some time during the departure process. You can feed back the progress information regularly through the phase.
- Arrive Site Check-in: There are two options:
Check-in: When entering the site, fill in the arrival time to complete the check-in. After the check-in is completed, you can enter the site to process the work order.
Direct handling without entering the site: For a work order that does not need to be handled directly, enter the reason and then submit the work order.
- Process Work order processing:
When processing a work order, you can select whether to suspend the work order in accordance with the task conditions. If the task conditions are not met, you can suspend the work order. If the task conditions are met, you can unsuspend the work order and continue processing the work order task. After the work order is handled, submit the work order for confirmation.
- Leave Site Check-in after departure: After the work order is handled, fill in the departure time to complete the check-in after departure, and then enter the next confirmation step.
- Confirm Confirm the processing of the work order:
When confirming the processing of a work order, determine whether to close or reject the work order in accordance with the processing of the work order. After the corresponding judgment is made, there are two processing options:
 Close: After the work order is closed, the next work order is closed.
 Reject: After the work order is rejected, the work order is returned to the work order processing step, and the FE that accepts the work order continues to complete the processing task.
- Closed Work order closure:
After a work order is closed, the entire work order service flow ends.

## Scenario

This section describes several troubleshooting scenarios, including simple troubleshooting scenarios and complicated troubleshooting scenarios.

### Simple Troubleshooting Scenarios

- Creating a Trouble Ticket
When a fault occurs, the O&M personnel manually creates a trouble ticket, fills in the basic information of the trouble ticket, and submits the trouble ticket to the FO O&M personnel.
- Fo O&M personnel handle trouble tickets.
After receiving the fault report, the FO O&M personnel found that the fault was within the scope of handling, and handled the 3.This fault ticket.
- Fo O&M personnel handle trouble tickets
After handling the fault, the FO O&M personnel fill in the root cause of the fault and close the fault ticket.

### Complicated Troubleshooting Scenarios

- Creating a Trouble Ticket
When a fault occurs, the O&M personnel manually create a trouble ticket, fill in the basic information of the trouble ticket, and submit the trouble ticket.
Sent to FO O&M personnel.
- Fo O&M personnel handle trouble tickets
After receiving the trouble ticket, the FO O&M personnel found that the trouble ticket was not handled by the FO O&M personnel. The FO O&M personnel escalated the trouble ticket to the BO O&M personnel.
- Troubleshooting Ticket Handling by BO O&M Personnel
When handling a fault, the O&M personnel found that the fault was difficult. Therefore, they dispatched a task work order to the O&M personnel of the FE.
- Fe O&M personnel handle work orders.
The FE O&M personnel handle the fault and fill in the root cause of the fault.
- The FO O&M personnel confirm the fault ticket.
The FO O&M personnel confirmed the root cause of the fault in the fault ticket, and found that there was no problem and the fault had been fixed. The FO O&M personnel closed the fault ticket.

# Trouble Ticket&&Work Ticket

There are different types of tickets in the system, such as trouble tickets and work orders. These tickets involve different aspects of O&M management and have different service processes, but have some common operations. Describes how to create, query, discard, terminate, and export documents. For the troubleshooting flow and maintenance personnel, refer to Section 3.3. For the configuration, refer to Section 1.3.

## Trouble Ticket

This chapter includes the following topics:
- Creating a Trouble Ticket
- Terminating a trouble ticket
- Discarding a trouble ticket
- Refresh the trouble ticket list
- Updating a Trouble Ticket
- Exporting a Trouble Ticket
- Handling a Trouble Ticket
- Workflow History
- Site alarm

### Creating A Trouble Ticket

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
- On the trouble ticket page, click +Add. The page for editing the new trouble ticket is displayed, see the following figure.
[图]
[图]
[图]
[图]
Note: On the page for creating a fault ticket, set the parameters as required.
- After editing the new information, click Submit. The trouble ticket is created successfully, see the following figure.
[图]
[图]
Note: After the trouble ticket is created, only the "Operator" assigned when the trouble ticket is created has the operation permission for the follow-up process of the trouble ticket.

### Terminating A Trouble Ticket

After entering the trouble ticket list page, you can forcibly terminate the unnecessary trouble tickets. The status of the terminated trouble tickets is closed, which can be queried through conditions.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
- Select the trouble ticket to be terminated, and click More > Terminate to terminate the trouble ticket, see the following figure.
[图]
- Click Confirm. The trouble ticket is terminated successfully, see the following figure.
[图]
- Search for the terminated trouble tickets. The status is close, see the following figure.
[图]

### Discarding A Trouble Ticket

After entering the trouble ticket list page, you can discard unnecessary trouble tickets. If a trouble ticket is discarded, it cannot be found on the page.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
- Select the trouble tickets to be discarded, and click More > Discard. The trouble tickets can be discarded, see the following figure.
[图]
- Click Confirm. The trouble ticket is discarded successfully, see the following figure.
[图]
- The discarded trouble tickets cannot be found on the page, see the following figure.
[图]
[图]

### Refresh The Trouble Ticket List

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
- Click Refresh to manually refresh the trouble ticket page, see the following figure.
[图]
- Click Auto Refresh to set the automatic refresh time. After the time is set, the page is refreshed in accordance with the default setting, see the following figure.
[图]
[图]

### Updating A Trouble Ticket

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
- Click Update. The page for updating the trouble ticket is displayed, see the following figure.
[图]
- Click Submit to submit the update information, see the following figure.
[图]

### Querying Fault Tickets

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
- Click Condition Query to configure the query conditions, see the following figure.
[图]
- After configuring the query conditions, click Query to query the corresponding trouble tickets, see the following figure.
[图]
- Click Save As Template to save the query template, see the following figure.
[图]
- Fill in the template information and click Confrim. The template is saved successfully, see the following figure.
[图]
- Click Condition Template. The saved query template is displayed, see the following figure.
[图]
- Click the template name. A new query window is displayed, see the following figure.
[图]
- Click the column search icon to search for some columns, see the following figure.
[图]

### Exporting A Trouble Ticket

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
- Click the Export icon to export the trouble ticket successfully, see the following figure.
[图]
[图]

### Handling A Trouble Ticket

Faults that can be handled directly after maintenance personnel claim the work order. The fault is handled directly. The maintenance personnel fill in the root cause and handling steps of the fault, and the fault ticket is closed directly. A task work order needs to be dispatched for a fault. The maintenance personnel select to generate a work order, and the system automatically generates the work order. The work order stays in the current processing step. The maintenance personnel can continue to escalate the work order, but can close the work order only after all work orders are processed and closed.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The login account has the permission to handle trouble tickets.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
1. Click Fo Accept in the Operation column. The Trouble Ticket Claim page is displayed, see the following figure.
[图]
[图]
There are two Fo Accept processing modes, see the following figure.
[图]
- If Claim is selected, click Accept, and select whether the ticket processing permission is shared by the group. Click YES, and the selected Operator operator group has the processing permission for this ticket. If you click NO, you can select Operator only.
[图]
- Select the rejection ticket and click Reject. Select the Operator confirmation person and enter the confirmation step to confirm whether the rejection ticket is allowed.
[图]
2. Click Fo Process in the Operation column. The Trouble Ticket page is displayed, see the following figure.
[图]
3. The O&M user can edit the trouble ticket information or start the next step of the trouble ticket, see the following figure.
[图]
4. In Step FO Process, there are multiple handling modes for fault tickets, see the following figure.
[图]
- Select a work order to be assigned to the WO, and click Create WO. Select the sub-type of the WO work order to be created, see the following figure.
[图]
Click Operator to select the O&M personnel of the WO, see the following figure.
[图]
Click Confirm, see the following figure.
[图]
Click Submit. The FO instruction is issued successfully. The corresponding WO is generated in the TT form, see the following figure.
[图]
- In Step FO Process, close the trouble ticket, and click Confirm to fill in the root cause information, see the following figure.
[图]
[图]

| Name | Value |
|---|---|
| RC Main Category | Level-1 root cause |
| RC Sub Category | Subcategory root cause |
| RC Description | Description |
| Alarm Clear Time | Alarm clearing time |
| Processing Description | Handling Procedure Description |

After editing the trouble ticket submission information, click OP erator to enter the confirmation step, see the following figure.
[图]
[图]
In the work order confirmation phase, you can close the trouble ticket or reject the FO.
[图]
- In step FO Process, click Transfer. The Operator selects another FO for processing.
[图]
- In Step FO Process, click Phased Reply to fill in the work order processing progress in this phase.
[图]
- In Step FO Process, click BO Process. The operator assigns it to the BO personnel. After the submission, the BO personnel claim it and process it.
[图]
- In Step FO Process, click Third Process. The operator selects a third-party person to be assigned. After the submission, the third-party person will claim the application and process it. [图]
[图]
[图]
[图]

### Workflow History

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
- Click More > Workflow History. The workflow history window of the trouble ticket is displayed, see the following figure.
[图]
- On the workflow history page, you can see the ticket processing process, current status, and handler, see the following figure.
[图]

### Site Alarm

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Trouble Ticket
Operation Steps
- Click More > Site Alarm. The site alarm window is displayed, see the following figure.
[图]
[图]

## Work Order

This chapter includes the following topics:
- Creating a Work Order

### Creating A Work Order

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
Click +Add. The page for creating and editing a work order is displayed, see the following figure.
[图]
[图]
Note: Set the parameters on the new work order page as required.
Click Operator to add a work order handler, see the following figure.
[图]
[图]
Note: The work order handler is configured in the work order process in Chapter 1.3.
After adding a ticket handler, click Submit. The ticket is created successfully, see the following figure.
[图]
[图]

### Refresh The Work Order List

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
- On the ticket page, click Refresh to manually refresh the ticket page, see the following figure.
[图]
- Click Auto Refresh to set the automatic refresh time. After the time is set, the page is refreshed in accordance with the default setting, see the following figure.
[图]
[图]

### Work Order Statistics List

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the work order page, click Count to count the number of work orders in each status, see the following figure.
[图]
[图]

### Discarded Work Order

After entering the ticket list page, you can discard unnecessary tickets. If a ticket is discarded, it cannot be queried on the page.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the Work Order page, select the work orders to be discarded, and click Discard, see the following figure.
[图]
Click Confirm to cancel the work order, see the following figure.
[图]
To cancel this work order, click Cancel.

### Querying Work Orders

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
- Quick query:
On the work order list page, enter the work order number to query the work order quickly, see the following figure.
[图]
- Condition query:
On the ticket list page, click Condition Query, see the following figure.
[图]
Set the query conditions, for example, WO No., TT No., ticket status, and Create Time. You can combine the query conditions with each other or query a single condition. Click Query, see the following figure.
[图]
- The following example shows how to query template configurations:
After the query conditions are configured, click Save As Template, see the following figure.
[图]
Enter the template name, and click Confirm to save the query template for use next time, see the following figure.
[图]
On the ticket list page, click Condition Templates to view the saved query template, see the following figure.
[图]
Click a template name to query the work orders that meet the template conditions, see the following figure.
[图]
- Filter query:
On the work order list page, click Column Search, see the following figure.
[图]
Enter the query conditions to quickly search for the data that meets the query conditions, see the following figure.
[图]

### Exporting A Work Order

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the work order list page, select multiple or all the work orders to be exported, and click Export to export the data of the work order list, see the following figure.
[图]
[图]

### Terminating A Work Order

After entering the ticket list page, you can forcibly terminate the process of stopping unnecessary tickets. The status of the terminated ticket is closed. You can query the status through conditions.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the ticket list page, select the ticket to be terminated, and click More > Terminate, see the following figure.
[图]
Click Confirm. The work order is terminated successfully, see the following figure.
[图]
Search for the work order whose status is close, see the following figure.
[图]

### Exporting A Work Order Template

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the work order list page, click More > Export Template to export the work order template, see the following figure.
[图]
[图]

### Handling A Work Order

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the work order list page, select the work order to be handled, and click Accept, see the following figure.
[图]
Options:
1) To receive the work order, select Process and click Submit.
[图]
[图]
[图]
After entering this flow, there are three options:
(1) In the work order list, find the received work order, and click Process. The process page is displayed, see the following figure.
[图]
Fill in the root cause of the fault. Select Submit to Confirm and Operator. Select the next operator. Click Submit. The work order enters the phase to be confirmed, see the following figure.
[图]
[图]
[图]
(2) In the work order list, find the received work order, and click Process. The process page is displayed, see the following figure.
[图]
[图]
Select Transfer, select the person to be transferred, and click Submit to transfer the work order to another person, see the following figure.
[图]
(3) In the work order list, find the received work order, and click Process. The process page is displayed, see the following figure.
[图]
Select Phased Reply, fill in the phase progress, and click Submit. The ticket stays in the Process phase. See the following figure.
[图]
[图]

### Updating A Work Order

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the work order list page, select the work order to be updated, and click Update, see the following figure.
[图]
Enter the information to be updated, and click Submit to update the work order information, see the following figure.
[图]

### Workflow History

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Ticket > Work Order
Operation Steps
On the ticket list page, select a ticket, and click More > Workflow History to view the workflow history of the ticket, see the following figure.
[图]
[图]

# Spare Parts

This chapter includes the following topics:
- Material Management
- Warehouse Management
- Inventory Management
- Warehousing Management
- Outbound Management
- Material transfer
- Transfer and Return
- Warehouse Check

## Material Management

### New Materials

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
- Enter the material management interface, and click +Add, see the following figure.
[图]
[图]
- Enter the information of the material to be added, and click Submit, see the following figure.
[图]
- The new material is displayed on the material management page, see the following figure.
[图]

### Import Materials

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
- On the material management page, click Import, see the following figure.
[图]
- Select the prepared material information file, and click Upload to import the material information, see the following figure.
[图]

### Export Materials

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
- On the material management page, select the materials to be exported, and click Export, see the following figure.
[图]
- The materials in the system can be exported successfully, see the following figure.
[图]

### Waste Materials

Material scrapping refers to deleting materials on the GUI, but they can be restored in the database and can be used after being restored. Material deletion cannot be restored from the database.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
- On the material management page, select the materials to be discarded, and click Discard, see the following figure.
[图]
- Click Confirm to discard the material, see the following figure.
[图]
- To cancel the discarded material, click Cancel.

### Delete Materials

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
- On the material management page, select the material to be deleted, and click Delete, see the following figure.
[图]
- Click Confirm to delete the material, see the following figure.
[图]

### Modify Materials

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
- On the material management page, select the material to be modified, and click Modify, see the following figure.
[图]
- Modify the corresponding material information, and click Submit, see the following figure.
[图]

### Query Materials

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Material Manage
Operation Steps
- On the material management page, enter Material No or Material Name to query material information, see the following figure.
[图]

## Warehouse Management

### Adding A Warehouse

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
- On the Warehouse Management page, click Add Warehouse, see the following figure.
[图]
- Enter the warehouse information, and click Submit, see the following figure.
[图]
- The new warehouse information is displayed on the warehouse list page, see the following figure.
[图]

### Adding A Warehouse

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
- On the Warehouse Management page, select a warehouse, and click Add Location, see the following figure.
[图]
- Enter the storage location name and number, and click Confirm, see the following figure.
[图]
[图]

### Query Warehouse/Warehouse Location

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
- On the Warehouse Management page, enter the warehouse name to quickly query the warehouse, see the following figure.
[图]
- On the Warehouse Management page, enter the warehousing position name to quickly query the warehousing position, see the following figure.
[图]

### Modify A Warehouse/storage Location

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
- On the Warehouse Management page, select the warehouse to be modified, and click Modify, see the following figure.
[图]
- After modifying the warehouse information, click Submit to modify the warehouse information, see the following figure.
[图]
- On the Warehouse Management page, select the storage location to be modified, and click Modify, see the following figure.
[图]
- After modifying the location information, click Confirm to modify the location information, see the following figure.
[图]

### Delete A Warehouse/storage Location

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
- On the Warehouse Management page, select the warehouse to be deleted, and click Delete, see the following figure.
[图]
- Click Delete again. The repository is deleted successfully, see the following figure.
[图]
- On the warehouse management page, select the storage location to be deleted, and click Delete, see the following figure.
[图]
- Click Delete again. The storage location is deleted successfully, see the following figure.
[图]

### Abandoned Warehouse/Warehouse Location

To discard a warehouse or storage location is to delete the warehouse or storage location on the page, but it can be restored in the database. After restoration, the warehouse or storage location can still be used. If a warehouse/storage location is deleted, it cannot be restored from the database.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Warehouse Manage
Operation Steps
- On the Warehouse Management page, select the warehouse to be discarded, and click Discard, see the following figure.
[图]
- Click Discard again. The warehouse is discarded successfully, see the following figure.
[图]
- On the warehouse management page, select the storage location to be discarded, and click Discard, see the following figure.
[图]
- Click Discard again. The storage location is discarded successfully, see the following figure.
[图]

## Inventory Management

### Set Inventory

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Storage Manage
Operation Steps
- On the Inventory Management page, click Set Storage, see the following figure.
[图]
- Set the maximum and minimum inventory quantity, and click Confirm, see the following figure.
[图]

## Spare Parts Warehousing

The spare parts warehousing flow is as follows. For the specific flow and O&M personnel, refer to Chapter 1.3, see the following figure.
[图]

### New Spare Parts Warehousing

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > In Stock
Operation Steps
On the spare parts warehousing page, click +Add, see the following figure.
[图]
Fill in the information to be warehoused, and click Submit, as shown in the figure below.
[图]
[图]
[图]

### Handle Warehousing Orders

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > In Stock
Operation Steps
On the warehousing list page, select the new warehousing order, and click Verify, see the following figure.
[图]
There are two procedures:
[图]
(1) If there is no problem with the warehousing order, select Agree and click Submit, see the following figure.
[图]
[图]
After entering the next procedure, ask others to confirm it. Click Confirm, see the following figure.
[图]
There are two flows:
[图]
(1) If there is no problem with the warehousing order, select Agree and click Submit. The warehousing process ends and the warehousing order is closed, see the following figure.
[图]
You can see that the warehousing order is closed in the warehousing order list, see the following figure.
[图]
(2) If you have any questions about the warehousing order, select Reject and click Submit to return the warehousing order. The warehousing order needs to be updated again, see the following figure.
[图]
[图]
Click Update, see the following figure.
[图]
Update the warehousing order, and click Submit to return to the original process, see the following figure.
[图]
- If you have any questions about the warehousing order, select Reject and click Submit. The warehousing order needs to be updated. After the update is completed, submit it again. After the submission is completed, return to the original process and verify it again.

### Query Warehousing Orders

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > In Stock
Operation Steps
(1) In the warehousing list, click Condition Query, see the following figure.
[图]
Enter the query conditions and click Query. The corresponding warehousing order is displayed, see the following figure.
[图]
[图]
(2) In the warehousing list, enter the warehousing number to quickly find the warehousing order, see the following figure.
[图]

### Discarded Warehousing Receipt

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > In Stock
Operation Steps
In the warehousing order list, select the warehousing order to be discarded, and click Discard. The warehousing order can be discarded, see the following figure.
[图]

### Terminate The Warehousing Receipt

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > In Stock
Operation Steps
In the list of warehousing documents, select the warehousing document to be terminated, and click Terminate, see the following figure.
[图]
The terminated warehousing document becomes closed, see the following figure.
[图]

## Spare Parts Exiting The Warehouse

The spare parts exit-warehouse flow is as follows. For the specific flow and O&M personnel, refer to Chapter 1.3, see the following figure.
[图]

### Adding An Outbound Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Out Stock
Operation Steps
- On the Ex-Warehousing page, click +Add. The Add Ex-Warehousing page is displayed, see the following figure.
[图]
[图]
- After editing the outbound information, click Submit, see the following figure.
[图]
[图]

### Handle Outbound Tasks

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Out Stock
Operation Steps
- Click Verify. The Verify flow page is displayed, see the following figure.
[图]
[图]
- The Verify O&M personnel determine that there is a problem with the delivery note, and select Rject.
[图]
The outbound order enters the Update process.
[图]
Re-submit the delivery note after the O&M personnel update it.
[图]
[图]
After the Verify O&M personnel review the application, the Verify O&M personnel determine that there is no problem. Select Agree to enter the Confirm process, see the following figure.
[图]
[图]
[图]
- Click Confirm. The Confirm page is displayed, see the following figure.
[图]
[图]
- The Confirm O&M personnel determine that there is a problem with the outbound order, and select Rject. The outbound order enters the Update process and repeats the above process. The Confirm O&M personnel determine that there is no problem, and select Agree. The items are lent successfully, and the stock-out ticket enters the Return process, see the following figure.
[图]
[图]
- Click Return. The Return page is displayed, see the following figure.
[图]
[图]
- Click Submit. The items are returned successfully. The lending ticket flow ends, see the following figure.
[图]

## Material Transfer

The material transfer process is as follows. The specific process and O&M personnel can be configured in Chapter 1.3, see the following figure.
[图]

### Add A Transfer Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Transfer W.H.
Operation Steps
- On the transfer page, click +Add. The Add Edit page is displayed, see the following figure.
[图]
[图]
Note: By default, the next process handler is the warehouse keeper added when the warehouse is created.
- After editing the new information, click Submit, see the following figure.
[图]
[图]

### Process The Transfer Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Transfer W.H.
Operation Steps
- After the transfer task is created, click Verify. The Verify page is displayed, see the following figure.
[图]
[图]
- If the Verify O&M personnel determine that the transfer conditions are not met, they can click Reject to reject the transfer and end the transfer task process. When the Verify O&M personnel determine that the transfer is qualified, click Agree and click Submit. The transfer task enters the next process, see the following figure.
[图]
[图]
- Click Transfer Outbound Operate. The Transfer Outbound Operate page is displayed, see the following figure.
[图]
[图]
- If the Transfer Outbound Operate O&M personnel determine that the transfer conditions are not met, they can click Reject to reject the transfer and return the transfer task to the Verify O&M personnel. When the Transfer Outbound Operate O&M personnel determine that the transfer is qualified, they select Agree and click Submit. The transfer task enters the Transfer Inbound Operate flow, see the following figure.
[图]
[图]
- Click Transfer Inbound Operate. The Transfer Inbound Operate page is displayed, see the following figure.
[图]
[图]
- If the Transfer Inbound Operate O&M personnel determine that the transfer conditions are not met, they can click Reject to reject the transfer and return the transfer task to the Verify O&M personnel. When the Transfer Inbound Operate O&M personnel determine that the transfer is qualified, click Agree and click Submit. The transfer task flow ends, see the following figure.
[图]
[图]

## Transfer and Return

The transfer return flow is as follows. The specific flow and O&M personnel can be configured in Chapter 1.3, see the following figure.
[图]

### Add A Transfer Return Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Return W.H.
Operation Steps
- On the Transfer Return page, click +Add. The Create Transfer Return page is displayed, see the following figure.
[图]
[图]
Note:
Return Material No.It should be consistent with the following figure.
[图]
The Return Material SN must be the same as the following:
[图]
- Click Submit to submit the task, see the following figure.
[图]
[图]

### Handle The Transfer and Return Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Return W.H.
Operation Steps
- Click Verify. The Verify page is displayed, see the following figure.
[图]
[图]
- If the Verify O&M personnel determine that the return conditions are not met, they can click Reject to reject the return and end the return task process. When the Verify O&M personnel determine that the warehouse transfer and return are qualified, they select Agree and click Submit. The warehouse transfer and return task enters the next process, see the following figure.
[图]
[图]
- Click Return Outbound Operate. The Return Outbound Operate page is displayed, see the following figure.
[图]
[图]
- If the Return Outbound Operate O&M personnel determine that the return conditions are not met, they can click Reject to reject the return and return the task to the Verify O&M personnel. When the Return Outbound Operate O&M personnel determine that the warehouse transfer and return are qualified, they select Agree and click Submit. The warehouse transfer and return task enters the Return Inbound Operate process, see the following figure.
[图]
[图]
- Click Return Inbound Operate. The Return Inbound Operate page is displayed, see the following figure.
[图]
[图]
- If the Return Inbound Operate O&M personnel determine that the transfer conditions are not met, they can click Reject to reject the transfer and return the task to the Verify O&M personnel. When the Return Inbound Operate O&M personnel determine that the warehouse transfer and return are qualified, they select Agree and click Submit. The warehouse transfer and return task flow ends, see the following figure.
[图]
[图]

## Warehouse Check

The warehouse check flow is as follows. For details, refer to Section 1.3.
[图]

### Adding A Check Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Check W.H.
Operation Steps
- On the Warehouse Check page, click +Add. The Add Task page is displayed, see the following figure.
[图]
[图]
- Add material information, see the following figure.
[图]
- Click Submit. A new task is created, see the following figure.
[图]
[图]

### Handling A Check Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SP Management > Check W.H.
Operation Steps
- On the Warehouse Check page, click Upload. The Upload page is displayed, see the following figure.
[图]
[图]
- Click Operation to update the material check status, see the following figure.
[图]
[图]
- When the Upload O&M personnel select the Finished status, the check procedure ends. When the Upload O&M personnel select the Not Finished status and click Submit, the task order enters the Confirm O&M personnel confirmation flow, see the following figure.
[图]
[图]
[图]
- Click Confirm. The Confirm flow page is displayed, see the following figure.
[图]
[图]
- When the Confirm O&M personnel determine that the check task is not completed, click Wait ReUpload. The check task is returned to the Upload O&M personnel and the process is restarted. When the Confirm O&M personnel determine that the check task ends, click Close and click Submit. The flow ends, see the following figure.
[图]
[图]

# DashBoard

The data of work orders can be collected and displayed in a dashboard, so that O&M personnel can learn more about work orders.
This chapter includes the following topics:
- WO DashBoard
- FLM WO Dashboard
- BO WO Dashboard

## WO DashBoard

Displays work order data in different dimensions and graphs.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > DashBoard > WO DashBoard
Operation Steps
- Log in to the system and enter the DashBoard interface, see the following figure.
[图]
[图]
- You can select combination conditions from different dimensions and click Query to query data, see the following figure.
[图]
- Click Customer Complaint Dashboard to view the work order data of customer complaints, see the following figure.
[图]

## FLM WO Dashboard

Work order data to be handled by field O&M personnel
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > DashBoard > FLM WO Dashboard
Operation Steps
- Click FLM WO Dashboard to view the work orders to be handled by the O&M personnel, see the following figure.
[图]

## BO WO Dashboard

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > DashBoard > BO WO Dashboard
Operation Steps
Click BO WO Dashboard to view the work orders to be handled by BO O&M personnel, see the following figure.
[图]

# Preventive Maintenance Management

Perform preventive maintenance on devices or resources to ensure stable system operation. Set preventive maintenance items as required. The preventive maintenance flow and O&M personnel can be configured in Chapter 1.3.
This chapter includes the following topics:
- PM Template
- PM Plan
- PM Task
- Punch List

## PM Template

### Creating A Template

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Template
Operation Steps
- On the Inspection Template page, click +Add. The Edit page is displayed, see the following figure.
[图]
[图]
- After editing the template, click Submit. The template is created successfully, see the following figure.
[图]
[图]
Note: For preventive maintenance items, refer to Section 1.4 Configurable.

### Modify A Template

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Template
Operation Steps
- Click Modify. The Modify dialog box is displayed, see the following figure.
[图]
[图]
- Click Submit to submit the modification.

### Discarded Template

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Template
Operation Steps
- Select a template and click Discard. The selected template is discarded, see the following figure.
[图]
[图]
- Click Confirm.

## PM Plan

### Adding A Preventive Maintenance Plan

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Plan
Operation Steps
- On the Inspection Plan page, click +Add. The Edit page is displayed, see the following figure.
[图]
[图]

| Parameter | Definition |
|---|---|
| Plan Begin Date | Planned Start Time |
| Plan End Date | Planned End Time |
| PM Template | Preventive Maintenance Template |
| Site | Site information to be inspected. One site corresponds to one inspection task. |

- After the site is added, click Modify to modify the site information, see the following figure.
[图]
[图]
Note:
Actual Patrol Inspector: Direct handler of the preventive maintenance task, see the following figure.
[图]
- On the Add Edit page, you can import a plan and export a template, see the following figure.
[图]
- Select the O&M personnel to receive the preventive maintenance plan, see the following figure.
[图]
- After editing the information, click Submit. The preventive maintenance plan is created successfully, see the following figure.
[图]
[图]

### Abandoning The Preventive Maintenance Plan

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Plan
Operation Steps
Select a preventive maintenance plan and click Discard. The preventive maintenance plan can be discarded, see the following figure.
[图]
[图]
Note: Discarded tickets are not in the search list.

### Terminate A Preventive Maintenance Plan

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Plan
Operation Steps
- Select a preventive maintenance plan, and click Terminate to terminate the plan, see the following figure.
[图]
[图]

### Exporting A Preventive Maintenance Plan

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Plan
Operation Steps
- Click Export to export the preventive maintenance plan, see the following figure.
[图]

### Process The Preventive Maintenance Plan

When creating a preventive maintenance plan, O&M personnel can specify an inspection plan approver (configured in the 1.3). After the plan is approved by the inspection plan approver, the plan is assigned to the corresponding inspection task according to the inspection site and assigned to the default site handler (the handler can be modified when the inspection site is added in the new plan). The inspection plan can be confirmed by the inspection plan approver only after the inspection task handler of all sites completes the inspection task.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the permission to operate preventive maintenance plans.
Operation Path
Workspace > e-flow > PM Management > PM Plan
Operation Steps
- Click Approve to approve the new preventive maintenance plan, see the following figure.
[图]
[图]
- The O&M personnel can approve or reject the preventive maintenance plan, see the following figure.
- Click Reject. The O&M personnel can reject the preventive maintenance plan, see the following figure.
[图]
Click Submit. The plan is rejected, see the following figure.
[图]
[图]
Note: Rejected tickets are in closed status and can be found in Condition Query.
- Click Agree to agree to the plan, see the following figure.
[图]
The agreed preventive maintenance plan is displayed in the preventive maintenance task list, see the following figure.
[图]
- The O&M personnel can obtain the completion progress of the preventive maintenance tasks corresponding to the preventive maintenance plan from "Completed/Total". When the tasks of all sites are completed, the O&M personnel who approve the preventive maintenance plan can confirm whether the preventive maintenance plan is completed, see the following figure.
The completed "1/1" has a confirmation button, and the uncompleted "0/1" cannot be confirmed.
[图]
- After the preventive maintenance task is completed, click Confirm to confirm that the preventive maintenance plan is completed, see the following figure.
[图]
[图]

## PM Task

### Adding A Preventive Maintenance Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Task
Operation Steps
- On the preventive maintenance task page, click +Add. The Edit page is displayed, see the following figure.
[图]
[图]
- After editing the new information, click Submit to create a preventive maintenance task, see the following figure.
[图]
[图]

### Discarding A Preventive Maintenance Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Task
Operation Steps
- Select a preventive maintenance task and click Discard. The preventive maintenance task is discarded, see the following figure.
[图]
[图]

### Terminate A Preventive Maintenance Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > PM Task
Operation Steps
- Select a preventive maintenance task and click Terminate to terminate the task, see the following figure.
[图]
[图]
- The terminated task is in Closed status, see the following figure.
[图]

### Creating A Preventive Maintenance Report

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
- The preventive maintenance task has been processed.
Operation Path
Workspace > e-flow > PM Management > PM Task
Operation Steps
- Select a preventive maintenance task that has been processed. A preventive maintenance report is generated, see the following figure.
[图]
- Click Inspection Report to download the report to the local PC, see the following figure.
[图]

### Processing Preventive Maintenance Tasks

After receiving the preventive maintenance task, the O&M personnel (accept) determine whether to forward the task to others or continue the next step in accordance with the task content (process). After inspecting each item, the process O&M personnel send it to the PM manager for confirmation. The PM manager rejects to return the data to the process or assigns the data to the FLM Leader O&M personnel. FLM Leader Verify that there is no problem in the preventive maintenance, and select Close. If there is any problem, return to the peocess and go back to the process.
See the following figure.
[图]
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
- Has the permission to receive and process preventive maintenance tasks.
Operation Path
Workspace > e-flow > PM Management > PM Task
Operation Steps
- Click Accept to receive the preventive maintenance task, see the following figure.
[图]
- There are two processing modes for preventive maintenance tasks: Wait Process and Transfer, see the following figure.
[图]
Note:
Wait Process: Enables the task to enter the processing flow.
Transfer: Assign to another handler
- Click Tranfer. The task is transferred to another person, see the following figure.
[图]
- Click Wait Process, see the following figure.
[图]
- Click Submit. The command is executed successfully, see the following figure.
[图]
- Click Process. The task processing page is displayed, see the following figure.
[图]
- Click Operation. The preventive maintenance items are completed, see the following figure.
[图]
[图]
- Click Submit to confirm the inspection items, see the following figure.
[图]
- After the inspection items are completed, select the inspection manager and click Submit to submit the processing result and wait for the inspection manager to confirm, see the following figure.
[图]
[图]
- Click PM Manager Approve. The approval page is displayed, see the following figure.
[图]
[图]
- According to the preventive maintenance result, the PM Manager O&M personnel can select FLM Leader or reject it, see the following figure.
[图]
- The PM Manager O&M personnel reject the flow, and the flow returns process, see the following figure.
[图]
[图]
- The PM Manager O&M personnel are assigned to the FLM Leader, see the following figure.
[图]
- Click Submit to submit the task, see the following figure.
[图]
- Click FLM Leader Aprrove. The approval page is displayed, see the following figure.
[图]
- FLM Leader can be set to reject or closed, see the following figure.
[图]
- Click closed, and select Close Task, see the following figure.
[图]
[图]
- Click Reject, and select Reject. The task is sent to the O&M personnel of the PROCESS by default, see the following figure.
[图]
[图]

## Punch List

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > PM Management > Punch List
Operation Steps
- On the Punch List page, click +Add. The Edit page is displayed, see the following figure.
[图]
[图]
- After editing the information, click Submit. The list is created successfully, see the following figure.
[图]
[图]

# My Task

All tasks assigned to the login account
This chapter includes the following topics:
- My Task

## Task Statistics

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > My Task
Operation Steps
- On the My Tasks page, click Count. The number of tasks is displayed, see the following figure.
[图]
[图]
[图]

## Task Details

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > My Task
Operation Steps
- On the My Task page, click Order Number. The details of the task are displayed, see the following figure.
[图]
[图]

## Processing Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > My Task
Operation Steps
- Click Execute in the Operation column to process the current task, see the following figure.
[图]
Note:
For details, refer to the corresponding chapter of each task.

## Workflow History

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > My Task
Operation Steps
- Click Workflow History in the Operation column to view the historical processing information of the current task, see the following figure.
[图]
[图]

# Change Management

This module provides the change task application and change task tracking functions. For example, an upgrade task needs to be applied for version upgrade, and a resource change task needs to be applied for device faults.
This chapter includes the following topics:
- Change Order

## Adding A Change Order

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Change Management > Change Request
Operation Steps
- On the Change Order page, click +Add. The page for editing the change order is displayed, see the following figure.
[图]
[图]
[图]
- After editing the new information, click Submit. The new information is created successfully, see the following figure.
[图]

## Termination Change Order

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Change Management > Change Request
Operation Steps
- Select a change order and click Terminate to terminate the change order, see the following figure.
[图]
- Click Confirm. The change order is terminated successfully, see the following figure.
[图]
- The terminated ticket is closed, see the following figure.
[图]

## Modify A Change Order

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Change Management > Change Request
Operation Steps
- Select a change order, and select More > Modify. The Modify page is displayed, see the following figure.
[图]
[图]
- After the modification, click Save. The change order is modified successfully, see the following figure.
[图]
[图]

## Abandonment Change Order

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Change Management > Change Request
Operation Steps
- Select a change order, and click Discard, see the following figure.
[图]
- Click Confirm. The change order can be discarded, see the following figure.
[图]

## Handling Change Orders

According to the actual situation, the specific process and operation personnel can be configured in Chapter 1.3, see the following figure.
[图]
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Change Management > Change Request
Operation Steps
- The new change order is approved by the domain maintenance personnel in accordance with the procedure. Click Domain Approve. The approval page is displayed, see the following figure.
[图]
[图]
[图]
- Click Reject. The change order is transferred to the following flow, see the following figure.
[图]
[图]
[图]
- Click Agree, and click Submit. The NOC O&M personnel approval flow goes to the next step, see the following figure.
[图]
[图]
- Click Approve. The approval page is displayed, see the following figure.
[图]
[图]
[图]
- Click Reject to go to the previous step. Click Agree to go to the next step (Start Implementing), see the following figure.
[图]
[图]
- Click Start Implementing. The Implementing page is displayed, see the following figure.
[图]
[图]
- Click Rject to return to the previous step. Click Agree to go to the next step, see the following figure.
[图]
- Click Result Feedback. The result feedback page is displayed, see the following figure.
[图]
- After selecting the execution result, click Submit to enter the Domain Lead Confirm flow, see the following figure.
[图]
[图]
- Click Domain Lead Confirm. The Confirm dialog box is displayed, see the following figure.
[图]
- Click Rject to return to the previous step. Click Agree to go to the next step (CR Manager Confirm), see the following figure.
[图]
[图]
- Click CR Manager Confirm. The CR Manager Confirm page is displayed, see the following figure.
[图]
- Click Rject to return to the previous step. Click Agree. The change order flow ends, see the following figure.
[图]

# Asset Change Order

If resources need to be changed in the TT, WO, preventive maintenance, and asset change processes, you can apply for a resource change form in this module.
This chapter includes the following topics:
- Asset Change Order
- Asset Audit

## Asset Change Order

### New Asset Change Order

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Asset Change Order > Asset Change Order
Operation Steps
- Click +Add. The page for adding an asset change order is displayed, see the following figure.
[图]
[图]
[图]
- After editing the information, click Submit. The asset change order is created successfully, see the following figure.
[图]
[图]

### Exporting An Asset Change Order

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Asset Change Order > Asset Change Order
Operation Steps
- Click Export Detail to export the asset change order, see the following figure.
[图]

### Handling Asset Change Orders

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Asset Change Order > Asset Change Order
Operation Steps
- Click Confirm. The Confirm page is displayed, see the following figure.
[图]
[图]
- Click the Rject button. The change order is returned to the Update button. The Confirm needs to be redistributed. Click the Agree button. The change order enters the Approve flow, see the following figure.
[图]
[图]
[图]
[图]
- Click Approve. The Approve page is displayed, see the following figure.
[图]
[图]
- Click Rject to return to Update and Confirm again. Click Closed. The change order flow ends, see the following figure.
[图]
[图]

## Asset Audit

### Audit of New Assets

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Asset Change Order > Asset Audit
Operation Steps
- Click +Add. The New Asset Audit tab is displayed, see the following figure.
[图]
[图]
- Click Submit to enter the Accept flow, see the following figure.
[图]
[图]

### Handling Asset Audit Forms

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Asset Change Order > Asset Audit
Operation Steps
- Click Accept. The accept flow page is displayed, see the following figure.
[图]
- When the Accept O&M personnel determine that the ticket task is not processed by themselves, they can click Transfer to transfer the task to other O&M personnel. Accept O&M personnel select the Wait Process button to enter the Process flow, see the following figure.
[图]
Note:
The subsequent procedure needs to be performed on the APP side.

# SLA Management

Assign different colors to the corresponding tickets in accordance with the TT and WO sql commands to display the urgency and completion progress of the tickets.
This chapter includes the following topics:
- SLA Management

## Creating An SLA Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SLA Management > SLA Management
Operation Steps
- Click +Add. The page for creating an SLA task is displayed, see the following figure.
[图]
[图]
[图]

| Parameter | Definition |
|---|---|
| Name | Self-defined |
| Type | Eflow→tt or eflow→wo, which must be the same as that in the event flow. |
| SLA Level | Controls the color display of TT or WO single SLA by level. |
| Triggering percentage | Task triggering percentage |
| SLQ Content | TT or WO that needs to be managed by the SLA. |

- Click Submit. The SLA task is created successfully, see the following figure.
[图]
[图]
Note:
This task corresponds to the SLA column of the TT sheet and WO sheet, see the following figure.
[图]

## Modifying An SLA Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SLA Management > SLA Management
Operation Steps
- Click Modify. The Modify page is displayed, see the following figure.
[图]
[图]
- After the modification, click Submit. The modification is successful, see the following figure.
[图]

## Delete An SLA Task

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > SLA Management > SLA Management
Operation Steps
- Click Delete. The task is deleted successfully, see the following figure.
[图]
[图]

# Message

Each step in the procedure is sent to the corresponding O&M personnel through SMS messages.
This chapter includes the following topics:
- SMS sending record
- Message template

## SMS Sending Record

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Message > SMS Send Records
Operation Steps
- The SMS sending record page displays the SMS messages sent in all flows. You can filter and export SMS messages, see the following figure.
[图]
[图]

## Message Template

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Message > Message Template
Operation Steps
- Click +New. The Edit dialog box is displayed, see the following figure.
[图]
[图]

| Parameter | Definition |
|---|---|
| Ticket | Module that the SMS message to be sent belongs to. |
| Operation Steps | Operation Steps of the Module for Sending SMS Messages |

- Click OK. The template is created successfully, see the following figure.
[图]
[图]
- Click Modify to modify the message template, see the following figure.
[图]
[图]
- Click Delete to delete the message template, see the following figure.
[图]
[图]

# GIS

This chapter includes the following topics:
- Gis

## Site View

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > GIS
Operation Steps
- On the gis page, click Site View. The site map is displayed, see the following figure.
[图]
[图]
- On the Site View page, select level-1 and level-2 areas, sites, and organizations, and then click Query. The histogram on the right shows the TT and WO orders of each day in the recent week, see the following figure.
[图]
- Click a site. The site information and the corresponding TT and WO are displayed, see the following figure.
[图]

## Person View

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > GIS
Operation Steps
- On the gis page, click Person View, see the following figure.
[图]
- On the Person View page, select a location type, a person, and a quick query to query the person tracks within the range, see the following figure.
[图]
- Select WO to view the WO tickets to be processed and different alarm statistics, see the following figure.
[图]
- Select PM to view the PM tickets to be processed.
[图]

## Tickets View

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > GIS
Operation Steps
- On the gis page, click Tickets View, see the following figure.
[图]
- On the Tickets View page, select a level-1 area, a level-2 area, and a site disconnection area, see the following figure.
[图]
- Click a site. The site information and the corresponding TT are displayed, see the following figure.
[图]
- Click TT to view the details, see the following figure.
[图]
[图]

# App Management

This chapter includes the following topics:
- Release Record
- App Download

## Release Record

The APP version can be released on this module.
Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > App Management > Release Record
Operation Steps
- Click +Add. The version release editing page is displayed, see the following figure.
[图]
[图]
[图]
- After editing the information, click Submit. The version is released successfully.

## App Download

Prerequisite
- The system is deployed successfully.
- You can log in to the system properly.
- The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > App Management > APP Download
Operation Steps
- After the version is released, the APP can be downloaded on this page, see the following figure.
[图]

# Leave Ticket Management

This chapter includes the following topics:
- Create a leave ticket
- Cancel the leave application
- Refresh the leave list
- Export leave application form
- Query leave tickets
- Handle leave application forms
- Workflow History

## Add A Leave Ticket

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
- Click +Add. The page for editing the leave ticket is displayed, see the following figure.
[图]
[图]
[图]
- After editing the information, click Submit. The leave ticket is created successfully, see the following figure.
[图]
[图]

## Cancel The Leave Application

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
- Click More-> Revoke to cancel the leave ticket, see the following figure.
[图]

## Refresh The Leave List

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
1. Click Refresh to manually refresh the trouble ticket page, see the following figure.
[图]

## Export Leave Application Form

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
Click Export > Export Setting, and select the names of the exported excel tables and the columns of the fields to be displayed. By default, the excel tables are exported offline, see the following figure.
[图]
- On the Export Settings page, click Confirm. The my Export page is displayed, where you can view the export progress and download documents.
[图]
[图]
[图]
- View the exported document
[图]
[图]

## Query Leave Tickets

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
- Click Advanced Query to configure the query conditions, see the following figure.
[图]
2. After configuring the query conditions, click Query. The corresponding leave ticket is displayed, see the following figure.
[图]

## Handle Leave Application Forms

If a leave applicant submits a leave application, the leave application shall be reviewed at different levels in accordance with the leave type. If the leave application type is Long-Term Leave or Resign, the leave application shall be reviewed at level 2. If the leave application type is Short-Term Leave, the leave application shall be reviewed at level 1 only. If the leave application is approved and the leave application time expires, the leave applicant's status shall be updated to Leave.
Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
- Click Approve. The page for reviewing the leave application is displayed, see the following figure.
[图]
[图]
- The following figure shows the multi-processing mode of leave tickets in step Approve.
[图]
- Select Reject, enter the rejection reason, and submit it. The ticket enters the step to be modified. You can modify the submitted application data.
[图]
- Select Agree. The ticket is automatically closed after being approved.

## Workflow History

Prerequisite
1. The system is deployed successfully.
2. You can log in to the system properly.
3. The user has the eFlow service operation permission.
Operation Path
Workspace > e-flow > Leave order
Operation steps:
On the ticket list page, select a leave ticket, and click More > Workflow History to view the workflow history of the leave ticket, see the following figure.
[图]
[图]
