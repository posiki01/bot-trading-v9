#!/usr/bin/env python3
"""
trading/monitoreo.py (V10.1 - ML CONECTADO)
Monitoreo de posiciones abiertas — ORQUESTADOR de decisiones.

CAMBIOS V10.1:
- ✅ Notifica al ML cuando se cierra una operación (para aprendizaje real)
- ✅ Preserva metadata completa (regimen, modo, score) para el ML
- ✅ Buffer de operaciones cerradas para auditoría
- ✅ Sin cambios en la lógica de trailing/stops/decisiones

RESPONSABILIDAD:
- Obtener posiciones de MT5
- Para cada posición, aplicar en orden:
    1. ¿SL/TP tocado?           → cerrar
    2. ¿Cierre por tesis?       → delegar a DecisorCierre
    3. ¿Timeout?                → delegar a TrailingEngine.verificar_timeout()
    4. ¿Trailing?               → delegar a TrailingEngine.calcular_movimiento_sl()
    5. ¿Cierre parcial?         → delegar a TrailingEngine.verificar_cierre_parcial()
- Aplicar las decisiones (mover SL, cerrar, cerrar parcial)
- Registrar en gestión de riesgo
- ✅ Notificar al ML para aprendizaje incremental

NO HACE:
- Cálculo de pip_val (usa TrailingEngine/helpers)
- Cálculo de ATR (usa TrailingEngine)
- Lógica de trailing (usa TrailingEngine)
- Lógica de cierre por régimen (usa DecisorCierre)
- Entrenamiento ML (solo notifica)
"""

import logging
import threading
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta
from utils.reloj import now_utc

try:
    from config.umbrales import Umbrales
except ImportError:
    Umbrales = None

logger = logging.getLogger('BotTrading.Monitoreo')


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class MonitorPosiciones:
    """
    Monitoreo de posiciones abiertas — orquestador de decisiones.
    V10.1 - ML CONECTADO.
    """

    # ============================================================
    # CONFIGURACIÓN
    # ============================================================

    # Si una posición está a menos de esta distancia del SL (%), cerrar manualmente
    DISTANCIA_CIERRE_PREVENTIVO_PCT = 0.05

    # Máximo de posiciones por ciclo (evita bloquear el thread)
    MAX_POSICIONES_POR_CICLO = 20

    # Máximo de operaciones cerradas en buffer (para auditoría)
    MAX_BUFFER_CERRADAS = 500

    def __init__(
        self,
        orquestador: Any,
        mt5: Any,
        gestion_riesgo: Any,
        trailing_engine: Optional[Any] = None,
        decisor_cierre: Optional[Any] = None,
        monitorear_manuales: bool = False,
    ):
        """
        Args:
            orquestador: Referencia al orquestador
            mt5: Conector MT5
            gestion_riesgo: GestionRiesgo
            trailing_engine: TrailingEngine (fuente de verdad para trailing/timeout)
            decisor_cierre: DecisorCierre (opcional, para cierre por tesis)
            monitorear_manuales: Si True, gestiona también posiciones manuales
        """
        self.orquestador = orquestador
        self.mt5 = mt5
        self.gestion_riesgo = gestion_riesgo
        self.monitorear_manuales = monitorear_manuales
        self.logger = logging.getLogger('BotTrading.Monitoreo')

        # ✅ TrailingEngine es la fuente de verdad
        if trailing_engine is None:
            from trading.trailing import create_trailing_engine
            trailing_engine = create_trailing_engine(
                config=getattr(orquestador, 'config', None),
                modo_backtest=getattr(orquestador, 'modo_backtest', False),
                modo_depuracion=getattr(orquestador, 'modo_depuracion', False),
            )
        self.trailing_engine = trailing_engine

        # ✅ DecisorCierre respetado
        self.decisor_cierre = decisor_cierre

        # Anti-duplicado de cierre
        self._cerrando: set = set()
        self._cerrando_lock = threading.Lock()

        # Stats thread-safe
        self._stats_lock = threading.RLock()
        self._stats = {
            'total_procesadas': 0,
            'cerradas': 0,
            'sl_movidos': 0,
            'cierres_parciales': 0,
            'timeouts': 0,
            'fallos_analisis': 0,
            'ultima_posicion_procesada': None,
            'sl_retrocesos_evitados': 0,
            'errores_procesamiento': 0,
            'notificaciones_ml': 0,
            'errores_notificacion_ml': 0,
        }

        # ✅ Buffer de operaciones cerradas (auditoría + fallback ML)
        self._buffer_cerradas: List[Dict[str, Any]] = []
        self._buffer_lock = threading.Lock()

        self.logger.info("🔍 MonitorPosiciones V10.1 ML-CONECTADO inicializado")
        self.logger.info(f"   Monitorear manuales: {monitorear_manuales}")
        self.logger.info(f"   TrailingEngine: {type(self.trailing_engine).__name__}")
        self.logger.info(f"   DecisorCierre: {'✅' if decisor_cierre else '❌ (lógica simple)'}")
        self.logger.info(f"   ML notificación: {'✅' if self._ml_disponible() else '❌'}")

    # ============================================================
    # HELPERS DE ML
    # ============================================================

    def _ml_disponible(self) -> bool:
        """Verifica si el orquestador tiene ML disponible."""
        return (
            hasattr(self.orquestador, 'notificar_ml_operacion_cerrada')
            and callable(getattr(self.orquestador, 'notificar_ml_operacion_cerrada'))
        )

    def _notificar_ml(self, operacion: Dict[str, Any]):
        """
        ✅ V10.1: Notifica al ML que se cerró una operación.
        Best-effort: si falla, no bloquea el flujo principal.
        """
        if not self._ml_disponible():
            return

        try:
            self.orquestador.notificar_ml_operacion_cerrada(operacion)
            self._incr_stat('notificaciones_ml')

            # Buffer local para auditoría
            with self._buffer_lock:
                self._buffer_cerradas.append(operacion)
                if len(self._buffer_cerradas) > self.MAX_BUFFER_CERRADAS:
                    self._buffer_cerradas = self._buffer_cerradas[-self.MAX_BUFFER_CERRADAS:]

        except Exception as e:
            self._incr_stat('errores_notificacion_ml')
            self.logger.debug(f"⚠️ Error notificando al ML: {e}")

    # ============================================================
    # CICLO PRINCIPAL
    # ============================================================

    def ejecutar_ciclo(self):
        """Ejecuta un ciclo de monitoreo."""
        posiciones = self._obtener_posiciones()

        if not posiciones:
            return

        self.logger.debug(f"🔍 Monitoreando {len(posiciones)} posiciones")

        posiciones = posiciones[: self.MAX_POSICIONES_POR_CICLO]

        for pos in posiciones:
            try:
                self._procesar_posicion(pos)
            except Exception as e:
                ticket = pos.get('ticket', 'N/A')
                self.logger.error(
                    f"❌ Error procesando {ticket}: {e}", exc_info=True
                )
                self._incr_stat('errores_procesamiento')

    def procesar(self, pos: Dict[str, Any]):
        """Procesa una posición individual (compatibilidad)."""
        self._procesar_posicion(pos)

    # ============================================================
    # OBTENER POSICIONES
    # ============================================================

    def _obtener_posiciones(self) -> List[Dict[str, Any]]:
        """Obtiene posiciones a monitorear."""
        # Backtest: desde estado
        if getattr(self.orquestador, 'modo_backtest', False):
            posiciones = []
            for ticket, meta in self.orquestador.estado.posiciones_abiertas.items():
                direccion = meta.get('direccion', 'COMPRA')
                pos = {
                    'ticket': ticket,
                    'simbolo': meta.get('simbolo', ''),
                    'tipo': 'BUY' if direccion in ('COMPRA', 'BUY') else 'SELL',
                    'precio_apertura': meta.get('entrada', 0),
                    'precio_actual': self._obtener_precio_simulado(meta.get('simbolo', '')),
                    'sl': meta.get('sl', 0),
                    'tp': meta.get('tp', 0),
                    'volumen': meta.get('lotes', 0),
                    'magic': getattr(self.orquestador.config, 'MAGIC_NUMBER', 0),
                    'time': meta.get('timestamp_apertura', time.time()),
                    'ganancia': meta.get('ganancia', 0.0),
                }
                posiciones.append(pos)
            return posiciones

        # Real: desde MT5
        try:
            return self.mt5.obtener_posiciones() or []
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo posiciones: {e}")
            return []

    def _obtener_precio_simulado(self, simbolo: str) -> float:
        """Precio simulado para backtest."""
        try:
            df = self.orquestador.cache.get_datos(
                simbolo=simbolo,
                timeframe=5,
                n_velas=10,
                fetch_func=self.mt5.obtener_datos,
            )
            if df is not None and len(df) > 0:
                return float(df['Close'].iloc[-1])
        except Exception:
            pass

        for meta in self.orquestador.estado.posiciones_abiertas.values():
            if meta.get('simbolo') == simbolo:
                return float(meta.get('entrada', 1.0))

        return 1.0

    # ============================================================
    # PROCESAR POSICIÓN (ORQUESTADOR)
    # ============================================================

    def _procesar_posicion(self, pos: Dict[str, Any]):
        """
        Procesa una posición aplicando decisiones en orden de prioridad:
        1. SL/TP tocado → cerrar
        2. Cierre por tesis → cerrar
        3. Timeout → cerrar
        4. Trailing → mover SL
        5. Cierre parcial → ejecutar
        """
        ticket = pos.get('ticket')
        simbolo = pos.get('simbolo', '')
        if not ticket or not simbolo:
            return

        # Evitar doble procesamiento del mismo ticket en el mismo ciclo
        if not self._marcar_procesando(ticket):
            self.logger.debug(f"⏭️ Ticket {ticket} ya en proceso")
            return

        try:
            self._incr_stat('total_procesadas')

            # Metadatos
            meta = self._obtener_metadatos(ticket)

            # Filtrar manuales
            es_manual = meta.get('es_manual', False) or (not meta.get('es_bot', True) and not meta)
            if es_manual and not self.monitorear_manuales:
                self.logger.debug(f"⏭️ Ticket {ticket} manual, ignorado")
                return

            # Dirección normalizada
            direccion = self._normalizar_direccion(
                meta.get('direccion', pos.get('tipo', 'COMPRA'))
            )

            # Precio actual (bid/ask según dirección de CIERRE)
            precio_actual = self._obtener_precio_actual(simbolo, direccion)
            if precio_actual is None or precio_actual <= 0:
                self.logger.warning(f"⚠️ {simbolo}: sin precio, skip")
                return

            # Entry price
            entry_price = float(
                pos.get('precio_apertura', meta.get('entrada', 0))
            )
            if entry_price <= 0:
                self.logger.warning(f"⚠️ {simbolo}: entry inválido, skip")
                return

            # Ganancia en pips
            ganancia_pips = self._calcular_ganancia_pips(
                entry_price, precio_actual, direccion, simbolo
            )

            # Log de estado
            self.logger.info(
                f"📊 {simbolo} [{direccion}] "
                f"entry={entry_price:.5f} "
                f"actual={precio_actual:.5f} "
                f"pips={ganancia_pips:.1f}"
            )

            # ============================================================
            # FASE 1: SL/TP TOCADO
            # ============================================================
            if self._verificar_sl_tp_tocado(pos, direccion, precio_actual):
                return

            # ============================================================
            # FASE 2: CIERRE POR TESIS
            # ============================================================
            razon_cierre = self._verificar_cierre_por_tesis(
                pos, meta, precio_actual, ganancia_pips, direccion,
            )
            if razon_cierre:
                self._cerrar_posicion(ticket, razon_cierre, precio_actual)
                self._incr_stat('cerradas')
                return

            # ============================================================
            # FASE 3: TIMEOUT (delegado a TrailingEngine)
            # ============================================================
            modo = meta.get('modo', 'RETEST')
            try:
                debe_cerrar, razon_to = self.trailing_engine.verificar_timeout(
                    pos=pos,
                    fecha=now_utc(),
                    ganancia_pips=ganancia_pips,
                    modo=modo,
                )
                if debe_cerrar:
                    self.logger.info(f"⏰ {simbolo}: TIMEOUT ({razon_to})")
                    self._cerrar_posicion(ticket, f"TIMEOUT_{razon_to}", precio_actual)
                    self._incr_stat('timeouts')
                    self._incr_stat('cerradas')
                    return
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: error timeout: {e}")

            # ============================================================
            # FASE 4: TRAILING (delegado a TrailingEngine)
            # ============================================================
            sl_movido = self._aplicar_trailing(
                pos, meta, precio_actual, ganancia_pips, direccion,
            )
            if sl_movido:
                self._incr_stat('sl_movidos')

            # ============================================================
            # FASE 5: CIERRE PARCIAL (delegado a TrailingEngine)
            # ============================================================
            if self._verificar_cierre_parcial(pos, ganancia_pips, modo):
                self._incr_stat('cierres_parciales')

            # Actualizar timestamp
            self._set_stat('ultima_posicion_procesada', now_utc().isoformat())

        finally:
            self._desmarcar_procesando(ticket)

    # ============================================================
    # FASE 1: SL/TP TOCADO
    # ============================================================

    def _verificar_sl_tp_tocado(
        self,
        pos: Dict[str, Any],
        direccion: str,
        precio_actual: float,
    ) -> bool:
        """
        Verifica si SL o TP fueron tocados.
        Usa precio bid/ask según dirección de cierre.
        """
        sl = float(pos.get('sl', 0))
        tp = float(pos.get('tp', 0))
        ticket = pos.get('ticket')
        simbolo = pos.get('simbolo', '')

        if direccion == 'COMPRA':
            if sl > 0 and precio_actual <= sl:
                self.logger.info(f"🎯 {simbolo}: SL alcanzado ({precio_actual:.5f} <= {sl:.5f})")
                self._cerrar_posicion(ticket, "SL", precio_actual)
                self._incr_stat('cerradas')
                return True
            if tp > 0 and precio_actual >= tp:
                self.logger.info(f"🎯 {simbolo}: TP alcanzado ({precio_actual:.5f} >= {tp:.5f})")
                self._cerrar_posicion(ticket, "TP", precio_actual)
                self._incr_stat('cerradas')
                return True
        else:
            if sl > 0 and precio_actual >= sl:
                self.logger.info(f"🎯 {simbolo}: SL alcanzado ({precio_actual:.5f} >= {sl:.5f})")
                self._cerrar_posicion(ticket, "SL", precio_actual)
                self._incr_stat('cerradas')
                return True
            if tp > 0 and precio_actual <= tp:
                self.logger.info(f"🎯 {simbolo}: TP alcanzado ({precio_actual:.5f} <= {tp:.5f})")
                self._cerrar_posicion(ticket, "TP", precio_actual)
                self._incr_stat('cerradas')
                return True

        return False

    def _verificar_sl_tp(
        self,
        pos: Dict[str, Any],
        ticket: int,
        ganancia_pips: float,
        precio_actual: float = 0,
    ) -> bool:
        """Compatibilidad con firma anterior."""
        if precio_actual <= 0:
            precio_actual = pos.get('precio_actual', 0)
        direccion = self._normalizar_direccion(
            pos.get('direccion', pos.get('tipo', 'COMPRA'))
        )
        return self._verificar_sl_tp_tocado(pos, direccion, precio_actual)

    # ============================================================
    # FASE 2: CIERRE POR TESIS
    # ============================================================

    def _verificar_cierre_por_tesis(
        self,
        pos: Dict[str, Any],
        meta: Dict[str, Any],
        precio_actual: float,
        ganancia_pips: float,
        direccion: str,
    ) -> Optional[str]:
        """
        Cierra por cambio de tesis.
        Si hay DecisorCierre inyectado, lo usa.
        Si no, lógica simple.
        """
        simbolo = pos.get('simbolo', '')
        regimen = meta.get('regimen', 'INCERTO')
        modo = meta.get('modo', 'RETEST')

        # 1. Decisor inyectado
        if self.decisor_cierre is not None:
            try:
                if hasattr(self.decisor_cierre, 'debe_cerrar'):
                    decision = self.decisor_cierre.debe_cerrar(
                        pos=pos,
                        meta=meta,
                        precio_actual=precio_actual,
                        ganancia_pips=ganancia_pips,
                    )
                    if isinstance(decision, tuple):
                        debe, razon = decision
                        if debe:
                            return razon
                    elif decision:
                        return "DECISOR_CIERRE"
            except Exception as e:
                self.logger.debug(f"⚠️ {simbolo}: error decisor: {e}")

        # 2. Lógica simple (fallback)
        if regimen in ('CHOP_VOLATIL', 'INCERTO') and ganancia_pips < 5:
            return f"REGIMEN_{regimen}_SIN_AVANCE"

        sl = float(pos.get('sl', 0))
        if sl > 0 and precio_actual > 0:
            distancia_pct = abs(precio_actual - sl) / precio_actual * 100
            if distancia_pct < self.DISTANCIA_CIERRE_PREVENTIVO_PCT:
                if ganancia_pips < 0:
                    return f"SL_PROXIMO_{distancia_pct:.3f}%"

        return None

    # ============================================================
    # FASE 4: TRAILING (delegado)
    # ============================================================

    def _aplicar_trailing(
        self,
        pos: Dict[str, Any],
        meta: Dict[str, Any],
        precio_actual: float,
        ganancia_pips: float,
        direccion: str,
    ) -> bool:
        """
        Delegado a TrailingEngine.calcular_movimiento_sl().
        Ya NO calcula SL manualmente.
        """
        simbolo = pos.get('simbolo', '')
        ticket = pos.get('ticket')
        sl_actual = float(pos.get('sl', 0))

        # H1 para reanálisis
        df_h1 = self._obtener_h1_con_cache(simbolo)

        regimen = meta.get('regimen', 'INCERTO')
        modo = meta.get('modo', 'RETEST')

        try:
            decision = self.trailing_engine.calcular_movimiento_sl(
                pos=pos,
                df_h1=df_h1,
                precio_actual=precio_actual,
                fecha=now_utc(),
                regimen=regimen,
                modo=modo,
            )
        except Exception as e:
            self.logger.debug(f"⚠️ {simbolo}: error trailing: {e}")
            return False

        # ¿Cerrar por análisis?
        if decision.cerrar:
            self.logger.info(f"🔒 {simbolo}: cierre por trailing ({decision.motivo_cierre or decision.razon})")
            self._cerrar_posicion(ticket, decision.motivo_cierre or decision.razon, precio_actual)
            self._incr_stat('cerradas')
            return False

        # ¿Mover SL?
        if decision.mover_sl and decision.nuevo_sl is not None:
            if direccion == 'COMPRA' and decision.nuevo_sl <= sl_actual:
                self._incr_stat('sl_retrocesos_evitados')
                return False
            if direccion == 'VENTA' and decision.nuevo_sl >= sl_actual:
                self._incr_stat('sl_retrocesos_evitados')
                return False

            self.logger.info(
                f"🔄 {simbolo}: {decision.fase} | "
                f"SL {sl_actual:.5f} → {decision.nuevo_sl:.5f} "
                f"(ganancia: {ganancia_pips:.1f}pips)"
            )
            if self._mover_sl(ticket, decision.nuevo_sl):
                if ticket in self.orquestador.estado.posiciones_abiertas:
                    self.orquestador.estado.posiciones_abiertas[ticket]['sl'] = decision.nuevo_sl
                return True

        return False

    # ============================================================
    # FASE 5: CIERRE PARCIAL
    # ============================================================

    def _verificar_cierre_parcial(
        self,
        pos: Dict[str, Any],
        ganancia_pips: float,
        modo: str,
    ) -> bool:
        """Delegado a TrailingEngine.verificar_cierre_parcial()."""
        try:
            debe_cerrar, volumen = self.trailing_engine.verificar_cierre_parcial(
                pos=pos,
                ganancia_pips=ganancia_pips,
                modo=modo,
            )
        except Exception as e:
            self.logger.debug(f"⚠️ Error cierre parcial: {e}")
            return False

        if not debe_cerrar or volumen <= 0:
            return False

        ticket = pos.get('ticket')
        simbolo = pos.get('simbolo', '')

        self.logger.info(
            f"✂️ {simbolo}: cierre parcial {volumen:.3f} "
            f"(ganancia: {ganancia_pips:.1f}pips)"
        )

        if self._cerrar_parcial(ticket, volumen):
            if ticket in self.orquestador.estado.posiciones_abiertas:
                self.orquestador.estado.posiciones_abiertas[ticket]['tp1_realizado'] = True
            return True

        return False

    # ============================================================
    # ACCIONES
    # ============================================================

    def _cerrar_posicion(
        self,
        ticket: int,
        razon: str,
        precio_cierre: Optional[float] = None,
    ) -> bool:
        """
        Cierra una posición. Idempotente.
        ✅ V10.1: Notifica al ML antes de limpiar el estado.
        """
        if ticket is None:
            return False

        # Anti-duplicado
        with self._cerrando_lock:
            if ticket in self._cerrando:
                self.logger.debug(f"⏭️ Ticket {ticket} ya en cierre")
                return False
            self._cerrando.add(ticket)

        try:
            simbolo = self._obtener_simbolo(ticket)
            self.logger.info(f"🔒 Cerrando {simbolo} [{ticket}]: {razon}")

            # Recuperar metadata ANTES de cerrar (para ML)
            meta = self._obtener_metadatos(ticket)

            # Ejecutar cierre
            if getattr(self.orquestador, 'modo_backtest', False):
                exito = self._cerrar_backtest(ticket)
            else:
                exito = self._cerrar_mt5(ticket)

            if not exito:
                self.logger.warning(f"⚠️ No se pudo cerrar {ticket}")
                return False

            # Detalle del cierre
            detalle = self._obtener_detalle_cierre(ticket)
            ganancia = 0.0
            comision = 0.0
            swap = 0.0

            if detalle:
                ganancia = float(detalle.get('ganancia', 0))
                comision = float(detalle.get('comision', 0))
                swap = float(detalle.get('swap', 0))

                # Registrar en gestión de riesgo
                self.gestion_riesgo.registrar_operacion({
                    'ticket': ticket,
                    'simbolo': simbolo,
                    'ganancia': ganancia,
                    'comision': comision,
                    'swap': swap,
                    'motivo_cierre': razon,
                    'regimen': meta.get('regimen', 'INCERTO'),
                    'modo': meta.get('modo', 'RETEST'),
                })

            # ✅ V10.1: Notificar al ML ANTES de limpiar estado
            self._notificar_ml({
                'ticket': ticket,
                'simbolo': simbolo,
                'ganancia': ganancia,
                'ganancia_neta': ganancia + comision + swap,
                'comision': comision,
                'swap': swap,
                'motivo_cierre': razon,
                'estado': 'CERRADA',
                'regimen': meta.get('regimen', 'INCERTO'),
                'modo': meta.get('modo', 'RETEST'),
                'score_h1': meta.get('score', 0),
                'direccion': meta.get('direccion', 'COMPRA'),
                'contexto_apertura': meta.get('contexto_apertura', {}),
                'timestamp': now_utc().isoformat(),
                'timestamp_salida': now_utc().isoformat(),
            })

            # Registrar en patrón tracker
            if hasattr(self.orquestador, 'patron_tracker') and self.orquestador.patron_tracker:
                try:
                    self.orquestador.patron_tracker.registrar_resultado(
                        simbolo=simbolo,
                        ganancia=ganancia,
                    )
                except Exception as e:
                    self.logger.debug(f"⚠️ Error patrón tracker: {e}")

            # Notificar (alertas Discord/Telegram)
            try:
                self.orquestador.notificaciones.notificar_cierre({
                    'simbolo': simbolo,
                    'ganancia': ganancia,
                    'motivo_cierre': razon,
                    'ticket': ticket,
                })
            except Exception:
                pass

            # Limpiar estado
            self.orquestador.estado.posiciones_abiertas.pop(ticket, None)

            self.logger.info(
                f"✅ Cerrada {simbolo} [{ticket}] | "
                f"PnL: ${ganancia:+.2f} | Motivo: {razon}"
            )
            return True

        except Exception as e:
            self.logger.error(f"❌ Error cerrando {ticket}: {e}", exc_info=True)
            return False

        finally:
            with self._cerrando_lock:
                self._cerrando.discard(ticket)

    def _cerrar_mt5(self, ticket: int) -> bool:
        try:
            return bool(self.mt5.cerrar_posicion(ticket))
        except Exception as e:
            self.logger.warning(f"⚠️ Error MT5 cerrando {ticket}: {e}")
            return False

    def _cerrar_backtest(self, ticket: int) -> bool:
        """Backtest: marca la posición como cerrada."""
        if ticket in self.orquestador.estado.posiciones_abiertas:
            meta = self.orquestador.estado.posiciones_abiertas[ticket]
            meta['estado'] = 'CERRADA'
            return True
        return True  # idempotente

    def _mover_sl(self, ticket: int, nuevo_sl: float) -> bool:
        """Mueve el SL."""
        try:
            if getattr(self.orquestador, 'modo_backtest', False):
                if ticket in self.orquestador.estado.posiciones_abiertas:
                    self.orquestador.estado.posiciones_abiertas[ticket]['sl'] = nuevo_sl
                return True

            exito = bool(self.mt5.modificar_sl(ticket, nuevo_sl))
            if exito and ticket in self.orquestador.estado.posiciones_abiertas:
                self.orquestador.estado.posiciones_abiertas[ticket]['sl'] = nuevo_sl
            return exito
        except Exception as e:
            self.logger.warning(f"⚠️ Error moviendo SL {ticket}: {e}")
            return False

    def _mover_tp(self, ticket: int, nuevo_tp: float) -> bool:
        """Mueve el TP (por si el decisor lo pide)."""
        try:
            if getattr(self.orquestador, 'modo_backtest', False):
                if ticket in self.orquestador.estado.posiciones_abiertas:
                    self.orquestador.estado.posiciones_abiertas[ticket]['tp'] = nuevo_tp
                return True

            if hasattr(self.mt5, 'modificar_tp'):
                return bool(self.mt5.modificar_tp(ticket, nuevo_tp))
            return False
        except Exception:
            return False

    def _cerrar_parcial(self, ticket: int, volumen: float) -> bool:
        """Cierra parcialmente."""
        if volumen <= 0:
            return False

        try:
            if getattr(self.orquestador, 'modo_backtest', False):
                return True
            return bool(self.mt5.cerrar_parcial(ticket, volumen))
        except Exception as e:
            self.logger.warning(f"⚠️ Error cierre parcial {ticket}: {e}")
            return False

    # ============================================================
    # HELPERS
    # ============================================================

    def _normalizar_direccion(self, direccion: Any) -> str:
        """Normaliza dirección a COMPRA/VENTA."""
        if direccion is None:
            return 'COMPRA'
        d = str(direccion).upper().strip()
        if d in ('BUY', 'LONG', 'COMPRA', 'B', '0'):
            return 'COMPRA'
        if d in ('SELL', 'SHORT', 'VENTA', 'S', '1'):
            return 'VENTA'
        return 'COMPRA'

    def _obtener_precio_actual(
        self,
        simbolo: str,
        direccion_cierre: str,
    ) -> Optional[float]:
        """
        Precio para cierre según dirección:
        - COMPRA → cierra a BID
        - VENTA  → cierra a ASK
        """
        if getattr(self.orquestador, 'modo_backtest', False):
            return self._obtener_precio_simulado(simbolo)

        try:
            tick = self.mt5.obtener_precio(simbolo)
            if not tick:
                return None

            bid = float(tick.get('bid', 0))
            ask = float(tick.get('ask', 0))

            if bid <= 0 or ask <= 0:
                return None

            return bid if direccion_cierre == 'COMPRA' else ask
        except Exception as e:
            self.logger.debug(f"⚠️ Error obteniendo precio {simbolo}: {e}")
            return None

    def _calcular_ganancia_pips(
        self,
        entry: float,
        precio_actual: float,
        direccion: str,
        simbolo: str,
    ) -> float:
        """Ganancia en pips."""
        pip_val = self._obtener_pip_val(simbolo)
        if pip_val <= 0:
            return 0.0

        if direccion == 'COMPRA':
            return (precio_actual - entry) / pip_val
        return (entry - precio_actual) / pip_val

    def _obtener_pip_val(self, simbolo: str) -> float:
        """pip_val del símbolo (delegado a helpers)."""
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

    def _obtener_metadatos(self, ticket: int) -> Dict[str, Any]:
        """Metadatos de la posición desde estado."""
        if hasattr(self.orquestador, 'estado'):
            return self.orquestador.estado.posiciones_abiertas.get(ticket, {})
        return {}

    def _obtener_simbolo(self, ticket: int) -> str:
        """Símbolo de un ticket."""
        meta = self._obtener_metadatos(ticket)
        if meta.get('simbolo'):
            return meta['simbolo']

        try:
            posiciones = self.mt5.obtener_posiciones()
            for p in posiciones:
                if p.get('ticket') == ticket:
                    return p.get('simbolo', '')
        except Exception:
            pass
        return ''

    def _obtener_detalle_cierre(self, ticket: int) -> Optional[Dict[str, Any]]:
        """Detalle del cierre."""
        try:
            return self.mt5.obtener_detalle_cierre(ticket)
        except Exception:
            return None

    def _obtener_h1_con_cache(self, simbolo: str) -> Optional[Any]:
        """H1 desde cache."""
        try:
            return self.orquestador.cache.get_datos(
                simbolo=simbolo,
                timeframe=60,
                n_velas=100,
                fetch_func=self.mt5.obtener_datos,
            )
        except Exception:
            return None

    # ============================================================
    # ANTI-DUPLICADO
    # ============================================================

    def _marcar_procesando(self, ticket: int) -> bool:
        """Marca ticket como en proceso. Retorna False si ya estaba."""
        with self._cerrando_lock:
            if ticket in self._cerrando:
                return False
            self._cerrando.add(ticket)
            return True

    def _desmarcar_procesando(self, ticket: int):
        with self._cerrando_lock:
            self._cerrando.discard(ticket)

    # ============================================================
    # STATS (THREAD-SAFE)
    # ============================================================

    def _incr_stat(self, key: str, delta: int = 1):
        with self._stats_lock:
            self._stats[key] = self._stats.get(key, 0) + delta

    def _set_stat(self, key: str, value: Any):
        with self._stats_lock:
            self._stats[key] = value

    def get_stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            stats = self._stats.copy()

        total = stats['total_procesadas']
        if total > 0:
            stats['tasa_cierre'] = round(stats['cerradas'] / total * 100, 2)
            stats['tasa_trailing'] = round(stats['sl_movidos'] / total * 100, 2)
        else:
            stats['tasa_cierre'] = 0
            stats['tasa_trailing'] = 0

        stats['posiciones_actuales'] = len(self.orquestador.estado.posiciones_abiertas)
        stats['cerrando_actual'] = len(self._cerrando)

        with self._buffer_lock:
            stats['buffer_cerradas'] = len(self._buffer_cerradas)

        return stats

    def obtener_operaciones_cerradas_recientes(self, limite: int = 50) -> List[Dict[str, Any]]:
        """Devuelve las últimas operaciones cerradas (auditoría)."""
        with self._buffer_lock:
            return list(self._buffer_cerradas[-limite:])


# ============================================================
# FACTORY
# ============================================================

def create_monitor_posiciones(
    orquestador: Any,
    mt5: Any,
    gestion_riesgo: Any,
    trailing_engine: Optional[Any] = None,
    decisor_cierre: Optional[Any] = None,
    monitorear_manuales: bool = False,
) -> MonitorPosiciones:
    """Crea una instancia de MonitorPosiciones."""
    return MonitorPosiciones(
        orquestador=orquestador,
        mt5=mt5,
        gestion_riesgo=gestion_riesgo,
        trailing_engine=trailing_engine,
        decisor_cierre=decisor_cierre,
        monitorear_manuales=monitorear_manuales,
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando MonitorPosiciones V10.1...")

    # Mock mínimo
    class MockEstado:
        def __init__(self):
            self.posiciones_abiertas = {}

    class MockConfig:
        MAGIC_NUMBER = 202606

    class MockCache:
        def get_datos(self, **kwargs):
            import pandas as pd
            import numpy as np
            n = 100
            return pd.DataFrame({
                'Open': np.random.randn(n) * 0.001 + 1.1,
                'High': np.random.randn(n) * 0.001 + 1.101,
                'Low': np.random.randn(n) * 0.001 + 1.099,
                'Close': np.random.randn(n) * 0.001 + 1.1,
                'Volume': np.random.randint(100, 1000, n),
            })

    class MockNotif:
        def notificar_cierre(self, op): pass

    class MockPatronTracker:
        def registrar_resultado(self, *args, **kwargs): pass

    class MockOrq:
        def __init__(self):
            self.modo_backtest = True
            self.modo_depuracion = True
            self.estado = MockEstado()
            self.config = MockConfig()
            self.cache = MockCache()
            self.notificaciones = MockNotif()
            self.patron_tracker = MockPatronTracker()
            self._ml_calls = []

        def notificar_ml_operacion_cerrada(self, op):
            self._ml_calls.append(op)

    class MockMT5:
        def obtener_datos(self, *args, **kwargs): return None
        def obtener_posiciones(self): return []
        def cerrar_posicion(self, ticket): return True
        def modificar_sl(self, *args, **kwargs): return True
        def obtener_detalle_cierre(self, ticket):
            return {'ganancia': 10.0, 'comision': -0.5, 'swap': 0.0}

    class MockRiesgo:
        def registrar_operacion(self, op): pass

    orq = MockOrq()
    mt5 = MockMT5()
    riesgo = MockRiesgo()

    monitor = MonitorPosiciones(orq, mt5, riesgo)
    print(f"✅ MonitorPosiciones V10.1 inicializado")
    print(f"   ML disponible: {monitor._ml_disponible()}")

    # Test ciclo vacío
    monitor.ejecutar_ciclo()
    print(f"✅ Ciclo vacío OK")

    # Añadir posición simulada
    orq.estado.posiciones_abiertas[12345] = {
        'simbolo': 'EURUSD',
        'direccion': 'COMPRA',
        'entrada': 1.1000,
        'sl': 1.0980,
        'tp': 1.1050,
        'lotes': 0.01,
        'modo': 'RETEST',
        'regimen': 'TREND_ALCISTA_FUERTE',
        'score': 75,
        'es_bot': True,
    }

    # Forzar cierre por SL
    orq.estado.posiciones_abiertas[12345]['sl'] = 1.10  # SL alcanzable
    monitor.ejecutar_ciclo()
    print(f"✅ Ciclo con posición OK")

    # Verificar que ML fue notificado
    print(f"\n📊 Llamadas al ML: {len(orq._ml_calls)}")
    if orq._ml_calls:
        op = orq._ml_calls[0]
        print(f"   Última op ML: {op['simbolo']} - ${op['ganancia']:.2f}")
        print(f"   Régimen: {op['regimen']}, Modo: {op['modo']}")

    # Stats
    import json
    print(f"\n📊 Stats:")
    print(json.dumps(monitor.get_stats(), indent=2, default=str))

    print("\n✅ Prueba completada")