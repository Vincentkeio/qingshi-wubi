@echo off
setlocal
rem Build the IMM32 compatibility test component: output\qingshi_game.ime
rem Reuses WeaselIPC.lib (IPC to WeaselServer) and WeaselTSF\KeyEvent.cpp (key mapping).
set "https_proxy="
set "http_proxy="
set "all_proxy="
set "no_proxy="
set "VSB=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
set "MSVC=%VSB%\VC\Tools\MSVC\14.44.35207"
set "SDK=C:\Program Files (x86)\Windows Kits\10"
set "SDKVER=10.0.26100.0"

set "PATH=%MSVC%\bin\Hostx64\x64;%PATH%"
set "INCLUDE=%MSVC%\include;%MSVC%\atlmfc\include;%SDK%\Include\%SDKVER%\ucrt;%SDK%\Include\%SDKVER%\um;%SDK%\Include\%SDKVER%\shared;%SDK%\Include\%SDKVER%\winrt;%SDK%\Include\%SDKVER%\cppwinrt"
set "LIB=%MSVC%\lib\x64;%MSVC%\atlmfc\lib\x64;%SDK%\Lib\%SDKVER%\ucrt\x64;%SDK%\Lib\%SDKVER%\um\x64"

cd /d "%~dp0"

set "BOOST_ROOT=%~dp0deps\boost_1_84_0"
set "IPC=%~dp0msbuild\Release\x64"

if not exist "msbuild\Release\x64\WeaselIME" mkdir "msbuild\Release\x64\WeaselIME"
if not exist output mkdir output

echo [1] compile
cl /nologo /c /EHsc /O2 /MT /GL /utf-8 /std:c++17 /DUNICODE /D_UNICODE /DWIN32_LEAN_AND_MEAN /D_CRT_SECURE_NO_WARNINGS ^
   /I "%~dp0include" /I "%~dp0WeaselTSF" /I "%BOOST_ROOT%" ^
   /Fo"msbuild\Release\x64\WeaselIME\\" ^
   WeaselIME\WeaselIME.cpp WeaselTSF\KeyEvent.cpp
if errorlevel 1 goto fail

echo [2] link
"%SDK%\bin\%SDKVER%\x64\rc.exe" /nologo /fo"msbuild\Release\x64\WeaselIME\WeaselIME.res" WeaselIME\WeaselIME.rc
if errorlevel 1 goto fail
link /nologo /DLL /LTCG /OUT:output\qingshi_game.ime /DEF:WeaselIME\WeaselIME.def ^
   "msbuild\Release\x64\WeaselIME\WeaselIME.obj" "msbuild\Release\x64\WeaselIME\KeyEvent.obj" ^
   "msbuild\Release\x64\WeaselIME\WeaselIME.res" ^
   "%IPC%\WeaselIPC.lib" ^
   imm32.lib user32.lib advapi32.lib shell32.lib ole32.lib oleaut32.lib uuid.lib ^
   /LIBPATH:"%BOOST_ROOT%\stage\lib"
if errorlevel 1 goto fail

echo.
echo === IME BUILD OK ===
dir /b output\qingshi_game.ime
if /I not "%~1"=="test" exit /b 0
cl /nologo /EHsc /O2 /MT /utf-8 /std:c++17 /DUNICODE /D_UNICODE ^
   /Fo"msbuild\Release\x64\WeaselIME\imm_result_test.obj" ^
   /Fe"msbuild\Release\x64\WeaselIME\imm_result_test.exe" ^
   ..\tests\imm_result_test.cpp imm32.lib user32.lib
if errorlevel 1 goto fail
msbuild\Release\x64\WeaselIME\imm_result_test.exe "%~dp0output\qingshi_game.ime"
if not "%errorlevel%"=="0" goto fail
exit /b 0

:fail
echo [FAIL]
exit /b 1
