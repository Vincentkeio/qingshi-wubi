@echo off
setlocal
rem 清除小写代理变量，避免 MSBuild 的 StringDictionary 大小写冲突
set "https_proxy="
set "http_proxy="
set "all_proxy="
set "no_proxy="
set "VSB=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
set "MSVC=%VSB%\VC\Tools\MSVC\14.44.35207"
set "SDK=C:\Program Files (x86)\Windows Kits\10"
set "SDKVER=10.0.26100.0"

set "PATH=%MSVC%\bin\Hostx64\x64;%VSB%\MSBuild\Current\Bin;%PATH%"
set "INCLUDE=%MSVC%\include;%SDK%\Include\%SDKVER%\ucrt;%SDK%\Include\%SDKVER%\um;%SDK%\Include\%SDKVER%\shared;%SDK%\Include\%SDKVER%\winrt;%SDK%\Include\%SDKVER%\cppwinrt"
set "LIB=%MSVC%\lib\x64;%SDK%\Lib\%SDKVER%\ucrt\x64;%SDK%\Lib\%SDKVER%\um\x64"

cd /d "%~dp0"

set "BOOST_ROOT=%~dp0deps\boost_1_84_0"
set "PLATFORM_TOOLSET=v143"
set VERSION_MAJOR=0
set VERSION_MINOR=17
set VERSION_PATCH=4
set WEASEL_BUILD=0
set PRODUCT_VERSION=0.17.4.0
set FILE_VERSION=0.17.4.0

echo [1] deps check
if not exist "%BOOST_ROOT%\boost\thread.hpp" goto fail_dep
if not exist "%BOOST_ROOT%\stage\lib\libboost_thread-vc143-mt-s-x64-1_84.lib" goto fail_dep
if not exist include\rime_api.h goto fail_dep
if not exist lib64\rime.lib goto fail_dep
echo     OK

copy /Y lib64\rime.lib lib\rime.lib >nul 2>&1
if not exist output mkdir output
if not exist output\data mkdir output\data

echo [2] render props
cscript //nologo render.js weasel.props BOOST_ROOT PLATFORM_TOOLSET VERSION_MAJOR VERSION_MINOR VERSION_PATCH PRODUCT_VERSION FILE_VERSION >nul
if errorlevel 1 goto fail_render
echo     OK

echo [3] msbuild x64 Release
msbuild weasel.sln /p:Configuration=Release /p:Platform=x64 /p:WindowsTargetPlatformVersion=%SDKVER% /m /v:minimal /nologo
if errorlevel 1 goto fail_build

echo.
echo === BUILD OK ===
dir /b output\*.exe output\*.dll 2>nul
exit /b 0

:fail_dep
echo [FAIL] dependency missing
exit /b 1
:fail_render
echo [FAIL] render.js
exit /b 2
:fail_build
echo [FAIL] msbuild
exit /b 3
