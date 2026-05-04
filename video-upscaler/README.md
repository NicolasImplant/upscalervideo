# video-upscaler

Pipeline de upscaling de video con IA que corre como **Cloud Run Job**. Descarga un video desde Google Cloud Storage, lo escala con [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN), mejora el audio y sube el resultado al bucket de salida. El trigger es Pub/Sub, no hay endpoints HTTP.

**Pipeline:** descarga → extracción de frames (FFmpeg) → upscaling (Real-ESRGAN x2/x4) → mejora de audio (anlmdn + EQ) → reensamblado → subida.

---

## Prerrequisitos

- Docker con soporte NVIDIA
- Credenciales GCP con acceso a los buckets de input/output
- Variables de entorno configuradas (ver `.env.example`)

---

## Primeros pasos (primera vez)

```bat
REM 1. Crear directorios locales
scripts\install.bat

REM 2. Copiar y completar variables de entorno
copy .env.example .env
REM  editar .env con GCP_PROJECT_ID, GCS_BUCKET_INPUT/OUTPUT, VIDEO_NAME, etc.

REM 3. Construir imagen Docker
scripts\build.bat
```

> Si necesitas regenerar el wheel de BasicSR desde cero:
> `git clone https://github.com/xinntao/BasicSR BasicSR && scripts\cleanup_basicsr.bat`

---

## Ejecución

```bat
docker compose up
```

Requiere `.env` con las variables de GCP y GPU NVIDIA disponible en el host.
Para desarrollo local sin GPU: ajusta `ESRGAN_DEVICE=cpu` y `STORAGE_BACKEND=local` en `.env`.
