from __future__ import annotations


class VideoUpscalerError(Exception):
    """Raíz de todas las excepciones del dominio."""

    def __init__(self, message: str, context: dict | None = None) -> None:
        super().__init__(message)
        self.context = context or {}


class ConfigurationError(VideoUpscalerError):
    """Error en configuración o variables de entorno."""


class StorageError(VideoUpscalerError):
    """Error al interactuar con el backend de almacenamiento."""


class StorageDownloadError(StorageError):
    """Fallo al descargar un archivo."""


class StorageUploadError(StorageError):
    """Fallo al subir un archivo."""


class ProcessorError(VideoUpscalerError):
    """Error base de procesadores."""

    def __init__(
        self,
        message: str,
        processor_name: str,
        context: dict | None = None,
    ) -> None:
        super().__init__(message, context)
        self.processor_name = processor_name


class FrameExtractionError(ProcessorError):
    """Fallo al extraer frames con FFmpeg."""


class UpscalingError(ProcessorError):
    """Fallo durante el upscaling con Real-ESRGAN."""


class AudioEnhancementError(ProcessorError):
    """Fallo al procesar el audio."""


class VideoAssemblyError(ProcessorError):
    """Fallo al reensamblar el video final."""


class SubprocessError(VideoUpscalerError):
    """Proceso externo retornó un error."""

    def __init__(
        self,
        message: str,
        returncode: int,
        stderr: str,
        context: dict | None = None,
    ) -> None:
        super().__init__(message, context)
        self.returncode = returncode
        self.stderr = stderr