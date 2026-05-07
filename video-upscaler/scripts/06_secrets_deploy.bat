@echo off
setlocal EnableDelayedExpansion

REM =============================================================================
REM  06_secrets_deploy.bat
REM
REM  Script de despliegue completo con Google Cloud Secret Manager.
REM  Idempotente: puede ejecutarse varias veces sin duplicar recursos.
REM
REM  Pasos:
REM    1. Habilitar APIs necesarias (incluyendo secretmanager)
REM    2. Crear Service Account con roles minimos
REM    3. Crear buckets GCS de input y output
REM    4. Crear o actualizar secretos en Secret Manager
REM    5. Otorgar al SA permiso de lectura sobre los secretos
REM    6. Build de imagen Docker via Cloud Build + push a Artifact Registry
REM    7. Crear o actualizar Cloud Run Job con --set-secrets
REM
REM  Uso:
REM    scripts\06_secrets_deploy.bat
REM
REM  Prerequisitos:
REM    - gcloud CLI autenticado con permisos de Owner (o roles equivalentes)
REM    - .env completo con todas las variables (ver .env.example)
REM =============================================================================

pushd "%~dp0.."
set "PROJECT_ROOT=%CD%"
popd

REM ---------------------------------------------------------------------------
REM Cargar variables desde .env
REM ---------------------------------------------------------------------------
if not exist "%PROJECT_ROOT%\.env" (
    echo [ERROR] No se encontro .env en: %PROJECT_ROOT%
    echo         Copia .env.example a .env y completa las variables.
    pause & exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%PROJECT_ROOT%\.env") do (
    if not "%%A"=="" if not "%%B"=="" set "%%A=%%B"
)

REM ---------------------------------------------------------------------------
REM Validar prerequisitos
REM ---------------------------------------------------------------------------
where gcloud >nul 2>&1
if errorlevel 1 (
    echo [ERROR] gcloud CLI no encontrado. Instala Google Cloud SDK.
    pause & exit /b 1
)

if "%GCP_PROJECT_ID%"=="" (
    echo [ERROR] GCP_PROJECT_ID no definido en .env
    pause & exit /b 1
)
if "%GCP_REGION%"=="" (
    echo [ERROR] GCP_REGION no definido en .env
    pause & exit /b 1
)

set "SA_EMAIL=%SA_NAME%@%GCP_PROJECT_ID%.iam.gserviceaccount.com"
set "IMAGE_TAG=%GCP_REGION%-docker.pkg.dev/%GCP_PROJECT_ID%/%GCP_ARTIFACT_REPO%/%IMAGE_NAME%:latest"

echo.
echo ===========================================================================
echo  video-upscaler — Deploy completo con Secret Manager
echo ===========================================================================
echo  Proyecto   : %GCP_PROJECT_ID%
echo  Region     : %GCP_REGION%
echo  Job        : %CLOUD_RUN_JOB_NAME%
echo  Imagen     : %IMAGE_TAG%
echo  SA         : %SA_EMAIL%
echo ===========================================================================
echo.

gcloud config set project %GCP_PROJECT_ID% --quiet
if errorlevel 1 ( echo [ERROR] No se pudo configurar el proyecto. & pause & exit /b 1 )

REM ---------------------------------------------------------------------------
REM [1/7] Habilitar APIs
REM ---------------------------------------------------------------------------
echo [1/7] Habilitando APIs...
echo.
for %%A in (
    artifactregistry.googleapis.com
    cloudbuild.googleapis.com
    run.googleapis.com
    storage.googleapis.com
    secretmanager.googleapis.com
    iam.googleapis.com
) do (
    gcloud services enable %%A --project=%GCP_PROJECT_ID% --quiet
    if errorlevel 1 ( echo   [ERROR] No se pudo habilitar %%A & pause & exit /b 1 )
    echo   [OK] %%A
)
echo.

REM ---------------------------------------------------------------------------
REM [2/7] Crear Service Account
REM ---------------------------------------------------------------------------
echo [2/7] Configurando Service Account...
echo.
gcloud iam service-accounts describe %SA_EMAIL% --project=%GCP_PROJECT_ID% >nul 2>&1
if errorlevel 1 (
    gcloud iam service-accounts create %SA_NAME% ^
        --display-name="Video Upscaler Job SA" ^
        --project=%GCP_PROJECT_ID% --quiet
    if errorlevel 1 ( echo   [ERROR] No se pudo crear el SA. & pause & exit /b 1 )
    echo   [OK] SA creado: %SA_EMAIL%
) else (
    echo   [OK] SA ya existe: %SA_EMAIL%
)

REM Roles de storage (R en input, RW en output)
for %%R in (roles/storage.objectViewer) do (
    gcloud storage buckets add-iam-policy-binding gs://%GCS_BUCKET_INPUT% ^
        --member="serviceAccount:%SA_EMAIL%" --role=%%R --quiet >nul 2>&1
)
for %%R in (roles/storage.objectCreator roles/storage.objectViewer) do (
    gcloud storage buckets add-iam-policy-binding gs://%GCS_BUCKET_OUTPUT% ^
        --member="serviceAccount:%SA_EMAIL%" --role=%%R --quiet >nul 2>&1
)
echo   [OK] Roles de storage asignados
echo.

REM ---------------------------------------------------------------------------
REM [3/7] Crear buckets GCS
REM ---------------------------------------------------------------------------
echo [3/7] Configurando buckets GCS...
echo.
for %%B in (%GCS_BUCKET_INPUT% %GCS_BUCKET_OUTPUT%) do (
    gcloud storage buckets describe gs://%%B --project=%GCP_PROJECT_ID% >nul 2>&1
    if errorlevel 1 (
        gcloud storage buckets create gs://%%B ^
            --project=%GCP_PROJECT_ID% ^
            --location=%GCP_REGION% ^
            --uniform-bucket-level-access ^
            --quiet
        if errorlevel 1 ( echo   [ERROR] No se pudo crear gs://%%B & pause & exit /b 1 )
        echo   [OK] Bucket creado: gs://%%B
    ) else (
        echo   [OK] Bucket ya existe: gs://%%B
    )
)
echo.

REM ---------------------------------------------------------------------------
REM [4/7] Crear o actualizar secretos en Secret Manager
REM
REM  Secretos gestionados:
REM    upscaler-gcp-project-id   -> GCP_PROJECT_ID
REM    upscaler-gcs-bucket-input -> GCS_BUCKET_INPUT
REM    upscaler-gcs-bucket-output-> GCS_BUCKET_OUTPUT
REM
REM  El resto de la configuracion (ESRGAN, FFmpeg, audio, paths) se pasa
REM  como env vars planas en el Cloud Run Job (no son sensibles).
REM ---------------------------------------------------------------------------
echo [4/7] Creando o actualizando secretos en Secret Manager...
echo.

call :upsert_secret "upscaler-gcp-project-id"    "%GCP_PROJECT_ID%"
call :upsert_secret "upscaler-gcs-bucket-input"  "%GCS_BUCKET_INPUT%"
call :upsert_secret "upscaler-gcs-bucket-output" "%GCS_BUCKET_OUTPUT%"

echo.

REM ---------------------------------------------------------------------------
REM [5/7] Otorgar al SA permiso de lectura sobre los secretos
REM ---------------------------------------------------------------------------
echo [5/7] Otorgando roles/secretmanager.secretAccessor al SA...
echo.
for %%S in (upscaler-gcp-project-id upscaler-gcs-bucket-input upscaler-gcs-bucket-output) do (
    gcloud secrets add-iam-policy-binding %%S ^
        --member="serviceAccount:%SA_EMAIL%" ^
        --role="roles/secretmanager.secretAccessor" ^
        --project=%GCP_PROJECT_ID% ^
        --quiet >nul 2>&1
    if errorlevel 1 ( echo   [WARN] No se pudo asignar acceso a %%S ) else ( echo   [OK] %%S )
)
echo.

REM ---------------------------------------------------------------------------
REM [6/7] Build y push de imagen Docker via Cloud Build
REM ---------------------------------------------------------------------------
echo [6/7] Build y push de imagen Docker (Cloud Build)...
echo.

gcloud artifacts repositories describe %GCP_ARTIFACT_REPO% ^
    --location=%GCP_REGION% --project=%GCP_PROJECT_ID% >nul 2>&1
if errorlevel 1 (
    gcloud artifacts repositories create %GCP_ARTIFACT_REPO% ^
        --repository-format=docker ^
        --location=%GCP_REGION% ^
        --project=%GCP_PROJECT_ID% --quiet
    if errorlevel 1 ( echo   [ERROR] No se pudo crear el repositorio. & pause & exit /b 1 )
    echo   [OK] Artifact Registry creado.
) else (
    echo   [OK] Artifact Registry ya existe.
)

gcloud auth configure-docker %GCP_REGION%-docker.pkg.dev --quiet
if errorlevel 1 ( echo   [ERROR] Docker auth fallo. & pause & exit /b 1 )

echo.
echo   Iniciando Cloud Build (10-20 min primera vez)...
echo.
gcloud builds submit ^
    --tag="%IMAGE_TAG%" ^
    --machine-type=E2_HIGHCPU_8 ^
    --timeout=40m ^
    --project=%GCP_PROJECT_ID% ^
    "%PROJECT_ROOT%"
if errorlevel 1 ( echo. & echo   [ERROR] Cloud Build fallo. & pause & exit /b 1 )
echo.
echo   [OK] Imagen publicada: %IMAGE_TAG%
echo.

REM ---------------------------------------------------------------------------
REM [7/7] Crear o actualizar Cloud Run Job con secretos
REM
REM  --set-secrets  : GCP_PROJECT_ID, GCS_BUCKET_INPUT, GCS_BUCKET_OUTPUT
REM                   se inyectan desde Secret Manager (no viajan en texto plano)
REM  --set-env-vars : resto de la configuracion (no sensible)
REM ---------------------------------------------------------------------------
echo [7/7] Desplegando Cloud Run Job...
echo.
gcloud beta run jobs describe %CLOUD_RUN_JOB_NAME% ^
    --region=%GCP_REGION% --project=%GCP_PROJECT_ID% >nul 2>&1
if errorlevel 1 ( set "JOB_CMD=create" ) else ( set "JOB_CMD=update" )
echo   Ejecutando: gcloud run jobs !JOB_CMD!...
echo.

gcloud beta run jobs !JOB_CMD! %CLOUD_RUN_JOB_NAME% ^
    --image="%IMAGE_TAG%" ^
    --region=%GCP_REGION% ^
    --project=%GCP_PROJECT_ID% ^
    --service-account=%SA_EMAIL% ^
    --gpu=1 --gpu-type=nvidia-l4 ^
    --cpu=4 --memory=16Gi ^
    --task-timeout=3600 ^
    --max-retries=1 ^
    --set-secrets="GCP_PROJECT_ID=upscaler-gcp-project-id:latest,GCS_BUCKET_INPUT=upscaler-gcs-bucket-input:latest,GCS_BUCKET_OUTPUT=upscaler-gcs-bucket-output:latest" ^
    --set-env-vars="GCS_INPUT_PREFIX=%GCS_INPUT_PREFIX%,GCS_OUTPUT_PREFIX=%GCS_OUTPUT_PREFIX%,GCS_UPLOAD_TIMEOUT_SECONDS=%GCS_UPLOAD_TIMEOUT_SECONDS%,GCS_DOWNLOAD_TIMEOUT_SECONDS=%GCS_DOWNLOAD_TIMEOUT_SECONDS%,GCS_MAX_RETRY_ATTEMPTS=%GCS_MAX_RETRY_ATTEMPTS%,APP_ENV=%APP_ENV%,LOG_LEVEL=%LOG_LEVEL%,LOG_FORMAT=%LOG_FORMAT%,VIDEO_TARGET_SCALE=%VIDEO_TARGET_SCALE%,VIDEO_OUTPUT_FPS=%VIDEO_OUTPUT_FPS%,VIDEO_OUTPUT_CRF=%VIDEO_OUTPUT_CRF%,VIDEO_OUTPUT_PRESET=%VIDEO_OUTPUT_PRESET%,VIDEO_OUTPUT_CODEC=%VIDEO_OUTPUT_CODEC%,VIDEO_OUTPUT_AUDIO_BITRATE=%VIDEO_OUTPUT_AUDIO_BITRATE%,VIDEO_OUTPUT_AUDIO_CODEC=%VIDEO_OUTPUT_AUDIO_CODEC%,ESRGAN_MODEL_NAME=%ESRGAN_MODEL_NAME%,ESRGAN_MODEL_PATH=%ESRGAN_MODEL_PATH%,ESRGAN_TILE_SIZE=%ESRGAN_TILE_SIZE%,ESRGAN_TILE_PAD=%ESRGAN_TILE_PAD%,ESRGAN_PRE_PAD=%ESRGAN_PRE_PAD%,ESRGAN_DEVICE=%ESRGAN_DEVICE%,ESRGAN_NUM_FEAT=%ESRGAN_NUM_FEAT%,ESRGAN_NUM_BLOCK=%ESRGAN_NUM_BLOCK%,ESRGAN_NUM_GROW_CH=%ESRGAN_NUM_GROW_CH%,AUDIO_ENABLE_ENHANCEMENT=%AUDIO_ENABLE_ENHANCEMENT%,AUDIO_DENOISER_STRENGTH=%AUDIO_DENOISER_STRENGTH%,AUDIO_DENOISER_PATCH_RADIUS=%AUDIO_DENOISER_PATCH_RADIUS%,AUDIO_EQ_FREQUENCY=%AUDIO_EQ_FREQUENCY%,AUDIO_EQ_GAIN_DB=%AUDIO_EQ_GAIN_DB%,AUDIO_EQ_WIDTH=%AUDIO_EQ_WIDTH%,FFMPEG_BINARY=%FFMPEG_BINARY%,FFPROBE_BINARY=%FFPROBE_BINARY%,FFMPEG_THREADS=%FFMPEG_THREADS%,FFMPEG_LOGLEVEL=%FFMPEG_LOGLEVEL%,TMP_BASE_DIR=%TMP_BASE_DIR%,FRAMES_SUBDIR=%FRAMES_SUBDIR%,FRAMES_UPSCALED_SUBDIR=%FRAMES_UPSCALED_SUBDIR%,FRAMES_FORMAT=%FRAMES_FORMAT%,AUDIO_RAW_FILENAME=%AUDIO_RAW_FILENAME%,AUDIO_CLEAN_FILENAME=%AUDIO_CLEAN_FILENAME%,INPUT_FILENAME=%INPUT_FILENAME%,STORAGE_BACKEND=%STORAGE_BACKEND%"

if errorlevel 1 ( echo. & echo   [ERROR] Deploy fallo. & pause & exit /b 1 )

echo.
echo ===========================================================================
echo  Deploy completado exitosamente.
echo ===========================================================================
echo.
echo  Job        : %CLOUD_RUN_JOB_NAME%
echo  Region     : %GCP_REGION%
echo  Imagen     : %IMAGE_TAG%
echo.
echo  Secretos activos en Secret Manager:
echo    upscaler-gcp-project-id    -> GCP_PROJECT_ID
echo    upscaler-gcs-bucket-input  -> GCS_BUCKET_INPUT
echo    upscaler-gcs-bucket-output -> GCS_BUCKET_OUTPUT
echo.
echo  Para procesar un video:
echo    scripts\run.bat mi_video.mp4
echo.
pause
exit /b 0

REM ---------------------------------------------------------------------------
REM Subrutina: crear o actualizar un secreto en Secret Manager
REM
REM  Uso: call :upsert_secret <secret-name> <valor>
REM
REM  - Si el secreto no existe: lo crea con replication automatica
REM  - Si ya existe: agrega una nueva version con el valor actualizado
REM  - Escribe el valor en un archivo temporal sin salto de linea final
REM    para evitar que Secret Manager almacene el '\n' como parte del valor
REM ---------------------------------------------------------------------------
:upsert_secret
set "_SECRET_NAME=%~1"
set "_SECRET_VALUE=%~2"
set "_TMP_FILE=%TEMP%\~upscaler_secret.tmp"

REM Escribir valor sin newline usando PowerShell
powershell -NoProfile -Command ^
    "[System.IO.File]::WriteAllText('%_TMP_FILE%', '%_SECRET_VALUE%', [System.Text.Encoding]::UTF8)" ^
    >nul 2>&1

gcloud secrets describe %_SECRET_NAME% --project=%GCP_PROJECT_ID% >nul 2>&1
if errorlevel 1 (
    gcloud secrets create %_SECRET_NAME% ^
        --data-file="%_TMP_FILE%" ^
        --replication-policy=automatic ^
        --project=%GCP_PROJECT_ID% ^
        --quiet
    if errorlevel 1 (
        echo   [ERROR] No se pudo crear el secreto: %_SECRET_NAME%
        del "%_TMP_FILE%" >nul 2>&1
        exit /b 1
    )
    echo   [OK] Secreto creado: %_SECRET_NAME%
) else (
    gcloud secrets versions add %_SECRET_NAME% ^
        --data-file="%_TMP_FILE%" ^
        --project=%GCP_PROJECT_ID% ^
        --quiet
    if errorlevel 1 (
        echo   [WARN] No se pudo actualizar la version de: %_SECRET_NAME%
    ) else (
        echo   [OK] Secreto actualizado: %_SECRET_NAME%
    )
)

del "%_TMP_FILE%" >nul 2>&1
exit /b 0
