@echo off
setlocal
pushd "%~dp0" || exit /b 1
call "%~dp0scripts\windows_env.bat"
if errorlevel 1 goto failed

"%MILKCHAN_PYTHON%" scripts\project.py --sentient-root "%SENTIENTMILK_ROOT%" build
if errorlevel 1 goto failed
if not exist "dist\MilkChan.exe" goto failed
echo [MilkChan] Built: %CD%\dist\MilkChan.exe
popd
exit /b 0

:failed
echo [MilkChan] Build failed. See the error above. 1>&2
popd
exit /b 1
