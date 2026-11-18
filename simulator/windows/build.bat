@echo off
rem Builds cpu_hog.exe with the C# compiler bundled in .NET Framework 4.x (present on Windows 7+ / Server 2008 R2+).
setlocal
cd /d "%~dp0"

set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo [ERROR] .NET Framework 4.x C# compiler not found.
    exit /b 1
)

"%CSC%" /nologo /optimize+ /target:exe /platform:anycpu /out:cpu_hog.exe CpuHog.cs
if errorlevel 1 (
    echo [ERROR] build failed
    exit /b 1
)
echo Built %~dp0cpu_hog.exe
endlocal
