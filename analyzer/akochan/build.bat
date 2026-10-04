@echo off
rem Build akochan and qmax_akochan on Windows (runs build.ps1 with MSYS2).
rem Usage: double-click, or "build.bat -Msys2 D:\msys64" if MSYS2 is not in C:\msys64.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
pause
