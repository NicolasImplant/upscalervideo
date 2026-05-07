@echo off
setlocal EnableDelayedExpansion
REM =============================================================================
REM _common.bat - utilidad compartida
REM NO ejecutar directamente. Los demas scripts lo llaman con CALL.
REM =============================================================================

REM -- Resolver raiz del proyecto -----------------------------------------------
pushd "%~dp0.."
set "PROJECT_ROOT=%CD%"
popd

REM -- Verificar que .env existe -------------------------------------------------
if not exist "%PROJECT_ROOT%\.env" (
    echo [ERROR] No se encontro .env en: %PROJECT_ROOT%
    echo         Copia .env.example a .env y completa los valores.
    exit /b 1
)

REM -- Cargar .env linea por linea -----------------------------------------------
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%PROJECT_ROOT%\.env") do (
    if not "%%A"=="" (
        set "%%A=%%B"
    )
)

REM -- Verificar gcloud instalado ------------------------------------------------
where gcloud >nul 2>&1
if errorlevel 1 (
    echo [ERROR] gcloud no encontrado.
    echo         Instala Google Cloud SDK: https://cloud.google.com/sdk/docs/install
    exit /b 1
)

REM -- Verificar ADC o credenciales de usuario ----------------------------------
REM Primero intenta ADC (application-default), luego credenciales de usuario
gcloud auth application-default print-access-token >nul 2>&1
if errorlevel 1 (
    gcloud auth print-access-token >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] No hay credenciales activas.
        echo         Opciones:
        echo           gcloud auth application-default login
        echo           gcloud auth login
        exit /b 1
    )
)

REM -- Verificar GCP_PROJECT_ID --------------------------------------------------
if "%GCP_PROJECT_ID%"=="" (
    echo [ERROR] GCP_PROJECT_ID no esta definido en .env
    exit /b 1
)

REM -- Apuntar al proyecto -------------------------------------------------------
gcloud config set project %GCP_PROJECT_ID% >nul 2>&1
echo   [OK] Proyecto: %GCP_PROJECT_ID%
exit /b 0
