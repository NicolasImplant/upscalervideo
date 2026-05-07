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
echo  [2/5] Creando Service Account
echo ============================================================
echo.
set "SA_EMAIL=%SA_NAME%@%GCP_PROJECT_ID%.iam.gserviceaccount.com"
echo SA: %SA_EMAIL%
echo.
gcloud iam service-accounts describe %SA_EMAIL% --project=%GCP_PROJECT_ID% >nul 2>&1
if errorlevel 1 (
    echo   Creando SA...
    gcloud iam service-accounts create %SA_NAME% --display-name="Video Upscaler Job SA" --project=%GCP_PROJECT_ID% --quiet
    if errorlevel 1 ( echo   [ERROR] No se pudo crear el SA. & pause & exit /b 1 )
    echo   [OK] SA creado.
) else ( echo   [OK] SA ya existe. )

echo   Asignando permisos en buckets...
gcloud storage buckets add-iam-policy-binding gs://%GCS_BUCKET_INPUT% --member="serviceAccount:%SA_EMAIL%" --role="roles/storage.objectViewer" >nul 2>&1
if errorlevel 1 ( echo   [WARN] Bucket input no existe aun. Ejecuta 03 primero. ) else ( echo   [OK] objectViewer en input. )
gcloud storage buckets add-iam-policy-binding gs://%GCS_BUCKET_OUTPUT% --member="serviceAccount:%SA_EMAIL%" --role="roles/storage.objectCreator" >nul 2>&1
if errorlevel 1 ( echo   [WARN] Bucket output no existe aun. Ejecuta 03 primero. ) else ( echo   [OK] objectCreator en output. )
gcloud projects add-iam-policy-binding %GCP_PROJECT_ID% --member="serviceAccount:%SA_EMAIL%" --role="roles/logging.logWriter" --quiet >nul 2>&1
if errorlevel 1 ( echo   [ERROR] No se pudo asignar logWriter. & pause & exit /b 1 )
echo   [OK] logWriter asignado.
echo.
echo  SA configurado. Siguiente: scripts\03_create_buckets.bat
echo.
pause
