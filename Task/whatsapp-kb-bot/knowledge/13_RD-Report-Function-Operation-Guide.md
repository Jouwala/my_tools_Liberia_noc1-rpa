iMind

RD Report Function Operation Guide

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

1 Report Template Upload Guide............................................................................ 1
2 Report Instance Creation Guide........................................................................... 4

Report Template Upload
Guide

Steps Overview

 Find template package from scenario package
 Login to system
 Enter Report Management
 Enter Template Management
 Upload template

Extract Report Template from Scenario Package

Find the scenario and extract it
Find UFMRD_Vxx.xx.xx.xx.zip under the rd path, which is the report template

Enter Template Management
Login to system ----> Report Management ----> Template Management
Login to System
**RD Report Function Operation Guide**

Browser access: https://IP:28001/uportal/framework/default.html
Enter username and password ----> Login to system
Report Management
Click to enter Report Management

Template Management

Upload Template Package

Click +Template Package ----> +Upload Template Package ----> Select template package
Find UFMRD_Vxx.xx.xx.xx.zip under the rd path, which is the template package
1 Report Template Upload Guide

Report Instance Creation
Guide

Report Creation Steps Overview

Steps overview, see corresponding sections for details
 Access TCF to view database port
 Create probe instance
 Log in to Uportal to create UFM-PG data source
 Create report instance

View Database Port

Login URL: https://IP/ngportal/login
Steps:
1. Login
2. Click: Public Service Management
3. Click: PostgreSQL
4. Click: Running Entity
5. Record: Record the database port (used when creating data source)

Click: Public Service Management
2 Report Instance Creation Guide

Click: PostgreSQL

Click: Running Entity
**RD Report Function Operation Guide**

Record: Record the database port (used when creating data source)
The port obtained here is 4508, use the actual obtained value

Create Probe Instance
1. Login: https://IP:28001/uportal/framework/default.html#/home Enter username and

password
2. Click to enter Access Management Service
3. Click New
Access Management Service

**Create New Probe**
2 Report Instance Creation Guide

Fill in the probe parameters

Create the probe according to the parameter table and click "Confirm"
Probe Parameter Table

一、Basic Information

Key                                       Value
*Access System Type                       ZTE-UFM

*Agent Name                               ufm-report

*Business Type                            REPORT

二、Public Information                      Value
ZTE-UFM-REPORT-ZTE-ZTE-UFM-UFM-01.01.447
Key
*Access Package Type

三、Advanced Configuration

Key                             Value                 unit
Delay Time(Min)                 0                     min
hour
Alarm Period(Hour)              72                    min

Active Condition Alarm Interval( 5                    min
Min)
daily
History Condition Alarm Interval( 30
Min)                                                  daily
daily
Historical condition alarm collection 20
days (days)

Number of days to retain files  4

Historical alarm collection days ( 2
days)
**RD Report Function Operation Guide**

Key                              Value                        unit
-
Professional network conditions for RAN;CS;PS;PERFORMANCE;TR
hour
historical alarms                M_DWDM;TRM_IP                -

History alarm exec time(hour)    12

Alarm Condition                  Jump Alarm Condition

Alarm Condition

zte.ran.nodeb#9990;zte.ran.enodeb#9970;zte.ran.bts#9980;zte.ran.nodeb#9991;zte.ran.enodeb#9971;zte.ran.

Start the probe

Log in to Uportal to create the data source for UFM-PG

1. Login: https://IP:28001/uportal/framework/default.html#/home Enter username and
password

2. Click to enter the report management section.
3. Click to enter the data source management section
4. Create a new data source
Note: If a data source named "ufm-pg" has already been created, there is no need to create it
again.
Fill in the parameters as follows:
2 Report Instance Creation Guide

Field                         explain                              example
Data Source Name *            Data source naming                   ufm-pg
Data Source Type *            Type, usually set as default         greenplum
Data Source Address *         The IP of the database, please fill  10.89.245.245
in the floating IP (the IP of MSB)
Data Source Port *            here.                                4508
Database Username             The PG port viewed through TCF       postgres
Database Password             Defaultly, PostgreSQL is used.       XXXXXX
Database Name                 Database password                    db_imind_ufm_pg_zenap
UFM-PG use db_imind_ufm_pg_
zenap

Create a report instance

1. Enter the report management section
2. Click to create a report
3. Basic Information (Enter the name of the report form)
4. Report generation method (select the generation method)
5. Template file (select the template file corresponding to the report)
6. Template parameters (default)
7. Data source (select the ufm-pg data source)
The general report consists of 6 chapters. For the purpose of demonstration, we will use "fm-
daily-daily_outage_report". All 6 reports need to be created. The list of reports is as follows:

Template name                 Description                          Generated Time
fm-daily-daily_outage_report
From the current alerts and the      daily
historical alerts from yesterday (
including 2G/3G/4G Site Down and
Cell Down alerts)
**RD Report Function Operation Guide**

Template name                   Description                           Generated Time
fm-daily_3day_worst_recur_site
fm-daily-ip_clock_link_failure  Report on frequently failed sites in  daily
fm-daily-network_outrage_trend  historical alarms over the past 3
fm-hourly-network-status        days

fm-hourly_active_site_down      The statistics of specific alarm IPs  daily
(Clock Link Failure Alarms) with a
Click to create a report         continuous duration exceeding 48
hours in the current alerts.

Based on historical and current       daily
alarm data, the daily outage
situation and the recent 15-day
trend are calculated.

Based on the statistics of the        hour
outage status of the first-level
operation area sites and the main
power failure/battery situation at
the exact hour

Statistically record the downtime     hour
duration of 2G and 3G sites at 2G
every hour.

Basic Information (Enter the report name)

Use "fm-daily-daily_outage_report" for the demonstration. After filling in the details, click "
Next"
2 Report Instance Creation Guide

Report generation method (select generation method)

Select "Scheduled Generation". Choose according to the corresponding generation time
column in the table. Once selected, proceed to the next step.

Template file (select the template file corresponding to the report)

For the demonstration, use "fm-daily-daily_outage_report", then select the corresponding
template and proceed to the next step.
**RD Report Function Operation Guide**

Template parameters (default)
Keep default and proceed to the next step

Data source (select the ufm-pg data source)
Data source type is selected as database, database is selected as ufm-pg, then click "Finish".
The fm-daily-daily_outage_report is created successfully. For other reports, follow the same
steps.
