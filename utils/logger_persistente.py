#!/usr/bin/env python3
"""
logs/logger_persistente.py (V8.0 - REFACTORIZADO)
Sistema de logs diarios persistentes con rotación y configuración centralizada.

MEJORAS V8.0:
- Integración con Config (nuevos parámetros)
- Formato de fecha con zona horaria
- Niveles de log por módulo
- Contexto de operación (símbolo, operación, etc.)
- Rotación por fecha y tamaño
- Filtro de emojis configurable
- Integración con SQLite (opcional)
"""

import logging
import sys
import os
import threading
import re
from datetime import datetime, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Optional, Dict, Any, Union
import json

# ============================================================
# IMPORTAR CONFIG
# ============================================================

try:
    from config.settings import Config
except ImportError:
    Config = None


# ============================================================
# FORMATTERS
# ============================================================

class ContextFormatter(logging.Formatter):
    """
    Formatter que añade contexto de operación al mensaje.
    Soporta emojis y formato personalizado.
    """
    
    def __init__(self, fmt=None, datefmt=None, style='%', 
                 include_context: bool = True,
                 filter_emojis: bool = False):
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)
        self.include_context = include_context
        self.filter_emojis = filter_emojis
        
        # Mapeo de emojis a texto (si está habilitado)
        self.EMOJI_MAP = {
            '🚀': '[LAUNCH]', '✅': '[OK]', '❌': '[ERROR]', '⚠️': '[WARN]',
            'ℹ️': '[INFO]', '🔄': '[REFRESH]', '📊': '[STATS]', '📈': '[UP]',
            '📉': '[DOWN]', '📁': '[FOLDER]', '📂': '[FOLDER]', '📡': '[SIGNAL]',
            '🔍': '[SEARCH]', '🛡️': '[SHIELD]', '🎯': '[TARGET]', '💾': '[SAVE]',
            '💰': '[MONEY]', '🧠': '[BRAIN]', '🌙': '[MOON]', '📰': '[NEWS]',
            '⚡': '[FLASH]', '📋': '[CLIPBOARD]', '🔔': '[NOTIFY]', '📝': '[NOTE]',
            '📌': '[PIN]', '💡': '[TIP]', '📣': '[ANNOUNCE]', '⚔️': '[CONFLICT]',
            '🏦': '[BANK]', '💹': '[TRADE]', '⏳': '[WAIT]', '⌛': '[TIMEOUT]',
            '🚨': '[ALERT]', '🔥': '[HOT]', '💀': '[DEAD]', '☠️': '[SKULL]',
            '💥': '[EXPLODE]', '🌀': '[CYCLONE]', '🌊': '[WAVE]', '⬆️': '[UP]',
            '⬇️': '[DOWN]', '➡️': '[RIGHT]', '⬅️': '[LEFT]', '🤖': '[BOT]',
        }
        self.DEFAULT_REPLACEMENT = '[ICON]'
        
        if self.filter_emojis:
            self.emoji_pattern = re.compile(
                "["
                "\U0001F600-\U0001F64F"
                "\U0001F300-\U0001F5FF"
                "\U0001F680-\U0001F6FF"
                "\U0001F700-\U0001F77F"
                "\U0001F780-\U0001F7FF"
                "\U0001F800-\U0001F8FF"
                "\U0001F900-\U0001F9FF"
                "\U0001FA00-\U0001FA6F"
                "\U0001FA70-\U0001FAFF"
                "\U00002702-\U000027B0"
                "\U000024C2-\U0001F251"
                "]+",
                flags=re.UNICODE
            )
    
    def format(self, record):
        # Obtener mensaje base
        msg = super().format(record)
        
        # Añadir contexto si existe
        if self.include_context and hasattr(record, 'context'):
            context = getattr(record, 'context')
            if context:
                msg = f"{msg} | {context}"
        
        # Filtrar emojis si está habilitado
        if self.filter_emojis:
            for emoji, text in self.EMOJI_MAP.items():
                if emoji in msg:
                    msg = msg.replace(emoji, text)
            msg = self.emoji_pattern.sub(self.DEFAULT_REPLACEMENT, msg)
        
        return msg


class JsonFormatter(logging.Formatter):
    """
    Formatter que produce logs en formato JSON (para integración con sistemas externos).
    """
    
    def format(self, record):
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'name': record.name,
            'message': record.getMessage(),
        }
        
        if hasattr(record, 'context'):
            log_entry['context'] = getattr(record, 'context')
        
        if record.exc_info:
            import traceback
            log_entry['exception'] = traceback.format_exc()
        
        return json.dumps(log_entry)


# ============================================================
# FILTROS PERSONALIZADOS
# ============================================================

class ModuleLevelFilter(logging.Filter):
    """Filtro que permite configurar niveles por módulo."""
    
    def __init__(self, module_levels: Dict[str, int]):
        self.module_levels = module_levels
    
    def filter(self, record):
        if record.name in self.module_levels:
            return record.levelno >= self.module_levels[record.name]
        return True


class OperationFilter(logging.Filter):
    """Filtro por tipo de operación (trading, sistema, etc.)."""
    
    def __init__(self, allowed_operations: set):
        self.allowed_operations = allowed_operations
    
    def filter(self, record):
        if hasattr(record, 'operation'):
            return record.operation in self.allowed_operations
        return True


# ============================================================
# LOGGER PERSISTENTE PRINCIPAL
# ============================================================

class LoggerPersistente:
    """
    Logger persistente con rotación, contexto y configuración centralizada.
    V8.0: Mejorado con nuevos features.
    
    USO:
        logger = LoggerPersistente()
        logger.info("Mensaje", contexto={"simbolo": "EURUSD", "operacion": "compra"})
    """
    
    _instancia_unica = None
    _lock = threading.RLock()
    
    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instancia_unica is None:
                cls._instancia_unica = super().__new__(cls)
            return cls._instancia_unica
    
    def __init__(self,
                 directorio_logs: Optional[Path] = None,
                 nivel_log: Union[str, int] = 'INFO',
                 nivel_consola: Union[str, int] = 'INFO',
                 max_bytes: int = 10 * 1024 * 1024,
                 backup_count: int = 5,
                 rotation_when: str = 'midnight',
                 rotation_interval: int = 1,
                 use_json: bool = False,
                 filter_emojis_consola: bool = False,
                 module_levels: Optional[Dict[str, int]] = None):
        """
        Inicializa el logger persistente.
        
        Args:
            directorio_logs: Directorio para logs
            nivel_log: Nivel para archivo
            nivel_consola: Nivel para consola
            max_bytes: Tamaño máximo de rotación
            backup_count: Número de backups
            rotation_when: 'midnight', 'H', 'D', etc.
            rotation_interval: Intervalo de rotación
            use_json: Log en formato JSON
            filter_emojis_consola: Filtrar emojis en consola
            module_levels: Niveles por módulo (ej: {'BotTrading.MT5': logging.DEBUG})
        """
        # Evitar reinicialización
        if hasattr(self, '_inicializado'):
            return
        self._inicializado = True
        
        # Directorio de logs
        if directorio_logs is None:
            directorio_logs = Path(__file__).parent.parent / "logs"
        self.directorio_logs = Path(directorio_logs)
        self.directorio_logs.mkdir(parents=True, exist_ok=True)
        
        # Determinar niveles desde Config o parámetros
        if Config is not None:
            nivel_log = getattr(Config, 'LOG_LEVEL', nivel_log)
            nivel_consola = getattr(Config, 'CONSOLE_LOG_LEVEL', nivel_consola)
        
        # Convertir niveles
        if isinstance(nivel_log, str):
            nivel_log = getattr(logging, nivel_log.upper(), logging.INFO)
        if isinstance(nivel_consola, str):
            nivel_consola = getattr(logging, nivel_consola.upper(), logging.INFO)
        
        # Configurar logger raíz
        self.logger = logging.getLogger('BotTrading')
        self.logger.setLevel(min(nivel_log, nivel_consola))
        self.logger.propagate = False
        
        # Limpiar handlers existentes
        self.logger.handlers.clear()
        
        # ===== HANDLER DE ARCHIVO CON ROTACIÓN POR FECHA =====
        archivo_log = self.directorio_logs / "bot.log"
        
        try:
            # Usar TimedRotatingFileHandler para rotación por fecha
            file_handler = TimedRotatingFileHandler(
                str(archivo_log),
                when=rotation_when,
                interval=rotation_interval,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(nivel_log)
            
            # Formatter para archivo (sin emojis, con fecha completa)
            file_formatter = ContextFormatter(
                fmt='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S %Z',
                include_context=True,
                filter_emojis=True  # Archivo sin emojis
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
        except Exception as e:
            # Fallback a RotatingFileHandler
            file_handler = RotatingFileHandler(
                str(archivo_log),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(nivel_log)
            file_formatter = ContextFormatter(
                fmt='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S',
                include_context=True,
                filter_emojis=True
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
        
        # ===== HANDLER DE CONSOLA =====
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(nivel_consola)
        
        # Formatter para consola (con emojis, hora corta)
        console_formatter = ContextFormatter(
            fmt='%(asctime)s | %(levelname)-7s | %(message)s',
            datefmt='%H:%M:%S',
            include_context=True,
            filter_emojis=filter_emojis_consola
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # ===== HANDLER JSON (opcional) =====
        if use_json:
            json_handler = RotatingFileHandler(
                str(self.directorio_logs / "bot.json"),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            json_handler.setLevel(nivel_log)
            json_handler.setFormatter(JsonFormatter())
            self.logger.addHandler(json_handler)
        
        # ===== FILTROS POR MÓDULO =====
        if module_levels:
            self.logger.addFilter(ModuleLevelFilter(module_levels))
        
        # ===== LIMPIEZA DE LOGS ANTIGUOS =====
        self._limpiar_logs_antiguos()
        
        # Mensaje de inicio
        self.logger.info("=" * 60)
        self.logger.info("🚀 LOGGER PERSISTENTE V8.0 INICIADO")
        self.logger.info(f"📁 {self.directorio_logs}")
        self.logger.info(f"📊 LOG LEVEL: {logging.getLevelName(nivel_log)}")
        self.logger.info(f"🖥️ CONSOLE LEVEL: {logging.getLevelName(nivel_consola)}")
        self.logger.info("=" * 60)
    
    def _limpiar_logs_antiguos(self, dias: int = 30):
        """Limpia logs antiguos en un hilo separado."""
        def limpiar():
            try:
                ahora = datetime.now(timezone.utc)
                for archivo in self.directorio_logs.glob("bot.log*"):
                    try:
                        mtime = datetime.fromtimestamp(archivo.stat().st_mtime, tz=timezone.utc)
                        if (ahora - mtime).days > dias:
                            archivo.unlink()
                            self.logger.debug(f"🧹 Log antiguo eliminado: {archivo.name}")
                    except Exception:
                        pass
                # Limpiar JSON logs
                for archivo in self.directorio_logs.glob("bot.json*"):
                    try:
                        mtime = datetime.fromtimestamp(archivo.stat().st_mtime, tz=timezone.utc)
                        if (ahora - mtime).days > dias:
                            archivo.unlink()
                            self.logger.debug(f"🧹 Log JSON antiguo eliminado: {archivo.name}")
                    except Exception:
                        pass
            except Exception:
                pass
        
        threading.Thread(target=limpiar, daemon=True, name="LogCleaner").start()
    
    # ============================================================
    # MÉTODOS DE LOG CON CONTEXTO
    # ============================================================
    
    def _log_with_context(self, level: int, msg: str, 
                          contexto: Optional[Dict[str, Any]] = None,
                          extra: Optional[Dict[str, Any]] = None):
        """Log interno con contexto."""
        extra = extra or {}
        if contexto:
            # Formatear contexto como string
            if isinstance(contexto, dict):
                context_str = " | ".join(f"{k}={v}" for k, v in contexto.items() if v is not None)
            else:
                context_str = str(contexto)
            extra['context'] = context_str
        
        self.logger.log(level, msg, extra=extra)
    
    def info(self, msg: str, contexto: Optional[Dict[str, Any]] = None):
        self._log_with_context(logging.INFO, msg, contexto)
    
    def error(self, msg: str, contexto: Optional[Dict[str, Any]] = None):
        self._log_with_context(logging.ERROR, msg, contexto)
    
    def warning(self, msg: str, contexto: Optional[Dict[str, Any]] = None):
        self._log_with_context(logging.WARNING, msg, contexto)
    
    def debug(self, msg: str, contexto: Optional[Dict[str, Any]] = None):
        self._log_with_context(logging.DEBUG, msg, contexto)
    
    def critical(self, msg: str, contexto: Optional[Dict[str, Any]] = None):
        self._log_with_context(logging.CRITICAL, msg, contexto)
    
    def exception(self, msg: str, contexto: Optional[Dict[str, Any]] = None):
        """Registra un error con traza completa."""
        extra = {}
        if contexto:
            if isinstance(contexto, dict):
                context_str = " | ".join(f"{k}={v}" for k, v in contexto.items() if v is not None)
            else:
                context_str = str(contexto)
            extra['context'] = context_str
        self.logger.exception(msg, extra=extra)
    
    def success(self, msg: str, contexto: Optional[Dict[str, Any]] = None):
        """Alias para mensajes de éxito."""
        self._log_with_context(logging.INFO, f"✅ {msg}", contexto)
    
    def trade(self, msg: str, simbolo: str, direccion: str = "", contexto: Optional[Dict[str, Any]] = None):
        """Log específico para operaciones de trading."""
        ctx = contexto or {}
        ctx['simbolo'] = simbolo
        if direccion:
            ctx['direccion'] = direccion
        self._log_with_context(logging.INFO, f"💹 {msg}", ctx)
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def get_logger(self):
        """Retorna el logger interno."""
        return self.logger
    
    def flush(self):
        """Fuerza el vaciado de todos los handlers."""
        for handler in self.logger.handlers:
            handler.flush()
    
    def set_level(self, nivel: Union[str, int]):
        """Cambia el nivel de log."""
        if isinstance(nivel, str):
            nivel = getattr(logging, nivel.upper(), logging.INFO)
        self.logger.setLevel(nivel)
        for handler in self.logger.handlers:
            handler.setLevel(nivel)


# ============================================================
# FUNCIÓN DE UTILIDAD PARA LOGS RÁPIDOS
# ============================================================

def get_logger() -> LoggerPersistente:
    """Obtiene la instancia singleton del logger."""
    return LoggerPersistente()


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    logger = LoggerPersistente(
        nivel_log='DEBUG',
        filter_emojis_consola=False
    )
    
    # Log simple
    logger.info("Mensaje de prueba")
    
    # Log con contexto
    logger.info("Operación ejecutada", contexto={
        'simbolo': 'EURUSD',
        'direccion': 'COMPRA',
        'entrada': 1.12345,
        'lotes': 0.01
    })
    
    # Log de trading
    logger.trade("Orden ejecutada", simbolo="EURUSD", direccion="COMPRA")
    
    # Log de éxito
    logger.success("Operación completada", contexto={"ticket": 12345})
    
    print("✅ Logs generados en:", logger.directorio_logs)