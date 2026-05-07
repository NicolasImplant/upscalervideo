# video-upscaler

Pipeline de upscaling de video basado en IA que corre como **Cloud Run Job** sobre GPU NVIDIA. Consume un video desde Google Cloud Storage, lo procesa frame por frame con Real-ESRGAN, aplica mejora de audio opcional y sube el resultado al bucket de salida. Diseñado como job batch de ejecución única — no expone endpoints HTTP.

---

## Tabla de contenidos

1. [Arquitectura](#arquitectura)
2. [Pipeline: etapas y detalles técnicos](#pipeline-etapas-y-detalles-técnicos)
3. [Real-ESRGAN: modelo y parámetros](#real-esrgan-modelo-y-parámetros)
4. [Referencia de configuración](#referencia-de-configuración)
5. [Despliegue en GCP](#despliegue-en-gcp)
6. [Desarrollo local](#desarrollo-local)
7. [Tests](#tests)
8. [Observabilidad](#observabilidad)
9. [Troubleshooting](#troubleshooting)

---

## Arquitectura

### Patrón hexagonal (Ports & Adapters)

El núcleo del sistema no conoce ni GCS ni Real-ESRGAN directamente. Ambas dependencias externas se inyectan a través de interfaces abstractas, lo que permite cambiar el backend de almacenamiento (GCS ↔ local) o el modelo de upscaling sin tocar la lógica de orquestación.

```
┌─────────────────────────────────────────────────────────────────┐
│                        DOMINIO / NÚCLEO                         │
│                                                                 │
│   main.py ──► VideoPipeline ──► ProcessorFactory               │
│                   │                    │                        │
│               JobMetrics           [lista de processors]        │
│               exceptions.py                                     │
└──────────────────────┬──────────────────────────────────────────┘
                       │ depende de interfaces (ABC)
         ┌─────────────┴──────────────┐
         │                            │
┌────────▼────────┐         ┌─────────▼────────┐
│  StoragePort    │         │  ProcessorPort   │
│  (ABC)          │         │  (ABC)           │
└────────┬────────┘         └─────────┬────────┘
         │ implementan                │ implementan
┌────────▼────────┐    ┌─────────────▼──────────────────────────┐
│ GCSStorageAd.   │    │ FrameExtractorProcessor                │
│ LocalStorageAd. │    │ VideoUpscalerProcessor (ESRGAN)        │
└─────────────────┘    │ AudioEnhancerProcessor (FFmpeg)        │
                       │ VideoAssemblerProcessor (FFmpeg)       │
                       └───────────────────────────────────────┘
```

### Capas y responsabilidades

| Capa | Archivos | Responsabilidad |
|---|---|---|
| Entry point | `main.py` | Construye dependencias, lanza pipeline, maneja exit codes |
| Orquestación | `pipeline.py` | Coordina pasos, gestiona workspace temporal, mide tiempos |
| Configuración | `config.py` | Todas las env vars con validación (pydantic-settings) |
| Interfaces | `processors/port.py`, `storage/port.py` | Contratos ABC que desacoplan capas |
| Fábrica | `processors/factory.py` | Construye la lista de procesadores según configuración |
| Procesadores | `processors/*.py` | Lógica de transformación (FFmpeg, Real-ESRGAN) |
| Adaptadores storage | `storage/*.py` | GCS con retry exponencial; copia local para dev |
| Cross-cutting | `metrics.py`, `logger.py`, `exceptions.py` | Observabilidad, logging estructurado, jerarquía de errores |

### Flujo de datos

```
GCS input bucket
       │
       ▼ download (con retry exponencial)
/tmp/upscaler/<video_stem>/input.mp4
       │
       ▼ FrameExtractorProcessor
       ├── frames/000001.png … frames/NNNNNN.png   (ffmpeg -q:v 1)
       └── audio_raw.aac                            (ffmpeg -acodec copy)
                                                    (omitido si no hay stream de audio)
       │
       ▼ VideoUpscalerProcessor
       └── frames_up/000001.png … (RealESRGANer, tile-based)
       │
       ▼ AudioEnhancerProcessor  [opcional: AUDIO_ENABLE_ENHANCEMENT=true]
       └── audio_clean.aac       (anlmdn denoising + equalizer vía FFmpeg -af)
       │
       ▼ VideoAssemblerProcessor
       └── <video_stem>_upscaled.mp4  (libx264, CRF 18, audio aac 192k)
       │
       ▼ upload (con retry exponencial)
GCS output bucket / output/<video_stem>_upscaled.mp4
```

---

## Pipeline: etapas y detalles técnicos

### 1. FrameExtractorProcessor

Usa `ffprobe` para detectar el FPS del video fuente antes de extraer frames. Si la detección falla, hace fallback a `VIDEO_OUTPUT_FPS`. Extrae frames en formato PNG con calidad máxima (`-q:v 1`) para no introducir artefactos de compresión antes del upscaling. La extracción de audio es condicional: verifica la existencia de un stream de audio con ffprobe antes de intentar extraer, evitando errores en videos silenciosos.

**Comandos FFmpeg generados:**
```bash
# Detección de FPS
ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate \
        -of default=noprint_wrappers=1:nokey=1 input.mp4

# Extracción de frames
ffmpeg -i input.mp4 -threads 0 -q:v 1 -y frames/%06d.png

# Extracción de audio (solo si hay stream de audio)
ffmpeg -i input.mp4 -vn -acodec copy -y audio_raw.aac
```

### 2. VideoUpscalerProcessor

Carga el modelo `RealESRGAN_x2plus` (RRDBNet, 23 bloques residuales) y procesa cada frame individualmente. El procesamiento **tile-based** divide cada frame en tiles de `ESRGAN_TILE_SIZE×ESRGAN_TILE_SIZE` píxeles con `ESRGAN_TILE_PAD` píxeles de overlap para evitar artefactos en los bordes — crítico cuando la VRAM no alcanza para el frame completo.

**Validación temprana:** el procesador verifica la existencia del modelo `.pth` al construirse (antes del download desde GCS), fallando rápido si el modelo está ausente.

**Parámetros de RRDBNet** (deben coincidir exactamente con el modelo descargado):

| Parámetro | `x2plus` | `x4plus` | Descripción |
|---|---|---|---|
| `ESRGAN_NUM_FEAT` | 64 | 64 | Feature channels por capa |
| `ESRGAN_NUM_BLOCK` | 23 | 23 | Residual Dense Blocks |
| `ESRGAN_NUM_GROW_CH` | 32 | 32 | Growth channels en DenseNet |
| `VIDEO_TARGET_SCALE` | 2 | 4 | Factor de escala de salida |

**Estimación de VRAM requerida** (por frame, sin tiles):

| Resolución entrada | Factor ×2 | VRAM aprox. |
|---|---|---|
| 480p (854×480) | → 960p | ~2 GB |
| 720p (1280×720) | → 1440p | ~4 GB |
| 1080p (1920×1080) | → 2160p | ~8 GB |

Con tiles de 256px y pad de 10px, el procesamiento funciona en GPUs de 8–16 GB independientemente de la resolución.

### 3. AudioEnhancerProcessor

Aplica un filtro compuesto de dos etapas vía FFmpeg:

```
anlmdn=s=<strength>:p=<patch_radius>,equalizer=f=<freq>:t=o:w=<width>:g=<gain_db>
```

- **anlmdn** (Non-Local Means Denoising): reduce ruido de fondo preservando transientes. `s` controla la agresividad (1–15); `p` define el radio del parche de comparación.
- **equalizer**: EQ de banda paramétrica para realzar frecuencias específicas. Útil para compensar pérdida de presencia en voces o instrumentos.

Si `audio_raw.aac` no existe (video sin audio), el procesador retorna éxito sin ejecutar nada.

### 4. VideoAssemblerProcessor

Reensambla frames upscalados con el audio procesado. Prioridad de fuente de audio: `audio_clean.aac` → `audio_raw.aac` → sin audio. El FPS usado en `-framerate` es el detectado en el paso 1 (`metrics.source_fps`), preservando la cadencia original del video.

**Comando FFmpeg generado (con audio):**
```bash
ffmpeg -framerate <source_fps> -i frames_up/%06d.png \
       -i audio_clean.aac \
       -c:v libx264 -crf 18 -preset slow -threads 0 \
       -c:a aac -b:a 192k \
       -y <video_stem>_upscaled.mp4
```

---

## Real-ESRGAN: modelo y parámetros

El modelo `RealESRGAN_x2plus.pth` se descarga durante el build de Docker desde el repositorio oficial de xinntao:

```
https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth
```

**¿Por qué x2plus y no x4plus?** El modelo x2plus produce resultados perceptualmente superiores para material de video con ruido real (compresión H.264/H.265) en comparación con x4plus, que está optimizado para imagen estática. Para escalar ×4, es preferible aplicar x2plus dos veces que usar x4plus directamente.

**BasicSR:** la arquitectura RRDBNet está implementada en `BasicSR`. Dado que BasicSR no publica wheels en PyPI con las dependencias correctas, el repo incluye un wheel pre-compilado en `wheels/basicsr-1.4.2-py3-none-any.whl` que se instala directamente durante el build de Docker.

---

## Referencia de configuración

Todas las variables se leen desde el entorno (o `.env` en desarrollo). Ver `.env.example` como plantilla.

### Identidad y entorno

| Variable | Default | Validación | Descripción |
|---|---|---|---|
| `APP_ENV` | `production` | `production\|development` | Afecta formato de logs |
| `LOG_LEVEL` | `INFO` | `DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` | Nivel de logging |
| `LOG_FORMAT` | `json` | `json\|console` | JSON estructurado (prod) o consola con colores (dev) |

### Google Cloud

| Variable | Default | Descripción |
|---|---|---|
| `GCP_PROJECT_ID` | — (requerido) | ID del proyecto GCP |
| `GCS_BUCKET_INPUT` | — (requerido) | Bucket de entrada de videos |
| `GCS_BUCKET_OUTPUT` | — (requerido) | Bucket de salida de videos procesados |
| `GCS_INPUT_PREFIX` | `input/` | Prefijo de ruta dentro del bucket de entrada |
| `GCS_OUTPUT_PREFIX` | `output/` | Prefijo de ruta dentro del bucket de salida |
| `GCS_UPLOAD_TIMEOUT_SECONDS` | `300` | Timeout por intento de upload |
| `GCS_DOWNLOAD_TIMEOUT_SECONDS` | `300` | Timeout por intento de download |
| `GCS_MAX_RETRY_ATTEMPTS` | `3` | Máximo de reintentos (backoff exponencial: 2^n segundos) |

### Video

| Variable | Default | Validación | Descripción |
|---|---|---|---|
| `VIDEO_NAME` | — (requerido) | — | Nombre del archivo en GCS (ej. `clip.mp4`) |
| `VIDEO_TARGET_SCALE` | `2` | `2–4` | Factor de upscaling. Debe coincidir con el modelo ESRGAN cargado |
| `VIDEO_SOURCE_FPS` | `null` | float | FPS del video fuente. `null` = auto-detect con ffprobe |
| `VIDEO_OUTPUT_FPS` | `30` | `>0` | FPS de fallback si ffprobe falla |
| `VIDEO_OUTPUT_CRF` | `18` | `0–51` | Calidad H.264. 0=lossless, 18=visualmente transparente, 51=peor |
| `VIDEO_OUTPUT_PRESET` | `slow` | — | Preset de codificación H.264. `slow`/`veryslow` = mejor compresión |
| `VIDEO_OUTPUT_CODEC` | `libx264` | — | Codec de video de salida |
| `VIDEO_OUTPUT_AUDIO_BITRATE` | `192k` | — | Bitrate del audio de salida |
| `VIDEO_OUTPUT_AUDIO_CODEC` | `aac` | — | Codec de audio de salida |

### Real-ESRGAN

| Variable | Default | Descripción |
|---|---|---|
| `ESRGAN_MODEL_NAME` | `RealESRGAN_x2plus` | Nombre identificador del modelo (usado en logs) |
| `ESRGAN_MODEL_PATH` | `/models/RealESRGAN_x2plus.pth` | Ruta absoluta al archivo del modelo. Debe existir al arrancar |
| `ESRGAN_TILE_SIZE` | `256` | Tamaño del tile en píxeles. Reducir si hay OOM en GPU |
| `ESRGAN_TILE_PAD` | `10` | Overlap entre tiles para evitar artefactos en bordes |
| `ESRGAN_PRE_PAD` | `0` | Padding previo al upscaling |
| `ESRGAN_DEVICE` | `cuda` | `cuda` (GPU) o `cpu` (muy lento, solo para desarrollo) |
| `ESRGAN_NUM_FEAT` | `64` | Feature channels del RRDBNet. No modificar sin cambiar el modelo |
| `ESRGAN_NUM_BLOCK` | `23` | Residual blocks del RRDBNet. No modificar sin cambiar el modelo |
| `ESRGAN_NUM_GROW_CH` | `32` | Growth channels del RRDBNet. No modificar sin cambiar el modelo |

### Mejora de audio

| Variable | Default | Validación | Descripción |
|---|---|---|---|
| `AUDIO_ENABLE_ENHANCEMENT` | `true` | bool | Activa/desactiva el paso de AudioEnhancerProcessor |
| `AUDIO_DENOISER_STRENGTH` | `7` | `1–15` | Agresividad del denoising anlmdn. 7=moderado, 15=máximo |
| `AUDIO_DENOISER_PATCH_RADIUS` | `0.002` | `>0` | Radio de parche para comparación de vecinos (segundos) |
| `AUDIO_EQ_FREQUENCY` | `100` | `>0` | Frecuencia central del EQ en Hz |
| `AUDIO_EQ_GAIN_DB` | `3` | — | Ganancia del EQ en dB (positivo=realce, negativo=corte) |
| `AUDIO_EQ_WIDTH` | `200` | `>0` | Ancho de banda del EQ en Hz |

### FFmpeg y paths

| Variable | Default | Descripción |
|---|---|---|
| `FFMPEG_BINARY` | `ffmpeg` | Ruta o nombre del ejecutable de FFmpeg |
| `FFPROBE_BINARY` | `ffprobe` | Ruta o nombre del ejecutable de ffprobe |
| `FFMPEG_THREADS` | `0` | Threads para FFmpeg. `0` = auto (usa todos los cores disponibles) |
| `FFMPEG_LOGLEVEL` | `error` | Verbosidad de FFmpeg: `quiet\|error\|warning\|info\|debug` |
| `TMP_BASE_DIR` | `/tmp/upscaler` | Directorio base para archivos temporales del job |
| `FRAMES_FORMAT` | `png` | Formato de frames intermedios: `png` (sin pérdida) o `jpg` |
| `STORAGE_BACKEND` | `gcs` | `gcs` para producción, `local` para desarrollo sin GCS |

---

## Despliegue en GCP

### Prerequisitos

- `gcloud` CLI autenticado con permisos de Owner o los roles mínimos:
  - `roles/run.admin`, `roles/artifactregistry.admin`, `roles/storage.admin`, `roles/iam.serviceAccountAdmin`
- Docker instalado y corriendo localmente (solo para builds locales)
- Variables de entorno completadas en `.env` (copiar desde `.env.example`)

### Secuencia de scripts (primera vez)

Los scripts leen todas las variables desde `.env` automáticamente:

```bat
REM 1. Habilitar APIs necesarias en el proyecto GCP
scripts\01_enable_apis.bat

REM 2. Crear Service Account con los permisos mínimos (Storage R/W, Run invoker)
scripts\02_create_sa.bat

REM 3. Crear buckets de input y output con lifecycle policies
scripts\03_create_buckets.bat

REM 4. Build de la imagen Docker vía Cloud Build y push a Artifact Registry
REM    (primera vez: ~15-20 min por descarga de PyTorch + CUDA)
scripts\04_build_push.bat

REM 5. Crear o actualizar el Cloud Run Job con la configuración de GPU
scripts\05_deploy_job.bat
```

### Infraestructura del Cloud Run Job

```
Cloud Run Job: video-upscaler-job
├── GPU:    NVIDIA L4 (1 unidad)
├── CPU:    4 vCPU
├── RAM:    16 GiB
├── Timeout: 3600s (1 hora)
├── Max retries: 1
└── Service Account: video-upscaler-sa@<project>.iam.gserviceaccount.com
```

La GPU L4 tiene 24 GB de VRAM, suficiente para tiles de 256px con cualquier resolución de entrada. Para videos 4K+ con alta densidad de frames, considerar aumentar el timeout.

### Ejecución diaria

```bat
REM Sube el video a GCS y dispara el job en un solo comando
scripts\run.bat C:\ruta\a\mi_video.mp4
```

El script:
1. Sube `mi_video.mp4` a `gs://<GCS_BUCKET_INPUT>/input/mi_video.mp4` usando `gsutil`
2. Dispara `gcloud run jobs execute` con `VIDEO_NAME=mi_video.mp4` como override
3. Espera a que el job termine (`--wait`) e informa el resultado
4. El video procesado queda en `gs://<GCS_BUCKET_OUTPUT>/output/mi_video_upscaled.mp4`

### Autenticación en el contenedor

El job se ejecuta bajo el Service Account configurado en `--service-account`. Cloud Run inyecta automáticamente las credenciales ADC (Application Default Credentials) — no se necesitan archivos de clave JSON ni `GOOGLE_APPLICATION_CREDENTIALS`.

---

## Desarrollo local

### Con GPU (docker-compose)

```bash
# 1. Copiar y completar variables
copy .env.example .env
# Editar .env: configurar GCP_PROJECT_ID, GCS_BUCKET_*, VIDEO_NAME, STORAGE_BACKEND=gcs

# 2. Construir y ejecutar
docker compose up
```

### Sin GPU (modo local, sin GCS)

Configura en `.env`:
```ini
STORAGE_BACKEND=local
ESRGAN_DEVICE=cpu
LOCAL_STORAGE_INPUT_DIR=C:/ruta/a/videos/input
LOCAL_STORAGE_OUTPUT_DIR=C:/ruta/a/videos/output
VIDEO_NAME=mi_video.mp4
```

Coloca el video en `LOCAL_STORAGE_INPUT_DIR/mi_video.mp4` y ejecuta:
```bash
docker compose up
```

El modo CPU es extremadamente lento (~5-10 segundos por frame). Usar solo para validar el pipeline end-to-end con clips muy cortos.

### Regenerar el wheel de BasicSR

El wheel `wheels/basicsr-1.4.2-py3-none-any.whl` está commiteado para evitar compilar BasicSR en cada build. Si necesitas una versión diferente:

```bash
git clone https://github.com/xinntao/BasicSR BasicSR
scripts\cleanup_basicsr.bat   # parchea setup.py y genera el wheel
```

---

## Tests

### Ejecución

```bash
# Instalar dependencias de test (solo primera vez)
pip install -r requirements-test.txt

# Correr todos los tests
cd video-upscaler
python -m pytest tests/ -v

# Con cobertura (requiere pytest-cov)
python -m pytest tests/ -v --cov=src --cov-report=term-missing
```

### Cobertura actual

81 tests distribuidos en 10 módulos:

| Módulo de tests | Qué verifica |
|---|---|
| `test_config.py` | Derivación de paths y blobs GCS desde `video_name`; flags de entorno |
| `test_metrics.py` | Registro de timings, acumulación, context manager `timed_step` |
| `test_exceptions.py` | Jerarquía de herencia; almacenamiento de `context` y `processor_name` |
| `test_storage_local.py` | Copy de archivos, manejo de prefijos GCS, creación de directorios |
| `test_storage_gcs.py` | Retry exponencial, backoff correcto, raise tras max intentos |
| `test_frame_extractor.py` | Parsing de fracciones FPS, fallback, detección de stream de audio |
| `test_video_upscaler.py` | Validación temprana del modelo (init-time, no runtime) |
| `test_audio_enhancer.py` | Skip silencioso sin audio; construcción del filtro AF con parámetros |
| `test_video_assembler.py` | Prioridad de fuentes de audio; FPS heredado de métricas |
| `test_pipeline.py` | Ordenamiento `build_pipeline` → `download`; limpieza de workspace |

### Estrategia de mocking

Las dependencias pesadas (`torch`, `cv2`, `basicsr`, `realesrgan`, `google-cloud-storage`) no están instaladas en el entorno de test. Se reemplazan con `MagicMock` a nivel de `sys.modules` en `tests/conftest.py` antes de que cualquier módulo `src.*` sea importado. El `GoogleAPIError` de Google se reemplaza por una subclase real de `Exception` para que los tests de retry funcionen correctamente.

---

## Observabilidad

### Formato de logs

En producción (`LOG_FORMAT=json`), cada línea es un objeto JSON:

```json
{
  "timestamp": "2026-05-06T14:23:01.123456Z",
  "level": "info",
  "logger": "src.pipeline",
  "event": "processor_done",
  "name": "frame_extractor",
  "message": "1847 frames extraídos a 29.97 fps",
  "metadata": null
}
```

En desarrollo (`LOG_FORMAT=console`), structlog formatea con colores y alineación legible por humanos.

### Métricas de job

Al finalizar, el pipeline emite un evento `app_done` con el resumen completo:

```json
{
  "event": "app_done",
  "video_name": "mi_video.mp4",
  "total_seconds": 847.3,
  "steps": {
    "download": 12.4,
    "frame_extractor": 48.2,
    "video_upscaler": 712.5,
    "audio_enhancer": 3.1,
    "video_assembler": 61.8,
    "upload": 9.3
  },
  "frame_count": 1847,
  "source_fps": 29.97,
  "errors": []
}
```

### Exit codes

| Código | Significado |
|---|---|
| `0` | Job completado exitosamente |
| `1` | Error de dominio (`VideoUpscalerError` y subclases) |
| `2` | Error inesperado (excepción no manejada) |

Cloud Run marca el task como fallido si el exit code es distinto de 0.

---

## Troubleshooting

### `CUDA out of memory` durante upscaling

Reducir `ESRGAN_TILE_SIZE`. Empezar con 128 y aumentar hasta encontrar el límite de la GPU:

```ini
ESRGAN_TILE_SIZE=128
ESRGAN_TILE_PAD=10
```

### `Modelo no encontrado: /models/RealESRGAN_x2plus.pth`

El `wget` del Dockerfile falló silenciosamente. Rebuildar la imagen:
```bash
scripts\04_build_push.bat
```
Verificar en Cloud Build logs que la línea `Downloading model...` completa sin errores HTTP.

### Job falla inmediatamente con `ValidationError`

Alguna variable de entorno requerida no está configurada. Revisar que el Cloud Run Job tenga todas las variables del `--set-env-vars` de `05_deploy_job.bat`. La más común: olvidar pasar `VIDEO_NAME` al ejecutar el job (usar `scripts\run.bat` que lo inyecta automáticamente).

### Frames extraídos: 0

FFmpeg no pudo leer el video. Causas comunes:
- El archivo en GCS está corrupto o incompleto
- El codec del video no está soportado por la versión de FFmpeg de la imagen

Verificar con: `ffprobe -v error -show_entries stream=codec_name input.mp4`

### Audio mejorado suena distorsionado

Reducir `AUDIO_DENOISER_STRENGTH` (valores altos eliminan también señal útil):
```ini
AUDIO_DENOISER_STRENGTH=3
AUDIO_DENOISER_PATCH_RADIUS=0.001
```

### Build de Docker falla en `pip install ./wheels/basicsr...`

El `.dockerignore` local podría estar excluyendo el wheel. Verificar que la línea en `.dockerignore` sea `!wheels/basicsr-1.4.2-py3-none-any.whl` (con `!` de inclusión), no sin él.
