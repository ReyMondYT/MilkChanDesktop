@echo off
setlocal
pushd "%~dp0" || exit /b 1
call "%~dp0scripts\windows_env.bat"
if errorlevel 1 goto failed

set "PYTHONPATH=%SENTIENTMILK_ROOT%;%PYTHONPATH%"
"%MILKCHAN_PYTHON%" -m milkchan.main %*
set "MILKCHAN_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %MILKCHAN_EXIT_CODE%

:failed
echo [MilkChan] Development setup failed. See the error above. 1>&2
popd
exit /b 1
