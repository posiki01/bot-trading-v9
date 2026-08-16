#!/usr/bin/env python3
"""
trading/sniper/sniper_checklist.py (V9.0 - REFACTORIZADO)
Sistema de verificación de condiciones para entrada Sniper.

RESPONSABILIDADES:
- Orquestar la evaluación del sniper
- Coordinar validaciones, modos, SL/TP y scoring
- Registrar resultados y estadísticas

MEJORAS V9.0:
- Separación de responsabilidades en submódulos
- Integración con umbrales centralizados
- Logs más informativos
- Código más limpio y mantenible
"""

import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone

# ============================================================
# IMPORTS DE SUBMÓDULOS
# ============================================================

from .sniper.sniper_validacion import SniperValidador
from .sniper.sniper_modos import DetectorModos, ModoEntrada
from .sniper.sniper_sl_tp import CalculadorSLTP
from .sniper.sniper_scoring import CalculadorScoreSniper
from .sniper.sniper_quality import ValidadorCalidad

logger = logging.getLogger('BotTrading.SniperChecklist')


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class SniperChecklist:
    """
    Sistema de verificación de condiciones para entrada Sniper.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    def __init__(self,
                 pipeline: Any,
                 config: Optional[Any] = None,
                 almacen: Optional[Any] = None,
                 mt5: Optional[Any] = None,
                 noticias: Optional[Any] = None,
                 patron_tracker: Optional[Any] = None,
                 ml_optimizer: Optional[Any] = None,
                 analysis_cache: Optional[Any] = None,
                 gestor_stops: Optional[Any] = None,
                 modo_depuracion: bool = False,
                 modo_backtest: bool = False):
        """
        Inicializa el checklist del sniper.
        
        Args:
            pipeline: Pipeline de oportunidades
            config: Configuración
            almacen: Almacenamiento
            mt5: Conector MT5
            noticias: Sistema de noticias
            patron_tracker: Tracker de patrones
            ml_optimizer: Optimizador ML
            analysis_cache: Caché de análisis
            gestor_stops: Gestor de stops
            modo_depuracion: Modo depuración
            modo_backtest: Modo backtest
        """
        self.pipeline = pipeline
        self.config = config
        self.almacen = almacen
        self.mt5 = mt5
        self.noticias = noticias
        self.patron_tracker = patron_tracker
        self.ml_optimizer = ml_optimizer
        self.analysis_cache = analysis_cache
        self.gestor_stops = gestor_stops
        self.modo_depuracion = modo_depuracion
        self.modo_backtest = modo_backtest
        
        self.logger = logging.getLogger('BotTrading.SniperChecklist')
        
        # Inicializar submódulos
        self.validador = SniperValidador(config, modo_backtest)
        self.detector_modos = DetectorModos(config, modo_backtest)
        self.calculador_sltp = CalculadorSLTP(config, modo_backtest)
        self.calculador_score = CalculadorScoreSniper(config, modo_backtest)
        self.validador_calidad = ValidadorCalidad(config, modo_backtest)
        
        # Estado
        self._stats = {
            'total_evaluaciones': 0,
            'disparos': 0,
            'disparos_por_modo': {},
            'rechazos': {},
            'tiempo_promedio': 0,
        }
        
        self.logger.info(f"🎯 SniperChecklist V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Depuración: {modo_depuracion}")
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def evaluar_sniper_optimizado(self,
                                  simbolo: str,
                                  df_m5: Any,
                                  precio_actual: float,
                                  direccion: str,
                                  estado_pipeline: Any,
                                  analisis_rapido: Any,
                                  analisis_medio: Any,
                                  ejecutar_pesado: bool = True,
                                  contexto_h1: Optional[Dict] = None,
                                  df_m15: Optional[Dict] = None,
                                  info_tick: Optional[Dict] = None,
                                  spread_pips: float = 0.0,
                                  regimen_objeto: Optional[Any] = None,
                                  calidad_horario: str = 'REGULAR',
                                  fecha_vela: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """
        Evaluación SNIPER - Método principal.
        
        Args:
            simbolo: Símbolo
            df_m5: DataFrame M5
            precio_actual: Precio actual
            direccion: Dirección sugerida
            estado_pipeline: Estado del pipeline
            analisis_rapido: Análisis rápido M5
            analisis_medio: Análisis medio M5
            ejecutar_pesado: Ejecutar análisis pesado
            contexto_h1: Contexto H1
            df_m15: Contexto M15
            info_tick: Información de tick
            spread_pips: Spread en pips
            regimen_objeto: Régimen objeto
            calidad_horario: Calidad del horario
            fecha_vela: Fecha de la vela
        
        Returns:
            Datos de la operación o None
        """
        start_time = time.time()
        self._stats['total_evaluaciones'] += 1
        
        # 1. Validaciones básicas
        valido, razon = self.validador.validar_datos_basicos(df_m5, direccion, simbolo)
        if not valido:
            self._registrar_rechazo(simbolo, razon, "BASICO")
            return None
        
        # 2. Validar contexto H1
        valido, razon, ctx = self.validador.validar_contexto_h1(contexto_h1 or {}, direccion, simbolo)
        if not valido:
            self._registrar_rechazo(simbolo, razon, "CONTEXTO")
            return None
        
        regimen_h1 = ctx.get('regimen_h1', 'INCERTO')
        score_h1 = ctx.get('score_h1', 0)
        
        # 3. Validar dirección por régimen
        valido, razon = self.validador.validar_direccion_por_regimen(direccion, regimen_h1)
        if not valido:
            self._registrar_rechazo(simbolo, razon, "REGIMEN")
            return None
        
        # 4. Validar capacidad
        valido, razon = self.validador.validar_capacidad(self.mt5, simbolo, None)
        if not valido:
            self._registrar_rechazo(simbolo, razon, "CAPACIDAD")
            return None
        
        # 5. Validar condiciones rápidas
        if analisis_rapido and not analisis_rapido.pasa_filtro:
            valido, razon = self.validador_calidad.validar_condiciones_rapidas(
                simbolo, analisis_rapido, direccion
            )
            if not valido:
                self._registrar_rechazo(simbolo, razon, "CAPA1")
                return None
        
        # 6. Validar condiciones medias
        if analisis_medio and not analisis_medio.pasa_filtro:
            valido, razon = self.validador_calidad.validar_condiciones_medias(
                simbolo, analisis_medio, direccion
            )
            if not valido:
                self._registrar_rechazo(simbolo, razon, "CAPA2")
                return None
        
        # 7. Calidad extra
        valido, razon = self.validador_calidad.validar_calidad_extra(
            simbolo, analisis_rapido, analisis_medio, direccion, score_h1, fecha_vela
        )
        if not valido:
            self._registrar_rechazo(simbolo, razon, "CALIDAD_EXTRA")
            return None
        
        # 8. Detectar modo
        modo, razon_modo, confluencias, ponderacion = self.detector_modos.detectar(
            simbolo=simbolo,
            df_m5=df_m5,
            precio_actual=precio_actual,
            direccion=direccion,
            analisis_rapido=analisis_rapido,
            analisis_medio=analisis_medio,
            analisis_pesado=None,  # Se podría pasar si está disponible
            contexto_h1=contexto_h1 or {},
            contexto_m15=df_m15
        )
        
        if modo == ModoEntrada.DESCONOCIDO:
            self._registrar_rechazo(simbolo, f"No se detectó modo: {razon_modo}", "MODO")
            return None
        
        # 9. Calcular score M5
        score_m5 = self.calculador_score.calcular_score_m5(
            modo=modo.value,
            analisis_rapido=analisis_rapido,
            analisis_medio=analisis_medio,
            analisis_pesado=None,
            df_m5=df_m5,
            direccion=direccion
        )
        
        # 10. Calcular score final
        score_final = self._calcular_score_final(score_h1, 0, score_m5, regimen_h1)
        
        # 11. Calcular SL/TP
        sl_tp = self.calculador_sltp.calcular(
            simbolo=simbolo,
            entry_price=precio_actual,
            direccion=direccion,
            modo=modo.value,
            analisis_medio=analisis_medio,
            df_m5=df_m5,
            contexto_h1=contexto_h1 or {},
            calidad_horario=calidad_horario
        )
        
        if not sl_tp:
            self._registrar_rechazo(simbolo, "SL/TP inválido", "SLTP")
            return None
        
        # 12. Validar R:R
        if sl_tp.get('rr', 0) < 1.0:
            self._registrar_rechazo(simbolo, f"R:R insuficiente: {sl_tp['rr']:.2f}", "RR")
            return None
        
        # 13. Construir resultado
        resultado = {
            'simbolo': simbolo,
            'direccion': direccion,
            'entry_price': precio_actual,
            'precio': precio_actual,
            'sl_propuesto': sl_tp['sl'],
            'tp_propuesto': sl_tp['tp'],
            'tp2': sl_tp.get('tp2', 0),
            'modo': modo.value,
            'es_sniper': True,
            'score': score_final,
            'score_final': score_final,
            'score_h1': score_h1,
            'score_m5': score_m5,
            'regimen': regimen_h1,
            'calidad_horario': calidad_horario,
            'rr': sl_tp.get('rr', 0),
            'atr_calculado': sl_tp.get('atr', 0.001),
            'atr_medio_calculado': sl_tp.get('atr_medio', 0.001),
            'razon_entrada': razon_modo,
            'confluencias': confluencias,
            'ponderacion_modo': ponderacion,
            'timestamp': time.time(),
        }
        
        # 14. Actualizar estadísticas
        self._stats['disparos'] += 1
        self._stats['disparos_por_modo'][modo.value] = \
            self._stats['disparos_por_modo'].get(modo.value, 0) + 1
        
        elapsed = (time.time() - start_time) * 1000
        self._stats['tiempo_promedio'] = (
            (self._stats['tiempo_promedio'] * (self._stats['disparos'] - 1) + elapsed)
            / self._stats['disparos']
        )
        
        # 15. Log
        self.logger.info(
            f"🎯 {simbolo}: SNIPER DISPARA! | "
            f"Modo: {modo.value} | "
            f"Score: {score_final:.1f} | "
            f"R:R: {sl_tp['rr']:.2f} | "
            f"Régimen: {regimen_h1}"
        )
        
        return resultado

    def set_precarga_modos(self, precarga_modos):
        """
        Inyecta el módulo de precarga de modos.
        
        Args:
            precarga_modos: Instancia de PrecargaModos
        """
        self.precarga_modos = precarga_modos
        self.logger.info("📦 Precarga de modos inyectada en SniperChecklist")
    
    def _calcular_score_final(self, score_h1: float, score_m15: float, score_m5: float, regimen: str) -> float:
        """Calcula score final ponderado."""
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
        score = (score_h1 * p['h1']) + (score_m15 * p['m15']) + (score_m5 * p['m5'])
        
        if self.modo_backtest:
            score = min(100, score * 1.1)
        
        return min(100.0, max(0.0, score))
    
    def _registrar_rechazo(self, simbolo: str, razon: str, paso: str = ""):
        """Registra un rechazo."""
        mensaje = f"❌ {simbolo}: {razon}"
        if paso:
            mensaje += f" [{paso}]"
        self.logger.debug(mensaje)
        
        if simbolo not in self._stats['rechazos']:
            self._stats['rechazos'][simbolo] = {}
        clave = f"{paso}: {razon}" if paso else razon
        self._stats['rechazos'][simbolo][clave] = \
            self._stats['rechazos'][simbolo].get(clave, 0) + 1
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def set_modo_backtest(self, modo: bool = True):
        """Activa modo backtest."""
        self.modo_backtest = modo
        self.validador.modo_backtest = modo
        self.detector_modos.modo_backtest = modo
        self.calculador_sltp.modo_backtest = modo
        self.calculador_score.modo_backtest = modo
        self.validador_calidad.modo_backtest = modo
        self.logger.info(f"🔧 Modo backtest: {'ACTIVADO' if modo else 'DESACTIVADO'}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas."""
        stats = self._stats.copy()
        total = stats['total_evaluaciones']
        if total > 0:
            stats['tasa_disparo'] = stats['disparos'] / total * 100
        else:
            stats['tasa_disparo'] = 0
        return stats


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_sniper_checklist(pipeline: Any,
                            config: Optional[Any] = None,
                            almacen: Optional[Any] = None,
                            mt5: Optional[Any] = None,
                            noticias: Optional[Any] = None,
                            patron_tracker: Optional[Any] = None,
                            ml_optimizer: Optional[Any] = None,
                            analysis_cache: Optional[Any] = None,
                            gestor_stops: Optional[Any] = None,
                            modo_depuracion: bool = False,
                            modo_backtest: bool = False) -> SniperChecklist:
    """
    Crea una instancia de SniperChecklist.
    
    Returns:
        SniperChecklist
    """
    return SniperChecklist(
        pipeline=pipeline,
        config=config,
        almacen=almacen,
        mt5=mt5,
        noticias=noticias,
        patron_tracker=patron_tracker,
        ml_optimizer=ml_optimizer,
        analysis_cache=analysis_cache,
        gestor_stops=gestor_stops,
        modo_depuracion=modo_depuracion,
        modo_backtest=modo_backtest
    )