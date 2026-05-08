@echo off
setlocal EnableDelayedExpansion

pushd "%~dp0.."
set "PROJECT_ROOT=%CD%"
popd

if not exist "%PROJECT_ROOT%\.env" (
    echo [ERROR] No se encontro .env en: %PROJECT_ROOT%
    pause & exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%PROJECT_ROOT%\.env") do (
    if not "%%A"=="" set "%%A=%%B"
)

where gcloud >nul 2>&1
if errorlevel 1 (
    echo [ERROR] gcloud no encontrado.
    pause & exit /b 1
)

call gcloud config set project %GCP_PROJECT_ID% --quiet
echo   [OK] Proyecto: %GCP_PROJECT_ID%
echo.
echo ============================================================
echo  [1/5] Habilitando APIs de GCP
echo ============================================================
echo.
echo   Habilitando run.googleapis.com...
call gcloud services enable run.googleapis.com --project=%GCP_PROJECT_ID% --quiet
if errorlevel 1 ( echo   [ERROR] Fallo run.googleapis.com & pause & exit /b 1 )
echo   [OK] run.googleapis.com
echo   Habilitando artifactregistry.googleapis.com...
call gcloud services enable artifactregistry.googleapis.com --project=%GCP_PROJECT_ID% --quiet
if errorlevel 1 ( echo   [ERROR] Fallo artifactregistry.googleapis.com & pause & exit /b 1 )
echo   [OK] artifactregistry.googleapis.com
echo   Habilitando storage.googleapis.com...
call gcloud services enable storage.googleapis.com --project=%GCP_PROJECT_ID% --quiet
if errorlevel 1 ( echo   [ERROR] Fallo storage.googleapis.com & pause & exit /b 1 )
echo   [OK] storage.googleapis.com
echo   Habilitando cloudbuild.googleapis.com...
call gcloud services enable cloudbuild.googleapis.com --project=%GCP_PROJECT_ID% --quiet
if errorlevel 1 ( echo   [ERROR] Fallo cloudbuild.googleapis.com & pause & exit /b 1 )
echo   [OK] cloudbuild.googleapis.com
echo   Habilitando logging.googleapis.com...
call gcloud services enable logging.googleapis.com --project=%GCP_PROJECT_ID% --quiet
if errorlevel 1 ( echo   [ERROR] Fallo logging.googleapis.com & pause & exit /b 1 )
echo   [OK] logging.googleapis.com
echo   Habilitando iam.googleapis.com...
call gcloud services enable iam.googleapis.com --project=%GCP_PROJECT_ID% --quiet
if errorlevel 1 ( echo   [ERROR] Fallo iam.googleapis.com & pause & exit /b 1 )
echo   [OK] iam.googleapis.com
echo.
echo  APIs habilitadas. Siguiente: scripts\02_create_sa.bat
echo.
pause
