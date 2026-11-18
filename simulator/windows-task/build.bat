@echo off
rem Builds mem_leak.exe (windowless) with the C# compiler bundled in .NET Framework 4.x.
setlocal
cd /d "%~dp0"

set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo [ERROR] .NET Framework 4.x C# compiler not found.
    exit /b 1
)

"%CSC%" /nologo /optimize+ /target:winexe /platform:anycpu /out:mem_leak.exe MemLeak.cs
if errorlevel 1 (
    echo [ERROR] build failed
    exit /b 1
)
echo Built %~dp0mem_leak.exe
endlocal
