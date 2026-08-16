#!/usr/bin/env python3
"""
analysis/ml_optimizer.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Motor de Machine Learning para optimización de pesos del Score Engine.

RESPONSABILIDADES:
- Orquestar el entrenamiento del modelo ML
- Gestionar pesos optimizados
- Coordinar Surrogate Trading
- Coordinar Hard Negative Mining
- Evaluar drift y reentrenar

MEJORAS V9.0:
- Separación de responsabilidades
- Logs detallados de entrenamiento
- Integración con umbrales centralizados
- Caché de predicciones
- Métricas de rendimiento del modelo
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
# IMPORTS
# ============================================================

from config.umbrales import Umbrales
from utils.helpers import safe_float
from utils.logger_persistente import LoggerPersistente

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
        # 5. RUTAS DE PERSISTENCIA
        # ============================================================
        
        self.base_dir = Path("data")
        if self.almacen:
            try:
                self.base_dir = Path(self.almacen.directorio_base) if hasattr(self.almacen, 'directorio_base') else Path("data")
            except Exception:
                self.base_dir = Path("data")
        
        self.ruta_pesos = str(self.base_dir / "ml_weights.json")
        self.ruta_historial_metricas = str(self.base_dir / "ml_metrics_history.json")
        self.ruta_historial_pesos = str(self.base_dir / "ml_weights_history.json")
        self.ruta_metadata = str(self.base_dir / "ml_metadata.json")
        
        # ============================================================
        # 6. CARGAR ESTADO
        # ============================================================
        
        self._cargar_pesos()
        self._cargar_historial()
        self._cargar_metadata()
        
        # ============================================================
        # 7. INICIALIZAR SCORE ENGINE
        # ============================================================
        
        self.score_engine = None
        self._inicializar_score_engine()
        
        self.logger.info(f"🧠 MLOptimizer V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Pesos: {self.pesos_optimizados}")
        self.logger.info(f"   Último reentreno: {self.fecha_ultimo_reentreno}")
    
    # ============================================================
    # INICIALIZACIÓN
    # ============================================================
    
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
    
    # ============================================================
    # PERSISTENCIA
    # ============================================================
    
    def _cargar_pesos(self):
        """Carga pesos desde archivo."""
        if not os.path.exists(self.ruta_pesos):
            return
        
        try:
            with open(self.ruta_pesos, 'r') as f:
                pesos = json.load(f)
            
            # Validar que tiene las claves correctas
            for key in self.PESOS_DEFECTO:
                if key not in pesos:
                    pesos[key] = self.PESOS_DEFECTO[key]
            
            self.pesos_optimizados = pesos
            self.logger.info(f"🧠 Pesos ML cargados: {pesos}")
        except Exception as e:
            self.logger.warning(f"⚠️ Error cargando pesos: {e}")
    
    def _guardar_pesos(self):
        """Guarda pesos en archivo."""
        try:
            os.makedirs(os.path.dirname(self.ruta_pesos), exist_ok=True)
            with open(self.ruta_pesos, 'w') as f:
                json.dump(self.pesos_optimizados, f, indent=2)
            self.logger.debug("🧠 Pesos ML guardados")
        except Exception as e:
            self.logger.warning(f"⚠️ Error guardando pesos: {e}")
    
    def _cargar_historial(self):
        """Carga historial de métricas y pesos."""
        # Cargar métricas
        if os.path.exists(self.ruta_historial_metricas):
            try:
                with open(self.ruta_historial_metricas, 'r') as f:
                    self.historial_metricas = json.load(f)
            except Exception as e:
                self.logger.warning(f"⚠️ Error cargando historial de métricas: {e}")
        
        # Cargar historial de pesos
        if os.path.exists(self.ruta_historial_pesos):
            try:
                with open(self.ruta_historial_pesos, 'r') as f:
                    self.historial_pesos = json.load(f)
            except Exception as e:
                self.logger.warning(f"⚠️ Error cargando historial de pesos: {e}")
    
    def _guardar_historial(self):
        """Guarda historial de métricas y pesos."""
        try:
            # Limitar historial
            max_hist = 2000
            if len(self.historial_metricas) > max_hist:
                self.historial_metricas = self.historial_metricas[-max_hist:]
            if len(self.historial_pesos) > max_hist:
                self.historial_pesos = self.historial_pesos[-max_hist:]
            
            os.makedirs(os.path.dirname(self.ruta_historial_metricas), exist_ok=True)
            
            with open(self.ruta_historial_metricas, 'w') as f:
                json.dump(self.historial_metricas, f, indent=2)
            
            with open(self.ruta_historial_pesos, 'w') as f:
                json.dump(self.historial_pesos, f, indent=2)
        except Exception as e:
            self.logger.warning(f"⚠️ Error guardando historial: {e}")
    
    def _cargar_metadata(self):
        """Carga metadata del modelo."""
        if not os.path.exists(self.ruta_metadata):
            return
        
        try:
            with open(self.ruta_metadata, 'r') as f:
                meta = json.load(f)
            
            fecha_corte = meta.get('fecha_corte')
            if fecha_corte:
                try:
                    self.fecha_corte_entrenamiento = datetime.fromisoformat(fecha_corte)
                except:
                    pass
            
            fecha_ultimo = meta.get('fecha_ultimo_reentreno')
            if fecha_ultimo:
                try:
                    self.fecha_ultimo_reentreno = datetime.fromisoformat(fecha_ultimo)
                except:
                    pass
        except Exception as e:
            self.logger.warning(f"⚠️ Error cargando metadata: {e}")
    
    def _guardar_metadata(self):
        """Guarda metadata del modelo."""
        try:
            meta = {
                'fecha_corte': self.fecha_corte_entrenamiento.isoformat() if self.fecha_corte_entrenamiento else None,
                'fecha_ultimo_reentreno': self.fecha_ultimo_reentreno.isoformat() if self.fecha_ultimo_reentreno else None,
                'version': '9.0',
            }
            with open(self.ruta_metadata, 'w') as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            self.logger.warning(f"⚠️ Error guardando metadata: {e}")
    
    # ============================================================
    # ENTRENAMIENTO PRINCIPAL
    # ============================================================
    
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
            from analysis.ml.ml_entrenamiento import EntrenadorML
            
            entrenador = EntrenadorML(
                pesos_defecto=self.PESOS_DEFECTO,
                w_min_floor=self.W_MIN_FLOOR,
                bias_max_abs=self.BIAS_MAX_ABS,
                max_cambio_peso=self.MAX_CAMBIO_PESO_RELATIVO,
                muestras_minimas=self.MUESTRAS_MINIMAS_ENTRENAMIENTO,
                score_engine=self.score_engine,
                modo_backtest=self.modo_backtest
            )
            
            resultado = entrenador.ejecutar(
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
            self._guardar_pesos()
            self._guardar_historial()
            self._guardar_metadata()
            
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
        """
        Prepara datos para entrenamiento.
        
        Args:
            lookback_days: Días a mirar hacia atrás
        
        Returns:
            Lista de registros de entrenamiento
        """
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
    
    # ============================================================
    # SURROGATE TRADING
    # ============================================================
    
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
            
            from analysis.ml.ml_surrogate import SurrogateTrader
            
            trader = SurrogateTrader(
                score_engine=self.score_engine,
                modo_backtest=self.modo_backtest
            )
            
            simulaciones = trader.generar_simulaciones(
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
        """
        Entrena el modelo con datos proporcionados.
        
        Args:
            datos: Datos de entrenamiento
            forzado: Forzar entrenamiento
        
        Returns:
            True si se entrenó correctamente
        """
        if self.esta_entrenando:
            return False
        
        try:
            self.esta_entrenando = True
            
            from analysis.ml.ml_entrenamiento import EntrenadorML
            
            entrenador = EntrenadorML(
                pesos_defecto=self.PESOS_DEFECTO,
                w_min_floor=self.W_MIN_FLOOR,
                bias_max_abs=self.BIAS_MAX_ABS,
                max_cambio_peso=self.MAX_CAMBIO_PESO_RELATIVO,
                muestras_minimas=self.MUESTRAS_MINIMAS_ENTRENAMIENTO,
                score_engine=self.score_engine,
                modo_backtest=self.modo_backtest
            )
            
            resultado = entrenador.ejecutar(
                datos=datos,
                pesos_actuales=self.pesos_optimizados,
                forzado=forzado
            )
            
            if not resultado['exito']:
                self.esta_entrenando = False
                return False
            
            self.pesos_optimizados = resultado['pesos']
            self.fecha_ultimo_reentreno = datetime.now(timezone.utc)
            
            self._guardar_pesos()
            self._guardar_metadata()
            
            if self.score_engine:
                self.score_engine.weights = self.pesos_optimizados
            
            self.esta_entrenando = False
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error entrenando con datos: {e}", exc_info=True)
            self.esta_entrenando = False
            return False
    
    # ============================================================
    # HARD NEGATIVE MINING
    # ============================================================
    
    def entrenar_con_rechazos(self) -> bool:
        """
        Analiza las oportunidades rechazadas y ajusta el bias del modelo.
        
        Returns:
            True si se ajustó correctamente
        """
        if not self.oportunidades_no_tomadas:
            return False
        
        from analysis.ml.ml_mining import HardNegativeMiner
        
        miner = HardNegativeMiner(
            bias_max_abs=self.BIAS_MAX_ABS,
            modo_backtest=self.modo_backtest
        )
        
        resultado = miner.ejecutar(
            oportunidades=self.oportunidades_no_tomadas,
            pesos_actuales=self.pesos_optimizados
        )
        
        if resultado['ajustado']:
            self.pesos_optimizados = resultado['pesos']
            self._guardar_pesos()
            
            if self.score_engine:
                self.score_engine.weights = self.pesos_optimizados
            
            self.logger.info(f"🧠 Hard Negative Mining: bias ajustado +{resultado['ajuste']:.2f}")
            return True
        
        return False
    
    # ============================================================
    # EVALUACIÓN DE DRIFT
    # ============================================================
    
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
        
        # Cooldown (4 horas)
        cooldown_horas = 4
        if self.ultimo_intento_reentreno:
            if (ahora - self.ultimo_intento_reentreno).total_seconds() < cooldown_horas * 3600:
                self.logger.debug(f"⏳ Reentrenamiento en cooldown ({cooldown_horas}h)")
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
            drift_detectado = self._detectar_drift()
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
    
    def _detectar_drift(self) -> bool:
        """Detecta drift en el modelo."""
        # Obtener operaciones recientes
        df_reciente = [op for op in self.historial_operaciones if op.get('estado') == 'CERRADA']
        df_reciente = df_reciente[-15:]  # Últimas 15
        
        if len(df_reciente) < 10:
            return False
        
        # Calcular MSE actual
        mse_actual = self._calcular_mse_reciente(df_reciente)
        
        if mse_actual is None:
            return False
        
        baseline_mse = self.metricas_referencia.get('mse', 100.0)
        
        # Si MSE actual es más del doble del baseline, hay drift
        if mse_actual > (baseline_mse * 2.0):
            self.logger.info(f"📊 Drift detectado (MSE: {mse_actual:.2f} vs {baseline_mse:.2f})")
            return True
        
        return False
    
    def _calcular_mse_reciente(self, operaciones: List[Dict]) -> Optional[float]:
        """Calcula MSE en operaciones recientes."""
        if not operaciones or len(operaciones) < 5:
            return None
        
        try:
            import numpy as np
            
            pesos = self.pesos_optimizados
            preds = []
            reales = []
            
            for op in operaciones:
                # Extraer features
                pts_est = op.get('pts_estructura', 50)
                pts_mom = op.get('pts_momentum', 50)
                pts_conf = op.get('pts_confluencia', 50)
                pts_inst = op.get('pts_institucional', 50)
                
                # Score H1
                score_h1 = (pts_est * 0.35 + pts_mom * 0.30 + 
                           pts_conf * 0.20 + pts_inst * 0.15)
                
                # Score M15 y M5 (simplificado)
                score_m15 = 50
                score_m5 = 50
                regimen = op.get('regimen', 'INCERTO')
                
                # Score final
                score_final = self._calcular_score_final(score_h1, score_m15, score_m5, regimen)
                
                preds.append(score_final)
                reales.append(op.get('ganancia_neta', 0))
            
            if len(preds) < 5:
                return None
            
            # Normalizar reales
            reales_np = np.array(reales)
            reales_norm = (reales_np - reales_np.min()) / (reales_np.max() - reales_np.min() + 0.001) * 100
            
            from sklearn.metrics import mean_squared_error
            return float(mean_squared_error(reales_norm, preds))
            
        except Exception as e:
            self.logger.debug(f"Error calculando MSE: {e}")
            return None
    
    def _calcular_score_final(self, score_h1: float, score_m15: float,
                              score_m5: float, regimen: str) -> float:
        """Calcula score final (simplificado)."""
        pesos = {
            'TREND_ALCISTA_FUERTE': {'h1': 0.55, 'm15': 0.20, 'm5': 0.25},
            'TREND_BAJISTA_FUERTE': {'h1': 0.55, 'm15': 0.20, 'm5': 0.25},
            'TREND_ALCISTA_DEBIL': {'h1': 0.45, 'm15': 0.25, 'm5': 0.30},
            'TREND_BAJISTA_DEBIL': {'h1': 0.45, 'm15': 0.25, 'm5': 0.30},
            'RANGO_AMPLIO': {'h1': 0.30, 'm15': 0.35, 'm5': 0.35},
            'RANGO_APRETADO': {'h1': 0.30, 'm15': 0.35, 'm5': 0.35},
            'CHOP_VOLATIL': {'h1': 0.20, 'm15': 0.30, 'm5': 0.50},
            'BREAKOUT_INMINENTE': {'h1': 0.35, 'm15': 0.25, 'm5': 0.40},
            'INCERTO': {'h1': 0.40, 'm15': 0.30, 'm5': 0.30},
        }
        
        p = pesos.get(regimen, pesos['INCERTO'])
        return (score_h1 * p['h1']) + (score_m15 * p['m15']) + (score_m5 * p['m5'])
    
    # ============================================================
    # PREDICCIÓN
    # ============================================================
    
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
    
    # ============================================================
    # UTILIDADES
    # ============================================================
    
    def obtener_pesos_optimizados(self) -> Dict[str, float]:
        """
        Obtiene los pesos optimizados actuales.
        
        Returns:
            Diccionario con pesos
        """
        return self.pesos_optimizados.copy()
    
    def reset_modelo(self) -> bool:
        """
        Reinicia el modelo a valores de fábrica.
        
        Returns:
            True si se reinició correctamente
        """
        try:
            self.pesos_optimizados = self.PESOS_DEFECTO.copy()
            self.historial_metricas = []
            self.historial_pesos = []
            self.metricas_referencia = {}
            self.fecha_ultimo_reentreno = datetime.now(timezone.utc) - timedelta(days=self.DIAS_ENTRE_REENTRENOS_FORZADOS)
            
            if self.score_engine:
                self.score_engine.weights = self.pesos_optimizados
            
            self._guardar_pesos()
            self._guardar_metadata()
            self.ml_activado = True
            
            self.logger.info("🧠 Modelo ML reiniciado a valores de fábrica")
            
            if self.notificador:
                self.notificador.enviar("🧠 ML RESET", "Modelo reiniciado a valores de fábrica", tipo='info')
            
            return True
        except Exception as e:
            self.logger.error(f"❌ Error reiniciando modelo: {e}")
            return False
    
    def get_metricas(self) -> Dict[str, Any]:
        """
        Obtiene métricas del modelo.
        
        Returns:
            Diccionario con métricas
        """
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
        """
        Activa modo backtest.
        
        Args:
            modo: Modo backtest
        """
        self.modo_backtest = modo
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