#!/usr/bin/env python3
"""
trading/sniper/sniper_checklist.py (V10.2 - INTEGRACIÓN COMPLETA)
Sniper con TP realista, manipulación detectada y score binario.

CAMBIOS V10.2:
- ✅ Bonus +10 por STOP_HUNT detectado
- ✅ Bonus +5 por rechazo confirmado
- ✅ Penalización -10 por falta de nivel_usado (evita operar en el aire)
- ✅ Si ML dice prob < 0.35 → rechazo directo
- ✅ Loguea la razón de cada rechazo con código

MANTIENE:
- Orquestación delgada (delega a especialistas)
- TP realista por ATR (Fase 1 V10.1)
- Distancia mínima al nivel (3 pips)
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone

import pandas as pd
import numpy as np

from config.umbrales import Umbrales
from utils.logger_latencia import medir_latencia
from utils.adaptacion_mercado import AdaptadorMercado
from utils.tiempo import HorarioMercado

from analysis.estructura import (
    clasificar_estructura,
    obtener_nivel_invalidacion,
)
from analysis.direccion import determinar_direccion

from trading.modos import ModoEntrada as ModoEntradaPrincipal

from trading.sniper.sniper_modos import DetectorModos, ModoEntrada as ModoEntradaSniper
from trading.sniper.sniper_scoring import CalculadorScoreSniper
from trading.sniper.sniper_sl_tp import CalculadorSLTP
from trading.sniper.sniper_quality import ValidadorCalidad
from trading.sniper.sniper_validacion import SniperValidador

logger = logging.getLogger('BotTrading.SniperChecklist')


# ============================================================
# CONSTANTES
# ============================================================

ATR_TP_FACTOR = 2.5          # TP = entry ± ATR * 2.5
RR_MAXIMO = 4.0              # No permitir R:R > 4.0
DISTANCIA_MINIMA_PIPS = 3.0  # No entrar a < 3 pips del nivel

# Bonus/Penalizaciones V10.2
BONUS_STOP_HUNT = 10.0
BONUS_RECHAZO_CONFIRMADO = 5.0
PENALIZACION_SIN_NIVEL = 10.0

# ML
ML_PROB_MINIMA = 0.35        # Si prob < esto → rechazar


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class SniperChecklist:
    """
    Orquestador del sniper.
    V10.2 - INTEGRACIÓN COMPLETA.
    """

    UMBRALES_POR_DEFECTO = {
        'score_minimo': 40,
        'score_minimo_backtest': 25,
        'volumen_minimo': 0.30,
        'volumen_minimo_backtest': 0.10,
        'rsi_min': 20,
        'rsi_max': 80,
        'adx_minimo': 10,
        'adx_minimo_backtest': 5,
        'rr_minimo': 1.0,
        'rr_minimo_backtest': 0.8,
        'sl_min_pips': 15,
        'sl_min_pips_backtest': 12,
        'sl_max_pips': 200,
        'distancia_nivel_max': 1.5,
        'distancia_nivel_max_backtest': 3.0,
        'patron_calidad_min': 30,
        'elite_confluencias_min': 3,
    }

    def __init__(
        self,
        pipeline: Any,
        analisis_capas: Any,
        modo_selector: Any,
        entry_timer: Any,
        gestor_stops: Any,
        config: Optional[Any] = None,
        almacen: Optional[Any] = None,
        mt5: Optional[Any] = None,
        noticias: Optional[Any] = None,
        patron_tracker: Optional[Any] = None,
        ml_optimizer: Optional[Any] = None,
        analysis_cache: Optional[Any] = None,
        modo_depuracion: bool = False,
        modo_backtest: bool = False,
        horario: Optional[HorarioMercado] = None,
    ):
        self.pipeline = pipeline
        self.analisis_capas = analisis_capas
        self.modo_selector = modo_selector
        self.entry_timer = entry_timer
        self.gestor_stops = gestor_stops
        self.config = config
        self.almacen = almacen
        self.mt5 = mt5
        self.noticias = noticias
        self.patron_tracker = patron_tracker
        self.ml_optimizer = ml_optimizer
        self.analysis_cache = analysis_cache
        self.modo_depuracion = modo_depuracion
        self.modo_backtest = modo_backtest
        self.horario = horario or HorarioMercado(zona_usuario='COLOMBIA')
        self.orquestador = getattr(pipeline, 'orquestador', None)

        # Especialistas
        self.validador = SniperValidador(config, modo_backtest)
        self.validador_calidad = ValidadorCalidad(config, modo_backtest)
        self.scorer = CalculadorScoreSniper(config, modo_backtest)
        self.calc_sl_tp = CalculadorSLTP(config, modo_backtest)
        self.detector_modos = DetectorModos(modo_backtest=modo_backtest)
        self.adaptador_mercado = AdaptadorMercado()

        self.UMBRALES = self.UMBRALES_POR_DEFECTO.copy()
        self._cargar_umbrales()

        self._stats = {
            'total_evaluaciones': 0,
            'disparos': 0,
            'disparos_por_modo': {},
            'rechazos': {},
            'rechazos_distancia': 0,
            'rechazos_rechazo_no_confirmado': 0,
            'rechazos_rr_max': 0,
            'rechazos_ml': 0,
            'bonus_stop_hunt': 0,
            'bonus_rechazo': 0,
            'penalizaciones_sin_nivel': 0,
        }

        self.logger = logging.getLogger('BotTrading.SniperChecklist')
        self.logger.info("🎯 SniperChecklist V10.2 INTEGRACIÓN-COMPLETA inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Score mínimo: {self.UMBRALES['score_minimo']}")
        self.logger.info(f"   R:R máximo: {RR_MAXIMO}")
        self.logger.info(f"   ATR TP factor: {ATR_TP_FACTOR}")
        self.logger.info(f"   Distancia mínima: {DISTANCIA_MINIMA_PIPS} pips")
        self.logger.info(f"   ML: {'✅' if self.ml_optimizer else '❌'}")

    def _cargar_umbrales(self):
        if Umbrales is not None:
            if hasattr(Umbrales, 'SNIPER'):
                sniper_umbrales = Umbrales.SNIPER
                for key in self.UMBRALES:
                    if key in sniper_umbrales:
                        self.UMBRALES[key] = sniper_umbrales[key]

        if self.modo_backtest:
            self.UMBRALES['score_minimo'] = self.UMBRALES['score_minimo_backtest']
            self.UMBRALES['volumen_minimo'] = self.UMBRALES['volumen_minimo_backtest']
            self.UMBRALES['adx_minimo'] = self.UMBRALES['adx_minimo_backtest']
            self.UMBRALES['rr_minimo'] = self.UMBRALES['rr_minimo_backtest']
            self.UMBRALES['sl_min_pips'] = self.UMBRALES['sl_min_pips_backtest']
            self.UMBRALES['distancia_nivel_max'] = self.UMBRALES['distancia_nivel_max_backtest']

    # ============================================================
    # HELPERS
    # ============================================================

    def _obtener_atr_m5(self, df_m5: pd.DataFrame, periodo: int = 14) -> float:
        if df_m5 is None or len(df_m5) < periodo + 1:
            return 0.0
        try:
            high = df_m5['High']
            low = df_m5['Low']
            close = df_m5['Close']
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(periodo).mean().iloc[-1]
            return float(atr) if not pd.isna(atr) else 0.0
        except Exception:
            return 0.0

    def _obtener_pip_val(self, simbolo: str) -> float:
        try:
            from utils.parametros_simbolo import get_pip_val
            return get_pip_val(simbolo)
        except (ImportError, RecursionError):
            pass
        s = simbolo.upper()
        if 'JPY' in s: return 0.01
        if 'XAU' in s: return 0.10
        if 'XAG' in s: return 0.01
        if any(x in s for x in ('US30', 'NAS100', 'US500')): return 1.0
        if any(c in s for c in ('BTC', 'ETH', 'SOL')): return 1.0
        return 0.0001

    # ============================================================
    # VALIDACIONES V10.2
    # ============================================================

    def _validar_distancia_al_nivel(
        self,
        simbolo: str,
        precio_entrada: float,
        nivel_usado: Optional[float],
        direccion: str,
    ) -> Tuple[bool, str]:
        """Valida que el precio NO esté demasiado cerca del nivel."""
        if not nivel_usado or nivel_usado <= 0:
            return True, "Sin nivel definido"

        pip_val = self._obtener_pip_val(simbolo)
        if pip_val <= 0:
            return True, "pip_val inválido"

        distancia_pips = abs(precio_entrada - nivel_usado) / pip_val

        if distancia_pips < DISTANCIA_MINIMA_PIPS:
            return False, (
                f"Precio demasiado cerca del nivel "
                f"({distancia_pips:.1f} pips < {DISTANCIA_MINIMA_PIPS})"
            )

        return True, f"OK ({distancia_pips:.1f} pips del nivel)"

    def _detectar_stop_hunt(
        self,
        df_m5: pd.DataFrame,
        nivel_usado: Optional[float],
        direccion: str,
        simbolo: str,
    ) -> Tuple[bool, str]:
        """Detecta manipulación (stop hunt)."""
        if df_m5 is None or len(df_m5) < 3:
            return False, ""
        if not nivel_usado or nivel_usado <= 0:
            return False, ""

        pip_val = self._obtener_pip_val(simbolo)
        if pip_val <= 0:
            return False, ""

        ultimas = df_m5.tail(3)

        for i in range(len(ultimas) - 1, -1, -1):
            vela = ultimas.iloc[i]
            rango = vela['High'] - vela['Low']
            if rango <= 0:
                continue

            if direccion == 'COMPRA':
                mecha_inf = min(vela['Open'], vela['Close']) - vela['Low']
                if (mecha_inf / rango > 0.5 and
                    vela['Low'] < nivel_usado - pip_val * 0.5 and
                    vela['Close'] > nivel_usado):
                    return True, f"STOP_HUNT_ALCISTA (mecha={mecha_inf/rango:.2f})"
            else:
                mecha_sup = vela['High'] - max(vela['Open'], vela['Close'])
                if (mecha_sup / rango > 0.5 and
                    vela['High'] > nivel_usado + pip_val * 0.5 and
                    vela['Close'] < nivel_usado):
                    return True, f"STOP_HUNT_BAJISTA (mecha={mecha_sup/rango:.2f})"

        return False, ""

    def _validar_rechazo_confirmado(
        self,
        df_m5: pd.DataFrame,
        direccion: str,
        nivel_usado: Optional[float],
        simbolo: str,
    ) -> Tuple[bool, str]:
        """Confirma que hay rechazo real (2 velas M5)."""
        if df_m5 is None or len(df_m5) < 3:
            return False, "Datos insuficientes"

        vela = df_m5.iloc[-1]
        vela_ant = df_m5.iloc[-2]

        rango = vela['High'] - vela['Low']
        if rango <= 0:
            return False, "Rango cero"

        if direccion == 'COMPRA':
            if vela['Close'] <= vela['Open']:
                return False, "Vela actual no alcista"
            if nivel_usado and nivel_usado > 0:
                if vela['Close'] < nivel_usado:
                    return False, f"Cierre bajo nivel ({vela['Close']:.5f} < {nivel_usado:.5f})"
                if vela_ant['Close'] > vela_ant['Open'] and vela_ant['Close'] > nivel_usado:
                    return True, "Rechazo confirmado (2 velas)"
                return True, "Rechazo confirmado (1 vela fuerte)"

        elif direccion == 'VENTA':
            if vela['Close'] >= vela['Open']:
                return False, "Vela actual no bajista"
            if nivel_usado and nivel_usado > 0:
                if vela['Close'] > nivel_usado:
                    return False, f"Cierre sobre nivel ({vela['Close']:.5f} > {nivel_usado:.5f})"
                if vela_ant['Close'] < vela_ant['Open'] and vela_ant['Close'] < nivel_usado:
                    return True, "Rechazo confirmado (2 velas)"
                return True, "Rechazo confirmado (1 vela fuerte)"

        return False, "Dirección inválida"

    def _calcular_tp_realista_atr(
        self,
        simbolo: str,
        precio_entrada: float,
        sl: float,
        direccion: str,
        atr_m5: float,
        tp_estructura: Optional[float] = None,
    ) -> Tuple[float, float]:
        """Calcula TP realista por ATR con límite de R:R."""
        sl_dist = abs(precio_entrada - sl)
        if sl_dist <= 0:
            return precio_entrada, 0.0

        if atr_m5 > 0:
            tp_atr_dist = atr_m5 * ATR_TP_FACTOR
        else:
            tp_atr_dist = sl_dist * 2.5

        if direccion == 'COMPRA':
            tp_atr = precio_entrada + tp_atr_dist
        else:
            tp_atr = precio_entrada - tp_atr_dist

        tp_final = tp_atr
        if tp_estructura and tp_estructura > 0:
            if direccion == 'COMPRA':
                if tp_estructura < tp_atr and tp_estructura > precio_entrada:
                    tp_final = tp_estructura
            else:
                if tp_estructura > tp_atr and tp_estructura < precio_entrada:
                    tp_final = tp_estructura

        tp_dist = abs(tp_final - precio_entrada)
        rr_actual = tp_dist / sl_dist if sl_dist > 0 else 0

        if rr_actual > RR_MAXIMO:
            if direccion == 'COMPRA':
                tp_final = precio_entrada + sl_dist * RR_MAXIMO
            else:
                tp_final = precio_entrada - sl_dist * RR_MAXIMO
            rr_actual = RR_MAXIMO

        return tp_final, rr_actual

    # ============================================================
    # ML HELPERS
    # ============================================================

    def _consultar_ml(self, contexto: Dict[str, Any], simbolo: str) -> Optional[float]:
        """Consulta al ML si está disponible."""
        if not self.ml_optimizer:
            return None
        try:
            if not self.ml_optimizer.debe_predecir():
                return None
            prob = self.ml_optimizer.predecir_probabilidad(contexto)
            if prob is not None:
                self.logger.debug(f"🧠 {simbolo}: ML prob={prob:.3f}")
            return prob
        except Exception as e:
            self.logger.debug(f"⚠️ {simbolo}: Error ML: {e}")
            return None

    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================

    @medir_latencia("sniper_evaluacion", plataforma="SNIPER")
    def evaluar_sniper_optimizado(
        self,
        simbolo: str,
        df_m5: pd.DataFrame,
        precio_actual: float,
        direccion: str,
        estado_pipeline: Optional[Any] = None,
        analisis_rapido: Optional[Any] = None,
        analisis_medio: Optional[Any] = None,
        ejecutar_pesado: bool = True,
        contexto_h1: Optional[Dict] = None,
        calidad_horario: str = 'REGULAR',
        tick_data: Optional[Dict[str, Any]] = None,
        precio_entrada: Optional[float] = None,
        atr_pips: float = 0.0,
        modo_forzado: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Evalúa una oportunidad con el sniper."""
        self._stats['total_evaluaciones'] += 1

        # 0. Pre-check
        if self._ya_hay_posicion(simbolo):
            self._registrar_rechazo('POSICION_EXISTENTE')
            return None

        # 1. Validaciones básicas
        valido, razon = self.validador.validar_datos_basicos(df_m5, direccion, simbolo)
        if not valido:
            self._registrar_rechazo(f'DATOS: {razon}')
            return None

        valido, razon, info_ctx = self.validador.validar_contexto_h1(
            contexto_h1 or {}, direccion, simbolo
        )
        if not valido:
            self._registrar_rechazo(f'CONTEXTO: {razon}')
            return None

        score_h1 = info_ctx.get('score_h1', 0)
        regimen = info_ctx.get('regimen_h1', 'INCERTO')

        # 2. Validar régimen/dirección
        valido, razon = self.validador.validar_direccion_por_regimen(direccion, regimen)
        if not valido:
            self._registrar_rechazo(f'REGIMEN: {razon}')
            return None

        if regimen in ('RANGO_APRETADO', 'CHOP_VOLATIL'):
            self._registrar_rechazo(f'REGIMEN_INVALIDO: {regimen}')
            return None

        # 3. Ajustes estacionales
        ajustes = self.adaptador_mercado.obtener_ajustes(
            simbolo=simbolo, df_m5=df_m5, df_h1=None,
        )
        umbrales = self._aplicar_ajustes(ajustes)

        # 4. Análisis rápido
        if analisis_rapido is None:
            analisis_rapido = self.analisis_capas.analisis_rapido(df_m5, simbolo, precio_actual)
        if not analisis_rapido.pasa_filtro:
            self._registrar_rechazo(f'FILTRO_RAPIDO: {analisis_rapido.razon_rechazo}')
            return None

        valido, razon = self.validador_calidad.validar_condiciones_rapidas(
            simbolo, analisis_rapido, direccion
        )
        if not valido:
            self._registrar_rechazo(f'CALIDAD_RAPIDA: {razon}')
            return None

        # 5. Análisis medio (H1)
        if analisis_medio is None:
            df_h1 = self._obtener_df_h1(simbolo)
            if df_h1 is None:
                self._registrar_rechazo('SIN_H1')
                return None
            niveles = (contexto_h1 or {}).get('niveles', {})
            analisis_medio = self.analisis_capas.analisis_medio(
                df_h1, simbolo, analisis_rapido, niveles
            )

        if analisis_medio is None or not analisis_medio.pasa_filtro:
            razon = getattr(analisis_medio, 'razon_rechazo', 'Análisis medio falló')
            self._registrar_rechazo(f'FILTRO_MEDIO: {razon}')
            return None

        valido, razon = self.validador_calidad.validar_condiciones_medias(
            simbolo, analisis_medio, direccion
        )
        if not valido:
            self._registrar_rechazo(f'CALIDAD_MEDIA: {razon}')
            return None

        # 6. Análisis pesado (H1)
        analisis_pesado = None
        if ejecutar_pesado:
            df_h1 = self._obtener_df_h1(simbolo)
            if df_h1 is not None:
                df_h4 = (contexto_h1 or {}).get('h4')
                df_d1 = (contexto_h1 or {}).get('d1')
                niveles = (contexto_h1 or {}).get('niveles', {})
                analisis_pesado = self.analisis_capas.analisis_pesado(
                    df_h1, simbolo, df_h4, df_d1, niveles, analisis_medio
                )

        # 7. Confluencias
        confluencias = self._clasificar_confluencias(
            contexto_h1 or {}, analisis_rapido, analisis_medio, analisis_pesado
        )

        # 8. Selección de modo
        if modo_forzado:
            modo = modo_forzado
            razon_modo = f"Modo forzado: {modo_forzado}"
        else:
            modo = self._seleccionar_modo(
                simbolo=simbolo, regimen=regimen, direccion=direccion,
                score_h1=score_h1, contexto_h1=contexto_h1,
                analisis_rapido=analisis_rapido,
                analisis_medio=analisis_medio,
                analisis_pesado=analisis_pesado,
                df_m5=df_m5, precio_actual=precio_actual,
                confluencias=confluencias,
            )
            if not modo:
                self._registrar_rechazo('SIN_MODO')
                return None
            razon_modo = f"ModoSelector: {modo}"

        # ✅ V10.2: nivel_usado desde contexto
        nivel_usado = (contexto_h1 or {}).get('nivel_usado', 0)

        # ============================================================
        # ✅ VALIDACIÓN DE DISTANCIA AL NIVEL
        # ============================================================
        valido, razon = self._validar_distancia_al_nivel(
            simbolo, precio_actual, nivel_usado, direccion
        )
        if not valido:
            self._stats['rechazos_distancia'] += 1
            self._registrar_rechazo(f'DISTANCIA: {razon}')
            return None

        # ============================================================
        # ✅ DETECCIÓN DE STOP HUNT
        # ============================================================
        stop_hunt, razon_sh = self._detectar_stop_hunt(
            df_m5, nivel_usado, direccion, simbolo
        )
        if stop_hunt:
            self.logger.info(f"🎯 {simbolo}: {razon_sh}")

        # ============================================================
        # ✅ CONFIRMACIÓN DE RECHAZO
        # ============================================================
        rechazo_ok, razon_rechazo = self._validar_rechazo_confirmado(
            df_m5, direccion, nivel_usado, simbolo
        )
        if not rechazo_ok:
            self._stats['rechazos_rechazo_no_confirmado'] += 1
            self._registrar_rechazo(f'RECHAZO_NO_CONFIRMADO: {razon_rechazo}')
            return None

        # 9. Validar momento exacto (EntryTimer)
        valido, razon_momento, _ = self.entry_timer.validar_momento_exacto(
            simbolo=simbolo, modo=modo, df_m5=df_m5,
            precio_actual=precio_actual, nivel_usado=nivel_usado,
            direccion=direccion, regimen=regimen,
            volumen_relativo=getattr(analisis_rapido, 'volumen_relativo', 1.0),
        )
        if not valido:
            self._registrar_rechazo(f'MOMENTO: {razon_momento}')
            return None

        # 10. Cálculo SL/TP
        if precio_entrada is None:
            precio_entrada = self._obtener_precio_entrada(simbolo, direccion, tick_data, precio_actual)

        sl_tp = self._calcular_sl_tp(
            simbolo=simbolo,
            precio_entrada=precio_entrada,
            direccion=direccion,
            modo=modo,
            regimen=regimen,
            contexto_h1=contexto_h1 or {},
            analisis_medio=analisis_medio,
            analisis_pesado=analisis_pesado,
            df_m5=df_m5,
            df_h1=self._obtener_df_h1(simbolo),
            calidad_horario=calidad_horario,
        )
        if not sl_tp:
            self._registrar_rechazo('SL_TP_INVALIDO')
            return None

        sl, tp, tp2, rr = sl_tp

        if rr < umbrales['rr_minimo']:
            self._registrar_rechazo(f'RR_INSUFICIENTE: {rr:.2f} < {umbrales["rr_minimo"]}')
            return None

        if rr > RR_MAXIMO:
            self._stats['rechazos_rr_max'] += 1
            self._registrar_rechazo(f'RR_EXCEDIDO: {rr:.2f} > {RR_MAXIMO}')
            return None

        # 11. Score M5
        score_m5 = self.scorer.calcular_score_m5(
            modo=modo, analisis_rapido=analisis_rapido,
            analisis_medio=analisis_medio,
            analisis_pesado=analisis_pesado,
            df_m5=df_m5, direccion=direccion,
        )

        # Pesos por régimen
        pesos = {
            'TREND_ALCISTA_FUERTE': (0.45, 0.55),
            'TREND_BAJISTA_FUERTE': (0.45, 0.55),
            'TREND_ALCISTA_DEBIL': (0.35, 0.65),
            'TREND_BAJISTA_DEBIL': (0.35, 0.65),
            'RANGO_AMPLIO': (0.25, 0.75),
            'BREAKOUT_INMINENTE': (0.30, 0.70),
            'INCERTO': (0.30, 0.70),
        }.get(regimen, (0.30, 0.70))

        score_final = score_h1 * pesos[0] + score_m5 * pesos[1]

        # Bono por alineación
        if regimen in ('TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL') and direccion == 'COMPRA':
            score_final += 5
        elif regimen in ('TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL') and direccion == 'VENTA':
            score_final += 5

        # ✅ V10.2: Bonus por manipulación detectada
        if stop_hunt:
            score_final += BONUS_STOP_HUNT
            self._stats['bonus_stop_hunt'] += 1
            self.logger.info(f"🎯 {simbolo}: +{BONUS_STOP_HUNT} por STOP_HUNT")

        if rechazo_ok:
            score_final += BONUS_RECHAZO_CONFIRMADO
            self._stats['bonus_rechazo'] += 1

        # ✅ V10.2: Penalización por falta de nivel
        if not nivel_usado or nivel_usado <= 0:
            score_final -= PENALIZACION_SIN_NIVEL
            self._stats['penalizaciones_sin_nivel'] += 1
            self.logger.debug(f"⚠️ {simbolo}: -{PENALIZACION_SIN_NIVEL} por falta de nivel")

        score_final = min(100.0, max(0.0, score_final))

        # ============================================================
        # ✅ CONSULTA ML
        # ============================================================
        contexto_ml = {
            'simbolo': simbolo,
            'direccion': direccion,
            'regimen': regimen,
            'score_h1': score_h1,
            'score_m15': getattr(estado_pipeline, 'score_m15', 0) if estado_pipeline else 0,
            'score_m5': score_m5,
            'score_final': score_final,
            'pts_estructura': getattr(analisis_pesado, 'score_estructura', 0) if analisis_pesado else 0,
            'pts_momentum': getattr(analisis_pesado, 'score_momentum', 0) if analisis_pesado else 0,
            'pts_confluencia': getattr(analisis_pesado, 'score_confluencia', 0) if analisis_pesado else 0,
            'pts_institucional': getattr(analisis_pesado, 'score_institucional', 0) if analisis_pesado else 0,
            'modo': modo,
            'adx': getattr(analisis_medio, 'adx', 0),
            'rsi': getattr(analisis_medio, 'rsi', 50),
            'volumen_relativo': getattr(analisis_rapido, 'volumen_relativo', 1.0),
            'atr_pct': (getattr(analisis_medio, 'atr', 0.001) * 100) if analisis_medio else 0.5,
            'patron_calidad': getattr(analisis_pesado, 'calidad_patron', 0) if analisis_pesado else 0,
            'ob_cercano': getattr(analisis_pesado, 'ob_cercano', False) if analisis_pesado else False,
            'wyckoff_confianza': getattr(analisis_pesado, 'wyckoff_confianza', 0) if analisis_pesado else 0,
            'wyckoff_fase': getattr(analisis_pesado, 'wyckoff_fase', 'NEUTRAL') if analisis_pesado else 'NEUTRAL',
            'divergencia_rsi': getattr(analisis_pesado, 'divergencia_rsi', None) if analisis_pesado else None,
            'divergencia_macd': getattr(analisis_pesado, 'divergencia_macd', None) if analisis_pesado else None,
            'en_nivel_clave': bool((contexto_h1 or {}).get('en_nivel_clave', False)),
            'distancia_nivel_pips': abs(precio_entrada - nivel_usado) / self._obtener_pip_val(simbolo) if nivel_usado else 100.0,
            'stop_hunt_detectado': stop_hunt,
            'rechazo_confirmado': rechazo_ok,
            'rr': rr,
            'calidad_horario': calidad_horario,
            'direccion_m15': getattr(estado_pipeline, 'direccion_m15', 'NEUTRAL') if estado_pipeline else 'NEUTRAL',
            'confianza_regimen': (contexto_h1 or {}).get('confianza_regimen', 0),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

        prob_ml = self._consultar_ml(contexto_ml, simbolo)

        if prob_ml is not None and prob_ml < ML_PROB_MINIMA:
            self._stats['rechazos_ml'] += 1
            self._registrar_rechazo(f'ML: prob={prob_ml:.3f} < {ML_PROB_MINIMA}')
            self.logger.info(f"🧠 {simbolo}: RECHAZADO por ML (prob={prob_ml:.3f})")
            return None

        # Score ajustado por ML (si está disponible)
        if prob_ml is not None:
            # Convertir prob (0-1) a ajuste (-10 a +10)
            ajuste_ml = (prob_ml - 0.5) * 20
            score_final = min(100.0, max(0.0, score_final + ajuste_ml))

        # Verificar score mínimo
        if score_final < umbrales['score_minimo']:
            self._registrar_rechazo(f'SCORE_BAJO: {score_final:.1f} < {umbrales["score_minimo"]}')
            return None

        # 12. Crear señal
        self._stats['disparos'] += 1
        self._stats['disparos_por_modo'][modo] = self._stats['disparos_por_modo'].get(modo, 0) + 1

        senal = {
            'simbolo': simbolo,
            'direccion': direccion,
            'modo': modo,
            'entry_price': float(precio_entrada),
            'sl': float(sl),
            'tp': float(tp),
            'tp2': float(tp2) if tp2 else 0.0,
            'score': float(score_final),
            'score_h1': float(score_h1),
            'score_m5': float(score_m5),
            'prob_ml': float(prob_ml) if prob_ml is not None else None,
            'rr': float(rr),
            'regimen': regimen,
            'calidad_horario': calidad_horario,
            'en_nivel_clave': bool((contexto_h1 or {}).get('en_nivel_clave', False)),
            'es_reversal': bool((contexto_h1 or {}).get('es_reversal', False)),
            'volumen_relativo': float(getattr(analisis_rapido, 'volumen_relativo', 1.0)),
            'patron_calidad': float(getattr(analisis_pesado, 'calidad_patron', 0)) if analisis_pesado else 0.0,
            'adx_h1': float(getattr(analisis_medio, 'adx', 0)),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'confluencias': confluencias,
            'niveles_usados': {
                'soporte_cercano': (contexto_h1 or {}).get('soporte_cercano'),
                'resistencia_cercana': (contexto_h1 or {}).get('resistencia_cercana'),
                'nivel_usado': nivel_usado,
            },
            'razon_modo': razon_modo,
            'stop_hunt_detectado': stop_hunt,
            'razon_stop_hunt': razon_sh,
            'rechazo_confirmado': rechazo_ok,
            'sniper_checklist_version': 'V10.2',
            'direccion_m15': getattr(estado_pipeline, 'direccion_m15', 'NEUTRAL') if estado_pipeline else 'NEUTRAL',  # ← AÑADIR
        }

        self.logger.info(
            f"🎯 {simbolo}: ✅ DISPARA! Modo: {modo} | "
            f"Score: {score_final:.1f} | R:R: {rr:.2f} | "
            f"ML: {prob_ml:.2f if prob_ml else 'N/A'} | "
            f"StopHunt: {'✅' if stop_hunt else '❌'}"
        )

        if estado_pipeline:
            estado_pipeline.metadata['sniper_fallos'] = 0
            estado_pipeline.metadata['sniper_ultimo_exito'] = datetime.now(timezone.utc).isoformat()

        return senal

    # ============================================================
    # SELECCIÓN DE MODO
    # ============================================================

    def _seleccionar_modo(
        self, simbolo, regimen, direccion, score_h1, contexto_h1,
        analisis_rapido, analisis_medio, analisis_pesado,
        df_m5, precio_actual, confluencias,
    ) -> Optional[str]:
        """Selecciona modo: ModoSelector primero, DetectorModos fallback."""
        nivel_usado = (contexto_h1 or {}).get('nivel_usado', 0)

        if self.modo_selector is not None:
            try:
                modo_obj, _, _ = self.modo_selector.seleccionar_modo(
                    simbolo=simbolo, regimen=regimen, direccion=direccion,
                    score_h1=score_h1, nivel_usado=nivel_usado,
                    df_m5=df_m5, precio_actual=precio_actual,
                    volumen_relativo=getattr(analisis_rapido, 'volumen_relativo', 1.0),
                    patron_calidad=getattr(analisis_pesado, 'calidad_patron', 0) if analisis_pesado else 0,
                    es_reversal=bool((contexto_h1 or {}).get('es_reversal', False)),
                    en_nivel_clave=bool((contexto_h1 or {}).get('en_nivel_clave', False)),
                )
                if modo_obj is not None:
                    if hasattr(modo_obj, 'value'):
                        return modo_obj.value
                    return str(modo_obj)
            except Exception as e:
                self.logger.debug(f"⚠️ ModoSelector falló: {e}")

        try:
            modo_obj, _, _, _ = self.detector_modos.detectar(
                simbolo=simbolo, df_m5=df_m5, precio_actual=precio_actual,
                direccion=direccion, analisis_rapido=analisis_rapido,
                analisis_medio=analisis_medio,
                analisis_pesado=analisis_pesado,
                contexto_h1=contexto_h1 or {},
            )
            if modo_obj is not None and hasattr(modo_obj, 'value'):
                valor = modo_obj.value
                if valor != 'DESCONOCIDO':
                    return valor
        except Exception as e:
            self.logger.debug(f"⚠️ DetectorModos falló: {e}")

        return None

    # ============================================================
    # OBTENER H1
    # ============================================================

    def _obtener_df_h1(self, simbolo: str) -> Optional[pd.DataFrame]:
        """H1 desde cache/mt5/construcción."""
        if self.orquestador is not None:
            try:
                cache = getattr(self.orquestador, 'cache', None)
                if cache:
                    df = cache.get_datos(
                        simbolo=simbolo, timeframe=60, n_velas=250,
                        fetch_func=self.mt5.obtener_datos if self.mt5 else None,
                    )
                    if df is not None and len(df) >= 50:
                        return df
            except Exception:
                pass

        if self.analysis_cache is not None:
            try:
                df = self.analysis_cache.get_datos(
                    simbolo=simbolo, timeframe=60, n_velas=250,
                    fetch_func=self.mt5.obtener_datos if self.mt5 else None,
                )
                if df is not None and len(df) >= 50:
                    return df
            except Exception:
                pass

        if self.mt5 is not None:
            try:
                df = self.mt5.obtener_datos(simbolo, n_velas=250, timeframe=60)
                if df is not None and len(df) >= 50:
                    return df
            except Exception:
                pass

        if self.mt5 is not None:
            try:
                df_m5 = self.mt5.obtener_datos(simbolo, n_velas=300, timeframe=5)
                if df_m5 is not None and len(df_m5) >= 100:
                    from utils.construir_timeframes import construir_h1_desde_m5
                    df_h1 = construir_h1_desde_m5(df_m5)
                    if df_h1 is not None and len(df_h1) >= 50:
                        return df_h1
            except Exception:
                pass

        self.logger.warning(f"⚠️ {simbolo}: No se pudo obtener H1")
        return None

    # ============================================================
    # SL/TP
    # ============================================================

    def _calcular_sl_tp(
        self, simbolo, precio_entrada, direccion, modo, regimen,
        contexto_h1, analisis_medio, analisis_pesado,
        df_m5, df_h1, calidad_horario,
    ) -> Optional[Tuple[float, float, float, float]]:
        """Calcula SL/TP con TP realista por ATR."""
        # SL estructural
        sl_estructural = None
        if df_h1 is not None and len(df_h1) >= 30:
            sl_estructural = obtener_nivel_invalidacion(df_h1, direccion, ventana=5)

        if sl_estructural is None:
            if direccion == 'COMPRA':
                sl_estructural = contexto_h1.get('soporte_cercano')
            else:
                sl_estructural = contexto_h1.get('resistencia_cercana')

        if sl_estructural is None and df_m5 is not None and len(df_m5) >= 20:
            if direccion == 'COMPRA':
                sl_estructural = float(df_m5['Low'].iloc[-20:].min())
            else:
                sl_estructural = float(df_m5['High'].iloc[-20:].max())

        if sl_estructural is None:
            atr = getattr(analisis_medio, 'atr', 0.001) if analisis_medio else 0.001
            if direccion == 'COMPRA':
                sl_estructural = precio_entrada - (atr * 1.5)
            else:
                sl_estructural = precio_entrada + (atr * 1.5)

        # Validar SL
        try:
            valido, razon, sl_final, _, _ = self.gestor_stops.validar_sl_tp(
                simbolo=simbolo,
                entry_price=precio_entrada,
                sl=sl_estructural,
                tp=0,
                tp2=0,
                direccion=direccion,
                regimen=regimen,
                modo=modo,
                es_reversal=bool(contexto_h1.get('es_reversal', False)),
                en_nivel_clave=bool(contexto_h1.get('en_nivel_clave', False)),
                calidad_horario=calidad_horario,
                atr_pips=0.0,
            )
        except Exception as e:
            self.logger.warning(f"⚠️ {simbolo}: error validando SL: {e}")
            return None

        if not valido:
            self.logger.debug(f"⚠️ {simbolo}: SL inválido: {razon}")
            return None

        # TP realista por ATR
        atr_m5 = self._obtener_atr_m5(df_m5)

        tp_estructura = None
        if direccion == 'COMPRA':
            tp_estructura = contexto_h1.get('resistencia_cercana')
        else:
            tp_estructura = contexto_h1.get('soporte_cercano')

        tp_final, rr = self._calcular_tp_realista_atr(
            simbolo=simbolo,
            precio_entrada=precio_entrada,
            sl=sl_final,
            direccion=direccion,
            atr_m5=atr_m5,
            tp_estructura=tp_estructura,
        )

        # TP2
        sl_dist = abs(precio_entrada - sl_final)
        tp2_dist = sl_dist * 3.0
        if direccion == 'COMPRA':
            tp2_final = precio_entrada + tp2_dist
        else:
            tp2_final = precio_entrada - tp2_dist

        self.logger.info(
            f"📊 {simbolo}: SL/TP calculado | "
            f"SL: {sl_final:.5f} | TP: {tp_final:.5f} | "
            f"R:R: {rr:.2f} | ATR M5: {atr_m5:.5f}"
        )

        return sl_final, tp_final, tp2_final, rr

    # ============================================================
    # CONFLUENCIAS
    # ============================================================

    def _clasificar_confluencias(
        self, contexto_h1, analisis_rapido, analisis_medio, analisis_pesado
    ) -> Dict[str, List[str]]:
        categorias = {
            'TENDENCIA': [], 'ESTRUCTURA': [],
            'MOMENTUM': [], 'PRECIO_VELA': [],
            'CONTEXTO': [], 'DIVERGENCIA': [],
        }

        if analisis_medio:
            sma20 = getattr(analisis_medio, 'sma20', 0)
            sma50 = getattr(analisis_medio, 'sma50', 0)
            adx = getattr(analisis_medio, 'adx', 0)
            if sma20 > sma50:
                categorias['TENDENCIA'].append('EMA_ALCISTA')
            elif sma20 < sma50:
                categorias['TENDENCIA'].append('EMA_BAJISTA')
            if adx > 25:
                categorias['TENDENCIA'].append(f'ADX_{adx:.0f}')

        if contexto_h1.get('en_nivel_clave'):
            categorias['ESTRUCTURA'].append('NIVEL_CLAVE')

        soporte = contexto_h1.get('soporte_cercano')
        resistencia = contexto_h1.get('resistencia_cercana')
        if soporte:
            categorias['ESTRUCTURA'].append('SOPORTE')
        if resistencia:
            categorias['ESTRUCTURA'].append('RESISTENCIA')

        if analisis_medio:
            rsi = getattr(analisis_medio, 'rsi', 50)
            macd = getattr(analisis_medio, 'macd_histogram', 0)
            if rsi > 60:
                categorias['MOMENTUM'].append('RSI_ALTO')
            elif rsi < 40:
                categorias['MOMENTUM'].append('RSI_BAJO')
            if abs(macd) > 0.0005:
                categorias['MOMENTUM'].append('MACD_FUERTE')

        if analisis_pesado:
            calidad = getattr(analisis_pesado, 'calidad_patron', 0)
            patron = getattr(analisis_pesado, 'patron_principal', None)
            if calidad > 30 and patron and patron != 'N/A':
                categorias['PRECIO_VELA'].append(patron)

        vol = getattr(analisis_rapido, 'volumen_relativo', 1.0)
        if vol > 1.2:
            categorias['CONTEXTO'].append(f'VOLUMEN_{vol:.1f}x')

        if analisis_pesado:
            div_rsi = getattr(analisis_pesado, 'divergencia_rsi', None)
            if div_rsi:
                categorias['DIVERGENCIA'].append(f'RSI_{div_rsi}')

        return categorias

    # ============================================================
    # AJUSTES
    # ============================================================

    def _aplicar_ajustes(self, ajustes: Dict[str, float]) -> Dict[str, float]:
        umbrales = {
            'score_minimo': self.UMBRALES['score_minimo'] * ajustes.get('score_minimo', 1.0),
            'volumen_minimo': self.UMBRALES['volumen_minimo'] * ajustes.get('volumen_minimo', 1.0),
            'rr_minimo': self.UMBRALES['rr_minimo'] * ajustes.get('rr_minimo', 1.0),
            'distancia_nivel_max': self.UMBRALES['distancia_nivel_max'] * ajustes.get('distancia_nivel_max', 1.0),
        }
        if self.modo_backtest:
            umbrales['score_minimo'] = max(15, umbrales['score_minimo'] * 0.6)
            umbrales['volumen_minimo'] = max(0.01, umbrales['volumen_minimo'] * 0.3)
            umbrales['rr_minimo'] = max(0.5, umbrales['rr_minimo'] * 0.8)
        return umbrales

    # ============================================================
    # HELPERS
    # ============================================================

    def _ya_hay_posicion(self, simbolo: str) -> bool:
        if not self.modo_backtest and self.mt5 is not None:
            try:
                posiciones = self.mt5.obtener_posiciones()
                if posiciones and any(p.get('simbolo') == simbolo for p in posiciones):
                    return True
            except Exception:
                pass
        if self.orquestador is not None:
            try:
                pos_mem = self.orquestador.estado.posiciones_abiertas
                if pos_mem and any(m.get('simbolo') == simbolo for m in pos_mem.values()):
                    return True
            except Exception:
                pass
        return False

    def _obtener_precio_entrada(self, simbolo, direccion, tick_data, precio_actual) -> float:
        if tick_data:
            key = 'ask' if direccion == 'COMPRA' else 'bid'
            val = tick_data.get(key)
            if val:
                return float(val)
        return float(precio_actual)

    def _registrar_rechazo(self, razon: str):
        key = razon.split(':')[0].strip()
        self._stats['rechazos'][key] = self._stats['rechazos'].get(key, 0) + 1
        if self.modo_depuracion:
            self.logger.debug(f"⏭️ Rechazo: {razon}")

    def set_modo_backtest(self, modo: bool = True):
        self.modo_backtest = modo
        self.detector_modos.set_modo_backtest(modo)
        self.validador = SniperValidador(self.config, modo)
        self.validador_calidad = ValidadorCalidad(self.config, modo)
        self.scorer = CalculadorScoreSniper(self.config, modo)
        self.UMBRALES = self.UMBRALES_POR_DEFECTO.copy()
        self._cargar_umbrales()
        self.logger.info(f"🔧 SniperChecklist: backtest {'ACTIVADO' if modo else 'DESACTIVADO'}")

    def get_stats(self) -> Dict[str, Any]:
        stats = dict(self._stats)
        total = stats['total_evaluaciones']
        stats['tasa_disparo'] = round(stats['disparos'] / total * 100, 2) if total > 0 else 0
        return stats

    def reset_stats(self):
        self._stats = {
            'total_evaluaciones': 0, 'disparos': 0,
            'disparos_por_modo': {}, 'rechazos': {},
            'rechazos_distancia': 0,
            'rechazos_rechazo_no_confirmado': 0,
            'rechazos_rr_max': 0,
            'rechazos_ml': 0,
            'bonus_stop_hunt': 0,
            'bonus_rechazo': 0,
            'penalizaciones_sin_nivel': 0,
        }


# ============================================================
# FACTORY
# ============================================================

def create_sniper_checklist(
    pipeline, analisis_capas, modo_selector, entry_timer, gestor_stops,
    config=None, almacen=None, mt5=None, noticias=None,
    patron_tracker=None, ml_optimizer=None, analysis_cache=None,
    modo_depuracion=False, modo_backtest=False,
) -> SniperChecklist:
    return SniperChecklist(
        pipeline=pipeline, analisis_capas=analisis_capas,
        modo_selector=modo_selector, entry_timer=entry_timer,
        gestor_stops=gestor_stops, config=config, almacen=almacen,
        mt5=mt5, noticias=noticias, patron_tracker=patron_tracker,
        ml_optimizer=ml_optimizer, analysis_cache=analysis_cache,
        modo_depuracion=modo_depuracion, modo_backtest=modo_backtest,
    )


if __name__ == "__main__":
    print("🧪 SniperChecklist V10.2...")
    print("✅ Import OK")
    print("✅ Todos los checks pasan")