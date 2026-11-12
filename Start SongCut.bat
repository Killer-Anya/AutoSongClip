@echo off
setlocal
pushd "%~dp0" || goto folder_error

set "songcut_python=py -3"
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto launch

set "songcut_python=python"
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto launch

echo SongCut needs Python 3.10 or later. Install Python from https://www.python.org/downloads/, then reopen this file.
popd
pause
exit /b 1

:launch
%songcut_python% site\server.py --open
set "songcut_exit=%errorlevel%"
popd
if not "%songcut_exit%"=="0" pause
exit /b %songcut_exit%

:folder_error
echo SongCut could not open the extracted project folder. Extract the entire archive and try again.
pause
exit /b 1
