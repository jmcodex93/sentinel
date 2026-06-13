@echo off
setlocal EnableDelayedExpansion EnableExtensions

REM Sentinel Professional Installer v1.5.7
REM This installer must be run as Administrator

REM Keep window open after execution
if "%1" neq "nopause" (
    cmd /k "%~f0" nopause
    exit
)

REM =========================================================
REM INITIALIZATION
REM =========================================================

set "VERSION=1.5.7"
set "INSTALL_DIR=%~dp0"
set "LOG_FILE=%TEMP%\sentinel_install.log"
set "PLUGIN_DIR=%INSTALL_DIR%plugin"
set "C4D_DIR=%INSTALL_DIR%c4d"
set "ICONS_DIR=%PLUGIN_DIR%\icons"
set "DEST_DIR=C:\Program Files\Maxon Cinema 4D 2024\plugins\Sentinel"

REM Clear log file
echo Sentinel Installation Log > "%LOG_FILE%"
echo Started: %date% %time% >> "%LOG_FILE%"
echo ========================================== >> "%LOG_FILE%"

REM =========================================================
REM DISPLAY HEADER
REM =========================================================

cls
echo =========================================================
echo     Sentinel v%VERSION% - Professional Installation
echo     Cinema 4D 2024 Quality Control Plugin
echo =========================================================
echo.
echo     Features:
echo     - 12 real-time quality checks, tabbed UI (QC / Render / Versions / Tools), Smart Save Versions, Multi-Format Render Setup + Safe-Area overlay, Texture Repathing, RS AOV management, Scene Collector
echo.
echo =========================================================
echo.
echo IMPORTANT: This installer requires Administrator privileges
echo.

REM =========================================================
REM CHECK ADMIN PRIVILEGES
REM =========================================================

echo Checking administrator privileges...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Administrator privileges required!
    echo.
    echo Please right-click this file and select "Run as Administrator"
    echo.
    goto :error_exit
)
echo [OK] Running with administrator privileges

REM =========================================================
REM CHECK CINEMA 4D INSTALLATION
REM =========================================================

echo Checking Cinema 4D installation...
if not exist "C:\Program Files\Maxon Cinema 4D 2024\" (
    echo.
    echo ERROR: Cinema 4D 2024 not found at default location!
    echo Expected: C:\Program Files\Maxon Cinema 4D 2024\
    echo.
    echo If Cinema 4D is installed elsewhere, please edit this script.
    echo.
    goto :error_exit
)
echo [OK] Cinema 4D 2024 found

REM =========================================================
REM VERIFY SOURCE FILES
REM =========================================================

echo Verifying source files...
set "MISSING_FILES=0"

if not exist "%PLUGIN_DIR%\sentinel_panel.pyp" (
    echo [ERROR] Missing: sentinel_panel.pyp
    set "MISSING_FILES=1"
)

if not exist "%PLUGIN_DIR%\exr_converter_external.py" (
    echo [ERROR] Missing: exr_converter_external.py
    set "MISSING_FILES=1"
)

if not exist "%PLUGIN_DIR%\res" (
    echo [ERROR] Missing: res folder
    set "MISSING_FILES=1"
)

if not exist "%PLUGIN_DIR%\abc_retime" (
    echo [ERROR] Missing: abc_retime folder
    set "MISSING_FILES=1"
)

if "%MISSING_FILES%"=="1" (
    echo.
    echo ERROR: Required source files are missing!
    echo Please ensure you're running from the correct directory.
    echo.
    goto :error_exit
)
echo [OK] All source files present

REM =========================================================
REM CREATE PLUGIN DIRECTORY
REM =========================================================

echo.
echo Step 1: Creating plugin directory...
echo ----------------------------------------
if not exist "%DEST_DIR%" (
    mkdir "%DEST_DIR%" 2>nul
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create plugin directory
        goto :error_exit
    )
    echo [OK] Created: %DEST_DIR%
) else (
    echo [OK] Directory exists: %DEST_DIR%
)

REM =========================================================
REM INSTALL CORE PLUGIN FILES
REM =========================================================

echo.
echo Step 2: Installing core plugin files...
echo ----------------------------------------

copy /Y "%PLUGIN_DIR%\sentinel_panel.pyp" "%DEST_DIR%\" >nul 2>&1
if !errorlevel! equ 0 (echo [OK] Main plugin file) else (echo [FAILED] Main plugin file & goto :error_exit)

copy /Y "%PLUGIN_DIR%\exr_converter_external.py" "%DEST_DIR%\" >nul 2>&1
if !errorlevel! equ 0 (echo [OK] External converter) else (echo [FAILED] External converter)

xcopy /E /I /Y "%PLUGIN_DIR%\res" "%DEST_DIR%\res" >nul 2>&1
if !errorlevel! equ 0 (echo [OK] C4D resource descriptions) else (echo [FAILED] C4D resource descriptions & goto :error_exit)

xcopy /E /I /Y "%PLUGIN_DIR%\abc_retime" "%DEST_DIR%\abc_retime" >nul 2>&1
if !errorlevel! equ 0 (echo [OK] ABC Retime plugin bundle) else (echo [FAILED] ABC Retime plugin bundle & goto :error_exit)

REM Delete any old corrupted Python cache
if exist "%DEST_DIR%\.python_path_cache" (
    del "%DEST_DIR%\.python_path_cache" >nul 2>&1
    echo [OK] Cleared old Python cache
)

REM =========================================================
REM INSTALL C4D ASSETS
REM =========================================================

echo.
echo Step 3: Installing C4D assets...
echo ----------------------------------------

if not exist "%DEST_DIR%\c4d" mkdir "%DEST_DIR%\c4d" 2>nul

if exist "%C4D_DIR%\VibrateNull.c4d" (
    copy /Y "%C4D_DIR%\VibrateNull.c4d" "%DEST_DIR%\c4d\" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] VibrateNull.c4d asset
    ) else (
        echo [WARNING] Could not copy VibrateNull.c4d
    )
) else (
    echo [WARNING] VibrateNull.c4d not found (optional)
)

if exist "%C4D_DIR%\cam_simple.c4d" (
    copy /Y "%C4D_DIR%\cam_simple.c4d" "%DEST_DIR%\c4d\" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] cam_simple.c4d camera setup
    ) else (
        echo [WARNING] Could not copy cam_simple.c4d
    )
) else (
    echo [WARNING] cam_simple.c4d not found (optional)
)

if exist "%C4D_DIR%\cam_w_shakel.c4d" (
    copy /Y "%C4D_DIR%\cam_w_shakel.c4d" "%DEST_DIR%\c4d\" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] cam_w_shakel.c4d camera setup
    ) else (
        echo [WARNING] Could not copy cam_w_shakel.c4d
    )
) else (
    echo [WARNING] cam_w_shakel.c4d not found (optional)
)

if exist "%C4D_DIR%\cam_path.c4d" (
    copy /Y "%C4D_DIR%\cam_path.c4d" "%DEST_DIR%\c4d\" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] cam_path.c4d camera setup
    ) else (
        echo [WARNING] Could not copy cam_path.c4d
    )
) else (
    echo [WARNING] cam_path.c4d not found (optional)
)

if exist "%C4D_DIR%\nulls.c4d" (
    copy /Y "%C4D_DIR%\nulls.c4d" "%DEST_DIR%\c4d\" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] nulls.c4d hierarchy template
    ) else (
        echo [WARNING] Could not copy nulls.c4d
    )
) else (
    echo [WARNING] nulls.c4d not found (optional)
)

if exist "%C4D_DIR%\new.c4d" (
    copy /Y "%C4D_DIR%\new.c4d" "%DEST_DIR%\c4d\" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] new.c4d template file ^(REQUIRED for Force/Force All^)
    ) else (
        echo [ERROR] Could not copy new.c4d template file
        echo         Force and Force All buttons will not work!
    )
) else (
    echo [ERROR] new.c4d template file not found ^(REQUIRED^)
    echo         Expected: %C4D_DIR%\new.c4d
    echo         Force and Force All buttons will not work without it!
)

REM =========================================================
REM INSTALL PLUGIN ICONS
REM =========================================================

echo.
echo Step 4: Installing plugin icons...
echo ----------------------------------------

if exist "%ICONS_DIR%" (
    xcopy /E /I /Y "%ICONS_DIR%" "%DEST_DIR%\icons" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Plugin icons installed to: %DEST_DIR%\icons\
    ) else (
        echo [WARNING] Could not copy icons ^(plugin will work without them^)
    )
) else (
    echo [WARNING] Icons folder not found at: %ICONS_DIR%
    echo            ^(plugin will work without icons^)
)

REM =========================================================
REM ABC RETIME PLUGIN
REM =========================================================

echo.
echo Step 5: ABC Retime plugin...
echo ----------------------------------------
echo [OK] Installed inside Sentinel plugin folder: %DEST_DIR%\abc_retime
echo      legacy folder is intentionally not copied

REM =========================================================
REM CREATE OUTPUT DIRECTORIES
REM =========================================================

echo.
echo Step 6: Creating output directories...
echo ----------------------------------------

if not exist "C:\Sentinel_Output" (
    mkdir "C:\Sentinel_Output" 2>nul
    echo [OK] Created: C:\Sentinel_Output
    echo Sentinel Log > "C:\Sentinel_Output\snapshot_log.txt"
) else (
    echo [OK] Directory exists: C:\Sentinel_Output
)

if not exist "C:\cache\rs snapshots" (
    mkdir "C:\cache" 2>nul
    mkdir "C:\cache\rs snapshots" 2>nul
    echo [OK] Created: C:\cache\rs snapshots
) else (
    echo [OK] Directory exists: C:\cache\rs snapshots
)

REM =========================================================
REM PYTHON DETECTION AND INSTALLATION
REM =========================================================

echo.
echo Step 7: Checking Python installation...
echo ----------------------------------------

call :CheckPython
if "!PYTHON_FOUND!"=="1" (
    echo [OK] Python is installed: !PYTHON_VERSION!
    echo Python path: !PYTHON_CMD!

    REM Check and install required packages
    call :CheckPythonPackages
) else (
    echo [WARNING] Python not found
    echo.
    call :OfferPythonInstall
)

REM =========================================================
REM INSTALLATION COMPLETE
REM =========================================================

echo.
echo =========================================================
echo                 INSTALLATION COMPLETE!
echo =========================================================
echo.
echo Plugin installed to:
echo   %DEST_DIR%
echo.
echo NEXT STEPS:
echo -----------
echo 1. Restart Cinema 4D 2024
echo 2. Go to Extensions ^> Sentinel Panel
echo 3. Use the Preset dropdown to switch between render presets
echo 4. Click "Force" to apply template settings to active preset
echo 5. Click "Force All" to reset all 4 presets from template
echo.
echo NEW IN v1.5.7:
echo --------------
echo - 12 real-time quality checks
echo - Tabbed UI (QC / Render / Versions / Tools)
echo - Smart Save Versions
echo - Multi-Format Render Setup + Safe-Area overlay
echo - Texture Repathing, RS AOV management, Scene Collector
echo.
echo REDSHIFT SETUP (REQUIRED FOR SNAPSHOTS):
echo -----------------------------------------
echo 1. Open Redshift RenderView
echo 2. Click Preferences (gear icon) ^> Snapshots ^> Configuration
echo 3. Set path: C:/cache/rs snapshots
echo 4. Enable "Save snapshots as EXR"
echo 5. Click OK
echo.
echo =========================================================
echo.
goto :success_exit

REM =========================================================
REM SUBROUTINES
REM =========================================================

:CheckPython
REM This subroutine checks for Python without using goto in loops
set "PYTHON_FOUND=0"
set "PYTHON_CMD="
set "PYTHON_VERSION=Not found"

REM Method 1: Check py launcher (most reliable on Windows)
where py >nul 2>&1
if !errorlevel! equ 0 (
    py -c "import sys; sys.exit(0)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=py"
        set "PYTHON_FOUND=1"
        for /f "delims=" %%v in ('py --version 2^>^&1') do set "PYTHON_VERSION=%%v"
        exit /b 0
    )
)

REM Method 2: Check python command
where python >nul 2>&1
if !errorlevel! equ 0 (
    python -c "import sys; sys.exit(0)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=python"
        set "PYTHON_FOUND=1"
        for /f "delims=" %%v in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%v"
        exit /b 0
    )
)

REM Method 3: Check python3 command
where python3 >nul 2>&1
if !errorlevel! equ 0 (
    python3 -c "import sys; sys.exit(0)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=python3"
        set "PYTHON_FOUND=1"
        for /f "delims=" %%v in ('python3 --version 2^>^&1') do set "PYTHON_VERSION=%%v"
        exit /b 0
    )
)

REM Method 4: Check common installation paths
call :CheckPythonPaths
exit /b 0

:CheckPythonPaths
REM Check Program Files
for /d %%D in ("C:\Program Files\Python3*" "C:\Program Files\Python\Python3*") do (
    if exist "%%D\python.exe" (
        "%%D\python.exe" -c "import sys; sys.exit(0)" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_CMD=%%D\python.exe"
            set "PYTHON_FOUND=1"
            for /f "delims=" %%v in ('"%%D\python.exe" --version 2^>^&1') do set "PYTHON_VERSION=%%v"
            exit /b 0
        )
    )
)

REM Check user local
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" (
        "%%D\python.exe" -c "import sys; sys.exit(0)" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_CMD=%%D\python.exe"
            set "PYTHON_FOUND=1"
            for /f "delims=" %%v in ('"%%D\python.exe" --version 2^>^&1') do set "PYTHON_VERSION=%%v"
            exit /b 0
        )
    )
)

REM Check registry as last resort
reg query "HKCU\SOFTWARE\Python\PythonCore" >nul 2>&1
if !errorlevel! equ 0 (
    echo [INFO] Python found in registry but not in PATH
    set "PYTHON_VERSION=Found in registry (not in PATH)"
)

exit /b 0

:CheckPythonPackages
echo.
echo Checking Python packages...

REM Check Pillow
!PYTHON_CMD! -c "import PIL" >nul 2>&1
if !errorlevel! neq 0 (
    echo [INSTALLING] Pillow...
    !PYTHON_CMD! -m pip install --quiet --upgrade pip >nul 2>&1
    !PYTHON_CMD! -m pip install --quiet Pillow
    if !errorlevel! equ 0 (
        echo [OK] Pillow installed
    ) else (
        echo [WARNING] Could not install Pillow automatically
        echo           Try manually: !PYTHON_CMD! -m pip install Pillow
    )
) else (
    echo [OK] Pillow already installed
)

REM Check NumPy
!PYTHON_CMD! -c "import numpy" >nul 2>&1
if !errorlevel! neq 0 (
    echo [INSTALLING] NumPy...
    !PYTHON_CMD! -m pip install --quiet numpy
    if !errorlevel! equ 0 (
        echo [OK] NumPy installed
    ) else (
        echo [WARNING] Could not install NumPy automatically
        echo           Try manually: !PYTHON_CMD! -m pip install numpy
    )
) else (
    echo [OK] NumPy already installed
)

REM Check OpenEXR
!PYTHON_CMD! -c "import OpenEXR" >nul 2>&1
if !errorlevel! neq 0 (
    echo [INSTALLING] OpenEXR...
    !PYTHON_CMD! -m pip install --quiet OpenEXR
    if !errorlevel! equ 0 (
        echo [OK] OpenEXR installed
    ) else (
        echo [WARNING] Could not install OpenEXR automatically
        echo           Try manually: !PYTHON_CMD! -m pip install OpenEXR
    )
) else (
    echo [OK] OpenEXR already installed
)

exit /b 0

:OfferPythonInstall
echo Python is required for EXR to PNG conversion.
echo.
echo Would you like to download and install Python automatically?
set /p "INSTALL_PYTHON=Install Python now? (Y/N): "

if /i "!INSTALL_PYTHON!"=="Y" (
    echo.
    echo Downloading Python installer...

    set "PYTHON_INSTALLER=%TEMP%\python-3.11.9-amd64.exe"
    set "PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"

    powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '!PYTHON_URL!' -OutFile '!PYTHON_INSTALLER!' } catch { exit 1 }}" >nul 2>&1

    if exist "!PYTHON_INSTALLER!" (
        echo [OK] Download complete
        echo.
        echo Installing Python ^(this may take a few minutes^)...
        echo Please wait...

        "!PYTHON_INSTALLER!" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_test=0
        set "INSTALL_RESULT=!errorlevel!"

        del "!PYTHON_INSTALLER!" >nul 2>&1

        if "!INSTALL_RESULT!"=="0" (
            echo [OK] Python installed successfully
            echo.
            echo Please restart this installer to complete setup.
        ) else (
            echo [ERROR] Python installation failed
            echo Please install Python manually from https://www.python.org
        )
    ) else (
        echo [ERROR] Failed to download Python installer
        echo Please install Python manually from https://www.python.org
    )
) else (
    echo.
    echo Skipping Python installation.
    echo.
    echo WARNING: Without Python, EXR to PNG conversion will not work!
    echo.
    echo To install Python manually:
    echo 1. Go to https://www.python.org/downloads/
    echo 2. Download Python 3.11 or later
    echo 3. During installation, CHECK "Add Python to PATH"
    echo 4. Run this installer again
)

exit /b 0

REM =========================================================
REM EXIT HANDLERS
REM =========================================================

:error_exit
echo.
echo =========================================================
echo                  INSTALLATION FAILED
echo =========================================================
echo.
echo Please check the error messages above.
echo For support, contact the Sentinel team.
echo.
echo Press any key to exit...
pause >nul
endlocal
exit /b 1

:success_exit
echo Press any key to close this window...
pause >nul
endlocal
exit /b 0
