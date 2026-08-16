#!/usr/bin/env python3
"""
backtesting/logger_backtest.py - Logger especializado para backtesting
"""

import logging
from datetime import datetime
from pathlib import Path


class BacktestLogger:
    """Logger especializado para backtesting con archivos separados."""
    
    def __init__(self, nombre: str = "backtest", directorio: Path = None):
        self.nombre = nombre
        self.directorio = directorio or Path("logs/backtests")
        self.directorio.mkdir(parents=True, exist_ok=True)
        
        # Crear logger
        self.logger = logging.getLogger(f"Backtest.{nombre}")
        self.logger.setLevel(logging.DEBUG)
        
        # Handler para archivo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archivo = self.directorio / f"{nombre}_{timestamp}.log"
        
        file_handler = logging.FileHandler(archivo, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        # Handler para consola (solo INFO y superior)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # Separadores para archivos de diagnóstico
        self.archivo_errores = self.directorio / f"{nombre}_errores_{timestamp}.log"
        self.archivo_operaciones = self.directorio / f"{nombre}_operaciones_{timestamp}.log"
        self.archivo_rechazos = self.directorio / f"{nombre}_rechazos_{timestamp}.log"
    
    def info(self, msg: str):
        self.logger.info(msg)
    
    def debug(self, msg: str):
        self.logger.debug(msg)
    
    def warning(self, msg: str):
        self.logger.warning(msg)
    
    def error(self, msg: str):
        self.logger.error(msg)
        self._guardar_en_archivo(self.archivo_errores, f"ERROR: {msg}")
    
    def operacion(self, msg: str):
        self.logger.info(f"📊 {msg}")
        self._guardar_en_archivo(self.archivo_operaciones, msg)
    
    def rechazo(self, msg: str):
        self.logger.debug(f"⏭️ {msg}")
        self._guardar_en_archivo(self.archivo_rechazos, msg)
    
    def _guardar_en_archivo(self, archivo: Path, msg: str):
        """Guarda mensaje en archivo específico."""
        try:
            with open(archivo, 'a', encoding='utf-8') as f:
                timestamp = datetime.now().strftime("%H:%M:%S")
                f.write(f"{timestamp} | {msg}\n")
        except Exception:
            pass