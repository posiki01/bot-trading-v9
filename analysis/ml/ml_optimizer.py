#!/usr/bin/env python3
"""
analysis/ml/ml_optimizer.py (V2.0 - ORQUESTACIÓN LIMPIA)
Orquestador del ciclo de vida del modelo ML.

RESPONSABILIDAD:
- Recibir operaciones cerradas reales
- Construir dataset → entrenar → validar → persistir
- Detectar drift y forzar reentrenamiento
- Proveer predicciones en tiempo real

NO HACE:
- Ingeniería de features (delega a FeatureExtractor)
- Construcción de dataset (delega a DatasetBuilder)
- Entrenamiento (delega a EntrenadorML)
- Predicción (delega a PredictorML)
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

from .ml_features import FeatureExtractor
from .ml_dataset import DatasetBuilder
from .ml_entrenamiento import EntrenadorML
from .ml_prediccion import PredictorML
from .ml_drift import DriftDetector
from .ml_persistencia import MLCache

logger = logging.getLogger('BotTrading.ML.Optimizer')


# ============================================================
# CONFIGURACIÓN
# ============================================================

MIN_OPS_PARA_ENTRENAR = 30
MIN_OPS_ENTRE_ENTRENAMIENTOS = 20
DIAS_ENTRE_REENTRENOS = 7
HORAS_COOLDOWN = 4


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class MLOptimizer:
    """
    Orquestador del modelo ML.
    Aprende de operaciones REALES del bot.
    """

    def __init__(
        self,
        almacen: Optional[Any] = None,
        notificador: Optional[Any] = None,
        config: Optional[Any] = None,
        modo_backtest: bool = False,
    ):
        self.almacen = almacen
        self.notificador = notificador
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.ML.Optimizer')

        # Componentes
        self._extractor = FeatureExtractor()
        self._dataset = DatasetBuilder(feature_extractor=self._extractor)
        self._entrenador = EntrenadorML(modo_backtest=modo_backtest)
        self._predictor = PredictorML()
        self._drift = DriftDetector()
        self._cache = MLCache(almacen=almacen, base_dir=Path("data"))

        # Estado
        self._entrenando = False
        self._ultima_fecha_entreno: Optional[datetime] = None
        self._ops_desde_ultimo_entreno = 0
        self._ops_buffer: List[Dict[str, Any]] = []

        # Cargar modelo guardado
        self._cargar_modelo_inicial()

        self.logger.info("🧠 MLOptimizer V2.0 inicializado")
        self.logger.info(f"   Modo: {'BACKTEST' if modo_backtest else 'REAL'}")
        self.logger.info(f"   Modelo cargado: {'✅' if self._predictor.tiene_modelo() else '❌'}")

    # ============================================================
    # CICLO PRINCIPAL
    # ============================================================

    def registrar_operacion_cerrada(self, operacion: Dict[str, Any]):
        """
        Registra una operación cerrada para futuros entrenamientos.
        Este es el punto de entrada principal.
        """
        if operacion.get('estado') != 'CERRADA':
            return

        if 'ganancia_neta' not in operacion:
            return

        # Añadir al buffer
        self._ops_buffer.append(operacion)
        self._ops_desde_ultimo_entreno += 1

        # Limitar buffer
        if len(self._ops_buffer) > 1000:
            self._ops_buffer = self._ops_buffer[-1000:]

        # ¿Toca entrenar?
        if self._debe_entrenar():
            self.entrenar()

    def debe_predecir(self) -> bool:
        """Indica si el modelo está listo para predecir."""
        return self._predictor.tiene_modelo()

    def predecir_probabilidad(self, contexto: Dict[str, Any]) -> Optional[float]:
        """
        Predice la probabilidad de que una operación sea ganadora.

        Args:
            contexto: Dict con el contexto de la operación (mismo formato
                      que las operaciones cerradas)

        Returns:
            float en [0, 1] o None si no hay modelo
        """
        if not self._predictor.tiene_modelo():
            return None

        features = self._extractor.extraer(contexto)
        if features is None:
            return None

        return self._predictor.predecir(features)

    # ============================================================
    # ENTRENAMIENTO
    # ============================================================

    def entrenar(self, forzado: bool = False) -> bool:
        """
        Entrena (o reentrena) el modelo.
        """
        if self._entrenando:
            self.logger.debug("⏳ Entrenamiento ya en curso")
            return False

        # Cooldown
        if not forzado and self._ultima_fecha_entreno:
            delta = (datetime.now(timezone.utc) - self._ultima_fecha_entreno).total_seconds() / 3600
            if delta < HORAS_COOLDOWN:
                self.logger.debug(f"⏳ Cooldown activo ({delta:.1f}h < {HORAS_COOLDOWN}h)")
                return False

        try:
            self._entrenando = True
            self.logger.info("🧠 Iniciando entrenamiento...")

            # 1. Recopilar operaciones
            operaciones = self._recopilar_operaciones()
            if len(operaciones) < MIN_OPS_PARA_ENTRENAR and not forzado:
                self.logger.info(f"⚠️ Operaciones insuficientes: {len(operaciones)} < {MIN_OPS_PARA_ENTRENAR}")
                return False

            # 2. Construir dataset
            resultado_dataset = self._dataset.construir(
                operaciones,
                lookback_dias=180,
                balancear=True,
            )
            if resultado_dataset is None:
                self.logger.warning("⚠️ No se pudo construir dataset")
                return False

            X, y, nombres = resultado_dataset

            # 3. Entrenar
            resultado = self._entrenador.ejecutar(X, y, nombres, forzado=forzado)

            if not resultado['exito']:
                self.logger.warning(f"⚠️ Entrenamiento falló: {resultado.get('razon')}")
                return False

            # 4. Guardar modelo
            modelo = resultado['modelo']
            metricas = resultado['metricas']

            self._predictor.set_modelo(modelo, self._extractor)
            self._guardar_modelo(modelo, metricas)

            self._ultima_fecha_entreno = datetime.now(timezone.utc)
            self._ops_desde_ultimo_entreno = 0

            self.logger.info(
                f"✅ Entrenamiento completado | "
                f"AUC={metricas['test'].get('roc_auc', 0):.3f} | "
                f"Acc={metricas['test'].get('accuracy', 0):.3f}"
            )

            # Notificar
            if self.notificador:
                try:
                    self.notificador.enviar(
                        "🧠 MODELO ML ACTUALIZADO",
                        f"n_muestras: {metricas.get('n_muestras', 0)}\n"
                        f"AUC: {metricas['test'].get('roc_auc', 0):.3f}\n"
                        f"Accuracy: {metricas['test'].get('accuracy', 0):.3f}\n"
                        f"Brier: {metricas['test'].get('brier', 0):.3f}",
                        tipo='info',
                    )
                except Exception:
                    pass

            return True

        except Exception as e:
            self.logger.error(f"❌ Error en entrenamiento: {e}", exc_info=True)
            return False
        finally:
            self._entrenando = False

    # ============================================================
    # DRIFT
    # ============================================================

    def evaluar_drift(self) -> bool:
        """Evalúa drift y reentrena si aplica."""
        if not self._predictor.tiene_modelo():
            return False

        operaciones = self._recopilar_operaciones()
        if len(operaciones) < 20:
            return False

        hay_drift = self._drift.detectar(operaciones, self._predictor)

        if hay_drift:
            self.logger.info("🌊 Drift detectado, reentrenando...")
            return self.entrenar(forzado=True)

        return False

    # ============================================================
    # UTILIDADES
    # ============================================================

    def _debe_entrenar(self) -> bool:
        """Determina si es momento de entrenar."""
        # Primera vez
        if self._ultima_fecha_entreno is None:
            return self._ops_desde_ultimo_entreno >= MIN_OPS_PARA_ENTRENAR

        # Por tiempo
        dias = (datetime.now(timezone.utc) - self._ultima_fecha_entreno).days
        if dias >= DIAS_ENTRE_REENTRENOS:
            return True

        # Por volumen
        if self._ops_desde_ultimo_entreno >= MIN_OPS_ENTRE_ENTRENAMIENTOS:
            return True

        return False

    def _recopilar_operaciones(self) -> List[Dict[str, Any]]:
        """Recopila operaciones cerradas del almacén + buffer."""
        ops = list(self._ops_buffer)

        if self.almacen:
            try:
                almacenadas = self.almacen.obtener_operaciones({
                    'estado': 'CERRADA',
                    'limite': 1000,
                    'orden': 'ASC',
                })
                # Deduplicar por ticket
                tickets_vistos = set()
                combinadas = []
                for op in ops + almacenadas:
                    ticket = op.get('ticket')
                    if ticket and ticket in tickets_vistos:
                        continue
                    if ticket:
                        tickets_vistos.add(ticket)
                    combinadas.append(op)
                return combinadas
            except Exception as e:
                self.logger.debug(f"⚠️ Error leyendo almacén: {e}")

        return ops

    def _cargar_modelo_inicial(self):
        """Intenta cargar modelo guardado."""
        try:
            modelo_data = self._cache.cargar_modelo()
            if modelo_data:
                self._predictor.cargar_modelo(modelo_data, self._extractor)
                self._ultima_fecha_entreno = modelo_data.get('fecha')
                self.logger.info(f"📂 Modelo cargado (entrenado: {self._ultima_fecha_entreno})")
        except Exception as e:
            self.logger.debug(f"⚠️ No se pudo cargar modelo: {e}")

    def _guardar_modelo(self, modelo, metricas: Dict):
        """Persiste el modelo."""
        try:
            self._cache.guardar_modelo(modelo, metricas, self._extractor.nombres_features())
        except Exception as e:
            self.logger.warning(f"⚠️ Error guardando modelo: {e}")

    # ============================================================
    # INFO
    # ============================================================

    def get_info(self) -> Dict[str, Any]:
        return {
            'tiene_modelo': self._predictor.tiene_modelo(),
            'ultima_fecha_entreno': self._ultima_fecha_entreno.isoformat() if self._ultima_fecha_entreno else None,
            'ops_desde_ultimo_entreno': self._ops_desde_ultimo_entreno,
            'metricas': self._entrenador.obtener_metricas(),
            'ops_en_buffer': len(self._ops_buffer),
        }


# ============================================================
# FACTORY
# ============================================================

def create_ml_optimizer(
    almacen: Optional[Any] = None,
    notificador: Optional[Any] = None,
    config: Optional[Any] = None,
    modo_backtest: bool = False,
    **kwargs,
) -> MLOptimizer:
    return MLOptimizer(
        almacen=almacen,
        notificador=notificador,
        config=config,
        modo_backtest=modo_backtest,
    )