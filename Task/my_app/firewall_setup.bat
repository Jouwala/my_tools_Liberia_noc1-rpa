@echo off
chcp 65001 >nul 2>&1
title Firewall Setup - Data Insight MVP

:: 检查管理员权限
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This script requires Administrator privileges.
    echo Please right-click and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

echo ============================================
echo   Firewall Setup for Data Insight MVP
echo ============================================
echo.
echo Adding inbound rules for ports 7090 and 7038...
echo.

:: 删除旧规则（如果存在）
netsh advfirewall firewall delete rule name="Data Insight Frontend (7090)" >nul 2>&1
netsh advfirewall firewall delete rule name="Data Insight Backend (7038)" >nul 2>&1
netsh advfirewall firewall delete rule name="Data Insight PostgreSQL (5432)" >nul 2>&1

:: 添加前端端口规则
echo [*] Adding rule for Frontend (port 7090)...
netsh advfirewall firewall add rule name="Data Insight Frontend (7090)" dir=in action=allow protocol=TCP localport=7090
if errorlevel 1 (
    echo [ERROR] Failed to add rule for port 7090
) else (
    echo [OK] Frontend port 7090 opened
)

:: 添加后端端口规则
echo [*] Adding rule for Backend (port 7038)...
netsh advfirewall firewall add rule name="Data Insight Backend (7038)" dir=in action=allow protocol=TCP localport=7038
if errorlevel 1 (
    echo [ERROR] Failed to add rule for port 7038
) else (
    echo [OK] Backend port 7038 opened
)

:: 添加 PostgreSQL 数据库端口规则
echo [*] Adding rule for PostgreSQL (port 5432)...
netsh advfirewall firewall add rule name="Data Insight PostgreSQL (5432)" dir=in action=allow protocol=TCP localport=5432
if errorlevel 1 (
    echo [ERROR] Failed to add rule for port 5432
) else (
    echo [OK] PostgreSQL port 5432 opened
)

echo.
echo ============================================
echo   Firewall rules added successfully!
echo ============================================
echo.
echo Other computers on the LAN can now access:
echo   - Frontend: port 7090
echo   - Backend:  port 7038
echo   - PostgreSQL: port 5432
echo.
echo Press any key to exit...
pause >nul
