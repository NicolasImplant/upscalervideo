# Estructura del proyecto — video-upscaler

Pipeline de upscaling de video con IA (Real-ESRGAN) sobre GPU NVIDIA, orquestado como Cloud Run Job. El trigger es Pub/Sub; no hay endpoints HTTP.

---

## Árbol de archivos

```
video-upscaler/
│
├── src/                            # Código fuente principal
│   ├── main.py                     # Entry point: construye storage y lanza el pipeline
│   ├── config.py                   # Settings (pydantic-settings, todas las env vars)
│   ├── pipeline.py                 # VideoPipeline: orquestador, no conoce GCS ni ESRGAN
│   ├── exceptions.py               # Jerarquía de excepciones del dominio
│   ├── metrics.py                  # JobMetrics + timed_step (context manager)
│   ├── logger.py                   # Configura structlog (JSON prod / console dev)
│   │
│   ├── processors/                 # Procesadores del pipeline (ports & adapters)
│   │   ├── port.py                 # ProcessorPort (ABC) + ProcessorResult (dataclass)
│   │   ├── factory.py              # ProcessorFactory: construye la lista de procesadores
│   │   ├── frame_extractor.py      # Extrae frames PNG y audio AAC via FFmpeg/ffprobe
│   │   ├── video_upscaler.py       # Upscalea frames con RealESRGANer (RRDBNet, tile-based)
│   │   ├── audio_enhancer.py       # Denoising anlmdn + equalizer via FFmpeg
│   │   ├── video_assembler.py      # Reensambla frames + audio en MP4 final
│   │   └── __init__.py
│   │
│   └── storage/                    # Adaptadores de almacenamiento
│       ├── port.py                 # StoragePort (ABC): download / upload
│       ├── gcs_adapter.py          # Google Cloud Storage con retry exponencial
│       ├── local_adapter.py        # Copia de archivos local (dev / sin GCS)
│       └── __init__.py
│
├── scripts/                        # Utilidades de desarrollo y build
│   ├── cleanup_basicsr.bat         # Parchea BasicSR/setup.py y genera el wheel (solo si se regenera)
│   ├── setup_project.bat           # Limpia wheels/, genera .gitignore/.dockerignore, valida estructura
│   ├── install.bat                 # Crea directorios locales + instrucciones de pip install
│   └── build.bat                   # Construye la imagen Docker (docker compose build)
│
├── wheels/
│   └── basicsr-1.4.2-py3-none-any.whl   # Wheel pre-compilado de BasicSR (commiteado)
│
├── Dockerfile                      # Imagen: nvidia/cuda 12.1 + Python 3.11 + FFmpeg
├── docker-compose.yml              # GPU reservada, env_file .env
│
├── requirements.txt                # Dependencias unificadas (ver orden de instalación)
│
├── README.md                       # Qué hace, prerrequisitos, cómo ejecutar
├── STRUCTURE.md                    # Este archivo
│
├── .env                            # Variables de entorno locales (no versionar)
├── .env.example                    # Plantilla documentada de todas las env vars
├── .gitignore
└── .dockerignore
```

> **BasicSR/** no está en el repo. El wheel pre-compilado en `wheels/` es suficiente para el build de Docker.
> Para regenerarlo: `git clone https://github.com/xinntao/BasicSR BasicSR && scripts\cleanup_basicsr.bat`

---

## Flujo de ejecución

```
main.py
  └── build_storage()          # GCSStorageAdapter | LocalStorageAdapter
  └── VideoPipeline.run()
        ├── storage.download()                    # GCS → /tmp/upscaler/<video>/input.mp4
        ├── FrameExtractorProcessor.process()     # input.mp4 → frames/*.png + audio_raw.aac
        ├── VideoUpscalerProcessor.process()      # frames/*.png → frames_up/*.png  (ESRGAN)
        ├── AudioEnhancerProcessor.process()      # audio_raw.aac → audio_clean.aac (FFmpeg)
        ├── VideoAssemblerProcessor.process()     # frames_up/ + audio → output_upscaled.mp4
        └── storage.upload()                      # output_upscaled.mp4 → GCS
```

---

## Capas de la arquitectura (Hexagonal)

| Capa | Archivos |
|---|---|
| **Dominio / Núcleo** | `pipeline.py`, `exceptions.py`, `metrics.py` |
| **Configuración** | `config.py`, `.env` |
| **Puertos (interfaces)** | `processors/port.py`, `storage/port.py` |
| **Adaptadores de procesamiento** | `processors/frame_extractor.py`, `video_upscaler.py`, `audio_enhancer.py`, `video_assembler.py` |
| **Adaptadores de almacenamiento** | `storage/gcs_adapter.py`, `storage/local_adapter.py` |
| **Infraestructura** | `Dockerfile`, `docker-compose.yml` |
| **Utilidades de build** | `scripts/`, `wheels/` |

---

## Variables de entorno clave

| Variable | Por defecto | Descripción |
|---|---|---|
| `STORAGE_BACKEND` | `gcs` | `gcs` o `local` |
| `VIDEO_NAME` | — | Nombre del archivo a procesar (ej. `video.mp4`) |
| `VIDEO_TARGET_SCALE` | `2` | Factor de escala: `2` o `4` |
| `VIDEO_TRIM_SECONDS` | `0` | Recortar a los primeros N segundos (`0` = sin recorte, útil para MVP) |
| `ESRGAN_DEVICE` | `cuda` | `cuda` (GPU) o `cpu` |
| `ESRGAN_MODEL_PATH` | `/models/RealESRGAN_x2plus.pth` | Ruta al modelo `.pth` |
| `AUDIO_ENABLE_ENHANCEMENT` | `true` | Activa/desactiva el paso de mejora de audio |
| `APP_ENV` | `production` | `production` o `development` |
| `LOG_FORMAT` | `json` | `json` (prod) o `console` (dev) |

Ver `.env.example` para la lista completa.

---

## Modos de ejecución

```bat
scripts\build.bat   REM docker compose build
docker compose up
```

Para desarrollo local sin GPU: ajusta `ESRGAN_DEVICE=cpu` y `STORAGE_BACKEND=local` en `.env`.
