@echo off
REM Sync data/mw_data/MW LINKS.kml -> frontend/public + live dist (_fe_dist)
REM Usage: double-click, or pass a custom KML: mw_links_sync.bat "path\to\xxx.kml"
setlocal

set PY=C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe
set ROOT=D:\01_RPA\Task\my_app
set KML=%ROOT%\data\mw_data\MW LINKS.kml
if not "%~1"=="" set KML=%~1

set OUT=%ROOT%\frontend\public\mw_ume_orange_links.geojson
set DIST=D:\01_RPA\Task\_fe_dist\mw_ume_orange_links.geojson

echo [1/3] Convert KML -^> GeoJSON
"%PY%" "%ROOT%\backend\services\mw_ume\kml_to_geojson.py" --kml "%KML%" --out "%OUT%"
if errorlevel 1 (echo FAILED: conversion error & goto :end)

echo [2/3] Deploy to live dist (_fe_dist)
copy /Y "%OUT%" "%DIST%" >nul
if errorlevel 1 (echo FAILED: copy error & goto :end)

echo [3/3] Verify over HTTP (7090 direct + 80 via nginx)
"%PY%" "%ROOT%\TMP\verify_mw_links.py"

:end
endlocal
pause
