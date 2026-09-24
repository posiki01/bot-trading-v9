#!/usr/bin/env python3
"""
trading/modos.py (V10.0 - REFACTORIZADO)
Sistema de selección de modo con validación única y priorización dinámica.

CAMBIOS V10.0:
- ✅ Validación de dirección por régimen EN UN SOLO LUGAR (elimina duplicación)
- ✅ Cache con invalidación correcta (TTL + invalidación por régimen)
- ✅ set_modo_backtest NO muta umbrales acumulativamente (fix bug)
- ✅ _consultar_metricas_modos usa filtro de régimen (fix bug SQLite)
- ✅ Eliminado _obtener_ponderacion (código muerto)
- ✅ Cada _evaluar_X valida SOLO su lógica específica
- ✅ Logs limpios, sin duplicación

ESTRUCTURA:
    1. Validar dirección por régimen (UNA VEZ)
    2. Iterar modos por prioridad
    3. Cada _evaluar_X valida su lógica específica
    4. Devolver primer modo válido
"""

import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from enum import Enum

from config.umbrales import Umbrales
from utils.helpers import safe_float

logger = logging.getLogger('BotTrading.Modos')


# ============================================================
# ENUMS
# ============================================================

class ModoEntrada(Enum):
    """Modos de entrada disponibles."""
    RETEST = "RETEST"
    BREAKOUT = "BREAKOUT"
    PULLBACK = "PULLBACK"
    NIVEL_FUERTE = "NIVEL_FUERTE"
    PATRON = "PATRON"
    RUPTURA_FALSA = "RUPTURA_FALSA"
    VELA_BORDE = "VELA_BORDE"
    RETEST_FALLBACK = "RETEST_FALLBACK"
    SNIPER_ELITE = "SNIPER_ELITE"


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class ModoSelector:
    """
    Sistema de selección de modo con priorización dinámica.
    V10.0 - REFACTORIZADO.
    """

    # ============================================================
    # PRIORIDAD BASE POR RÉGIMEN
    # ============================================================
    PRIORIDAD_BASE_POR_REGIMEN = {
        'TREND_ALCISTA_FUERTE': [
            ModoEntrada.RETEST,
            ModoEntrada.BREAKOUT,
        ],
        'TREND_ALCISTA_DEBIL': [
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.BREAKOUT,
        ],
        'TREND_BAJISTA_FUERTE': [
            ModoEntrada.RETEST,
            ModoEntrada.BREAKOUT,
        ],
        'TREND_BAJISTA_DEBIL': [
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.BREAKOUT,
        ],
        'RANGO_AMPLIO': [
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.VELA_BORDE,
            ModoEntrada.RUPTURA_FALSA,
        ],
        'RANGO_APRETADO': [
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.RETEST,
            ModoEntrada.VELA_BORDE,
            ModoEntrada.RUPTURA_FALSA,
        ],
        'BREAKOUT_INMINENTE': [
            ModoEntrada.BREAKOUT,
            ModoEntrada.RUPTURA_FALSA,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
        ],
        'CHOP_VOLATIL': [
            ModoEntrada.RETEST_FALLBACK,
            ModoEntrada.RETEST,
        ],
        'INCERTO': [
            ModoEntrada.RETEST_FALLBACK,
            ModoEntrada.NIVEL_FUERTE,
        ],
    }

    # ============================================================
    # SCORE MÍNIMO BASE POR MODO (backtest aplica factor después)
    # ============================================================
    SCORE_MINIMO_POR_MODO = {
        ModoEntrada.RETEST: 55,
        ModoEntrada.BREAKOUT: 65,
        ModoEntrada.PULLBACK: 65,
        ModoEntrada.NIVEL_FUERTE: 60,
        ModoEntrada.PATRON: 55,
        ModoEntrada.RUPTURA_FALSA: 50,
        ModoEntrada.VELA_BORDE: 50,
        ModoEntrada.RETEST_FALLBACK: 50,
        ModoEntrada.SNIPER_ELITE: 70,
    }

    # ============================================================
    # CONFIGURACIÓN DEL SISTEMA DE APRENDIZAJE
    # ============================================================
    APRENDIZAJE_CONFIG = {
        'min_operaciones_para_aprender': 5,
        'peso_winrate': 0.5,
        'peso_factor_beneficio': 0.5,
        'usar_prioridad_base_si_datos_insuficientes': True,
        'penalizacion_falta_datos': 0.3,
    }

    # ============================================================
    # REGLAS DE DIRECCIÓN POR RÉGIMEN (ÚNICA FUENTE DE VERDAD)
    # ============================================================
    DIRECCIONES_PERMITIDAS = {
        'TREND_ALCISTA_FUERTE': ['COMPRA'],
        'TREND_ALCISTA_DEBIL': ['COMPRA'],
        'TREND_BAJISTA_FUERTE': ['VENTA'],
        'TREND_BAJISTA_DEBIL': ['VENTA'],
        'RANGO_AMPLIO': ['COMPRA', 'VENTA'],
        'RANGO_APRETADO': ['COMPRA', 'VENTA'],
        'BREAKOUT_INMINENTE': ['COMPRA', 'VENTA'],
        'CHOP_VOLATIL': ['COMPRA', 'VENTA'],
        'INCERTO': ['COMPRA', 'VENTA'],
    }

    # Score mínimo para permitir contra-tendencia
    SCORE_CONTRA_TENDENCIA = 80

    # Score mínimo para operar en rango/incerto
    SCORE_MINIMO_RANGO = 60
    SCORE_MINIMO_INCERTO = 70

    # ============================================================
    # INIT
    # ============================================================

    def __init__(
        self,
        config: Optional[Any] = None,
        entry_timer: Optional[Any] = None,
        almacen: Optional[Any] = None,
        modo_backtest: bool = False,
        modo_depuracion: bool = False,
    ):
        self.config = config
        self.entry_timer = entry_timer
        self.almacen = almacen
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.Modos')

        # Cargar configuración
        self._cargar_configuracion()

        # Guardar umbrales base para restaurar (no mutar)
        self._umbrales_base = dict(self.SCORE_MINIMO_POR_MODO)

        # Cache de prioridades dinámicas
        self._cache_prioridades: Dict[str, Tuple[List[ModoEntrada], float]] = {}
        self._cache_ttl = 300

        # Stats
        self._stats = {
            'total_consultas': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'modos_promovidos': 0,
            'modos_degradados': 0,
            'rechazos_por_direccion': 0,
        }

        self.logger.info("🎯 ModoSelector V10.0 REFACTORIZADO inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Modos: {len(self.SCORE_MINIMO_POR_MODO)}")

    def _cargar_configuracion(self):
        """Carga configuración desde Umbrales."""
        if Umbrales is None:
            return

        # Score mínimo por modo
        if hasattr(Umbrales, 'MODOS'):
            modos_config = Umbrales.MODOS
            for modo in self.SCORE_MINIMO_POR_MODO:
                key = f'score_modo_{modo.value.lower()}'
                if key in modos_config:
                    self.SCORE_MINIMO_POR_MODO[modo] = modos_config[key]

        # Config de aprendizaje
        if hasattr(Umbrales, 'APRENDIZAJE'):
            self.APRENDIZAJE_CONFIG.update(Umbrales.APRENDIZAJE)

    # ============================================================
    # ✅ APLICAR MODO BACKTEST (SIN MUTACIÓN ACUMULATIVA)
    # ============================================================

    def set_modo_backtest(self, modo: bool = True):
        """
        Activa/desactiva modo backtest.
        ✅ V10.0: NO muta los umbrales acumulativamente.
        """
        if self.modo_backtest == modo:
            return  # Ya está en el estado correcto

        self.modo_backtest = modo

        # Restaurar desde base (no acumular)
        self.SCORE_MINIMO_POR_MODO = dict(self._umbrales_base)

        if modo:
            for m in self.SCORE_MINIMO_POR_MODO:
                self.SCORE_MINIMO_POR_MODO[m] = max(
                    15, self.SCORE_MINIMO_POR_MODO[m] - 10
                )

        # Invalidar caché
        self._cache_prioridades.clear()

        self.logger.info(f"🔧 ModoSelector: backtest {'ACTIVADO' if modo else 'DESACTIVADO'}")

    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================

    def seleccionar_modo(
        self,
        simbolo: str,
        regimen: str,
        direccion: str,
        score_h1: float,
        nivel_usado: Optional[float] = None,
        df_m5: Optional[Any] = None,
        precio_actual: float = 0,
        volumen_relativo: float = 1.0,
        patron_calidad: float = 0,
        es_reversal: bool = False,
        en_nivel_clave: bool = False,
        fecha_vela: Optional[datetime] = None,
    ) -> Tuple[Optional[ModoEntrada], str, Dict]:
        """
        Selecciona el mejor modo de entrada según régimen y condiciones.

        Returns:
            (modo, razon, detalles)
        """
        detalles = {
            'simbolo': simbolo,
            'regimen': regimen,
            'direccion': direccion,
            'score_h1': score_h1,
            'nivel_usado': nivel_usado,
            'volumen': volumen_relativo,
            'patron_calidad': patron_calidad,
            'es_reversal': es_reversal,
            'en_nivel_clave': en_nivel_clave,
        }

        # ✅ VALIDACIÓN 1: Dirección NEUTRAL
        if direccion == 'NEUTRAL':
            return None, "Dirección NEUTRAL", detalles

        # ✅ VALIDACIÓN 2: Dirección vs régimen (ÚNICA)
        valido, razon = self._validar_direccion_regimen(direccion, regimen, score_h1)
        if not valido:
            self._stats['rechazos_por_direccion'] += 1
            return None, razon, detalles

        # ✅ VALIDACIÓN 3: Score mínimo para régimen
        valido, razon = self._validar_score_regimen(score_h1, regimen)
        if not valido:
            return None, razon, detalles

        # ✅ VALIDACIÓN 4: Modo operativo según régimen (CHOP, INCERTO)
        if regimen == 'CHOP_VOLATIL' and not en_nivel_clave and patron_calidad < 40:
            return None, "CHOP sin nivel ni patrón", detalles

        # 5. Obtener prioridades
        modos_prioridad = self._obtener_prioridades(regimen)

        if self.modo_depuracion:
            self.logger.debug(
                f"🔍 {simbolo}: Prioridades para {regimen}: "
                f"{[m.value for m in modos_prioridad]}"
            )

        # 6. Iterar modos por prioridad
        for modo in modos_prioridad:
            # Verificar score mínimo del modo
            score_min = self.SCORE_MINIMO_POR_MODO.get(modo, 40)
            if self.modo_backtest:
                score_min = max(15, score_min - 10)

            if score_h1 < score_min:
                if self.modo_depuracion:
                    self.logger.debug(
                        f"   ⏭️ {modo.value}: score {score_h1:.0f} < {score_min}"
                    )
                continue

            # Verificar condiciones ESPECÍFICAS del modo
            valido, razon = self._verificar_condiciones_modo(
                modo=modo,
                regimen=regimen,
                direccion=direccion,
                score_h1=score_h1,
                nivel_usado=nivel_usado,
                volumen_relativo=volumen_relativo,
                patron_calidad=patron_calidad,
                es_reversal=es_reversal,
                en_nivel_clave=en_nivel_clave,
            )

            if not valido:
                if self.modo_depuracion:
                    self.logger.debug(f"   ⏭️ {modo.value}: {razon}")
                continue

            # Verificar momento exacto
            if self.entry_timer and df_m5 is not None and precio_actual > 0:
                valido_momento, razon_momento, _ = self.entry_timer.validar_momento_exacto(
                    simbolo=simbolo,
                    modo=modo.value,
                    df_m5=df_m5,
                    precio_actual=precio_actual,
                    nivel_usado=nivel_usado,
                    direccion=direccion,
                    regimen=regimen,
                    volumen_relativo=volumen_relativo,
                    fecha_vela=fecha_vela,
                )

                if not valido_momento:
                    if self.modo_depuracion:
                        self.logger.debug(
                            f"   ⏭️ {modo.value}: momento no exacto - {razon_momento}"
                        )
                    continue

            # ✅ MODO SELECCIONADO
            detalles['modo_seleccionado'] = modo.value
            detalles['score_min_usado'] = score_min

            self.logger.info(
                f"🎯 {simbolo}: Modo seleccionado: {modo.value} "
                f"(score: {score_h1:.0f}, min: {score_min})"
            )
            return modo, f"Seleccionado {modo.value}", detalles

        self.logger.debug(f"⏭️ {simbolo}: No se encontró modo válido para {regimen}")
        return None, "No se encontró modo válido", detalles

    # ============================================================
    # VALIDACIÓN ÚNICA DE DIRECCIÓN POR RÉGIMEN
    # ============================================================

    def _validar_direccion_regimen(
        self,
        direccion: str,
        regimen: str,
        score_h1: float,
    ) -> Tuple[bool, str]:
        """
        Valida si la dirección es coherente con el régimen.
        ✅ ÚNICA FUENTE DE VERDAD para esta validación.
        """
        permitidas = self.DIRECCIONES_PERMITIDAS.get(regimen, ['COMPRA', 'VENTA'])

        if direccion in permitidas:
            return True, "OK"

        # Dirección contra tendencia → permitir solo con score muy alto
        if score_h1 >= self.SCORE_CONTRA_TENDENCIA:
            return True, f"Contra-tendencia permitida (score={score_h1:.0f})"

        return False, f"{direccion} contra régimen {regimen} (score={score_h1:.0f})"

    # ============================================================
    # VALIDACIÓN DE SCORE POR RÉGIMEN
    # ============================================================

    def _validar_score_regimen(self, score_h1: float, regimen: str) -> Tuple[bool, str]:
        """Score mínimo según tipo de régimen."""
        if regimen in ('RANGO_AMPLIO', 'RANGO_APRETADO', 'BREAKOUT_INMINENTE'):
            if score_h1 < self.SCORE_MINIMO_RANGO:
                return False, f"Score bajo para {regimen} ({score_h1:.0f} < {self.SCORE_MINIMO_RANGO})"

        if regimen == 'INCERTO':
            if score_h1 < self.SCORE_MINIMO_INCERTO:
                return False, f"Score bajo para INCERTO ({score_h1:.0f} < {self.SCORE_MINIMO_INCERTO})"

        return True, "OK"

    # ============================================================
    # CONDICIONES ESPECÍFICAS POR MODO
    # ============================================================
    # IMPORTANTE: Cada _evaluar_X valida SOLO su lógica específica.
    # La validación de dirección ya se hizo en _validar_direccion_regimen().
    # NO duplicar.

    def _verificar_condiciones_modo(
        self,
        modo: ModoEntrada,
        regimen: str,
        direccion: str,
        score_h1: float,
        nivel_usado: Optional[float],
        volumen_relativo: float,
        patron_calidad: float,
        es_reversal: bool,
        en_nivel_clave: bool,
    ) -> Tuple[bool, str]:
        """Verifica condiciones específicas del modo (sin duplicar dirección)."""

        # RETEST
        if modo == ModoEntrada.RETEST:
            if not en_nivel_clave and not nivel_usado:
                if score_h1 >= 75:
                    return True, "RETEST sin nivel pero score alto"
                return False, "Sin nivel clave"

            if regimen in ('CHOP_VOLATIL', 'INCERTO') and score_h1 < 65:
                return False, f"Score bajo para {regimen}"

            return True, "RETEST válido"

        # NIVEL_FUERTE
        elif modo == ModoEntrada.NIVEL_FUERTE:
            if not en_nivel_clave and not nivel_usado:
                return False, "No hay nivel clave"

            if score_h1 < 70:
                return False, f"Score bajo ({score_h1:.0f} < 70)"

            return True, "NIVEL_FUERTE válido"

        # BREAKOUT
        elif modo == ModoEntrada.BREAKOUT:
            if volumen_relativo < 0.6:
                return False, f"Volumen bajo ({volumen_relativo:.2f}x < 0.6x)"

            if regimen not in ('BREAKOUT_INMINENTE', 'TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE'):
                return False, f"Régimen no adecuado"

            return True, "BREAKOUT válido"

        # PULLBACK
        elif modo == ModoEntrada.PULLBACK:
            if regimen not in ('TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE',
                               'TREND_ALCISTA_DEBIL', 'TREND_BAJISTA_DEBIL'):
                return False, "Régimen no adecuado"

            if score_h1 < 60:
                return False, f"Score bajo ({score_h1:.0f} < 60)"

            return True, "PULLBACK válido"

        # PATRON
        elif modo == ModoEntrada.PATRON:
            if patron_calidad < 25:
                return False, f"Calidad patrón baja ({patron_calidad:.0f} < 25)"
            return True, "PATRON válido"

        # RUPTURA_FALSA
        elif modo == ModoEntrada.RUPTURA_FALSA:
            if regimen not in ('RANGO_AMPLIO', 'RANGO_APRETADO', 'BREAKOUT_INMINENTE'):
                return False, f"Régimen no adecuado"
            return True, "RUPTURA_FALSA válido"

        # VELA_BORDE
        elif modo == ModoEntrada.VELA_BORDE:
            if not en_nivel_clave and not nivel_usado:
                return False, "No hay nivel clave"
            return True, "VELA_BORDE válido"

        # SNIPER_ELITE
        elif modo == ModoEntrada.SNIPER_ELITE:
            if score_h1 < 70:
                return False, f"Score bajo ({score_h1:.0f} < 70)"

            if not en_nivel_clave and patron_calidad < 35:
                return False, "Falta nivel clave o patrón"

            return True, "SNIPER_ELITE válido"

        # RETEST_FALLBACK
        elif modo == ModoEntrada.RETEST_FALLBACK:
            if score_h1 < 55:
                return False, f"Score bajo ({score_h1:.0f} < 55)"
            return True, "RETEST_FALLBACK válido"

        return True, "Condiciones OK"

    # ============================================================
    # PRIORIDADES DINÁMICAS
    # ============================================================

    def _obtener_prioridades(self, regimen: str) -> List[ModoEntrada]:
        """
        Obtiene modos priorizados para un régimen.
        V10.0: cache con invalidación + aprendizaje real.
        """
        # Cache
        cached = self._cache_prioridades.get(regimen)
        if cached:
            modos, ts = cached
            if time.time() - ts < self._cache_ttl:
                self._stats['cache_hits'] += 1
                return modos.copy()

        self._stats['cache_misses'] += 1
        self._stats['total_consultas'] += 1

        # Prioridad base
        prioridad_base = list(
            self.PRIORIDAD_BASE_POR_REGIMEN.get(
                regimen,
                self.PRIORIDAD_BASE_POR_REGIMEN['INCERTO']
            )
        )

        # Sin almacén → devolver base
        if not self.almacen:
            self._cache_prioridades[regimen] = (prioridad_base, time.time())
            return prioridad_base

        # Consultar métricas reales (con filtro de régimen)
        modos_metrics = self._consultar_metricas_modos(regimen)

        if not modos_metrics:
            self._cache_prioridades[regimen] = (prioridad_base, time.time())
            return prioridad_base

        # Calcular puntuaciones dinámicas
        puntuaciones: Dict[ModoEntrada, float] = {}
        min_ops = self.APRENDIZAJE_CONFIG['min_operaciones_para_aprender']

        for modo in prioridad_base:
            modo_str = modo.value
            metrics = modos_metrics.get(modo_str)

            if metrics and metrics.get('total', 0) >= min_ops:
                winrate = metrics.get('winrate', 0)
                factor_beneficio = min(metrics.get('factor_beneficio', 0), 3.0)

                puntuacion = (
                    winrate * self.APRENDIZAJE_CONFIG['peso_winrate'] +
                    factor_beneficio * self.APRENDIZAJE_CONFIG['peso_factor_beneficio'] * 100
                )
                puntuaciones[modo] = puntuacion
            else:
                # Sin datos → penalización suave
                puntuaciones[modo] = -self.APRENDIZAJE_CONFIG['penalizacion_falta_datos'] * 100

        # Ordenar por puntuación descendente, manteniendo prioridad base como desempate
        orden_base = {m: i for i, m in enumerate(prioridad_base)}
        modos_ordenados = sorted(
            puntuaciones.keys(),
            key=lambda m: (-puntuaciones[m], orden_base.get(m, 999))
        )

        # Stats de promoción
        if self.modo_depuracion:
            for i, modo in enumerate(modos_ordenados):
                pos_base = orden_base.get(modo, len(prioridad_base))
                if i < pos_base:
                    self._stats['modos_promovidos'] += 1
                elif i > pos_base:
                    self._stats['modos_degradados'] += 1

        # Cache
        self._cache_prioridades[regimen] = (modos_ordenados, time.time())

        self.logger.debug(
            f"📊 Prioridades dinámicas {regimen}: "
            f"{[m.value for m in modos_ordenados]}"
        )

        return modos_ordenados

    def _consultar_metricas_modos(self, regimen: str) -> Dict[str, Dict[str, float]]:
        """
        Consulta métricas de modos para un régimen específico.
        ✅ V10.0: usa filtro de régimen (fix bug SQLite).
        """
        if not self.almacen:
            return {}

        try:
            operaciones = self.almacen.obtener_operaciones({
                'estado': 'CERRADA',
                'regimen': regimen,  # ✅ Ahora el SQLite SÍ lo soporta
                'limite': 1000,
            })

            if not operaciones:
                return {}

            # Agrupar por modo
            modos_stats: Dict[str, Dict[str, Any]] = {}
            for op in operaciones:
                modo = op.get('modo', 'DESCONOCIDO')
                if modo not in modos_stats:
                    modos_stats[modo] = {'total': 0, 'ganadoras': 0, 'pnl_total': 0.0,
                                         'perdedoras_ganancia': 0.0}

                modos_stats[modo]['total'] += 1
                ganancia = float(op.get('ganancia', 0.0) or 0.0)
                modos_stats[modo]['pnl_total'] += ganancia

                if ganancia > 0:
                    modos_stats[modo]['ganadoras'] += 1
                else:
                    modos_stats[modo]['perdedoras_ganancia'] += abs(ganancia)

            # Calcular métricas finales
            resultados: Dict[str, Dict[str, float]] = {}
            for modo, stats in modos_stats.items():
                total = stats['total']
                if total <= 0:
                    continue

                winrate = (stats['ganadoras'] / total) * 100

                ganancia_bruta = sum(
                    float(op.get('ganancia', 0) or 0)
                    for op in operaciones
                    if op.get('modo') == modo and float(op.get('ganancia', 0) or 0) > 0
                )
                perdida_bruta = stats['perdedoras_ganancia']

                factor_beneficio = (
                    ganancia_bruta / perdida_bruta
                    if perdida_bruta > 0 else 0
                )

                resultados[modo] = {
                    'total': total,
                    'winrate': winrate,
                    'factor_beneficio': factor_beneficio,
                    'pnl_total': stats['pnl_total'],
                }

            return resultados

        except Exception as e:
            self.logger.warning(f"⚠️ Error consultando métricas de modos: {e}")
            return {}

    # ============================================================
    # MÉTODOS PÚBLICOS DE CONSULTA
    # ============================================================

    def set_entry_timer(self, entry_timer: Any):
        """Inyecta el EntryTimer."""
        self.entry_timer = entry_timer
        self.logger.info("⏱️ EntryTimer inyectado en ModoSelector")

    def set_almacen(self, almacen: Any):
        """Inyecta el almacenamiento SQLite."""
        self.almacen = almacen
        self._cache_prioridades.clear()  # Invalidar caché
        self.logger.info("💾 Almacenamiento SQLite inyectado en ModoSelector")

    def invalidar_cache(self):
        """Invalida la caché de prioridades."""
        self._cache_prioridades.clear()
        self.logger.debug("🧹 Cache de prioridades invalidada")

    def obtener_score_minimo(self, modo: ModoEntrada) -> int:
        """Obtiene el score mínimo para un modo."""
        score = self.SCORE_MINIMO_POR_MODO.get(modo, 40)
        if self.modo_backtest:
            score = max(15, score - 10)
        return score

    def obtener_modos_prioritarios(self, regimen: str) -> List[str]:
        """Obtiene modos prioritarios como strings."""
        modos = self._obtener_prioridades(regimen)
        return [m.value for m in modos]

    def es_modo_valido_para_regimen(self, modo: ModoEntrada, regimen: str) -> bool:
        """Verifica si un modo es válido para un régimen."""
        modos = self._obtener_prioridades(regimen)
        return modo in modos

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del selector."""
        return self._stats.copy()

    # ============================================================
    # COMPATIBILIDAD
    # ============================================================

    def seleccionar_modo_legacy(
        self,
        simbolo: str,
        regimen: str,
        direccion: str,
        score_h1: float,
        nivel_usado: Optional[float] = None,
        df_m5: Optional[Any] = None,
        precio_actual: float = 0,
        volumen_relativo: float = 1.0,
        patron_calidad: float = 0,
        es_reversal: bool = False,
        en_nivel_clave: bool = False,
        fecha_vela: Optional[datetime] = None,
    ) -> Tuple[Optional[str], str, Dict]:
        """Versión legacy que retorna el modo como string."""
        modo, razon, detalles = self.seleccionar_modo(
            simbolo=simbolo,
            regimen=regimen,
            direccion=direccion,
            score_h1=score_h1,
            nivel_usado=nivel_usado,
            df_m5=df_m5,
            precio_actual=precio_actual,
            volumen_relativo=volumen_relativo,
            patron_calidad=patron_calidad,
            es_reversal=es_reversal,
            en_nivel_clave=en_nivel_clave,
            fecha_vela=fecha_vela,
        )
        if modo:
            return modo.value, razon, detalles
        return None, razon, detalles


# ============================================================
# FACTORY
# ============================================================

def create_modo_selector(
    config: Optional[Any] = None,
    entry_timer: Optional[Any] = None,
    almacen: Optional[Any] = None,
    modo_backtest: bool = False,
    modo_depuracion: bool = False,
) -> ModoSelector:
    return ModoSelector(
        config=config,
        entry_timer=entry_timer,
        almacen=almacen,
        modo_backtest=modo_backtest,
        modo_depuracion=modo_depuracion,
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    if str(Path(__file__).parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).parent.parent))

    print("🧪 Probando ModoSelector V10.0 REFACTORIZADO...")

    selector = ModoSelector(modo_backtest=True, modo_depuracion=True)

    print(f"✅ Inicializado")
    print(f"   Modos configurados: {len(selector.SCORE_MINIMO_POR_MODO)}")

    # Test 1: Selección en tendencia alcista
    modo, razon, detalles = selector.seleccionar_modo(
        simbolo='EURUSD',
        regimen='TREND_ALCISTA_FUERTE',
        direccion='COMPRA',
        score_h1=75,
        nivel_usado=1.0950,
        en_nivel_clave=True,
        volumen_relativo=1.5,
    )
    print(f"\n1. TREND_ALCISTA_FUERTE + COMPRA → {modo.value if modo else 'None'}")
    print(f"   Razón: {razon}")
    assert modo is not None

    # Test 2: VENTA contra tendencia alcista (debe rechazar)
    modo, razon, _ = selector.seleccionar_modo(
        simbolo='EURUSD',
        regimen='TREND_ALCISTA_FUERTE',
        direccion='VENTA',
        score_h1=70,
        en_nivel_clave=True,
    )
    print(f"\n2. TREND_ALCISTA_FUERTE + VENTA → {modo.value if modo else 'None'}")
    print(f"   Razón: {razon}")
    assert modo is None
    assert 'contra' in razon.lower()

    # Test 3: VENTA contra tendencia con score alto (debe permitir)
    modo, razon, _ = selector.seleccionar_modo(
        simbolo='EURUSD',
        regimen='TREND_ALCISTA_FUERTE',
        direccion='VENTA',
        score_h1=85,  # alto
        en_nivel_clave=True,
    )
    print(f"\n3. TREND_ALCISTA_FUERTE + VENTA + score 85 → {modo.value if modo else 'None'}")
    print(f"   Razón: {razon}")
    assert modo is not None, "Score alto debe permitir contra-tendencia"

    # Test 4: CHOP_VOLATIL sin nivel (rechazar)
    modo, razon, _ = selector.seleccionar_modo(
        simbolo='EURUSD',
        regimen='CHOP_VOLATIL',
        direccion='COMPRA',
        score_h1=70,
        en_nivel_clave=False,
        patron_calidad=20,
    )
    print(f"\n4. CHOP_VOLATIL sin nivel → {modo.value if modo else 'None'}")
    print(f"   Razón: {razon}")
    assert modo is None

    # Test 5: Rango con score bajo (rechazar)
    modo, razon, _ = selector.seleccionar_modo(
        simbolo='EURUSD',
        regimen='RANGO_AMPLIO',
        direccion='COMPRA',
        score_h1=50,  # < SCORE_MINIMO_RANGO (60)
        en_nivel_clave=True,
    )
    print(f"\n5. RANGO_AMPLIO + score 50 → {modo.value if modo else 'None'}")
    print(f"   Razón: {razon}")
    assert modo is None

    # Test 6: set_modo_backtest no muta acumulativamente
    selector.set_modo_backtest(False)
    umbrales_off = dict(selector.SCORE_MINIMO_POR_MODO)

    selector.set_modo_backtest(True)
    umbrales_on = dict(selector.SCORE_MINIMO_POR_MODO)

    selector.set_modo_backtest(False)
    umbrales_off2 = dict(selector.SCORE_MINIMO_POR_MODO)

    print(f"\n6. Umbrales RETEST: off={umbrales_off[ModoEntrada.RETEST]}, "
          f"on={umbrales_on[ModoEntrada.RETEST]}, off2={umbrales_off2[ModoEntrada.RETEST]}")

    assert umbrales_off == umbrales_off2, "❌ set_modo_backtest muta acumulativamente"
    print("   ✅ No acumulativo")

    # Stats
    print(f"\n📊 Stats: {selector.get_stats()}")

    print("\n✅ Todas las pruebas pasan")