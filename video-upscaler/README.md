# video-upscaler

Pipeline de upscaling de video basado en IA que corre como **Cloud Run Job** sobre GPU NVIDIA L4. Descarga un video desde Google Cloud Storage, lo procesa frame por frame con Real-ESRGAN (×2 o ×4), aplica mejora de audio opcional vía FFmpeg y sube el resultado al bucket de salida. Diseñado como job batch de ejecución única — no expone endpoints HTTP.

Credenciales sensibles (`GCP_PROJECT_ID`, `GCS_BUCKET_INPUT`, `GCS_BUCKET_OUTPUT`) se almacenan en **Secret Manager** y se inyectan al contenedor en runtime. El resto de la configuración viaja como variables de entorno planas.

---

## Tabla de contenidos

1. [Arquitectura](#arquitectura)
2. [Pipeline: etapas y detalles técnicos](#pipeline-etapas-y-detalles-técnicos)
3. [Real-ESRGAN: modelo y parámetros](#real-esrgan-modelo-y-parámetros)
4. [Referencia de configuración](#referencia-de-configuración)
5. [Despliegue en GCP](#despliegue-en-gcp)
6. [Secret Manager](#secret-manager)
7. [Desarrollo local](#desarrollo-local)
8. [Tests](#tests)
9. [Observabilidad](#observabilidad)
10. [Troubleshooting](#troubleshooting)

---

## Arquitectura

### Patrón hexagonal (Ports & Adapters)

El núcleo del sistema no conoce ni GCS ni Real-ESRGAN directamente. Ambas dependencias externas se inyectan a través de interfaces abstractas (`ABC`), lo que permite cambiar el backend de almacenamiento (GCS ↔ local) o el modelo de upscaling sin tocar la lógica de orquestación.

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
| Entry point | `src/main.py` | Construye dependencias, lanza pipeline, maneja exit codes |
| Orquestación | `src/pipeline.py` | Coordina pasos, gestiona workspace temporal, mide tiempos |
| Configuración | `src/config.py` | Todas las env vars con validación (pydantic-settings) |
| Interfaces | `src/processors/port.py`, `src/storage/port.py` | Contratos ABC que desacoplan capas |
| Fábrica | `src/processors/factory.py` | Construye la lista de procesadores según configuración |
| Procesadores | `src/processors/*.py` | Lógica de transformación: FFmpeg y Real-ESRGAN |
| Adaptadores storage | `src/storage/*.py` | GCS con retry exponencial; copia local para dev |
| Cross-cutting | `src/metrics.py`, `src/logger.py`, `src/exceptions.py` | Observabilidad, logging estructurado, jerarquía de errores |

### Flujo de datos

```
GCS input bucket
gs://<GCS_BUCKET_INPUT>/<GCS_INPUT_PREFIX><VIDEO_NAME>
       │
       ▼ download — retry exponencial (2^n s, hasta GCS_MAX_RETRY_ATTEMPTS)
/tmp/upscaler/<video_stem>/input.mp4
       │
       ▼ FrameExtractorProcessor
       ├── frames/000001.png … frames/NNNNNN.png   (ffmpeg -q:v 1, sin pérdida)
       └── audio_raw.aac                            (ffmpeg -acodec copy)
                                                    [omitido si no hay stream de audio]
       │
       ▼ VideoUpscalerProcessor
       └── frames_up/000001.png … NNNNNN.png        (RealESRGANer, tile-based)
       │
       ▼ AudioEnhancerProcessor  [solo si AUDIO_ENABLE_ENHANCEMENT=true]
       └── audio_clean.aac       (anlmdn denoising + EQ paramétrico vía FFmpeg -af)
       │
       ▼ VideoAssemblerProcessor
       └── <video_stem>_upscaled.mp4  (libx264, CRF 18, aac 192k)
       │
       ▼ upload — retry exponencial
GCS output bucket
gs://<GCS_BUCKET_OUTPUT>/<GCS_OUTPUT_PREFIX><video_stem>_upscaled.mp4
       │
       ▼ cleanup (bloque finally)
/tmp/upscaler/<video_stem>/  ← eliminado completamente
```

---

## Pipeline: etapas y detalles técnicos

### 1. FrameExtractorProcessor

Usa `ffprobe` para detectar el FPS del video fuente antes de extraer frames. Si la detección falla (o la respuesta no es parseable como fracción), hace fallback a `VIDEO_OUTPUT_FPS`. Los frames se extraen en formato PNG con calidad máxima (`-q:v 1`) para no introducir artefactos de compresión antes del upscaling.

La extracción de audio es condicional: verifica la existencia de un stream de audio con `ffprobe` antes de intentar extraer, evitando errores en videos silenciosos.

**Comandos FFmpeg generados:**

```bash
# Detección de FPS (devuelve fracción, ej. "30000/1001")
ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate \
        -of default=noprint_wrappers=1:nokey=1 input.mp4

# Extracción de frames (numerados con 6 dígitos)
ffmpeg -i input.mp4 -threads 0 -q:v 1 -y frames/%06d.png

# Extracción de audio (solo si hay stream de audio)
ffmpeg -i input.mp4 -vn -acodec copy -y audio_raw.aac
```

### 2. VideoUpscalerProcessor

Carga el modelo `RealESRGAN_x2plus` (arquitectura RRDBNet, 23 bloques residuales densos) y procesa cada frame individualmente. El procesamiento **tile-based** divide cada frame en tiles de `ESRGAN_TILE_SIZE × ESRGAN_TILE_SIZE` píxeles con `ESRGAN_TILE_PAD` píxeles de overlap para evitar artefactos en bordes — crítico cuando la VRAM no alcanza para el frame completo.

**Validación temprana:** el procesador verifica la existencia del archivo `.pth` al construirse (antes del download desde GCS), fallando rápido si el modelo está ausente en lugar de descubrir el error al inicio del upscaling.

**Parámetros RRDBNet** — deben coincidir exactamente con los pesos del modelo descargado:

| Parámetro | `x2plus` | `x4plus` | Descripción |
|---|---|---|---|
| `ESRGAN_NUM_FEAT` | `64` | `64` | Feature channels por capa convolucional |
| `ESRGAN_NUM_BLOCK` | `23` | `23` | Residual Dense Blocks (RRDB) |
| `ESRGAN_NUM_GROW_CH` | `32` | `32` | Growth channels en bloques DenseNet internos |
| `VIDEO_TARGET_SCALE` | `2` | `4` | Factor de escala de salida |

**VRAM requerida por frame sin tiles** (referencia orientativa):

| Resolución entrada | Factor ×2 | VRAM aprox. |
|---|---|---|
| 480p (854×480) | → 1708×960 | ~2 GB |
| 720p (1280×720) | → 2560×1440 | ~4 GB |
| 1080p (1920×1080) | → 3840×2160 (4K) | ~8 GB |

Con `ESRGAN_TILE_SIZE=256` y `ESRGAN_TILE_PAD=10`, el procesamiento funciona en cualquier resolución con GPUs de 8+ GB de VRAM. La L4 tiene 24 GB, suficiente para tiles generosos incluso en 4K.

### 3. AudioEnhancerProcessor

Aplica un filtro compuesto de dos etapas en cadena vía FFmpeg:

```
anlmdn=s=<strength>:p=<patch_radius>,equalizer=f=<freq>:t=o:w=<width>:g=<gain_db>
```

- **`anlmdn`** (Non-Local Means Denoising): reduce ruido de fondo estacionario (ventiladores, hiss) preservando transientes. El parámetro `s` controla la agresividad (1–15); `p` define el radio del parche de comparación de vecinos en segundos.
- **`equalizer`**: EQ de banda paramétrica para compensar pérdidas en la cadena de procesamiento. Útil para realzar presencia en voces (100–3000 Hz) o cortar rumble subsónico.

Si `audio_raw.aac` no existe (video sin audio), el procesador retorna éxito sin ejecutar nada — sin error, sin log de advertencia.

### 4. VideoAssemblerProcessor

Reensambla los frames upscalados con el audio procesado. Prioridad de fuente de audio:

```
audio_clean.aac  →  audio_raw.aac  →  sin pista de audio
```

El FPS usado en `-framerate` es el detectado en el paso 1 (`metrics.source_fps`), no el valor de configuración — preserva la cadencia original del video fuente.

**Comando FFmpeg generado (con audio):**

```bash
ffmpeg -framerate <source_fps> \
       -i frames_up/%06d.png \
       -i audio_clean.aac \
       -c:v libx264 -crf 18 -preset slow -threads 0 \
       -c:a aac -b:a 192k \
       -y <video_stem>_upscaled.mp4
```

---

## Real-ESRGAN: modelo y parámetros

El modelo `RealESRGAN_x2plus.pth` se descarga durante el build de Docker desde el repositorio oficial:

```
https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth
```

**¿Por qué `x2plus` y no `x4plus`?**

El modelo `x2plus` produce resultados perceptualmente superiores para material de video con ruido real (artefactos de compresión H.264/H.265, ruido de cámara) comparado con `x4plus`, que está optimizado para imagen estática limpia. Para escalar ×4 desde video de baja calidad, aplicar `x2plus` dos veces produce mejores resultados que `x4plus` directamente.

**Dependencia BasicSR:**

La arquitectura RRDBNet está implementada en `BasicSR`. Dado que BasicSR no publica wheels en PyPI con las dependencias resueltas correctamente, el repositorio incluye un wheel pre-compilado en `wheels/basicsr-1.4.2-py3-none-any.whl` que se instala durante el build de Docker, evitando conflictos de dependencias y tiempos de compilación.

---

## Referencia de configuración

Todas las variables se leen desde el entorno (o `.env` en desarrollo local). Copiar `.env.example` como plantilla base.

### Identidad y entorno

| Variable | Default | Validación | Descripción |
|---|---|---|---|
| `APP_ENV` | `production` | `production\|development` | Afecta formato de logs y comportamiento de errores |
| `LOG_LEVEL` | `INFO` | `DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` | Nivel mínimo de logging |
| `LOG_FORMAT` | `json` | `json\|console` | `json` para Cloud Logging; `console` con colores para desarrollo |

### Google Cloud

| Variable | Default | Descripción |
|---|---|---|
| `GCP_PROJECT_ID` | — (requerido) | ID del proyecto GCP. En producción se inyecta desde Secret Manager |
| `GCS_BUCKET_INPUT` | — (requerido) | Bucket de entrada. En producción se inyecta desde Secret Manager |
| `GCS_BUCKET_OUTPUT` | — (requerido) | Bucket de salida. En producción se inyecta desde Secret Manager |
| `GCS_INPUT_PREFIX` | `input/` | Prefijo de ruta dentro del bucket de entrada |
| `GCS_OUTPUT_PREFIX` | `output/` | Prefijo de ruta dentro del bucket de salida |
| `GCS_UPLOAD_TIMEOUT_SECONDS` | `300` | Timeout por intento de upload (segundos) |
| `GCS_DOWNLOAD_TIMEOUT_SECONDS` | `300` | Timeout por intento de download (segundos) |
| `GCS_MAX_RETRY_ATTEMPTS` | `3` | Máximo de reintentos. Backoff exponencial: espera `2^intento` segundos entre reintentos |

### Video

| Variable | Default | Validación | Descripción |
|---|---|---|---|
| `VIDEO_NAME` | — (requerido) | — | Nombre del archivo a procesar en GCS (ej. `clip.mp4`). Inyectado por `run.bat` al disparar el job |
| `VIDEO_LOCAL_PATH` | — (opcional) | — | Path local del video. Solo usado por `scripts\run.bat` como fallback si no se pasa argumento |
| `VIDEO_TARGET_SCALE` | `2` | `2–4` | Factor de upscaling. Debe coincidir con el modelo ESRGAN cargado |
| `VIDEO_OUTPUT_FPS` | `30` | `>0` | FPS de fallback si `ffprobe` no puede detectar el FPS fuente |
| `VIDEO_OUTPUT_CRF` | `18` | `0–51` | Calidad H.264. `0`=lossless, `18`=visualmente transparente, `51`=calidad mínima |
| `VIDEO_OUTPUT_PRESET` | `slow` | — | Preset H.264. `slow`/`veryslow` maximizan compresión a costa de tiempo de encode |
| `VIDEO_OUTPUT_CODEC` | `libx264` | — | Codec de video de salida |
| `VIDEO_OUTPUT_AUDIO_BITRATE` | `192k` | — | Bitrate del audio de salida |
| `VIDEO_OUTPUT_AUDIO_CODEC` | `aac` | — | Codec de audio de salida |

### Real-ESRGAN

| Variable | Default | Descripción |
|---|---|---|
| `ESRGAN_MODEL_NAME` | `RealESRGAN_x2plus` | Nombre identificador del modelo (usado en logs) |
| `ESRGAN_MODEL_PATH` | `/models/RealESRGAN_x2plus.pth` | Ruta absoluta al archivo `.pth`. El procesador verifica su existencia al inicializarse |
| `ESRGAN_TILE_SIZE` | `256` | Tamaño del tile en píxeles. Reducir si hay OOM en GPU (ej. `128`) |
| `ESRGAN_TILE_PAD` | `10` | Overlap entre tiles adyacentes. Elimina artefactos en bordes de tile |
| `ESRGAN_PRE_PAD` | `0` | Padding adicional previo al upscaling |
| `ESRGAN_DEVICE` | `cuda` | `cuda` para GPU (producción) o `cpu` (muy lento, solo validación local) |
| `ESRGAN_NUM_FEAT` | `64` | Feature channels del RRDBNet. No modificar sin cambiar el archivo `.pth` |
| `ESRGAN_NUM_BLOCK` | `23` | Residual Dense Blocks del RRDBNet. No modificar sin cambiar el archivo `.pth` |
| `ESRGAN_NUM_GROW_CH` | `32` | Growth channels del RRDBNet. No modificar sin cambiar el archivo `.pth` |

### Mejora de audio

| Variable | Default | Validación | Descripción |
|---|---|---|---|
| `AUDIO_ENABLE_ENHANCEMENT` | `true` | bool | Activa/desactiva `AudioEnhancerProcessor` completo |
| `AUDIO_DENOISER_STRENGTH` | `7` | `1–15` | Agresividad del denoising `anlmdn`. `3`=suave, `7`=moderado, `15`=agresivo |
| `AUDIO_DENOISER_PATCH_RADIUS` | `0.002` | `>0` | Radio del parche de comparación en segundos |
| `AUDIO_EQ_FREQUENCY` | `100` | `>0` | Frecuencia central del EQ en Hz |
| `AUDIO_EQ_GAIN_DB` | `3` | — | Ganancia del EQ en dB. Positivo=realce, negativo=corte |
| `AUDIO_EQ_WIDTH` | `200` | `>0` | Ancho de banda del EQ en Hz |

### FFmpeg, paths y storage

| Variable | Default | Descripción |
|---|---|---|
| `FFMPEG_BINARY` | `ffmpeg` | Nombre o ruta absoluta del ejecutable FFmpeg |
| `FFPROBE_BINARY` | `ffprobe` | Nombre o ruta absoluta del ejecutable ffprobe |
| `FFMPEG_THREADS` | `0` | Threads para FFmpeg. `0` = auto (usa todos los cores disponibles) |
| `FFMPEG_LOGLEVEL` | `error` | Verbosidad de FFmpeg: `quiet\|error\|warning\|info\|debug` |
| `TMP_BASE_DIR` | `/tmp/upscaler` | Directorio base para archivos temporales del job |
| `FRAMES_SUBDIR` | `frames` | Subdirectorio de frames extraídos dentro del workspace |
| `FRAMES_UPSCALED_SUBDIR` | `frames_up` | Subdirectorio de frames upscalados dentro del workspace |
| `FRAMES_FORMAT` | `png` | Formato de frames intermedios: `png` (sin pérdida) o `jpg` |
| `AUDIO_RAW_FILENAME` | `audio_raw.aac` | Nombre del archivo de audio extraído |
| `AUDIO_CLEAN_FILENAME` | `audio_clean.aac` | Nombre del archivo de audio mejorado |
| `INPUT_FILENAME` | `input.mp4` | Nombre del archivo de video descargado en el workspace |
| `STORAGE_BACKEND` | `gcs` | `gcs` para producción, `local` para desarrollo sin GCS |
| `LOCAL_STORAGE_INPUT_DIR` | — | Solo con `STORAGE_BACKEND=local`. Directorio de entrada local |
| `LOCAL_STORAGE_OUTPUT_DIR` | — | Solo con `STORAGE_BACKEND=local`. Directorio de salida local |

---

## Despliegue en GCP

### Prerequisitos

- `gcloud` CLI instalado y autenticado (`gcloud auth login`)
- Permisos de Owner en el proyecto GCP o los roles mínimos:
  `roles/run.admin`, `roles/artifactregistry.admin`, `roles/storage.admin`, `roles/iam.serviceAccountAdmin`, `roles/secretmanager.admin`, `roles/cloudbuild.builds.editor`
- Archivo `.env` completado (copiar desde `.env.example`)
- **Windows CMD** — los scripts son `.bat`. Ejecutar desde `cmd.exe`, no desde PowerShell directamente

> **Nota técnica:** En Windows, `gcloud` es `gcloud.cmd` (un archivo batch). Los scripts `.bat` deben invocar otros `.bat` con `call`. Sin `call`, el script padre termina al invocar el comando hijo. Todos los scripts de este repo ya incluyen `call gcloud` y `call gsutil`.

### Deploy completo (método recomendado)

El script `06_secrets_deploy.bat` realiza los 7 pasos en secuencia. Es **idempotente**: puede ejecutarse múltiples veces sin duplicar recursos.

```bat
cd video-upscaler
scripts\06_secrets_deploy.bat
```

**Pasos que ejecuta:**

| Paso | Acción |
|---|---|
| 1/7 | Habilita APIs: `artifactregistry`, `cloudbuild`, `run`, `storage`, `secretmanager`, `iam` |
| 2/7 | Crea Service Account `video-upscaler-sa` con roles mínimos en los buckets |
| 3/7 | Crea buckets GCS de input y output con `--uniform-bucket-level-access` |
| 4/7 | Crea o actualiza secretos en Secret Manager con los valores de `.env` |
| 5/7 | Otorga `roles/secretmanager.secretAccessor` al SA sobre los 3 secretos |
| 6/7 | Build de imagen Docker vía Cloud Build + push a Artifact Registry (~10 min primera vez) |
| 7/7 | Crea o actualiza el Cloud Run Job con `--set-secrets` y `--set-env-vars` |

### Deploy paso a paso (alternativa)

Los scripts numerados ejecutan cada paso individualmente y son útiles para debugging o deploys parciales:

```bat
scripts\01_enable_apis.bat      REM Habilitar APIs
scripts\02_create_sa.bat        REM Crear Service Account
scripts\03_create_buckets.bat   REM Crear buckets GCS
scripts\02_create_sa.bat        REM Segunda vez: asignar permisos en los buckets ya creados
scripts\04_build_push.bat       REM Build Docker + push a Artifact Registry
scripts\05_deploy_job.bat       REM Crear/actualizar Cloud Run Job (sin Secret Manager)
```

> `05_deploy_job.bat` pasa todas las variables como `--set-env-vars` en texto plano (sin Secret Manager). Para producción usar `06_secrets_deploy.bat`.

### Infraestructura del Cloud Run Job

```
Cloud Run Job: video-upscaler-job
├── Imagen:         us-central1-docker.pkg.dev/<project>/video-upscaler/video-upscaler-job:latest
├── GPU:            NVIDIA L4 (1 unidad, 24 GB VRAM)
├── CPU:            4 vCPU
├── RAM:            16 GiB
├── Timeout:        3600 s (1 hora)
├── Max retries:    1
├── Redundancia:    --no-gpu-zonal-redundancy (requerido para GPUs por limitaciones de capacidad zonal)
└── Service Account: video-upscaler-sa@<project>.iam.gserviceaccount.com
```

### Procesamiento de un video (uso diario)

```bat
REM Con path explícito como argumento
scripts\run.bat "C:\Videos\mi_video.mp4"

REM O configurando VIDEO_LOCAL_PATH en .env y sin argumento
scripts\run.bat
```

`run.bat` resuelve el path del video con esta prioridad:
1. Argumento de línea de comandos (`%1`)
2. Variable `VIDEO_LOCAL_PATH` del `.env`
3. Error si ninguno está definido

Una vez resuelto el path:
1. Sube el video a `gs://<GCS_BUCKET_INPUT>/<GCS_INPUT_PREFIX><video_name>` vía `gsutil` con upload compuesto para archivos grandes
2. Dispara `gcloud beta run jobs execute` con `--update-env-vars VIDEO_NAME=<video_name>`
3. Espera a que el job termine (`--wait`) e informa resultado
4. El video procesado queda en `gs://<GCS_BUCKET_OUTPUT>/<GCS_OUTPUT_PREFIX><video_stem>_upscaled.mp4`

### Autenticación en el contenedor

El job corre bajo el Service Account configurado en `--service-account`. Cloud Run inyecta automáticamente las credenciales ADC (Application Default Credentials) al contenedor — no se necesitan archivos de clave JSON ni `GOOGLE_APPLICATION_CREDENTIALS`.

---

## Secret Manager

Los secretos gestionados son los únicos valores sensibles que identifican el entorno de producción:

| Nombre del secreto | Variable de entorno | Valor |
|---|---|---|
| `upscaler-gcp-project-id` | `GCP_PROJECT_ID` | ID del proyecto GCP |
| `upscaler-gcs-bucket-input` | `GCS_BUCKET_INPUT` | Nombre del bucket de entrada |
| `upscaler-gcs-bucket-output` | `GCS_BUCKET_OUTPUT` | Nombre del bucket de salida |

El resto de la configuración (parámetros ESRGAN, FFmpeg, audio, paths) no es sensible y viaja como `--set-env-vars` en texto plano.

### Creación y actualización de secretos

El script `06_secrets_deploy.bat` usa la subrutina `:upsert_secret` que:
1. Escribe el valor en un archivo temporal **sin newline final** usando PowerShell (`[System.IO.File]::WriteAllText` con UTF-8) — Secret Manager almacenaría el `\n` como parte del valor si se usara `echo` o `Set-Content`
2. Si el secreto no existe: `gcloud secrets create --data-file`
3. Si ya existe: `gcloud secrets versions add --data-file` (crea nueva versión)
4. Elimina el archivo temporal

### Acceso desde el contenedor

El Cloud Run Job usa `--set-secrets` para montar los secretos como variables de entorno:

```
--set-secrets="GCP_PROJECT_ID=upscaler-gcp-project-id:latest,
               GCS_BUCKET_INPUT=upscaler-gcs-bucket-input:latest,
               GCS_BUCKET_OUTPUT=upscaler-gcs-bucket-output:latest"
```

Cloud Run resuelve la versión `:latest` en cada ejecución, por lo que actualizar un secreto vía `06_secrets_deploy.bat` se refleja en el siguiente job sin necesidad de redesplegar.

### Permisos

El Service Account `video-upscaler-sa` tiene `roles/secretmanager.secretAccessor` sobre cada secreto individualmente (no a nivel de proyecto), siguiendo el principio de mínimo privilegio.

---

## Desarrollo local

### Con GPU (docker-compose)

Requiere Docker con soporte NVIDIA (nvidia-container-toolkit instalado y Docker configurado con el runtime de NVIDIA).

```bash
# 1. Completar variables en .env
copy .env.example .env
# Editar .env: GCP_PROJECT_ID, GCS_BUCKET_*, VIDEO_NAME, STORAGE_BACKEND=gcs

# 2. Construir imagen y ejecutar
docker compose up --build
```

`docker-compose.yml` reserva 1 GPU NVIDIA y monta `/tmp/upscaler` como volumen para inspeccionar archivos temporales durante el procesamiento.

### Sin GPU (modo local, sin GCS)

Para validar el pipeline end-to-end sin GPU ni GCS:

```ini
# .env
STORAGE_BACKEND=local
ESRGAN_DEVICE=cpu
LOCAL_STORAGE_INPUT_DIR=C:/Videos/input
LOCAL_STORAGE_OUTPUT_DIR=C:/Videos/output
VIDEO_NAME=test_clip.mp4
```

Colocar el video en `LOCAL_STORAGE_INPUT_DIR/test_clip.mp4` y ejecutar:

```bash
docker compose up
```

> El modo CPU es extremadamente lento (~5–10 segundos por frame a 1080p). Usar solo con clips de 5–10 segundos para validar el flujo completo.

### Sin Docker (entorno Python directo)

```bash
# Instalar dependencias
pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu121
pip install wheels/basicsr-1.4.2-py3-none-any.whl
pip install -r requirements.txt

# Ejecutar
python -m src.main
```

### Regenerar el wheel de BasicSR

El wheel `wheels/basicsr-1.4.2-py3-none-any.whl` está commiteado para evitar compilar BasicSR en cada build. Si necesitas una versión diferente:

```bash
git clone https://github.com/xinntao/BasicSR BasicSR
# Parchar setup.py para eliminar dependencias problemáticas y generar wheel
pip wheel BasicSR/ --no-deps -w wheels/
```

---

## Tests

### Ejecución

```bash
# Instalar dependencias de test
pip install -r requirements-test.txt

# Correr todos los tests
python -m pytest tests/ -v

# Con reporte de cobertura
python -m pytest tests/ -v --cov=src --cov-report=term-missing
```

### Cobertura actual: 81 tests en 10 módulos

| Módulo | Qué verifica |
|---|---|
| `test_config.py` | Derivación de paths y blobs GCS desde `video_name`; flags de entorno; validadores pydantic |
| `test_metrics.py` | Registro de timings, acumulación de pasos, context manager `timed_step` |
| `test_exceptions.py` | Jerarquía de herencia; almacenamiento de `context` y `processor_name` en excepciones |
| `test_storage_local.py` | Copia de archivos, manejo de prefijos, creación de directorios de destino |
| `test_storage_gcs.py` | Retry exponencial correcto, backoff 2^n, `StorageError` tras agotar reintentos |
| `test_frame_extractor.py` | Parsing de fracciones de FPS (`30000/1001`), fallback a `VIDEO_OUTPUT_FPS`, detección condicional de audio |
| `test_video_upscaler.py` | Validación temprana del modelo en `__init__` (no en `process`); error claro si `.pth` no existe |
| `test_audio_enhancer.py` | Skip silencioso cuando no hay `audio_raw.aac`; construcción correcta del filtro `af` con parámetros configurados |
| `test_video_assembler.py` | Prioridad de fuentes de audio; FPS heredado de `metrics.source_fps` |
| `test_pipeline.py` | Ordenamiento `build_pipeline` → `download`; limpieza de workspace en bloque `finally` |

### Estrategia de mocking

Las dependencias pesadas no están instaladas en el entorno de test. Se reemplazan con `MagicMock` en `sys.modules` dentro de `tests/conftest.py` **antes** de que cualquier módulo `src.*` sea importado:

```python
# Dependencias reemplazadas con MagicMock
"torch", "torchvision", "cv2", "numpy",
"basicsr", "basicsr.archs", "basicsr.archs.rrdbnet_arch",
"realesrgan", "realesrgan.utils",
"google.cloud.storage", "google.api_core.exceptions"
```

`GoogleAPIError` se reemplaza por una subclase real de `Exception` (no un mock) para que las sentencias `except GoogleAPIError` en los adaptadores de storage funcionen correctamente en los tests de retry.

---

## Observabilidad

### Formato de logs (producción: `LOG_FORMAT=json`)

Cada línea es un objeto JSON independiente compatible con Cloud Logging:

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

En desarrollo (`LOG_FORMAT=console`), structlog usa `ConsoleRenderer` con colores y alineación legible por humanos.

### Evento final `app_done`

Al completar el pipeline (o al fallar), se emite un evento de resumen con todos los tiempos y métricas:

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

Los tiempos de cada paso los registra `metrics.timed_step()`, un context manager que mide con `time.perf_counter()` y actualiza `JobMetrics.steps`.

### Exit codes

| Código | Significado |
|---|---|
| `0` | Job completado exitosamente |
| `1` | Error de dominio (`VideoUpscalerError` y cualquier subclase) |
| `2` | Error inesperado (excepción no manejada) |

Cloud Run marca el task como fallido si el exit code es distinto de `0` y aplica la política de reintentos configurada en `--max-retries`.

---

## Troubleshooting

### `CUDA out of memory` durante upscaling

Reducir `ESRGAN_TILE_SIZE`. El consumo de VRAM escala cuadráticamente con el tamaño del tile:

```ini
ESRGAN_TILE_SIZE=128   # ~4x menos VRAM que 256
ESRGAN_TILE_PAD=10
```

Empezar con `128` y aumentar en incrementos de 64 hasta encontrar el límite estable de la GPU.

### `Modelo no encontrado: /models/RealESRGAN_x2plus.pth`

El `wget` del Dockerfile falló silenciosamente durante el build. Rebuildar la imagen:

```bat
scripts\04_build_push.bat
```

Verificar en los logs de Cloud Build que la línea `wget -q -O /models/RealESRGAN_x2plus.pth` completa sin errores HTTP (403, 404 o timeout).

### Job falla inmediatamente con `ValidationError`

Variable de entorno requerida no configurada o con valor inválido. Revisar que el Cloud Run Job tenga todas las variables del `--set-env-vars`. La más común: `VIDEO_NAME` no inyectado al disparar el job. Siempre usar `scripts\run.bat` que lo inyecta automáticamente vía `--update-env-vars`.

### Frames extraídos: 0

FFmpeg no pudo leer el video. Causas comunes:
- El archivo en GCS está incompleto (upload interrumpido)
- El codec no está soportado por la versión de FFmpeg de la imagen Ubuntu 22.04

Diagnóstico:
```bash
ffprobe -v error -show_entries stream=codec_name,width,height -of json input.mp4
```

### Audio mejorado suena distorsionado o con artefactos

Reducir `AUDIO_DENOISER_STRENGTH`. Valores altos eliminan también señal útil junto con el ruido:

```ini
AUDIO_DENOISER_STRENGTH=3
AUDIO_DENOISER_PATCH_RADIUS=0.001
```

### `spec.template.metadata.annotations: Currently Cloud Run jobs are unable to offer GPU enabled instances with zonal redundancy`

Añadir `--no-gpu-zonal-redundancy` al comando de deploy. Ya incluido en `06_secrets_deploy.bat`. Si se usa `05_deploy_job.bat`, añadirlo manualmente al comando `gcloud beta run jobs`.

### Build de Docker falla en `pip install ./wheels/basicsr...`

El `.dockerignore` puede estar excluyendo el directorio `wheels/`. Verificar que `.dockerignore` tenga:

```
!wheels/
```

(con `!` de inclusión explícita). Sin esta línea, el contexto de build no incluye el wheel.

### Scripts `.bat` terminan sin ejecutar nada (solo muestran el banner)

Síntoma: el script imprime el encabezado y regresa al prompt sin ejecutar ningún paso. Causa: se invocó `gcloud` sin `call`. En Windows, `gcloud` es `gcloud.cmd` — invocar un `.bat/.cmd` sin `call` desde otro `.bat` termina el proceso padre al retornar el hijo.

Todos los scripts de este repositorio ya incluyen `call gcloud` y `call gsutil`. Si se añaden comandos nuevos, siempre usar `call`:

```bat
REM Correcto
call gcloud run jobs execute %JOB_NAME% --region=%GCP_REGION%

REM Incorrecto (el script termina aquí)
gcloud run jobs execute %JOB_NAME% --region=%GCP_REGION%
```
