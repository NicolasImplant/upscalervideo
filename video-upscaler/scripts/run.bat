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
echo  video-upscaler -- procesar video
echo ============================================================
echo.
if "%~1"=="" (
    echo [ERROR] Indica el archivo de video.
    echo Uso: scripts\run.bat mi_video.mp4
    pause & exit /b 1
)
set "VIDEO_PATH=%~1"
set "VIDEO_NAME=%~nx1"
set "VIDEO_STEM=%~n1"
if not exist "%VIDEO_PATH%" (
    echo [ERROR] Archivo no encontrado: %VIDEO_PATH%
    pause & exit /b 1
)
set "GCS_DEST=gs://%GCS_BUCKET_INPUT%/%GCS_INPUT_PREFIX%%VIDEO_NAME%"
echo  Video  : %VIDEO_PATH%
echo  Nombre : %VIDEO_NAME%
echo  Destino: %GCS_DEST%
echo.
echo [1/2] Subiendo video...
gsutil -o "GSUtil:parallel_composite_upload_threshold=50M" cp "%VIDEO_PATH%" "%GCS_DEST%"
if errorlevel 1 ( echo [ERROR] Fallo el upload. & pause & exit /b 1 )
echo   [OK] Video subido.
echo.
echo [2/2] Ejecutando Cloud Run Job...
gcloud beta run jobs execute %CLOUD_RUN_JOB_NAME% --region=%GCP_REGION% --project=%GCP_PROJECT_ID% --update-env-vars="VIDEO_NAME=%VIDEO_NAME%" --wait
if errorlevel 1 ( echo [ERROR] El job fallo. & pause & exit /b 1 )
echo.
echo ============================================================
echo  Listo. Video disponible en:
echo  gs://%GCS_BUCKET_OUTPUT%/%GCS_OUTPUT_PREFIX%%VIDEO_STEM%_upscaled.mp4
echo ============================================================
echo.
pause
