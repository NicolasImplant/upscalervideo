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
    echo [ERROR] gcloud CLI no encontrado. Instala Google Cloud SDK.
    pause & exit /b 1
)
where gsutil >nul 2>&1
if errorlevel 1 (
    echo [ERROR] gsutil no encontrado. Viene incluido con Google Cloud SDK.
    pause & exit /b 1
)

gcloud config set project %GCP_PROJECT_ID% --quiet
echo   [OK] Proyecto : %GCP_PROJECT_ID%
echo   [OK] Job      : %CLOUD_RUN_JOB_NAME%
echo.
echo ============================================================
echo  video-upscaler -- procesar video
echo ============================================================
echo.

REM Resolver el path del video:
REM   1. Argumento de linea de comandos  (prioridad alta)
REM   2. VIDEO_LOCAL_PATH del .env       (default configurado)
if not "%~1"=="" (
    set "VIDEO_PATH=%~1"
) else if not "%VIDEO_LOCAL_PATH%"=="" (
    set "VIDEO_PATH=%VIDEO_LOCAL_PATH%"
) else (
    echo [ERROR] No se especifico el video.
    echo.
    echo  Opciones:
    echo    1. Pasar el path como argumento:
    echo         scripts\run.bat "C:\ruta\a\mi_video.mp4"
    echo.
    echo    2. Configurar VIDEO_LOCAL_PATH en .env y ejecutar sin argumentos:
    echo         VIDEO_LOCAL_PATH=C:\ruta\a\mi_video.mp4
    echo         scripts\run.bat
    pause & exit /b 1
)

REM Extraer nombre y stem del path resuelto
for %%F in ("%VIDEO_PATH%") do (
    set "VIDEO_NAME=%%~nxF"
    set "VIDEO_STEM=%%~nF"
)

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
