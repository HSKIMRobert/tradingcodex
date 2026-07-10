@echo off
setlocal
set "TRADINGCODEX_ROOT=%~dp0"
set "TRADINGCODEX_WORKSPACE_ROOT=%TRADINGCODEX_ROOT%"
set "TRADINGCODEX_PACKAGE_SPEC={{TRADINGCODEX_MCP_PACKAGE_SPEC_CMD_SET}}"
if defined TRADINGCODEX_HOME goto projected_home_present
set "TRADINGCODEX_HOME={{TRADINGCODEX_HOME_CMD_SET}}"
set "TRADINGCODEX_HOME_SOURCE={{TRADINGCODEX_HOME_SOURCE_CMD_SET}}"
goto projected_home_done

:projected_home_present
if not defined TRADINGCODEX_HOME_SOURCE set "TRADINGCODEX_HOME_SOURCE=environment_override"

:projected_home_done
if not defined TRADINGCODEX_SERVICE_ADDR set "TRADINGCODEX_SERVICE_ADDR={{TRADINGCODEX_SERVICE_ADDR_CMD_SET}}"
{{TRADINGCODEX_DB_ENV_CMD}}
cd /d "%TRADINGCODEX_ROOT%"

if defined TRADINGCODEX_PYTHON goto custom_python
where py >nul 2>nul
if errorlevel 1 goto check_python
py -3 -c "import sys; raise SystemExit(sys.version_info.major != 3 or sys.version_info.minor not in range(11, 15))" >nul 2>nul
if not errorlevel 1 goto py_launcher

:check_python
where python >nul 2>nul
if errorlevel 1 goto check_uvx
python -c "import sys; raise SystemExit(sys.version_info.major != 3 or sys.version_info.minor not in range(11, 15))" >nul 2>nul
if not errorlevel 1 goto python_launcher

:check_uvx
where uvx >nul 2>nul
if not errorlevel 1 goto uvx_launcher
echo tcx: no compatible Python or uvx executable was found. 1>&2
exit /b 127

:custom_python
"%TRADINGCODEX_PYTHON%" -c "import sys; raise SystemExit(sys.version_info.major != 3 or sys.version_info.minor not in range(11, 15))" >nul 2>nul
if errorlevel 1 (
  echo tcx: TRADINGCODEX_PYTHON must be a working Python 3.11 through 3.14 interpreter. 1>&2
  exit /b 1
)
"%TRADINGCODEX_PYTHON%" "%TRADINGCODEX_ROOT%.tradingcodex\cli.py" %*
exit /b %errorlevel%

:py_launcher
py -3 "%TRADINGCODEX_ROOT%.tradingcodex\cli.py" %*
exit /b %errorlevel%

:python_launcher
python "%TRADINGCODEX_ROOT%.tradingcodex\cli.py" %*
exit /b %errorlevel%

:uvx_launcher
uvx --from "%TRADINGCODEX_PACKAGE_SPEC%" python "%TRADINGCODEX_ROOT%.tradingcodex\cli.py" %*
exit /b %errorlevel%
