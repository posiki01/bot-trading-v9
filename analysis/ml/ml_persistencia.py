#!/usr/bin/env python3
"""
analysis/ml/ml_persistencia.py (V2.0 - MODELO PERSISTENTE)
Persistencia del modelo ML con pickle + metadata.

CAMBIOS V2.0:
- ✅ Guarda/carga el MODELO entrenado (no solo pesos)
- ✅ Metadata con métricas y fecha de entrenamiento
- ✅ Compatible con modelos sklearn (HistGradientBoosting, CalibratedClassifierCV)
- ✅ Fallback JSON para compatibilidad con pesos viejos
"""

import json
import pickle
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger('BotTrading.ML.Persistencia')


class MLCache:
    """
    Persistencia del modelo ML y metadata.
    V2.0 - Guarda el modelo completo, no solo pesos.
    """

    MODELO_FILE = "ml_model.pkl"
    METADATA_FILE = "ml_metadata_v2.json"

    def __init__(
        self,
        almacen: Optional[Any] = None,
        base_dir: Path = Path("data"),
    ):
        self.almacen = almacen
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.ruta_modelo = self.base_dir / self.MODELO_FILE
        self.ruta_metadata = self.base_dir / self.METADATA_FILE

    # ============================================================
    # MODELO (pickle)
    # ============================================================

    def guardar_modelo(
        self,
        modelo: Any,
        metricas: Dict[str, Any],
        nombres_features: List[str],
    ) -> bool:
        """
        Guarda el modelo entrenado + metadata.

        Args:
            modelo: Modelo sklearn entrenado
            metricas: Diccionario con métricas del entrenamiento
            nombres_features: Lista de nombres de features en orden

        Returns:
            True si se guardó correctamente
        """
        try:
            # 1. Metadata
            metadata = {
                'fecha': datetime.now(timezone.utc).isoformat(),
                'n_features': len(nombres_features),
                'nombres_features': nombres_features,
                'metricas': metricas,
                'version': '2.0',
            }

            # 2. Guardar metadata primero (atómico)
            temp_meta = self.ruta_metadata.with_suffix('.tmp')
            with open(temp_meta, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, default=str)
            temp_meta.replace(self.ruta_metadata)

            # 3. Guardar modelo con pickle
            temp_modelo = self.ruta_modelo.with_suffix('.tmp')
            with open(temp_modelo, 'wb') as f:
                pickle.dump(modelo, f, protocol=pickle.HIGHEST_PROTOCOL)
            temp_modelo.replace(self.ruta_modelo)

            logger.info(f"💾 Modelo guardado: {self.ruta_modelo}")
            logger.info(f"   Métricas: AUC={metricas.get('test', {}).get('roc_auc', 0):.3f}")

            # 4. Guardar en almacén (opcional, para respaldo)
            if self.almacen:
                try:
                    config = self.almacen.obtener_configuracion()
                    config['ml_metadata_v2'] = metadata
                    self.almacen.guardar_configuracion(config)
                except Exception as e:
                    logger.debug(f"⚠️ No se pudo guardar metadata en SQLite: {e}")

            return True

        except Exception as e:
            logger.error(f"❌ Error guardando modelo: {e}", exc_info=True)
            return False

    def cargar_modelo(self) -> Optional[Dict[str, Any]]:
        """
        Carga el modelo + metadata.

        Returns:
            Dict con {'modelo': ..., 'metadata': ..., 'nombres_features': [...]}
            o None si no existe
        """
        # Verificar que ambos archivos existan
        if not self.ruta_modelo.exists():
            logger.debug("📂 No hay modelo guardado")
            return None

        try:
            # 1. Cargar modelo
            with open(self.ruta_modelo, 'rb') as f:
                modelo = pickle.load(f)

            # 2. Cargar metadata
            metadata = {}
            if self.ruta_metadata.exists():
                with open(self.ruta_metadata, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

            fecha_str = metadata.get('fecha')
            fecha = None
            if fecha_str:
                try:
                    fecha = datetime.fromisoformat(fecha_str)
                except Exception:
                    pass

            logger.info(f"📂 Modelo cargado (entrenado: {fecha_str})")

            return {
                'modelo': modelo,
                'metadata': metadata,
                'nombres_features': metadata.get('nombres_features', []),
                'fecha': fecha,
            }

        except Exception as e:
            logger.error(f"❌ Error cargando modelo: {e}", exc_info=True)
            return None

    def existe_modelo(self) -> bool:
        """Verifica si hay un modelo guardado."""
        return self.ruta_modelo.exists() and self.ruta_metadata.exists()

    def eliminar_modelo(self) -> bool:
        """Elimina el modelo guardado (para reset)."""
        try:
            if self.ruta_modelo.exists():
                self.ruta_modelo.unlink()
            if self.ruta_metadata.exists():
                self.ruta_metadata.unlink()
            logger.info("🗑️ Modelo eliminado")
            return True
        except Exception as e:
            logger.error(f"❌ Error eliminando modelo: {e}")
            return False

    # ============================================================
    # COMPATIBILIDAD CON V1 (pesos)
    # ============================================================

    def cargar_pesos(self) -> Optional[Dict]:
        """Compatibilidad: carga pesos antiguos si existen."""
        ruta = self.base_dir / "ml_weights.json"
        if not ruta.exists():
            return None
        try:
            with open(ruta, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def guardar_pesos(self, pesos: Dict):
        """Compatibilidad: guarda pesos (legacy)."""
        try:
            ruta = self.base_dir / "ml_weights.json"
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(pesos, f, indent=2)
        except Exception as e:
            logger.debug(f"⚠️ Error guardando pesos legacy: {e}")

    def cargar_metricas(self) -> Optional[Dict]:
        """Compatibilidad: carga métricas legacy."""
        ruta = self.base_dir / "ml_metrics.json"
        if not ruta.exists():
            return None
        try:
            with open(ruta, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def guardar_metricas(self, metricas: Dict):
        """Compatibilidad: guarda métricas legacy."""
        try:
            ruta = self.base_dir / "ml_metrics.json"
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(metricas, f, indent=2, default=str)
        except Exception as e:
            logger.debug(f"⚠️ Error guardando métricas legacy: {e}")

    def cargar_metadata(self) -> Optional[Dict]:
        """Compatibilidad: carga metadata legacy."""
        ruta = self.base_dir / "ml_metadata.json"
        if not ruta.exists():
            return None
        try:
            with open(ruta, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def guardar_metadata(self, metadata: Dict):
        """Compatibilidad: guarda metadata legacy."""
        try:
            ruta = self.base_dir / "ml_metadata.json"
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, default=str)
        except Exception as e:
            logger.debug(f"⚠️ Error guardando metadata legacy: {e}")