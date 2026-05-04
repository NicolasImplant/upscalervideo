FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg python3.11 python3.11-dev python3-pip wget curl \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

WORKDIR /app

COPY requirements.txt .
COPY BasicSR/ ./BasicSR/

RUN pip install --upgrade pip && \
    pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu121 && \
    pip install ./BasicSR && \
    pip install -r requirements.txt

# Descargar modelo ESRGAN
RUN mkdir -p /models && \
    wget -q -O /models/RealESRGAN_x2plus.pth \
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"

COPY src/ ./src/

RUN useradd -m -u 1000 appuser && chown -R appuser /app /models
USER appuser

ENTRYPOINT ["python3", "-m", "src.main"]