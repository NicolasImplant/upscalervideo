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
echo  [4/5] Build y push de imagen Docker
echo ============================================================
echo.
set "IMAGE_TAG=%GCP_REGION%-docker.pkg.dev/%GCP_PROJECT_ID%/%GCP_ARTIFACT_REPO%/%IMAGE_NAME%:latest"
echo  Imagen: %IMAGE_TAG%
echo.
gcloud artifacts repositories describe %GCP_ARTIFACT_REPO% --location=%GCP_REGION% --project=%GCP_PROJECT_ID% >nul 2>&1
if errorlevel 1 (
    gcloud artifacts repositories create %GCP_ARTIFACT_REPO% --repository-format=docker --location=%GCP_REGION% --project=%GCP_PROJECT_ID% --quiet
    if errorlevel 1 ( echo   [ERROR] No se pudo crear el repositorio. & pause & exit /b 1 )
    echo   [OK] Repositorio creado.
) else ( echo   [OK] Repositorio ya existe. )

gcloud auth configure-docker %GCP_REGION%-docker.pkg.dev --quiet
if errorlevel 1 ( echo   [ERROR] Docker auth fallo. & pause & exit /b 1 )
echo   [OK] Docker autenticado.
echo.
echo   Iniciando Cloud Build (10-20 min primera vez)...
echo.
gcloud builds submit --tag="%IMAGE_TAG%" --machine-type=E2_HIGHCPU_8 --timeout=40m --project=%GCP_PROJECT_ID% "%PROJECT_ROOT%"
if errorlevel 1 ( echo. & echo   [ERROR] Cloud Build fallo. & pause & exit /b 1 )
echo.
echo  Imagen publicada: %IMAGE_TAG%
echo  Siguiente: scripts\05_deploy_job.bat
echo.
pause
