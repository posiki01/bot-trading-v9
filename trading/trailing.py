#!/usr/bin/env python3
"""
trading/trailing.py (V10.0 - CORREGIDO)
Motor de Trailing Stop con reanálisis de mercado y estrategia por fases.

CORRECCIONES V10.0:
- ✅ verificar_timeout(): acepta 'time' (unix), 'time_msc' (ms) o 'fecha_entrada' (datetime)
  El bug anterior usaba pos['fecha_entrada'] que NUNCA existía → timeout jamás disparaba
- ✅ _normalizar_direccion(): robusta a BUY/SELL/COMPRA/VENTA
- ✅ _reanalizar_mercado(): cachea por hash, no por id(df)
- ✅ Logs separados de hot path
- ✅ Compatibilidad total con interfaz previa
"""

import logging
import hashlib
from typing import Dict, Any, Optional, Tuple, List, Union
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from utils.reloj import now_utc

try:
    from config.umbrales import Umbrales
except ImportError:
    Umbrales = None

logger = logging.getLogger('BotTrading.Trailing')


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class DecisionTrailing:
    """Decisión de trailing."""
    mover_sl: bool = False
    nuevo_sl: Optional[float] = None
    cerrar: bool = False
    motivo_cierre: Optional[str] = None
    razon: str = ""
    fase: str = "NINGUNA"
    analisis: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalisisMercado:
    """Resultado del reanálisis de mercado."""
    soporte_intacto: bool = False
    soporte_cercano: bool = False
    dist_soporte: float = 999.0
    resistencia_cercana: bool = False
    dist_resistencia: float = 999.0
    pullback_valido: bool = False
    regimen_cambio: bool = False
    cerrar: bool = False
    razon: str = ""
    estructura_rota: bool = False


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class TrailingEngine:
    """
    Motor de Trailing Stop con reanálisis de mercado.
    V10.0 - CORREGIDO.
    """

    # ============================================================
    # CONFIGURACIÓN POR MODO
    # ============================================================

    CONFIG_POR_MODO = {
        'RETEST': {
            'breakeven_umbral': 20,
            'breakeven_margen': 0,
            'trailing_umbral': 40,
            'trailing_distancia': 15,
            'trailing_agresivo_umbral': 70,
            'trailing_agresivo_distancia': 10,
            'timeout_minutos': 480,
            'min_pips_para_mover': 15,
            'cierre_parcial_umbral': 25,
            'cierre_parcial_porcentaje': 0.5,
        },
        'BREAKOUT': {
            'breakeven_umbral': 25,
            'breakeven_margen': 0,
            'trailing_umbral': 50,
            'trailing_distancia': 20,
            'trailing_agresivo_umbral': 80,
            'trailing_agresivo_distancia': 15,
            'timeout_minutos': 360,
            'min_pips_para_mover': 20,
            'cierre_parcial_umbral': 30,
            'cierre_parcial_porcentaje': 0.5,
        },
        'PULLBACK': {
            'breakeven_umbral': 25,
            'breakeven_margen': 0,
            'trailing_umbral': 45,
            'trailing_distancia': 18,
            'trailing_agresivo_umbral': 80,
            'trailing_agresivo_distancia': 12,
            'timeout_minutos': 480,
            'min_pips_para_mover': 18,
            'cierre_parcial_umbral': 30,
            'cierre_parcial_porcentaje': 0.5,
        },
        'NIVEL_FUERTE': {
            'breakeven_umbral': 15,
            'breakeven_margen': 0,
            'trailing_umbral': 35,
            'trailing_distancia': 12,
            'trailing_agresivo_umbral': 60,
            'trailing_agresivo_distancia': 8,
            'timeout_minutos': 360,
            'min_pips_para_mover': 12,
            'cierre_parcial_umbral': 20,
            'cierre_parcial_porcentaje': 0.5,
        },
        'SNIPER_ELITE': {
            'breakeven_umbral': 15,
            'breakeven_margen': 0,
            'trailing_umbral': 35,
            'trailing_distancia': 12,
            'trailing_agresivo_umbral': 60,
            'trailing_agresivo_distancia': 8,
            'timeout_minutos': 480,
            'min_pips_para_mover': 12,
            'cierre_parcial_umbral': 25,
            'cierre_parcial_porcentaje': 0.5,
        },
        'PATRON': {
            'breakeven_umbral': 20,
            'breakeven_margen': 0,
            'trailing_umbral': 40,
            'trailing_distancia': 15,
            'trailing_agresivo_umbral': 70,
            'trailing_agresivo_distancia': 10,
            'timeout_minutos': 360,
            'min_pips_para_mover': 15,
            'cierre_parcial_umbral': 25,
            'cierre_parcial_porcentaje': 0.5,
        },
        'RETEST_FALLBACK': {
            'breakeven_umbral': 20,
            'breakeven_margen': 0,
            'trailing_umbral': 40,
            'trailing_distancia': 15,
            'trailing_agresivo_umbral': 70,
            'trailing_agresivo_distancia': 10,
            'timeout_minutos': 360,
            'min_pips_para_mover': 15,
            'cierre_parcial_umbral': 25,
            'cierre_parcial_porcentaje': 0.5,
        },
        'RUPTURA_FALSA': {
            'breakeven_umbral': 15,
            'breakeven_margen': 0,
            'trailing_umbral': 30,
            'trailing_distancia': 12,
            'trailing_agresivo_umbral': 50,
            'trailing_agresivo_distancia': 8,
            'timeout_minutos': 240,
            'min_pips_para_mover': 12,
            'cierre_parcial_umbral': 20,
            'cierre_parcial_porcentaje': 0.5,
        },
        'VELA_BORDE': {
            'breakeven_umbral': 15,
            'breakeven_margen': 0,
            'trailing_umbral': 30,
            'trailing_distancia': 12,
            'trailing_agresivo_umbral': 50,
            'trailing_agresivo_distancia': 8,
            'timeout_minutos': 240,
            'min_pips_para_mover': 12,
            'cierre_parcial_umbral': 20,
            'cierre_parcial_porcentaje': 0.5,
        },
    }

    # ============================================================
    # MULTIPLICADORES POR RÉGIMEN
    # ============================================================

    REGIMEN_MULTIPLICADORES = {
        'TREND_ALCISTA_FUERTE': 1.3,
        'TREND_BAJISTA_FUERTE': 1.3,
        'TREND_ALCISTA_DEBIL': 1.1,
        'TREND_BAJISTA_DEBIL': 1.1,
        'RANGO_AMPLIO': 0.9,
        'RANGO_APRETADO': 0.7,
        'CHOP_VOLATIL': 0.5,
        'BREAKOUT_INMINENTE': 1.1,
        'INCERTO': 0.8,
    }

    # ============================================================
    # INIT
    # ============================================================

    def __init__(
        self,
        config: Optional[Any] = None,
        modo_backtest: bool = False,
        modo_depuracion: bool = False,
    ):
        self.config = config
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.Trailing')

        # Copia profunda de config por instancia
        self.CONFIG_POR_MODO = {k: v.copy() for k, v in self.CONFIG_POR_MODO.items()}

        self._cargar_configuracion()

        # Caché de análisis
        self._cache_analisis: Dict[str, Dict] = {}
        self._cache_ttl = 60

        self.logger.info("🚀 TrailingEngine V10.0 CORREGIDO inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")

    def _cargar_configuracion(self):
        """Carga desde Umbrales."""
        if Umbrales is None:
            return
        if hasattr(Umbrales, 'TRAILING'):
            tcfg = Umbrales.TRAILING
            for modo in self.CONFIG_POR_MODO:
                k = f'trailing_breakeven_{modo.lower()}'
                if k in tcfg:
                    self.CONFIG_POR_MODO[modo]['breakeven_umbral'] = tcfg[k]
                k = f'trailing_distancia_{modo.lower()}'
                if k in tcfg:
                    self.CONFIG_POR_MODO[modo]['trailing_distancia'] = tcfg[k]
                k = f'trailing_agresivo_umbral_{modo.lower()}'
                if k in tcfg:
                    self.CONFIG_POR_MODO[modo]['trailing_agresivo_umbral'] = tcfg[k]

        if self.modo_backtest:
            for modo in self.CONFIG_POR_MODO:
                c = self.CONFIG_POR_MODO[modo]
                c['breakeven_umbral'] = int(c['breakeven_umbral'] * 0.8)
                c['trailing_umbral'] = int(c['trailing_umbral'] * 0.8)
                c['timeout_minutos'] = int(c['timeout_minutos'] * 0.5)
                c['min_pips_para_mover'] = int(c['min_pips_para_mover'] * 0.8)

    # ============================================================
    # HELPERS
    # ============================================================

    def _normalizar_direccion(self, direccion: Any) -> str:
        """Normaliza dirección."""
        if direccion is None:
            return 'COMPRA'
        d = str(direccion).upper().strip()
        if d in ('BUY', 'LONG', 'COMPRA', 'B', '0'):
            return 'COMPRA'
        if d in ('SELL', 'SHORT', 'VENTA', 'S', '1'):
            return 'VENTA'
        return 'COMPRA'

    def _obtener_digits(self, simbolo: str) -> int:
        try:
            from utils.parametros_simbolo import get_digits
            return get_digits(simbolo)
        except (ImportError, RecursionError):
            pass
        s = simbolo.upper()
        if 'JPY' in s: return 3
        if 'XAU' in s: return 2
        if 'XAG' in s: return 3
        if any(x in s for x in ('US30', 'NAS100', 'US500')): return 1
        if any(c in s for c in ('BTC', 'ETH', 'SOL')): return 2
        return 5

    def _obtener_pip_val(self, simbolo: str, precio: float = 0.0) -> float:
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
    # ✅ FIX PRINCIPAL: CÁLCULO ROBUSTO DE TIEMPO ABIERTO
    # ============================================================

    def _calcular_tiempo_abierto_minutos(
        self,
        pos: Dict[str, Any],
        fecha_actual: datetime,
    ) -> float:
        """
        Calcula minutos desde apertura. Acepta múltiples formatos de timestamp.

        Formatos soportados (en orden de prioridad):
        - 'fecha_entrada' (datetime)      → backtest / estado interno
        - 'time_msc' (unix ms)            → MT5 posiciones
        - 'time' (unix s)                 → MT5 posiciones
        - 'timestamp_apertura' (str ISO)  → almacén interno

        Si ninguno existe → retorna 0 (NO un default de fecha_actual, que era el bug).
        """
        # Normalizar fecha_actual
        if fecha_actual.tzinfo is None:
            fecha_actual = fecha_actual.replace(tzinfo=timezone.utc)

        # 1. fecha_entrada (datetime)
        fe = pos.get('fecha_entrada')
        if isinstance(fe, datetime):
            if fe.tzinfo is None:
                fe = fe.replace(tzinfo=timezone.utc)
            return max(0.0, (fecha_actual - fe).total_seconds() / 60.0)

        # 2. time_msc (ms unix)
        tmsc = pos.get('time_msc')
        if tmsc:
            try:
                fe = datetime.fromtimestamp(float(tmsc) / 1000.0, tz=timezone.utc)
                return max(0.0, (fecha_actual - fe).total_seconds() / 60.0)
            except (ValueError, TypeError, OSError):
                pass

        # 3. time (s unix)
        t = pos.get('time')
        if t:
            try:
                fe = datetime.fromtimestamp(float(t), tz=timezone.utc)
                return max(0.0, (fecha_actual - fe).total_seconds() / 60.0)
            except (ValueError, TypeError, OSError):
                pass

        # 4. timestamp_apertura (str ISO)
        ts = pos.get('timestamp_apertura')
        if isinstance(ts, str):
            try:
                fe = datetime.fromisoformat(ts)
                if fe.tzinfo is None:
                    fe = fe.replace(tzinfo=timezone.utc)
                return max(0.0, (fecha_actual - fe).total_seconds() / 60.0)
            except ValueError:
                pass

        # 5. Fallback: 0 minutos (NO fecha_actual, que era el bug)
        self.logger.warning(
            f"⚠️ {pos.get('simbolo', '?')}: Sin timestamp de apertura para calcular timeout"
        )
        return 0.0

    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================

    def calcular_movimiento_sl(
        self,
        pos: Dict[str, Any],
        df_h1: Optional[Any],
        precio_actual: float,
        fecha: datetime,
        regimen: str = 'INCERTO',
        modo: str = 'RETEST',
    ) -> DecisionTrailing:
        """Calcula si se debe mover el SL y a dónde."""
        simbolo = pos.get('simbolo', '')
        direccion = self._normalizar_direccion(
            pos.get('direccion', pos.get('tipo', 'COMPRA'))
        )
        entry_price = pos.get('entrada', pos.get('precio_apertura', 0))
        sl_actual = pos.get('sl', 0)

        if entry_price <= 0 or sl_actual <= 0:
            return DecisionTrailing(razon="Datos de posición inválidos")

        pip_val = self._obtener_pip_val(simbolo, precio_actual)
        if pip_val <= 0:
            pip_val = 0.0001

        digits = self._obtener_digits(simbolo)

        # Ganancia en pips
        if direccion == 'COMPRA':
            ganancia_pips = (precio_actual - entry_price) / pip_val
        else:
            ganancia_pips = (entry_price - precio_actual) / pip_val

        # Reanálisis
        analisis = self._reanalizar_mercado(
            simbolo=simbolo,
            df_h1=df_h1,
            precio_actual=precio_actual,
            entry_price=entry_price,
            direccion=direccion,
            soporte_original=pos.get('nivel_usado', 0),
            regimen=regimen,
            modo=modo,
            ganancia_pips=ganancia_pips,
        )

        if analisis.cerrar:
            return DecisionTrailing(
                cerrar=True,
                motivo_cierre=analisis.razon,
                razon=f"Cierre por reanálisis: {analisis.razon}",
                analisis=analisis.__dict__,
            )

        # Configuración
        cfg = self.CONFIG_POR_MODO.get(modo, self.CONFIG_POR_MODO['RETEST']).copy()
        mult = self.REGIMEN_MULTIPLICADORES.get(regimen, 1.0)
        cfg['breakeven_umbral'] = int(cfg['breakeven_umbral'] * mult)
        cfg['trailing_umbral'] = int(cfg['trailing_umbral'] * mult)
        cfg['trailing_agresivo_umbral'] = int(cfg['trailing_agresivo_umbral'] * mult)

        if self.modo_backtest:
            cfg['breakeven_umbral'] = max(5, cfg['breakeven_umbral'] - 5)
            cfg['trailing_umbral'] = max(10, cfg['trailing_umbral'] - 10)

        decision = self._decidir_trailing(
            ganancia_pips=ganancia_pips,
            precio_actual=precio_actual,
            entry_price=entry_price,
            sl_actual=sl_actual,
            direccion=direccion,
            cfg=cfg,
            pip_val=pip_val,
            digits=digits,
            analisis=analisis,
        )
        decision.analisis = analisis.__dict__
        self._log_decision(simbolo, ganancia_pips, decision)
        return decision

    def _decidir_trailing(
        self, ganancia_pips, precio_actual, entry_price, sl_actual,
        direccion, cfg, pip_val, digits, analisis,
    ) -> DecisionTrailing:
        """Decide qué fase aplicar (la mejor, no la primera)."""
        if ganancia_pips < cfg.get('min_pips_para_mover', 15):
            return DecisionTrailing(
                razon=f"Ganancia insuficiente ({ganancia_pips:.1f}pips)",
                fase="ESPERA",
            )

        mejor: Optional[DecisionTrailing] = None
        mejor_dist = float('inf')

        # FASE 1: BREAKEVEN
        if ganancia_pips >= cfg['breakeven_umbral']:
            if direccion == 'COMPRA':
                nuevo = entry_price + cfg['breakeven_margen'] * pip_val
            else:
                nuevo = entry_price - cfg['breakeven_margen'] * pip_val

            razon = f"BREAKEVEN (umbral {cfg['breakeven_umbral']}pips)"
            if analisis.resistencia_cercana and direccion == 'COMPRA':
                nuevo = entry_price + 2 * pip_val
                razon = f"BREAKEVEN_URGENTE"
            elif analisis.soporte_cercano and direccion == 'VENTA':
                nuevo = entry_price - 2 * pip_val
                razon = f"BREAKEVEN_URGENTE"

            cand = self._crear_decision_sl(nuevo, sl_actual, direccion, razon, "BREAKEVEN")
            if cand.mover_sl:
                d = abs(precio_actual - nuevo)
                if d < mejor_dist:
                    mejor, mejor_dist = cand, d

        # FASE 2: TRAILING SUAVE
        if ganancia_pips >= cfg['trailing_umbral']:
            if direccion == 'COMPRA':
                nuevo = precio_actual - cfg['trailing_distancia'] * pip_val
            else:
                nuevo = precio_actual + cfg['trailing_distancia'] * pip_val

            cand = self._crear_decision_sl(
                nuevo, sl_actual, direccion,
                f"TRAILING_SUAVE ({cfg['trailing_distancia']}pips)",
                "TRAILING_SUAVE",
            )
            if cand.mover_sl:
                d = abs(precio_actual - nuevo)
                if d < mejor_dist:
                    mejor, mejor_dist = cand, d

        # FASE 3: TRAILING AGRESIVO
        if ganancia_pips >= cfg['trailing_agresivo_umbral']:
            if direccion == 'COMPRA':
                nuevo = precio_actual - cfg['trailing_agresivo_distancia'] * pip_val
            else:
                nuevo = precio_actual + cfg['trailing_agresivo_distancia'] * pip_val

            cand = self._crear_decision_sl(
                nuevo, sl_actual, direccion,
                f"TRAILING_AGRESSIVO ({cfg['trailing_agresivo_distancia']}pips)",
                "TRAILING_AGRESSIVO",
            )
            if cand.mover_sl:
                d = abs(precio_actual - nuevo)
                if d < mejor_dist:
                    mejor, mejor_dist = cand, d

        return mejor or DecisionTrailing(razon="Sin cambio de SL", fase="NINGUNA")

    def _crear_decision_sl(self, nuevo_sl, sl_actual, direccion, razon, fase) -> DecisionTrailing:
        """Crea decisión validando monotonicidad."""
        if direccion == 'COMPRA' and nuevo_sl <= sl_actual:
            return DecisionTrailing(razon=f"SL no mejora", fase=fase)
        if direccion == 'VENTA' and nuevo_sl >= sl_actual:
            return DecisionTrailing(razon=f"SL no mejora", fase=fase)
        return DecisionTrailing(mover_sl=True, nuevo_sl=nuevo_sl, razon=razon, fase=fase)

    # ============================================================
    # REANÁLISIS DE MERCADO
    # ============================================================

    def _reanalizar_mercado(
        self, simbolo, df_h1, precio_actual, entry_price,
        direccion, soporte_original, regimen, modo, ganancia_pips,
    ) -> AnalisisMercado:
        """Reanálisis con cache por hash (no id())."""
        resultado = AnalisisMercado()

        if df_h1 is None or len(df_h1) < 20:
            resultado.razon = "Sin datos suficientes"
            return resultado

        # Cache key por hash del df
        try:
            cache_key = self._hash_df(df_h1)
            cached = self._cache_analisis.get(cache_key)
            if cached:
                return AnalisisMercado(**cached)
        except Exception:
            cache_key = None

        try:
            high = df_h1['High']
            low = df_h1['Low']
            lookback = min(50, len(df_h1))

            # Soportes / resistencias locales
            soportes: List[float] = []
            resistencias: List[float] = []

            for i in range(5, len(df_h1) - 5):
                if low.iloc[i] == low.iloc[i - 5:i + 5].min():
                    soportes.append(float(low.iloc[i]))
                if high.iloc[i] == high.iloc[i - 5:i + 5].max():
                    resistencias.append(float(high.iloc[i]))

            # Soporte original
            if soporte_original > 0:
                min_reciente = float(low.iloc[-20:].min())
                if min_reciente >= soporte_original * 0.999:
                    resultado.soporte_intacto = True
                    resultado.dist_soporte = (precio_actual - soporte_original) / soporte_original * 100
                else:
                    resultado.cerrar = True
                    resultado.razon = f"Soporte roto (orig: {soporte_original:.5f})"
                    return resultado

            # Soporte cercano
            for p in soportes:
                dist = (precio_actual - p) / precio_actual * 100
                if 0 < dist < 1.0 and dist < resultado.dist_soporte:
                    resultado.soporte_cercano = True
                    resultado.dist_soporte = dist

            # Resistencia cercana
            for p in resistencias:
                dist = (p - precio_actual) / precio_actual * 100
                if 0 < dist < 1.0 and dist < resultado.dist_resistencia:
                    resultado.resistencia_cercana = True
                    resultado.dist_resistencia = dist

            # Pullback
            if resultado.soporte_cercano and ganancia_pips > 10 and resultado.dist_soporte < 0.5:
                resultado.pullback_valido = True

            # Ruptura de estructura
            max_rec = float(high.iloc[-lookback:].max())
            min_rec = float(low.iloc[-lookback:].min())

            if direccion == 'COMPRA' and precio_actual < min_rec:
                resultado.estructura_rota = True
                resultado.cerrar = True
                resultado.razon = "Ruptura de mínimo reciente"
                return resultado
            elif direccion == 'VENTA' and precio_actual > max_rec:
                resultado.estructura_rota = True
                resultado.cerrar = True
                resultado.razon = "Ruptura de máximo reciente"
                return resultado

            # Cambio de régimen
            if regimen in ('CHOP_VOLATIL', 'INCERTO') and ganancia_pips < 5:
                resultado.regimen_cambio = True
                resultado.cerrar = True
                resultado.razon = f"Régimen {regimen} sin avance"
                return resultado

            resultado.razon = "Análisis completado"

        except Exception as e:
            self.logger.error(f"Error en reanálisis {simbolo}: {e}")
            resultado.razon = f"Error: {e}"

        # Guardar en caché
        if cache_key:
            self._cache_analisis[cache_key] = resultado.__dict__

        return resultado

    def _hash_df(self, df) -> str:
        """Hash rápido para cache de df."""
        try:
            n = min(20, len(df))
            closes = df['Close'].iloc[-n:].values.tobytes()
            return hashlib.md5(closes).hexdigest()[:16]
        except Exception:
            return ""

    # ============================================================
    # ✅ FIX: TIMEOUT
    # ============================================================

    def verificar_timeout(
        self,
        pos: Dict[str, Any],
        fecha: datetime,
        ganancia_pips: float,
        modo: str = 'RETEST',
    ) -> Tuple[bool, str]:
        """
        Verifica si debe cerrarse por TIMEOUT.

        FIX V10.0:
        - Antes usaba pos.get('fecha_entrada', fecha) → siempre devolvía 0 minutos
        - Ahora usa _calcular_tiempo_abierto_minutos() con múltiples formatos
        """
        tiempo_abierto = self._calcular_tiempo_abierto_minutos(pos, fecha)

        cfg = self.CONFIG_POR_MODO.get(modo, self.CONFIG_POR_MODO['RETEST'])
        timeout_min = cfg.get('timeout_minutos', 480)

        if tiempo_abierto > timeout_min:
            if ganancia_pips > 15:
                return False, f"Timeout con ganancia significativa ({ganancia_pips:.1f}pips)"
            if 5 < ganancia_pips <= 15:
                return False, f"Timeout con ganancia moderada"
            if ganancia_pips < 0:
                return True, f"TIMEOUT_PERDIDA ({tiempo_abierto:.0f}min)"
            if abs(ganancia_pips) < 5:
                return True, f"TIMEOUT_BREAKEVEN ({tiempo_abierto:.0f}min)"

        return False, "OK"

    # ============================================================
    # CIERRE PARCIAL
    # ============================================================

    def verificar_cierre_parcial(
        self,
        pos: Dict[str, Any],
        ganancia_pips: float,
        modo: str = 'RETEST',
    ) -> Tuple[bool, float]:
        """Cierre parcial en 1R."""
        if pos.get('tp1_realizado', False):
            return False, 0.0

        cfg = self.CONFIG_POR_MODO.get(modo, self.CONFIG_POR_MODO['RETEST'])
        umbral = cfg.get('cierre_parcial_umbral', 25)
        pct = cfg.get('cierre_parcial_porcentaje', 0.5)

        if ganancia_pips > umbral:
            volumen = pos.get('lotes', 0)
            vol_cerrar = volumen * pct
            if vol_cerrar >= 0.01:
                return True, round(vol_cerrar, 3)
        return False, 0.0

    # ============================================================
    # LOGGING
    # ============================================================

    def _log_decision(self, simbolo: str, ganancia_pips: float, decision: DecisionTrailing):
        if decision.mover_sl:
            self.logger.info(
                f"🔄 {simbolo}: {decision.razon} | "
                f"SL→{decision.nuevo_sl:.5f} | "
                f"Ganancia: {ganancia_pips:.1f}pips | Fase: {decision.fase}"
            )
        elif decision.cerrar:
            self.logger.info(
                f"🔒 {simbolo}: {decision.razon} | Ganancia: {ganancia_pips:.1f}pips"
            )
        elif self.modo_depuracion:
            self.logger.debug(f"⏭️ {simbolo}: {decision.razon}")

    # ============================================================
    # MANTENIMIENTO
    # ============================================================

    def limpiar_cache(self):
        self._cache_analisis.clear()

    # ============================================================
    # COMPATIBILIDAD
    # ============================================================

    def calcular_movimiento_sl_legacy(self, pos, df_h1, precio_actual, fecha,
                                     regimen='INCERTO', modo='RETEST') -> Dict[str, Any]:
        d = self.calcular_movimiento_sl(pos, df_h1, precio_actual, fecha, regimen, modo)
        return {
            'mover_sl': d.mover_sl,
            'nuevo_sl': d.nuevo_sl,
            'razon': d.razon,
            'cerrar': d.cerrar,
            'motivo_cierre': d.motivo_cierre,
            'analisis': d.analisis,
        }


# ============================================================
# FACTORY
# ============================================================

def create_trailing_engine(
    config: Optional[Any] = None,
    modo_backtest: bool = False,
    modo_depuracion: bool = False,
) -> TrailingEngine:
    return TrailingEngine(config=config, modo_backtest=modo_backtest, modo_depuracion=modo_depuracion)


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Test TrailingEngine V10.0 (verificar_timeout)...")

    engine = TrailingEngine(modo_backtest=True, modo_depuracion=True)

    now = now_utc()

    # Timeout efectivo en backtest para RETEST: 480 * 0.5 = 240 min (4h)
    TIMEOUT_MIN = engine.CONFIG_POR_MODO['RETEST']['timeout_minutos']
    print(f"⏱️ Timeout efectivo RETEST: {TIMEOUT_MIN} min")

    # TEST 1: 'time' unix — 5h atrás (> timeout)
    pos1 = {
        'simbolo': 'EURUSD', 'direccion': 'COMPRA',
        'entrada': 1.1000, 'sl': 1.0990, 'lotes': 0.01,
        'time': int((now - timedelta(hours=5)).timestamp()),
    }
    debe, razon = engine.verificar_timeout(pos1, now, ganancia_pips=-5)
    print(f"TEST 1 (time unix, 5h, pérdida): {debe} - {razon}")
    assert debe is True, "❌ Debería cerrar"

    # TEST 2: 'time_msc' — 30 min atrás (< timeout)
    pos2 = {
        'simbolo': 'EURUSD', 'direccion': 'COMPRA',
        'entrada': 1.1000, 'sl': 1.0990, 'lotes': 0.01,
        'time_msc': int((now - timedelta(minutes=30)).timestamp() * 1000),
    }
    debe, razon = engine.verificar_timeout(pos2, now, ganancia_pips=-5)
    print(f"TEST 2 (time_msc, 30min): {debe} - {razon}")
    assert debe is False, "❌ No debería cerrar"

    # TEST 3: 'fecha_entrada' datetime — 5h (> timeout)
    pos3 = {
        'simbolo': 'EURUSD', 'direccion': 'COMPRA',
        'entrada': 1.1000, 'sl': 1.0990, 'lotes': 0.01,
        'fecha_entrada': now - timedelta(hours=5),
    }
    debe, razon = engine.verificar_timeout(pos3, now, ganancia_pips=-3)
    print(f"TEST 3 (fecha_entrada, 5h, pérdida): {debe} - {razon}")
    assert debe is True, "❌ Debería cerrar"

    # TEST 4: sin timestamp → no cierra (evita el bug anterior)
    pos4 = {
        'simbolo': 'EURUSD', 'direccion': 'COMPRA',
        'entrada': 1.1000, 'sl': 1.0990, 'lotes': 0.01,
    }
    debe, razon = engine.verificar_timeout(pos4, now, ganancia_pips=-3)
    print(f"TEST 4 (sin timestamp): {debe} - {razon}")
    assert debe is False, "❌ No debe cerrar sin datos"

    # TEST 5: 'timestamp_apertura' ISO string
    pos5 = {
        'simbolo': 'EURUSD', 'direccion': 'COMPRA',
        'entrada': 1.1000, 'sl': 1.0990, 'lotes': 0.01,
        'timestamp_apertura': (now - timedelta(hours=6)).isoformat(),
    }
    debe, razon = engine.verificar_timeout(pos5, now, ganancia_pips=-8)
    print(f"TEST 5 (timestamp ISO, 6h, pérdida): {debe} - {razon}")
    assert debe is True, "❌ Debería cerrar"

    print("\n✅ Todos los tests pasan")