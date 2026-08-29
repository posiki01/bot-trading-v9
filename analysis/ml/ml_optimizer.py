#!/usr/bin/env python3
"""
analysis/ml_optimizer.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Motor de Machine Learning para optimización de pesos del Score Engine.

RESPONSABILIDADES:
- Orquestar el entrenamiento del modelo ML
- Gestionar pesos optimizados
- Coordinar Surrogate Trading, Hard Negative Mining y drift
- Proveer predicciones de puntuación

MEJORAS V9.0:
- Separación de responsabilidades en submódulos
- Logs detallados de entrenamiento
- Integración con umbrales centralizados
- Métricas de rendimiento del modelo
- Caché de predicciones
- Soporte para backtest
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import os

# ============================================================
# IMPORTS REFACTORIZADOS
# ============================================================

from config.umbrales import Umbrales
from utils.helpers import safe_float
from utils.logger_persistente import LoggerPersistente

# Submódulos (se importan dinámicamente para evitar dependencias circulares)
from .ml_entrenamiento import EntrenadorML
from .ml_surrogate import SurrogateTrader
from .ml_mining import HardNegativeMiner
from .ml_drift import DriftDetector
from .ml_persistencia import MLCache

logger = logging.getLogger('BotTrading.MLOptimizer')


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class MLOptimizer:
    """
    Optimizador de ML con ventana deslizante, ponderación temporal y aprendizaje por simulación.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    # ============================================================
    # CONFIGURACIÓN
    # ============================================================
    
    PESOS_DEFECTO = {
        'w_tecnica': 0.35,
        'w_institucional': 0.45,
        'w_fundamental': 0.20,
        'bias': 0.0,
        'bias_compra': 0.0,
        'bias_venta': 0.0,
    }
    
    W_MIN_FLOOR = 0.20
    BIAS_MAX_ABS = 15.0
    MAX_CAMBIO_PESO_RELATIVO = 0.35
    MUESTRAS_MINIMAS_ENTRENAMIENTO = 30
    MAX_EDAD_OPERACIONES_DIAS = 90
    DIAS_ENTRE_REENTRENOS_FORZADOS = 7
    COOLDOWN_HORAS = 4
    
    def __init__(self,
                 historial_ops: Optional[List[Dict]] = None,
                 oportunidades_no_tomadas: Optional[List[Dict]] = None,
                 almacen: Optional[Any] = None,
                 notificador: Optional[Any] = None,
                 score_engine_weights: Optional[Dict] = None,
                 config: Optional[Any] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el optimizador ML.
        
        Args:
            historial_ops: Historial de operaciones
            oportunidades_no_tomadas: Oportunidades rechazadas
            almacen: Almacenamiento
            notificador: Sistema de notificaciones
            score_engine_weights: Pesos iniciales
            config: Configuración
            modo_backtest: Modo backtest
        """
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.MLOptimizer')
        
        # ============================================================
        # 1. DATOS
        # ============================================================
        
        self.historial_operaciones = historial_ops or []
        self.oportunidades_no_tomadas = oportunidades_no_tomadas or []
        self.almacen = almacen
        self.notificador = notificador
        
        # ============================================================
        # 2. PESOS
        # ============================================================
        
        self.pesos_optimizados = self.PESOS_DEFECTO.copy()
        if score_engine_weights:
            self.pesos_optimizados.update(score_engine_weights)
        
        # ============================================================
        # 3. ESTADO
        # ============================================================
        
        self.fecha_ultimo_reentreno: Optional[datetime] = None
        self.ultimo_intento_reentreno: Optional[datetime] = None
        self.esta_entrenando = False
        self.ml_activado = True
        
        # ============================================================
        # 4. MÉTRICAS
        # ============================================================
        
        self.metricas_referencia: Dict = {}
        self.historial_metricas: List[Dict] = []
        self.historial_pesos: List[Dict] = []
        
        # ============================================================
        # 5. CACHÉ Y PERSISTENCIA
        # ============================================================
        
        self._cache = MLCache(almacen=almacen, base_dir=Path("data"))
        self._cargar_estado()
        
        # ============================================================
        # 6. INICIALIZAR SCORE ENGINE
        # ============================================================
        
        self.score_engine = None
        self._inicializar_score_engine()
        
        # ============================================================
        # 7. SUBMÓDULOS
        # ============================================================
        
        self._entrenador = EntrenadorML(
            pesos_defecto=self.PESOS_DEFECTO,
            w_min_floor=self.W_MIN_FLOOR,
            bias_max_abs=self.BIAS_MAX_ABS,
            max_cambio_peso=self.MAX_CAMBIO_PESO_RELATIVO,
            muestras_minimas=self.MUESTRAS_MINIMAS_ENTRENAMIENTO,
            score_engine=self.score_engine,
            modo_backtest=self.modo_backtest
        )
        
        self._surrogate = SurrogateTrader(
            score_engine=self.score_engine,
            modo_backtest=self.modo_backtest
        )
        
        self._miner = HardNegativeMiner(
            bias_max_abs=self.BIAS_MAX_ABS,
            modo_backtest=self.modo_backtest
        )
        
        self._drift_detector = DriftDetector(
            metricas_referencia=self.metricas_referencia,
            pesos_optimizados=self.pesos_optimizados,
            score_engine=self.score_engine,
            modo_backtest=self.modo_backtest
        )
        
        self.logger.info(f"🧠 MLOptimizer V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Pesos: {self.pesos_optimizados}")
        self.logger.info(f"   Último reentreno: {self.fecha_ultimo_reentreno}")

    # ================================================================
    # INICIALIZACIÓN
    # ================================================================
    
    def _inicializar_score_engine(self):
        """Inicializa el ScoreEngine con los pesos actuales."""
        try:
            from analysis.scoring import ScoreEngine
            self.score_engine = ScoreEngine(
                config=self.config,
                pesos=self.pesos_optimizados,
                modo_backtest=self.modo_backtest
            )
        except Exception as e:
            self.logger.warning(f"⚠️ Error inicializando ScoreEngine: {e}")
            self.score_engine = None
    
    def _cargar_estado(self):
        """Carga estado desde almacenamiento."""
        # Cargar pesos
        pesos = self._cache.cargar_pesos()
        if pesos:
            self.pesos_optimizados = pesos
        
        # Cargar métricas
        metricas = self._cache.cargar_metricas()
        if metricas:
            self.metricas_referencia = metricas.get('referencia', {})
            self.historial_metricas = metricas.get('historial', [])
            self.historial_pesos = metricas.get('historial_pesos', [])
        
        # Cargar metadata
        meta = self._cache.cargar_metadata()
        if meta:
            if meta.get('fecha_ultimo_reentreno'):
                try:
                    self.fecha_ultimo_reentreno = datetime.fromisoformat(meta['fecha_ultimo_reentreno'])
                except:
                    pass

    # ================================================================
    # ENTRENAMIENTO PRINCIPAL
    # ================================================================
    
    def entrenar_modelo(self, lookback_days: int = 90, forzado: bool = False) -> bool:
        """
        Entrena el modelo con operaciones reales cerradas.
        
        Args:
            lookback_days: Días a mirar hacia atrás
            forzado: Forzar entrenamiento aunque no haya datos suficientes
        
        Returns:
            True si se entrenó correctamente
        """
        if self.modo_backtest:
            self.logger.info("🧪 Modo backtest: saltando entrenamiento")
            return False
        
        if self.esta_entrenando:
            self.logger.debug("⏳ Entrenamiento en progreso")
            return False
        
        try:
            self.esta_entrenando = True
            self.logger.info("🧠 Iniciando entrenamiento del modelo ML...")
            
            # 1. Preparar datos
            datos = self._preparar_datos_entrenamiento(lookback_days)
            
            if not datos:
                self.logger.warning("⚠️ Sin datos suficientes para entrenar")
                self.esta_entrenando = False
                return False
            
            self.logger.info(f"📊 Datos preparados: {len(datos)} registros")
            
            # 2. Ejecutar entrenamiento
            resultado = self._entrenador.ejecutar(
                datos=datos,
                pesos_actuales=self.pesos_optimizados,
                forzado=forzado
            )
            
            if not resultado['exito']:
                self.logger.warning(f"⚠️ Entrenamiento falló: {resultado.get('razon', 'Desconocida')}")
                self.esta_entrenando = False
                return False
            
            # 3. Actualizar pesos
            self.pesos_optimizados = resultado['pesos']
            self.fecha_ultimo_reentreno = datetime.now(timezone.utc)
            
            # 4. Actualizar métricas
            self.metricas_referencia = {
                'r2': resultado.get('r2_test', 0),
                'mse': resultado.get('mse_test', 0),
                'n_muestras': len(datos),
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            self.historial_metricas.append(self.metricas_referencia)
            self.historial_pesos.append({
                **self.pesos_optimizados,
                'timestamp': self.fecha_ultimo_reentreno.isoformat(),
                'n_muestras': len(datos),
                'r2_test': resultado.get('r2_test', 0),
            })
            
            # 5. Persistir
            self._cache.guardar_pesos(self.pesos_optimizados)
            self._cache.guardar_metricas({
                'referencia': self.metricas_referencia,
                'historial': self.historial_metricas,
                'historial_pesos': self.historial_pesos,
            })
            self._cache.guardar_metadata({
                'fecha_ultimo_reentreno': self.fecha_ultimo_reentreno.isoformat(),
            })
            
            # 6. Actualizar ScoreEngine
            if self.score_engine:
                self.score_engine.weights = self.pesos_optimizados
            
            self.logger.info(f"✅ Modelo entrenado exitosamente (R2: {resultado.get('r2_test', 0):.4f})")
            self.logger.info(f"   Pesos: {self.pesos_optimizados}")
            
            self.esta_entrenando = False
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error en entrenamiento: {e}", exc_info=True)
            self.esta_entrenando = False
            return False
    
    def _preparar_datos_entrenamiento(self, lookback_days: int) -> List[Dict]:
        """Prepara datos para entrenamiento."""
        datos = []
        
        # 1. Operaciones cerradas
        for op in self.historial_operaciones:
            if op.get('estado') == 'CERRADA':
                datos.append(op.copy())
        
        # 2. Oportunidades no tomadas (con outcome evaluado)
        for op in self.oportunidades_no_tomadas:
            if op.get('evaluado_outcome'):
                op_c = op.copy()
                if 'timestamp' not in op_c and 'timestamp_propuesta' in op_c:
                    op_c['timestamp'] = op_c['timestamp_propuesta']
                datos.append(op_c)
        
        if not datos:
            return []
        
        # Filtrar por antigüedad
        ahora = datetime.now(timezone.utc)
        fecha_corte = ahora - timedelta(days=lookback_days)
        
        datos_filtrados = []
        for op in datos:
            try:
                ts_str = op.get('timestamp', '2000-01-01T00:00:00')
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                
                if ts > fecha_corte:
                    datos_filtrados.append(op)
            except Exception:
                continue
        
        # Ordenar por fecha
        datos_filtrados.sort(
            key=lambda x: datetime.fromisoformat(x.get('timestamp', '2000-01-01T00:00:00'))
        )
        
        return datos_filtrados
    
    # ================================================================
    # SURROGATE TRADING
    # ================================================================
    
    def entrenar_con_simulaciones(self, mt5_connector: Any, simbolos: List[str],
                                  velas_back: int = 300) -> bool:
        """
        Entrena el modelo con simulaciones de trading en velas históricas.
        
        Args:
            mt5_connector: Conector MT5
            simbolos: Lista de símbolos
            velas_back: Número de velas a analizar
        
        Returns:
            True si se entrenó correctamente
        """
        if self.modo_backtest:
            self.logger.info("🧪 Modo backtest: saltando surrogate trading")
            return False
        
        if not mt5_connector:
            self.logger.warning("⚠️ Sin conector MT5, no se puede hacer Surrogate Trading")
            return False
        
        if self.esta_entrenando:
            self.logger.debug("⏳ Entrenamiento en progreso")
            return False
        
        try:
            self.logger.info(f"🧠 Iniciando Surrogate Trading en {len(simbolos)} símbolos...")
            
            simulaciones = self._surrogate.generar_simulaciones(
                mt5_connector=mt5_connector,
                simbolos=simbolos,
                velas_back=velas_back
            )
            
            if not simulaciones or len(simulaciones) < 50:
                self.logger.warning(f"⚠️ Solo {len(simulaciones) if simulaciones else 0} simulaciones. Necesarias 50.")
                return False
            
            self.logger.info(f"🧠 Generadas {len(simulaciones)} operaciones simuladas")
            
            # Entrenar con simulaciones
            return self.entrenar_modelo_con_datos(simulaciones, forzado=True)
            
        except Exception as e:
            self.logger.error(f"❌ Error en Surrogate Trading: {e}", exc_info=True)
            return False
    
    def entrenar_modelo_con_datos(self, datos: List[Dict], forzado: bool = False) -> bool:
        """Entrena el modelo con datos proporcionados."""
        if self.esta_entrenando:
            return False
        
        try:
            self.esta_entrenando = True
            
            resultado = self._entrenador.ejecutar(
                datos=datos,
                pesos_actuales=self.pesos_optimizados,
                forzado=forzado
            )
            
            if not resultado['exito']:
                self.esta_entrenando = False
                return False
            
            self.pesos_optimizados = resultado['pesos']
            self.fecha_ultimo_reentreno = datetime.now(timezone.utc)
            
            self._cache.guardar_pesos(self.pesos_optimizados)
            self._cache.guardar_metadata({
                'fecha_ultimo_reentreno': self.fecha_ultimo_reentreno.isoformat(),
            })
            
            if self.score_engine:
                self.score_engine.weights = self.pesos_optimizados
            
            self.esta_entrenando = False
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error entrenando con datos: {e}", exc_info=True)
            self.esta_entrenando = False
            return False
    
    # ================================================================
    # HARD NEGATIVE MINING
    # ================================================================
    
    def entrenar_con_rechazos(self) -> bool:
        """
        Analiza las oportunidades rechazadas y ajusta el bias del modelo.
        
        Returns:
            True si se ajustó correctamente
        """
        if not self.oportunidades_no_tomadas:
            return False
        
        resultado = self._miner.ejecutar(
            oportunidades=self.oportunidades_no_tomadas,
            pesos_actuales=self.pesos_optimizados
        )
        
        if resultado['ajustado']:
            self.pesos_optimizados = resultado['pesos']
            self._cache.guardar_pesos(self.pesos_optimizados)
            
            if self.score_engine:
                self.score_engine.weights = self.pesos_optimizados
            
            self.logger.info(f"🧠 Hard Negative Mining: bias ajustado +{resultado['ajuste']:.2f}")
            return True
        
        return False
    
    # ================================================================
    # EVALUACIÓN DE DRIFT
    # ================================================================
    
    def evaluar_drift(self, mt5_connector: Optional[Any] = None,
                      simbolos: Optional[List[str]] = None) -> bool:
        """
        Evalúa drift y fuerza reentrenamiento.
        
        Args:
            mt5_connector: Conector MT5
            simbolos: Lista de símbolos
        
        Returns:
            True si se reentrenó
        """
        if self.modo_backtest:
            return False
        
        ahora = datetime.now(timezone.utc)
        
        # Cooldown
        if self.ultimo_intento_reentreno:
            if (ahora - self.ultimo_intento_reentreno).total_seconds() < self.COOLDOWN_HORAS * 3600:
                self.logger.debug(f"⏳ Reentrenamiento en cooldown ({self.COOLDOWN_HORAS}h)")
                return False
        
        # 1. Reentreno forzado por tiempo
        if self.fecha_ultimo_reentreno:
            dias_transcurridos = (ahora - self.fecha_ultimo_reentreno).days
        else:
            dias_transcurridos = 999
        
        if dias_transcurridos >= self.DIAS_ENTRE_REENTRENOS_FORZADOS:
            self.logger.info(f"🧠 Reentrenamiento forzado por tiempo ({dias_transcurridos} días)")
            self.ultimo_intento_reentreno = ahora
            
            if mt5_connector and simbolos:
                if self.entrenar_con_simulaciones(mt5_connector, simbolos):
                    return True
            
            return self.entrenar_modelo(forzado=True)
        
        # 2. Evaluar drift por métricas
        if self.metricas_referencia and self.historial_operaciones:
            # Actualizar detector con últimos datos
            self._drift_detector.actualizar_metricas(self.metricas_referencia)
            
            drift_detectado = self._drift_detector.detectar(
                operaciones=self.historial_operaciones,
                pesos_actuales=self.pesos_optimizados
            )
            
            if drift_detectado:
                self.logger.info("🧠 Drift detectado, reentrenando...")
                self.ultimo_intento_reentreno = ahora
                
                if mt5_connector and simbolos:
                    if self.entrenar_con_simulaciones(mt5_connector, simbolos):
                        return True
                
                return self.entrenar_modelo(forzado=True)
        
        # 3. Hard Negative Mining (cada 12 horas)
        if not hasattr(self, '_ultimo_rechazo_mining'):
            self._ultimo_rechazo_mining = None
        
        if self._ultimo_rechazo_mining is None or \
           (ahora - self._ultimo_rechazo_mining).total_seconds() > 12 * 3600:
            self.entrenar_con_rechazos()
            self._ultimo_rechazo_mining = ahora
        
        return False
    
    # ================================================================
    # PREDICCIÓN
    # ================================================================
    
    def predecir_puntuacion(self, analisis_raw: Dict, sentimiento_noticias: float,
                            reporte_cot: float, sniper_confirmado: bool = False,
                            regimen: Optional[str] = None,
                            fase: Optional[int] = None) -> float:
        """
        Predice la puntuación usando el ScoreEngine.
        
        Args:
            analisis_raw: Análisis crudo
            sentimiento_noticias: Sentimiento de noticias
            reporte_cot: Reporte COT
            sniper_confirmado: Sniper confirmado
            regimen: Régimen
            fase: Fase
        
        Returns:
            Puntuación predicha
        """
        try:
            if self.score_engine is None:
                return 50.0
            
            # Extraer régimen y fase
            if regimen is None:
                regimen = analisis_raw.get('regimen', 'UNCERTAIN')
            if fase is None:
                fase = analisis_raw.get('fase', 1)
            
            # Calcular score
            score = self.score_engine.calcular_puntuacion_maestra(
                analisis_raw=analisis_raw,
                sentimiento_noticias=sentimiento_noticias,
                reporte_cot=reporte_cot,
                sniper_confirmado=sniper_confirmado,
                regimen=regimen,
                fase=fase
            )
            
            return float(score) if score is not None else 50.0
            
        except Exception as e:
            self.logger.error(f"❌ Error en predicción ML: {e}")
            return 50.0
    
    # ================================================================
    # UTILIDADES
    # ================================================================
    
    def obtener_pesos_optimizados(self) -> Dict[str, float]:
        """Obtiene los pesos optimizados actuales."""
        return self.pesos_optimizados.copy()
    
    def reset_modelo(self) -> bool:
        """Reinicia el modelo a valores de fábrica."""
        try:
            self.pesos_optimizados = self.PESOS_DEFECTO.copy()
            self.historial_metricas = []
            self.historial_pesos = []
            self.metricas_referencia = {}
            self.fecha_ultimo_reentreno = datetime.now(timezone.utc) - timedelta(days=self.DIAS_ENTRE_REENTRENOS_FORZADOS)
            
            if self.score_engine:
                self.score_engine.weights = self.pesos_optimizados
            
            self._cache.guardar_pesos(self.pesos_optimizados)
            self._cache.guardar_metadata({
                'fecha_ultimo_reentreno': self.fecha_ultimo_reentreno.isoformat(),
            })
            self.ml_activado = True
            
            self.logger.info("🧠 Modelo ML reiniciado a valores de fábrica")
            
            if self.notificador:
                self.notificador.enviar("🧠 ML RESET", "Modelo reiniciado a valores de fábrica", tipo='info')
            
            return True
        except Exception as e:
            self.logger.error(f"❌ Error reiniciando modelo: {e}")
            return False
    
    def get_metricas(self) -> Dict[str, Any]:
        """Obtiene métricas del modelo."""
        return {
            'pesos_actuales': self.pesos_optimizados,
            'fecha_ultimo_reentreno': self.fecha_ultimo_reentreno.isoformat() if self.fecha_ultimo_reentreno else None,
            'metricas_referencia': self.metricas_referencia,
            'historial_metricas': self.historial_metricas[-10:],
            'total_entrenamientos': len(self.historial_metricas),
            'ml_activado': self.ml_activado,
            'modo_backtest': self.modo_backtest,
        }
    
    def set_modo_backtest(self, modo: bool = True):
        """Activa modo backtest."""
        self.modo_backtest = modo
        self._entrenador.modo_backtest = modo
        self._surrogate.modo_backtest = modo
        self._miner.modo_backtest = modo
        self._drift_detector.modo_backtest = modo
        self.logger.info(f"🔧 Modo backtest: {'ACTIVADO' if modo else 'DESACTIVADO'}")


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_ml_optimizer(historial_ops: Optional[List[Dict]] = None,
                        oportunidades_no_tomadas: Optional[List[Dict]] = None,
                        almacen: Optional[Any] = None,
                        notificador: Optional[Any] = None,
                        score_engine_weights: Optional[Dict] = None,
                        config: Optional[Any] = None,
                        modo_backtest: bool = False) -> MLOptimizer:
    """
    Crea una instancia de MLOptimizer.
    
    Args:
        historial_ops: Historial de operaciones
        oportunidades_no_tomadas: Oportunidades rechazadas
        almacen: Almacenamiento
        notificador: Sistema de notificaciones
        score_engine_weights: Pesos iniciales
        config: Configuración
        modo_backtest: Modo backtest
    
    Returns:
        MLOptimizer
    """
    return MLOptimizer(
        historial_ops=historial_ops,
        oportunidades_no_tomadas=oportunidades_no_tomadas,
        almacen=almacen,
        notificador=notificador,
        score_engine_weights=score_engine_weights,
        config=config,
        modo_backtest=modo_backtest
    )