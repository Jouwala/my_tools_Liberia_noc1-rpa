@echo off
cd /d d:\01_RPA\Task\my_app\backend\services\cn_ems

set JAVA=D:\ems1\ems1\jdk\jdk\windows\bin\java.exe
set JDK_EXT=D:\ems1\ems1\jdk\jdk\windows\jre\lib\ext
set BOOT_CP=D:\ems1\ems1\jdk\jdk-ext\windows\uep-prert.jar
set CP=.;_kpi_launcher.jar;D:\ems1\ems1\ums-client\procs\bsf\core\bin\ums-run.jar

%JAVA% -Xbootclasspath/p:%BOOT_CP% -Djava.ext.dirs=%JDK_EXT% -Dusf.platform.name=windows -DfamilyType="D:\ems1\ems1\" -DprocType=full -Dumd=true -cp "%CP%" EmsMmlTest2 %1 %2 %3 %4
