#!/usr/bin/env python3
"""
trading/ejecucion.py (V10.0 - CONTEXTO COMPLETO PARA ML)
Ejecución de órdenes de trading con validación completa y contexto ML.

CAMBIOS V10.0:
- ✅ contexto_apertura completo (regimen, sesion, modo, scores, ML prob, etc.)
- ✅ Se guarda en SQLite + memoria (posiciones_abiertas) para el monitor
- ✅ Nuevo método _inferir_sesion_actual()
- ✅ Preserva direccion_m15, stop_hunt, rechazo_confirmado, confluencias
- ✅ Compatible con SniperChecklist V10.2

MANTIENE:
- Cálculo correcto de valor de pip para JPY (V9.74)
- Validación de SL/TP considerando spread
- Prevención de duplicados
- Lotes mínimos por tipo de activo
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from decimal import Decimal

from trading.stops import GestorStops, create_gestor_stops
from utils.reloj import now_utc

logger = logging.getLogger('BotTrading.Ejecucion')


class EjecutorOperaciones:
    """
    Ejecuta órdenes de trading con validación robusta.
    V10.0 - CONTEXTO COMPLETO PARA ML.
    """

    def __init__(self,
                 orquestador: Any,
                 mt5: Any,
                 gestion_riesgo: Any,
                 gestor_stops: Any,
                 notificaciones: Any,
                 modo_backtest: bool = False,
                 almacen: Optional[Any] = None):
        """Inicializa el ejecutor de operaciones."""
        self.orquestador = orquestador
        self.mt5 = mt5
        self.gestion_riesgo = gestion_riesgo
        self.gestor_stops = gestor_stops
        self.notificaciones = notificaciones
        self.almacen = almacen
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.Ejecutor')

        self._lock_operaciones = threading.Lock()
        self._operaciones_pendientes: Dict[str, str] = {}
        self._reintentos_por_simbolo: Dict[str, int] = {}
        self._max_reintentos = 3

        # Mínimos absolutos
        self.SL_MINIMO_ABSOLUTO_PIPS = 5
        self.TP_FACTOR_MINIMO = 1.2

        self.logger.info("📈 EjecutorOperaciones V10.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   SL mínimo: {self.SL_MINIMO_ABSOLUTO_PIPS} pips")
        self.logger.info(f"   TP mínimo: {self.TP_FACTOR_MINIMO}x SL")

    # ============================================================
    # HELPERS DE SÍMBOLO
    # ============================================================

    def _obtener_pip_val(self, simbolo: str) -> float:
        """
        Obtiene el valor de un pip para el símbolo.
        3 fuentes en orden: MT5, nombre del símbolo, default Forex.
        """
        simbolo_upper = simbolo.upper()

        # FUENTE 1: MT5
        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, '_pip_size_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None and hasattr(info, 'point') and info.point > 0:
                    point = float(info.point)

                    if 'JPY' in simbolo_upper:
                        pip_val = 0.01
                    elif 'XAU' in simbolo_upper:
                        pip_val = 0.10
                    elif 'XAG' in simbolo_upper:
                        pip_val = 0.01
                    elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
                        pip_val = 1.0
                    elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                        pip_val = 1.0
                    else:
                        pip_val = point * 10 if point < 0.001 else point

                    if 'XAU' in simbolo_upper and pip_val == 0.0001:
                        return 0.10
                    if 'BTC' in simbolo_upper and pip_val == 0.0001:
                        return 1.0
                    return pip_val
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: Error obteniendo pip_val de MT5: {e}")

        # FUENTE 2: Nombre del símbolo
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.10
        if 'XAG' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0

        # FUENTE 3: Default Forex
        return 0.0001

    def _obtener_precio_actual(self, simbolo: str) -> float:
        """Obtiene el precio actual del símbolo."""
        if self.modo_backtest:
            return 1.0

        try:
            tick = self.mt5.obtener_precio(simbolo)
            if tick:
                return float(tick.get('bid', tick.get('ask', 0)))
        except Exception as e:
            self.logger.debug(f"⚠️ Error obteniendo precio para {simbolo}: {e}")

        return 1.0

    def _calcular_valor_pip(self, simbolo: str) -> float:
        """Calcula el valor de 1 pip en USD para 1 lote estándar."""
        simbolo_upper = simbolo.upper()
        tamano_contrato = self._obtener_tamano_contrato(simbolo)
        pip_val = self._obtener_pip_val(simbolo)

        # Para pares JPY, el valor depende del precio actual
        if 'JPY' in simbolo_upper:
            precio_actual = self._obtener_precio_actual(simbolo)
            if precio_actual > 0:
                return (tamano_contrato * pip_val) / precio_actual
            return tamano_contrato * pip_val / 100

        return tamano_contrato * pip_val

    def _obtener_tamano_contrato(self, simbolo: str) -> float:
        """Obtiene el tamaño del contrato para cada símbolo."""
        simbolo_upper = simbolo.upper()

        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, 'obtener_info_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None and hasattr(info, 'trade_contract_size') and info.trade_contract_size > 0:
                    return float(info.trade_contract_size)
            except Exception:
                pass

        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        if 'XAU' in simbolo_upper:
            return 100.0
        if 'XAG' in simbolo_upper:
            return 5000.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        return 100000.0

    def _obtener_digits(self, simbolo: str) -> int:
        """Obtiene el número de decimales para el símbolo."""
        simbolo_upper = simbolo.upper()

        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, 'obtener_info_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None and hasattr(info, 'digits'):
                    digits = int(info.digits)
                    if 'XAU' in simbolo_upper and digits == 5:
                        return 2
                    if 'JPY' in simbolo_upper and digits == 5:
                        return 3
                    return digits
            except Exception:
                pass

        if 'JPY' in simbolo_upper:
            return 3
        if 'XAU' in simbolo_upper:
            return 2
        if 'XAG' in simbolo_upper:
            return 3
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1
        if 'BTC' in simbolo_upper or 'ETH' in simbolo_upper or 'SOL' in simbolo_upper:
            return 2
        return 5

    def _obtener_apalancamiento_real(self, simbolo: str) -> float:
        """Obtiene el apalancamiento real del broker."""
        if not self.modo_backtest and self.mt5:
            try:
                cuenta = self.mt5.info_cuenta()
                if cuenta:
                    apalancamiento = float(cuenta.get('apalancamiento', 0) or 0)
                    if apalancamiento > 0:
                        return apalancamiento
            except Exception:
                pass

        simbolo_upper = simbolo.upper()
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            return 200
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 20
        elif 'BTC' in simbolo_upper:
            return 2
        elif any(c in simbolo_upper for c in ['ETH', 'SOL']):
            return 5
        else:
            return 500

    def _obtener_spread_max(self, simbolo: str) -> float:
        """Obtiene el spread máximo permitido."""
        simbolo_upper = simbolo.upper()
        spread_max = {
            'EURUSD': 2, 'GBPUSD': 2, 'USDJPY': 2,
            'AUDUSD': 2, 'USDCAD': 2, 'USDCHF': 2,
            'EURJPY': 3, 'GBPJPY': 3, 'AUDJPY': 3,
            'XAUUSD': 30, 'XAGUSD': 30,
            'US30': 5, 'NAS100': 5, 'US500': 5,
            'BTCUSD': 50, 'ETHUSD': 50, 'SOLUSD': 50,
        }
        return spread_max.get(simbolo_upper, 3)

    def _obtener_paso_lote(self, simbolo: str) -> float:
        """Obtiene el paso de lote del broker."""
        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, 'obtener_info_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None:
                    if hasattr(info, 'volume_step') and info.volume_step > 0:
                        return float(info.volume_step)
                    if hasattr(info, 'trade_volume_step') and info.trade_volume_step > 0:
                        return float(info.trade_volume_step)
            except Exception:
                pass
        return 0.01

    def _estimar_margen(self, simbolo: str, lotes: float, precio: float) -> float:
        """Estima el margen requerido."""
        simbolo_upper = simbolo.upper()
        apalancamiento = self._obtener_apalancamiento_real(simbolo)
        contract_size = self._obtener_tamano_contrato(simbolo)

        valor_operacion = lotes * contract_size * precio

        if simbolo_upper.endswith('JPY'):
            valor_operacion_usd = valor_operacion / precio
        else:
            valor_operacion_usd = valor_operacion

        return valor_operacion_usd / apalancamiento

    def _inferir_sesion_actual(self) -> str:
        """
        ✅ V10.0: Infiere la sesión de mercado actual desde UTC.
        Usado para poblar contexto_apertura y para el ML.
        """
        try:
            hora = now_utc().hour + now_utc().minute / 60.0

            if 0 <= hora < 8:
                return 'ASIAN'
            if 13 <= hora < 16:
                return 'OVERLAP_LDN_NY'
            if 8 <= hora < 16:
                return 'LONDON'
            if 16 <= hora < 22:
                return 'NEW_YORK'
            return 'ASIAN'
        except Exception:
            return 'LONDON'

    # ============================================================
    # ✅ V10.0: CONSTRUCCIÓN DEL CONTEXTO COMPLETO
    # ============================================================

    def _construir_contexto_apertura(
        self,
        señal: Dict[str, Any],
        regimen: str,
        modo: str,
        score: float,
        calidad_horario: str,
    ) -> Dict[str, Any]:
        """
        Construye el contexto_apertura completo para el ML.
        Este snapshot es lo que permite al modelo aprender POR QUÉ se abrió.
        """
        niveles_usados = señal.get('niveles_usados', {}) or {}

        return {
            # Contexto base
            'regimen': regimen,
            'sesion': self._inferir_sesion_actual(),
            'modo': modo,
            'calidad_horario': calidad_horario,

            # Scores
            'score': score,
            'score_h1': señal.get('score_h1', 0),
            'score_m5': señal.get('score_m5', 0),
            'prob_ml': señal.get('prob_ml'),

            # Direccionalidad multi-TF
            'direccion_m15': señal.get('direccion_m15', 'NEUTRAL'),
            'direccion_regimen': señal.get('regimen', 'NONE'),

            # Detección de manipulación
            'stop_hunt_detectado': señal.get('stop_hunt_detectado', False),
            'razon_stop_hunt': señal.get('razon_stop_hunt', ''),
            'rechazo_confirmado': señal.get('rechazo_confirmado', False),

            # Niveles
            'nivel_usado': niveles_usados.get('nivel_usado'),
            'soporte_cercano': niveles_usados.get('soporte_cercano'),
            'resistencia_cercana': niveles_usados.get('resistencia_cercana'),
            'en_nivel_clave': señal.get('en_nivel_clave', False),
            'es_reversal': señal.get('es_reversal', False),

            # Métricas
            'rr': señal.get('rr', 0),
            'volumen_relativo': señal.get('volumen_relativo', 1.0),
            'patron_calidad': señal.get('patron_calidad', 0),
            'adx_h1': señal.get('adx_h1', 0),

            # Confluencias (estructura anidada)
            'confluencias': señal.get('confluencias', {}),

            # Referencia al dict de niveles (para el monitor)
            'niveles': niveles_usados,
        }

    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================

    def ejecutar(self, señal: Dict[str, Any]) -> bool:
        """
        Ejecuta una operación con validación completa.
        V10.0 - Incluye contexto_apertura completo para el ML.
        """
        from config.umbrales import Umbrales

        # ============================================================
        # 1. EXTRAER DATOS DE LA SEÑAL
        # ============================================================
        simbolo = señal.get('simbolo')
        direccion = señal.get('direccion')
        entry_price = señal.get('entry_price', 0)
        sl = señal.get('sl', 0)
        tp = señal.get('tp', 0)
        tp2 = señal.get('tp2', 0)
        score = señal.get('score', 0)
        modo = señal.get('modo', 'RETEST')
        regimen = señal.get('regimen', 'INCERTO')
        calidad_horario = señal.get('calidad_horario', 'REGULAR')
        volumen_relativo = señal.get('volumen_relativo', 1.0)

        self.logger.info(f"🚀 Ejecutando {simbolo} {direccion}...")
        self.logger.info(f"   Entry: {entry_price:.5f}, SL: {sl:.5f}, TP: {tp:.5f}")
        self.logger.info(f"   Modo: {modo}, Score: {score:.1f}")

        prob_ml = señal.get('prob_ml')
        if prob_ml is not None:
            self.logger.info(f"   ML prob: {prob_ml:.3f}")

        # ============================================================
        # 2. VALIDACIONES PREVIAS
        # ============================================================
        if not simbolo or not direccion:
            self.logger.error("❌ Señal incompleta")
            return False

        direccion = direccion.upper().strip()
        if direccion in ['BUY', 'LONG']:
            direccion = 'COMPRA'
        elif direccion in ['SELL', 'SHORT']:
            direccion = 'VENTA'

        if direccion not in ['COMPRA', 'VENTA']:
            self.logger.error(f"❌ Dirección inválida: {direccion}")
            return False

        if entry_price <= 0 or sl <= 0 or tp <= 0:
            self.logger.error(f"❌ Precios inválidos: entry={entry_price}, sl={sl}, tp={tp}")
            return False

        # Validar SL/TP
        if direccion == 'COMPRA':
            if sl >= entry_price:
                self.logger.error(f"❌ {simbolo}: SL INVERTIDO (SL={sl:.5f} >= Entry={entry_price:.5f})")
                return False
            if tp <= entry_price:
                self.logger.error(f"❌ {simbolo}: TP INVERTIDO (TP={tp:.5f} <= Entry={entry_price:.5f})")
                return False
            if tp <= sl:
                self.logger.error(f"❌ {simbolo}: TP <= SL (TP={tp:.5f} <= SL={sl:.5f})")
                return False
        else:
            if sl <= entry_price:
                self.logger.error(f"❌ {simbolo}: SL INVERTIDO (SL={sl:.5f} <= Entry={entry_price:.5f})")
                return False
            if tp >= entry_price:
                self.logger.error(f"❌ {simbolo}: TP INVERTIDO (TP={tp:.5f} >= Entry={entry_price:.5f})")
                return False
            if tp >= sl:
                self.logger.error(f"❌ {simbolo}: TP >= SL (TP={tp:.5f} >= SL={sl:.5f})")
                return False

        # Validar SL mínimo
        pip_val = self._obtener_pip_val(simbolo)
        if pip_val <= 0:
            pip_val = 0.0001

        sl_dist = abs(entry_price - sl)
        sl_dist_pips = sl_dist / pip_val if pip_val > 0 else 0

        if sl_dist_pips < self.SL_MINIMO_ABSOLUTO_PIPS:
            self.logger.error(
                f"❌ {simbolo}: SL demasiado cerca "
                f"({sl_dist_pips:.1f} pips < {self.SL_MINIMO_ABSOLUTO_PIPS})"
            )
            return False

        # Validar TP mínimo
        tp_dist = abs(tp - entry_price)
        tp_dist_pips = tp_dist / pip_val if pip_val > 0 else 0
        min_tp_pips = sl_dist_pips * self.TP_FACTOR_MINIMO

        if tp_dist_pips < min_tp_pips:
            self.logger.error(
                f"❌ {simbolo}: TP demasiado cerca "
                f"({tp_dist_pips:.1f} pips < {min_tp_pips:.1f})"
            )
            return False

        # ============================================================
        # 3. PREVENCIÓN DE DUPLICADOS
        # ============================================================
        with self._lock_operaciones:
            if simbolo in self._operaciones_pendientes:
                self.logger.error(f"⛔ {simbolo}: Operación YA EN PROCESO")
                return False
            self._operaciones_pendientes[simbolo] = now_utc().isoformat()

        try:
            # 3.2 Verificar en MT5
            if not self.modo_backtest:
                valido, razon = self._verificar_posiciones_existentes(simbolo, direccion)
                if not valido:
                    self.logger.error(f"⛔ {razon}")
                    return False

            # 4. OBTENER CAPITAL
            capital = self._obtener_capital_real()
            if isinstance(capital, Decimal):
                capital = float(capital)

            if capital <= 0:
                self.logger.error(f"❌ Capital insuficiente: ${capital:.2f}")
                return False

            # 5. VALIDAR CAPITAL MÍNIMO
            valido_capital, razon_capital = self._validar_capital_minimo(simbolo, capital)
            if not valido_capital:
                self.logger.error(f"❌ {razon_capital}")
                return False

            self.logger.info(f"✅ {simbolo}: Capital suficiente (${capital:.2f})")

            simbolo_upper = simbolo.upper()
            digits = self._obtener_digits(simbolo)

            # 6. SL en pips
            sl_pips = sl_dist_pips
            if sl_pips <= 0:
                self.logger.error(f"❌ SL inválido: {sl_pips:.1f} pips")
                return False

            # ============================================================
            # 7. CALCULAR LOTES
            # ============================================================
            lotes_max_por_activo = getattr(Umbrales, 'LOTES_MAX_POR_ACTIVO', {})
            lotes_min_por_activo = getattr(Umbrales, 'LOTES_MIN_POR_ACTIVO', {})
            riesgo_max_por_operacion = getattr(Umbrales, 'RIESGO_MAX_POR_OPERACION', {})

            lote_max = lotes_max_por_activo.get(simbolo_upper, 0.10)
            lote_min = lotes_min_por_activo.get(simbolo_upper, 0.01)
            riesgo_pct = float(riesgo_max_por_operacion.get(simbolo_upper, 0.01))

            # Valor del pip REAL
            valor_pip_por_lote = self._calcular_valor_pip(simbolo)
            precio_actual = self._obtener_precio_actual(simbolo)

            # Spread actual
            spread_actual = 0
            if not self.modo_backtest:
                tick = self.mt5.obtener_precio(simbolo)
                if tick:
                    spread_actual = float(tick.get('spread_pips', 0))

            spread_max = self._obtener_spread_max(simbolo)

            if spread_actual > spread_max:
                factor_spread = 0.5
                self.logger.warning(f"⚠️ {simbolo}: Spread alto ({spread_actual:.1f} pips)")
            elif spread_actual > spread_max * 0.7:
                factor_spread = 0.7
            else:
                factor_spread = 1.0

            riesgo_dinero = capital * riesgo_pct

            if sl_pips > 0 and valor_pip_por_lote > 0:
                lotes_por_riesgo = riesgo_dinero / (sl_pips * valor_pip_por_lote)
            else:
                lotes_por_riesgo = lote_min

            lotes = lotes_por_riesgo * factor_spread

            paso_lote = self._obtener_paso_lote(simbolo)
            lotes = round(lotes / paso_lote) * paso_lote

            if lotes < lote_min:
                lotes = lote_min
            if lotes > lote_max:
                lotes = lote_max

            self.logger.info(f"📊 {simbolo}: Lotes calculados: {lotes:.3f}")
            self.logger.info(f"   Valor pip real: ${valor_pip_por_lote:.4f}/pip")
            self.logger.info(f"   SL: {sl_pips:.1f} pips")
            self.logger.info(f"   Riesgo: ${riesgo_dinero:.2f} ({riesgo_pct*100:.2f}%)")

            if lotes <= 0:
                self.logger.error(f"❌ {simbolo}: Lotes inválidos ({lotes:.3f})")
                return False

            # 8. Validar lote mínimo del broker
            lote_minimo_broker = self._obtener_lote_minimo_broker(simbolo)
            if lotes < lote_minimo_broker:
                lotes = lote_minimo_broker
                self.logger.info(f"📊 {simbolo}: Lotes ajustados a mínimo broker ({lotes:.3f})")

            # 9. Verificar margen real
            valido_margen, razon_margen = self._verificar_margen_real(simbolo, lotes, entry_price)
            if not valido_margen:
                self.logger.error(f"❌ {razon_margen}")
                return False

            # 10. Validar SL/TP con gestor_stops
            valido, razon, sl_validado, tp_validado, tp2_validado = self.gestor_stops.validar_sl_tp(
                simbolo=simbolo,
                entry_price=entry_price,
                sl=sl,
                tp=tp,
                tp2=tp2,
                direccion=direccion,
                regimen=regimen,
                modo=modo,
                es_reversal=señal.get('es_reversal', False),
                en_nivel_clave=señal.get('en_nivel_clave', False),
                calidad_horario=calidad_horario,
                atr_pips=señal.get('atr_pips', 0)
            )

            if not valido:
                self.logger.error(f"❌ SL/TP inválido: {razon}")
                return False

            self.logger.info(f"✅ SL/TP validado: {simbolo} {direccion}")
            self.logger.info(f"   SL: {sl_validado:.{digits}f}, TP: {tp_validado:.{digits}f}")

            # 11. Validar SL/TP por modo
            valido_modo_sl_tp, razon_modo_sl_tp = self._validar_sl_tp_por_modo(
                simbolo=simbolo,
                modo=modo,
                sl=sl_validado,
                tp=tp_validado,
                entry_price=entry_price,
                direccion=direccion,
                regimen=regimen
            )

            if not valido_modo_sl_tp:
                self.logger.error(f"❌ {razon_modo_sl_tp}")
                return False

            # 12. Validar R:R >= 1.5
            rr = abs(tp_validado - entry_price) / abs(sl_validado - entry_price) if abs(sl_validado - entry_price) > 0 else 0

            if rr < 1.5 - 0.001:
                self.logger.error(f"❌ {simbolo}: R:R insuficiente ({rr:.2f} < 1.5)")
                return False

            self.logger.info(f"✅ {simbolo}: R:R válido ({rr:.2f} >= 1.5)")

            # 13. Obtener tick actual
            tick = self.mt5.obtener_precio(simbolo) if not self.modo_backtest else None
            bid = 0
            ask = 0

            if not self.modo_backtest:
                if not tick:
                    self.logger.error(f"❌ No se pudo obtener precio para {simbolo}")
                    return False

                bid = tick.get('bid', 0)
                ask = tick.get('ask', 0)

                if direccion == 'COMPRA':
                    if sl_validado >= ask:
                        self.logger.error(f"❌ {simbolo}: SL INVERTIDO para COMPRA")
                        return False
                    if tp_validado <= ask:
                        self.logger.error(f"❌ {simbolo}: TP inválido para COMPRA")
                        return False
                else:
                    if sl_validado <= bid:
                        self.logger.error(f"❌ {simbolo}: SL INVERTIDO para VENTA")
                        return False
                    if tp_validado >= bid:
                        self.logger.error(f"❌ {simbolo}: TP inválido para VENTA")
                        return False

                if direccion == 'COMPRA':
                    precio_ejecucion = ask
                else:
                    precio_ejecucion = bid
            else:
                precio_ejecucion = entry_price

            # 14. Validación extra antes de enviar
            valido_extra, razon_extra = self._validar_sl_tp_antes_enviar(
                simbolo=simbolo,
                entry_price=entry_price,
                sl=sl_validado,
                tp=tp_validado,
                direccion=direccion,
                bid=bid,
                ask=ask
            )

            if not valido_extra:
                self.logger.error(f"❌ {simbolo}: {razon_extra}")
                return False

            self.logger.info(f"✅ {simbolo}: SL/TP validado correctamente antes de enviar")

            # ============================================================
            # 15. ENVIAR ORDEN
            # ============================================================
            comentario = f"Bot_{modo}_{score:.0f}"

            magic_number = getattr(self.mt5, 'magic_number', None)
            if magic_number is None:
                magic_number = getattr(self.orquestador.config, 'MAGIC_NUMBER', 0)

            try:
                resultado = self.mt5.enviar_orden(
                    simbolo=simbolo,
                    tipo=direccion,
                    volumen=lotes,
                    sl=sl_validado,
                    tp=tp_validado,
                    comentario=comentario,
                    magic_number=magic_number
                )
            except TypeError:
                self.logger.warning(f"⚠️ {simbolo}: Conector no acepta magic_number")
                resultado = self.mt5.enviar_orden(
                    simbolo=simbolo,
                    tipo=direccion,
                    volumen=lotes,
                    sl=sl_validado,
                    tp=tp_validado,
                    comentario=comentario
                )

            if not resultado or resultado.get('ticket') is None:
                self.logger.error(f"❌ Falló ejecución de {simbolo}: {resultado.get('comentario', 'Error')}")
                return False

            # SL/TP reales del broker
            sl_real = resultado.get('sl', sl_validado)
            tp_real = resultado.get('tp', tp_validado)
            precio_ejecutado = resultado.get('precio', precio_ejecucion)

            # ============================================================
            # 16. REGISTRAR OPERACIÓN (CON CONTEXTO COMPLETO PARA ML)
            # ============================================================
            ticket = resultado.get('ticket')

            # ✅ V10.0: construir contexto_apertura completo
            contexto_apertura = self._construir_contexto_apertura(
                señal=señal,
                regimen=regimen,
                modo=modo,
                score=score,
                calidad_horario=calidad_horario,
            )

            operacion = {
                'ticket': ticket,
                'simbolo': simbolo,
                'direccion': direccion,
                'entrada': precio_ejecutado,
                'lotes': lotes,
                'sl': sl_real,
                'tp': tp_real,
                'tp2': tp2_validado,
                'timestamp': now_utc().isoformat(),
                'estado': 'ABIERTA',
                'modo': modo,
                'score': score,
                'regimen': regimen,
                'direccion_m15': señal.get('direccion_m15', 'NEUTRAL'),
                'prob_ml': prob_ml,
                'es_sniper': True,
                # ✅ V10.0: contexto completo (features para ML)
                'contexto_apertura': contexto_apertura,
            }

            # Guardar en SQLite
            if self.almacen:
                try:
                    self.almacen.guardar_operacion(operacion)
                except Exception as e:
                    self.logger.warning(f"⚠️ Error guardando operación: {e}")

            # ✅ Guardar en memoria (para el monitor)
            if hasattr(self, 'orquestador') and self.orquestador:
                self.orquestador.estado.posiciones_abiertas[ticket] = operacion

            # Notificar
            self.notificaciones.notificar_operacion({
                'simbolo': simbolo,
                'direccion': direccion,
                'entrada': precio_ejecutado,
                'sl': sl_real,
                'tp': tp_real,
                'lotes': lotes,
                'score': score,
                'modo': modo,
                'ticket': ticket,
                'es_sniper': True,
                'prob_ml': prob_ml,
            })

            self.logger.info(
                f"✅ ORDEN EJECUTADA: {simbolo} {direccion} {lotes:.3f} @ "
                f"{precio_ejecutado:.{digits}f}"
            )
            self.logger.info(f"   SL: {sl_real:.{digits}f}, TP: {tp_real:.{digits}f}")
            self.logger.info(
                f"   Contexto: régimen={regimen}, sesión={contexto_apertura['sesion']}, "
                f"modo={modo}, ML={prob_ml if prob_ml is not None else 'N/A'}"
            )

            return True

        finally:
            with self._lock_operaciones:
                if simbolo in self._operaciones_pendientes:
                    del self._operaciones_pendientes[simbolo]

    # ============================================================
    # MÉTODOS AUXILIARES
    # ============================================================

    def _verificar_posiciones_existentes(self, simbolo: str, direccion: str) -> Tuple[bool, str]:
        """Verifica si ya existe una posición del mismo símbolo."""
        try:
            posiciones = self.mt5.obtener_posiciones()
            if not posiciones:
                return True, "Sin posiciones"

            for pos in posiciones:
                if pos.get('simbolo') == simbolo:
                    tipo = pos.get('tipo')
                    if tipo in ['BUY', 0, 'COMPRA']:
                        direccion_existente = 'COMPRA'
                    elif tipo in ['SELL', 1, 'VENTA']:
                        direccion_existente = 'VENTA'
                    else:
                        direccion_existente = pos.get('direccion', 'DESCONOCIDO')

                    if direccion_existente == direccion:
                        return False, f"⛔ {simbolo}: YA EXISTE posición {direccion}"

            return True, "Sin conflictos"
        except Exception as e:
            self.logger.warning(f"⚠️ Error verificando posiciones: {e}")
            return True, "No se pudo verificar"

    def _obtener_capital_real(self) -> float:
        """Obtiene capital REAL desde MT5."""
        if self.modo_backtest:
            return float(self.gestion_riesgo.capital_actual)

        try:
            cuenta = self.mt5.info_cuenta()
            if cuenta and cuenta.get('balance', 0) > 0:
                return float(cuenta['balance'])
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo capital: {e}")

        return float(self.gestion_riesgo.capital_actual)

    def _validar_capital_minimo(self, simbolo: str, capital: float) -> Tuple[bool, str]:
        """Valida si el capital es suficiente para operar el símbolo."""
        try:
            precio = 0
            if not self.modo_backtest:
                tick = self.mt5.obtener_precio(simbolo)
                if tick:
                    precio = float(tick.get('ask', tick.get('bid', 0)))

            if precio <= 0:
                return True, "OK"

            margen_requerido = self._estimar_margen(simbolo, 0.01, precio)
            capital_minimo = margen_requerido * 2

            self.logger.info(f"📊 {simbolo}: Capital mínimo requerido: ${capital_minimo:.2f}")

            if capital < capital_minimo:
                return False, f"Capital insuficiente para {simbolo} (${capital:.2f} < ${capital_minimo:.2f})"

            return True, "OK"
        except Exception:
            return True, "OK"

    def _verificar_margen_real(self, simbolo: str, lotes: float, precio: float) -> Tuple[bool, str]:
        """Verifica si hay margen REAL disponible."""
        if self.modo_backtest:
            return True, "Backtest"

        try:
            margen_requerido = self._estimar_margen(simbolo, lotes, precio)

            cuenta = self.mt5.info_cuenta()
            if not cuenta:
                return False, "No se pudo obtener cuenta"

            margen_libre = float(cuenta.get('margen_libre', 0) or 0)
            if margen_libre <= 0:
                margen_libre = float(cuenta.get('margin_free', 0) or 0)
            if margen_libre <= 0:
                margen_libre = float(cuenta.get('equity', 0) or 0)

            margen_con_seguridad = margen_requerido * 1.20

            if margen_con_seguridad > margen_libre:
                return False, f"Margen insuficiente (req: ${margen_requerido:.2f}, libre: ${margen_libre:.2f})"

            return True, "OK"
        except Exception as e:
            self.logger.warning(f"⚠️ Error verificando margen: {e}")
            return True, "OK"

    def _validar_sl_tp_por_modo(self, simbolo: str, modo: str, sl: float, tp: float,
                                entry_price: float, direccion: str, regimen: str) -> Tuple[bool, str]:
        """Validación específica de SL/TP según el modo de entrada."""
        pip_val = self._obtener_pip_val(simbolo)
        sl_dist = abs(entry_price - sl)
        sl_pips = sl_dist / pip_val if pip_val > 0 else 0
        tp_dist = abs(tp - entry_price)
        tp_pips = tp_dist / pip_val if pip_val > 0 else 0

        rr_min_modo = {
            'RETEST': 1.2,
            'BREAKOUT': 1.5,
            'PULLBACK': 1.2,
            'NIVEL_FUERTE': 1.0,
            'SNIPER_ELITE': 1.5,
            'PATRON': 1.2,
            'RUPTURA_FALSA': 0.8,
            'VELA_BORDE': 0.8,
            'RETEST_FALLBACK': 0.8,
        }.get(modo, 1.0)

        rr = tp_pips / sl_pips if sl_pips > 0 else 0

        if rr < rr_min_modo - 0.01:
            return False, f"R:R insuficiente para {modo} ({rr:.2f} < {rr_min_modo})"

        sl_min_activo = {
            'XAUUSD': 50, 'XAGUSD': 50,
            'US30': 30, 'NAS100': 30, 'US500': 25,
            'BTCUSD': 100, 'ETHUSD': 80, 'SOLUSD': 60,
            'EURUSD': 10, 'GBPUSD': 10, 'USDJPY': 10,
            'AUDUSD': 10, 'USDCAD': 10, 'USDCHF': 10,
            'EURGBP': 10, 'EURJPY': 15, 'GBPJPY': 18,
        }.get(simbolo, 10)

        if sl_pips < sl_min_activo - 0.01:
            return False, f"SL demasiado cerca para {simbolo} ({sl_pips:.0f} < {sl_min_activo} pips)"

        return True, "SL/TP válido para modo"

    def _obtener_lote_minimo_broker(self, simbolo: str) -> float:
        """Obtiene el lote mínimo del broker para el símbolo."""
        simbolo_upper = simbolo.upper()

        if not self.modo_backtest and self.mt5 and hasattr(self.mt5, 'obtener_info_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None:
                    if hasattr(info, 'volume_min') and info.volume_min > 0:
                        return float(info.volume_min)
                    if hasattr(info, 'trade_volume_min') and info.trade_volume_min > 0:
                        return float(info.trade_volume_min)
            except Exception:
                pass

        LOTES_MINIMOS_BROKER = {
            'US500': 0.10, 'US30': 0.10, 'NAS100': 0.10,
            'XAUUSD': 0.01, 'XAGUSD': 0.01,
            'BTCUSD': 0.01, 'ETHUSD': 0.01, 'SOLUSD': 0.01,
            'EURUSD': 0.01, 'GBPUSD': 0.01, 'USDJPY': 0.01,
            'AUDUSD': 0.01, 'USDCAD': 0.01, 'USDCHF': 0.01,
            'EURGBP': 0.01, 'EURJPY': 0.01, 'GBPJPY': 0.01,
        }

        return LOTES_MINIMOS_BROKER.get(simbolo_upper, 0.01)

    def _validar_sl_tp_antes_enviar(self,
                                    simbolo: str,
                                    entry_price: float,
                                    sl: float,
                                    tp: float,
                                    direccion: str,
                                    bid: float = 0,
                                    ask: float = 0) -> Tuple[bool, str]:
        """Validación EXTRA de SL/TP antes de enviar al broker."""
        if entry_price <= 0 or sl <= 0 or tp <= 0:
            return False, f"Precios inválidos"

        pip_val = self._obtener_pip_val(simbolo)
        if pip_val <= 0:
            pip_val = 0.0001

        if direccion == 'COMPRA':
            if sl >= entry_price:
                return False, f"SL INVERTIDO para COMPRA"
            if tp <= entry_price:
                return False, f"TP INVERTIDO para COMPRA"
            if tp <= sl:
                return False, f"TP <= SL para COMPRA"
        else:
            if sl <= entry_price:
                return False, f"SL INVERTIDO para VENTA"
            if tp >= entry_price:
                return False, f"TP INVERTIDO para VENTA"
            if tp >= sl:
                return False, f"TP >= SL para VENTA"

        spread_pips = 0
        if bid > 0 and ask > 0:
            spread_pips = (ask - bid) / pip_val if pip_val > 0 else 0

        sl_dist = abs(entry_price - sl)
        sl_dist_pips = sl_dist / pip_val if pip_val > 0 else 0
        min_sl_pips = self.SL_MINIMO_ABSOLUTO_PIPS + spread_pips

        if sl_dist_pips < min_sl_pips:
            return False, f"SL demasiado cerca considerando spread ({spread_pips:.1f} pips)"

        tp_dist = abs(tp - entry_price)
        tp_dist_pips = tp_dist / pip_val if pip_val > 0 else 0
        min_tp_pips = sl_dist_pips * self.TP_FACTOR_MINIMO + spread_pips

        if tp_dist_pips < min_tp_pips:
            return False, f"TP demasiado cerca considerando spread ({spread_pips:.1f} pips)"

        if bid > 0 and ask > 0:
            if direccion == 'COMPRA':
                if sl >= ask:
                    return False, f"SL INVERTIDO para COMPRA vs ASK"
                if tp <= ask:
                    return False, f"TP INVERTIDO para COMPRA vs ASK"
            else:
                if sl <= bid:
                    return False, f"SL INVERTIDO para VENTA vs BID"
                if tp >= bid:
                    return False, f"TP INVERTIDO para VENTA vs BID"

        return True, "OK"


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_ejecutor_operaciones(orquestador: Any,
                                mt5: Any,
                                gestion_riesgo: Any,
                                gestor_stops: Optional[GestorStops] = None,
                                notificaciones: Optional[Any] = None,
                                modo_backtest: bool = False,
                                almacen: Optional[Any] = None) -> EjecutorOperaciones:
    """Crea una instancia de EjecutorOperaciones."""
    return EjecutorOperaciones(
        orquestador=orquestador,
        mt5=mt5,
        gestion_riesgo=gestion_riesgo,
        gestor_stops=gestor_stops,
        notificaciones=notificaciones,
        modo_backtest=modo_backtest,
        almacen=almacen
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando EjecutorOperaciones V10.0...")

    # Mock mínimo para verificar _construir_contexto_apertura
    class MockOrq:
        def __init__(self):
            class Estado:
                def __init__(self):
                    self.posiciones_abiertas = {}
            self.estado = Estado()
            class Config:
                MAGIC_NUMBER = 202606
            self.config = Config()

    class MockMT5:
        magic_number = 202606
        def obtener_info_simbolo(self, s): return None
        def obtener_precio(self, s): return None
        def info_cuenta(self): return None
        def obtener_posiciones(self): return []

    class MockRiesgo:
        capital_actual = 1000.0

    class MockNotif:
        def notificar_operacion(self, op): pass

    class MockStops:
        def validar_sl_tp(self, **kwargs):
            return True, "OK", kwargs.get('sl'), kwargs.get('tp'), kwargs.get('tp2', 0)

    orq = MockOrq()
    ejecutor = EjecutorOperaciones(
        orquestador=orq,
        mt5=MockMT5(),
        gestion_riesgo=MockRiesgo(),
        gestor_stops=MockStops(),
        notificaciones=MockNotif(),
        modo_backtest=True,
    )

    # Test contexto_apertura
    señal = {
        'simbolo': 'EURUSD',
        'direccion': 'COMPRA',
        'modo': 'RETEST',
        'score': 72.5,
        'score_h1': 70,
        'score_m5': 75,
        'prob_ml': 0.68,
        'direccion_m15': 'COMPRA',
        'stop_hunt_detectado': True,
        'razon_stop_hunt': 'STOP_HUNT_ALCISTA',
        'rechazo_confirmado': True,
        'rr': 1.8,
        'confluencias': {'TENDENCIA': ['EMA_ALCISTA'], 'ESTRUCTURA': ['NIVEL_CLAVE']},
        'niveles_usados': {
            'nivel_usado': 1.0950,
            'soporte_cercano': 1.0950,
            'resistencia_cercana': 1.1050,
        },
        'en_nivel_clave': True,
        'es_reversal': False,
        'volumen_relativo': 1.5,
        'patron_calidad': 65,
        'adx_h1': 28,
    }

    contexto = ejecutor._construir_contexto_apertura(
        señal=señal,
        regimen='TREND_ALCISTA_FUERTE',
        modo='RETEST',
        score=72.5,
        calidad_horario='BUENA',
    )

    import json
    print("\n📋 contexto_apertura generado:")
    print(json.dumps(contexto, indent=2, default=str))

    # Validaciones
    assert contexto['regimen'] == 'TREND_ALCISTA_FUERTE'
    assert contexto['modo'] == 'RETEST'
    assert contexto['score'] == 72.5
    assert contexto['prob_ml'] == 0.68
    assert contexto['direccion_m15'] == 'COMPRA'
    assert contexto['stop_hunt_detectado'] is True
    assert contexto['rechazo_confirmado'] is True
    assert contexto['nivel_usado'] == 1.0950
    assert contexto['sesion'] in ('ASIAN', 'LONDON', 'NEW_YORK', 'OVERLAP_LDN_NY')
    print("\n✅ Todas las validaciones pasan")

    print("\n✅ Prueba completada")