@echo off
setlocal EnableDelayedExpansion
REM =============================================================================
REM 00_cleanup_scripts.bat
REM Elimina scripts viejos que ya no aplican en el flujo actual.
REM Ejecutar una sola vez para limpiar scripts\.
REM =============================================================================

echo.
echo ============================================================
echo  Limpiando scripts obsoletos
echo ============================================================
echo.

set "SCRIPTS_DIR=%~dp0"

for %%F in (
    build.bat
    cleanup_basicsr.bat
    install.bat
    setup_project.bat
) do (
    if exist "%SCRIPTS_DIR%%%F" (
        del /q "%SCRIPTS_DIR%%%F"
        echo   [eliminado] %%F
    ) else (
        echo   [no existe] %%F
    )
)

echo.
echo Scripts actuales en scripts\:
dir /b "%SCRIPTS_DIR%*.bat"
echo.
echo ============================================================
echo  Listo. El flujo correcto es:
echo    01_enable_apis.bat
echo    02_create_sa.bat
echo    03_create_buckets.bat
echo    02_create_sa.bat   (segunda vez para permisos en buckets)
echo    04_build_push.bat
echo    05_deploy_job.bat
echo    run.bat video.mp4  (uso diario)
echo ============================================================
echo.
pause
