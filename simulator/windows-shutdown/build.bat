@echo off
rem Builds pressure_leak.exe and mem_guard.exe (windowless, x64) with the C# compiler bundled in .NET Framework 4.x.
setlocal
cd /d "%~dp0"

set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo [ERROR] 64-bit .NET Framework 4.x C# compiler not found.
    exit /b 1
)

"%CSC%" /nologo /optimize+ /target:winexe /platform:x64 /out:pressure_leak.exe PressureLeak.cs
if errorlevel 1 (
    echo [ERROR] pressure_leak build failed
    exit /b 1
)
"%CSC%" /nologo /optimize+ /target:winexe /platform:x64 /out:mem_guard.exe MemGuard.cs
if errorlevel 1 (
    echo [ERROR] mem_guard build failed
    exit /b 1
)
echo Built %~dp0pressure_leak.exe and %~dp0mem_guard.exe
endlocal
