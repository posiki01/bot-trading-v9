#!/usr/bin/env python3
"""
analysis/ml/ml_persistencia.py (V9.0)
Persistencia de datos ML.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger('BotTrading.ML.Persistencia')


class MLCache:
    """
    Caché y persistencia de datos ML.
    V9.0 - COMPLETO.
    """
    
    def __init__(self, almacen: Optional[Any] = None, base_dir: Path = Path("data")):
        """
        Inicializa la caché ML.
        
        Args:
            almacen: Almacenamiento SQLite (opcional)
            base_dir: Directorio base para archivos
        """
        self.almacen = almacen
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # Rutas de archivos
        self.ruta_pesos = self.base_dir / "ml_weights.json"
        self.ruta_metricas = self.base_dir / "ml_metrics.json"
        self.ruta_metadata = self.base_dir / "ml_metadata.json"
        self.ruta_historial_metricas = self.base_dir / "ml_metrics_history.json"
        self.ruta_historial_pesos = self.base_dir / "ml_weights_history.json"
    
    def cargar_pesos(self) -> Optional[Dict]:
        """Carga pesos desde archivo."""
        # Intentar desde almacenamiento primero
        if self.almacen:
            try:
                config = self.almacen.obtener_configuracion()
                if config and 'ml_weights' in config:
                    return config['ml_weights']
            except Exception:
                pass
        
        # Fallback: archivo JSON
        if not self.ruta_pesos.exists():
            return None
        
        try:
            with open(self.ruta_pesos, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"Error cargando pesos: {e}")
            return None
    
    def guardar_pesos(self, pesos: Dict):
        """Guarda pesos en archivo."""
        # Guardar en almacenamiento
        if self.almacen:
            try:
                config = self.almacen.obtener_configuracion()
                config['ml_weights'] = pesos
                self.almacen.guardar_configuracion(config)
            except Exception:
                pass
        
        # Guardar en archivo
        try:
            with open(self.ruta_pesos, 'w') as f:
                json.dump(pesos, f, indent=2)
        except Exception as e:
            logger.warning(f"Error guardando pesos: {e}")
    
    def cargar_metricas(self) -> Optional[Dict]:
        """Carga métricas desde archivo."""
        if not self.ruta_metricas.exists():
            return None
        
        try:
            with open(self.ruta_metricas, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"Error cargando métricas: {e}")
            return None
    
    def guardar_metricas(self, metricas: Dict):
        """Guarda métricas en archivo."""
        try:
            with open(self.ruta_metricas, 'w') as f:
                json.dump(metricas, f, indent=2)
        except Exception as e:
            logger.warning(f"Error guardando métricas: {e}")
    
    def cargar_metadata(self) -> Optional[Dict]:
        """Carga metadata desde archivo."""
        if not self.ruta_metadata.exists():
            return None
        
        try:
            with open(self.ruta_metadata, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"Error cargando metadata: {e}")
            return None
    
    def guardar_metadata(self, metadata: Dict):
        """Guarda metadata en archivo."""
        try:
            with open(self.ruta_metadata, 'w') as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            logger.warning(f"Error guardando metadata: {e}")
    
    def cargar_historial_metricas(self) -> Optional[list]:
        """Carga historial de métricas."""
        if not self.ruta_historial_metricas.exists():
            return None
        
        try:
            with open(self.ruta_historial_metricas, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"Error cargando historial de métricas: {e}")
            return None
    
    def guardar_historial_metricas(self, historial: list):
        """Guarda historial de métricas."""
        try:
            with open(self.ruta_historial_metricas, 'w') as f:
                json.dump(historial, f, indent=2)
        except Exception as e:
            logger.warning(f"Error guardando historial de métricas: {e}")
    
    def cargar_historial_pesos(self) -> Optional[list]:
        """Carga historial de pesos."""
        if not self.ruta_historial_pesos.exists():
            return None
        
        try:
            with open(self.ruta_historial_pesos, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"Error cargando historial de pesos: {e}")
            return None
    
    def guardar_historial_pesos(self, historial: list):
        """Guarda historial de pesos."""
        try:
            with open(self.ruta_historial_pesos, 'w') as f:
                json.dump(historial, f, indent=2)
        except Exception as e:
            logger.warning(f"Error guardando historial de pesos: {e}")