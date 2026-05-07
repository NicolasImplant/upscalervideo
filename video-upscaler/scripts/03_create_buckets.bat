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

gcloud config set project %GCP_PROJECT_ID% --quiet
echo   [OK] Proyecto: %GCP_PROJECT_ID%
echo.
echo ============================================================
echo  [3/5] Creando buckets de Cloud Storage
echo ============================================================
echo.
echo  Input  : gs://%GCS_BUCKET_INPUT%
echo  Output : gs://%GCS_BUCKET_OUTPUT%
echo  Region : %GCP_REGION%
echo.
gcloud storage buckets describe gs://%GCS_BUCKET_INPUT% >nul 2>&1
if errorlevel 1 (
    gcloud storage buckets create gs://%GCS_BUCKET_INPUT% --location=%GCP_REGION% --uniform-bucket-level-access --project=%GCP_PROJECT_ID%
    if errorlevel 1 ( echo   [ERROR] No se pudo crear bucket input. & pause & exit /b 1 )
    echo   [OK] gs://%GCS_BUCKET_INPUT% creado.
) else ( echo   [OK] gs://%GCS_BUCKET_INPUT% ya existe. )

gcloud storage buckets describe gs://%GCS_BUCKET_OUTPUT% >nul 2>&1
if errorlevel 1 (
    gcloud storage buckets create gs://%GCS_BUCKET_OUTPUT% --location=%GCP_REGION% --uniform-bucket-level-access --project=%GCP_PROJECT_ID%
    if errorlevel 1 ( echo   [ERROR] No se pudo crear bucket output. & pause & exit /b 1 )
    echo   [OK] gs://%GCS_BUCKET_OUTPUT% creado.
) else ( echo   [OK] gs://%GCS_BUCKET_OUTPUT% ya existe. )

echo.
echo  Buckets listos.
echo  Siguiente: scripts\02_create_sa.bat (segunda vez para permisos)
echo.
pause
