#!/usr/bin/env python3
"""
analysis/ml/ml_persistencia.py (V9.0)
Persistencia de pesos y métricas del modelo ML.
"""

import json
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger('BotTrading.ML.Persistencia')


class MLPersistencia:
    """
    Gestor de persistencia para el modelo ML.
    V9.0 - INDEPENDIENTE.
    """
    
    # Pesos por defecto
    PESOS_DEFECTO = {
        'w_tecnica': 0.35,
        'w_institucional': 0.45,
        'w_fundamental': 0.20,
        'bias': 0.0,
        'bias_compra': 0.0,
        'bias_venta': 0.0,
    }
    
    def __init__(self, base_dir: Optional[Path] = None, almacen: Optional[Any] = None):
        """
        Inicializa el gestor de persistencia.
        
        Args:
            base_dir: Directorio base para archivos
            almacen: Almacenamiento SQLite (opcional)
        """
        self.base_dir = Path(base_dir) if base_dir else Path("data")
        self.almacen = almacen
        
        # Rutas de archivos
        self.ruta_pesos = self.base_dir / "ml_weights.json"
        self.ruta_historial_metricas = self.base_dir / "ml_metrics_history.json"
        self.ruta_historial_pesos = self.base_dir / "ml_weights_history.json"
        self.ruta_metadata = self.base_dir / "ml_metadata.json"
        
        # Crear directorio
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"📁 MLPersistencia V9.0 inicializado en {self.base_dir}")
    
    # ================================================================
    # PESOS
    # ================================================================
    
    def cargar_pesos(self) -> Dict[str, float]:
        """
        Carga pesos desde archivo.
        
        Returns:
            Diccionario con pesos
        """
        if not self.ruta_pesos.exists():
            logger.debug("No hay pesos guardados, usando valores por defecto")
            return self.PESOS_DEFECTO.copy()
        
        try:
            with open(self.ruta_pesos, 'r', encoding='utf-8') as f:
                pesos = json.load(f)
            
            # Validar que tiene las claves correctas
            for key in self.PESOS_DEFECTO:
                if key not in pesos:
                    pesos[key] = self.PESOS_DEFECTO[key]
            
            logger.debug(f"🧠 Pesos cargados: {pesos}")
            return pesos
            
        except Exception as e:
            logger.warning(f"⚠️ Error cargando pesos: {e}")
            return self.PESOS_DEFECTO.copy()
    
    def guardar_pesos(self, pesos: Dict[str, float]) -> bool:
        """
        Guarda pesos en archivo.
        
        Args:
            pesos: Diccionario con pesos
        
        Returns:
            True si se guardó correctamente
        """
        try:
            # Asegurar que todas las claves existen
            pesos_completos = self.PESOS_DEFECTO.copy()
            pesos_completos.update(pesos)
            
            with open(self.ruta_pesos, 'w', encoding='utf-8') as f:
                json.dump(pesos_completos, f, indent=2)
            
            logger.debug("🧠 Pesos guardados")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error guardando pesos: {e}")
            return False
    
    # ================================================================
    # HISTORIAL
    # ================================================================
    
    def cargar_historial_metricas(self) -> List[Dict]:
        """Carga historial de métricas."""
        if not self.ruta_historial_metricas.exists():
            return []
        
        try:
            with open(self.ruta_historial_metricas, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ Error cargando historial de métricas: {e}")
            return []
    
    def guardar_historial_metricas(self, historial: List[Dict]) -> bool:
        """Guarda historial de métricas."""
        try:
            # Limitar tamaño
            if len(historial) > 2000:
                historial = historial[-2000:]
            
            with open(self.ruta_historial_metricas, 'w', encoding='utf-8') as f:
                json.dump(historial, f, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"❌ Error guardando historial de métricas: {e}")
            return False
    
    def cargar_historial_pesos(self) -> List[Dict]:
        """Carga historial de pesos."""
        if not self.ruta_historial_pesos.exists():
            return []
        
        try:
            with open(self.ruta_historial_pesos, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ Error cargando historial de pesos: {e}")
            return []
    
    def guardar_historial_pesos(self, historial: List[Dict]) -> bool:
        """Guarda historial de pesos."""
        try:
            # Limitar tamaño
            if len(historial) > 2000:
                historial = historial[-2000:]
            
            with open(self.ruta_historial_pesos, 'w', encoding='utf-8') as f:
                json.dump(historial, f, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"❌ Error guardando historial de pesos: {e}")
            return False
    
    # ================================================================
    # METADATA
    # ================================================================
    
    def cargar_metadata(self) -> Dict[str, Any]:
        """Carga metadata del modelo."""
        if not self.ruta_metadata.exists():
            return {}
        
        try:
            with open(self.ruta_metadata, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ Error cargando metadata: {e}")
            return {}
    
    def guardar_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Guarda metadata del modelo."""
        try:
            metadata['version'] = '9.0'
            metadata['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            with open(self.ruta_metadata, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"❌ Error guardando metadata: {e}")
            return False
    
    # ================================================================
    # EXPORTACIÓN
    # ================================================================
    
    def exportar_modelo(self, ruta: Optional[Path] = None) -> bool:
        """
        Exporta todo el estado del modelo.
        
        Args:
            ruta: Ruta del archivo (opcional)
        
        Returns:
            True si se exportó correctamente
        """
        if ruta is None:
            ruta = self.base_dir / f"ml_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            data = {
                'pesos': self.cargar_pesos(),
                'metadata': self.cargar_metadata(),
                'historial_metricas': self.cargar_historial_metricas(),
                'historial_pesos': self.cargar_historial_pesos(),
                'exported_at': datetime.now(timezone.utc).isoformat(),
            }
            
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"📊 Modelo exportado a {ruta}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error exportando modelo: {e}")
            return False
    
    def importar_modelo(self, ruta: Path) -> bool:
        """
        Importa un modelo exportado.
        
        Args:
            ruta: Ruta del archivo
        
        Returns:
            True si se importó correctamente
        """
        try:
            with open(ruta, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'pesos' in data:
                self.guardar_pesos(data['pesos'])
            
            if 'metadata' in data:
                self.guardar_metadata(data['metadata'])
            
            if 'historial_metricas' in data:
                self.guardar_historial_metricas(data['historial_metricas'])
            
            if 'historial_pesos' in data:
                self.guardar_historial_pesos(data['historial_pesos'])
            
            logger.info(f"📥 Modelo importado desde {ruta}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error importando modelo: {e}")
            return False