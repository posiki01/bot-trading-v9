#!/usr/bin/env python3
"""
trading/ejecucion.py (V9.65 - REFACTORIZADO DEFINITIVO)
Ejecución de órdenes de trading con validación completa.

V9.65 - CORRECCIONES CRÍTICAS:
- ✅ Prevención de duplicación de operaciones (bloqueo atómico)
- ✅ Capital REAL desde MT5 (no de memoria)
- ✅ Verificación de margen REAL disponible
- ✅ Validación SL/TP según modo de entrada
- ✅ Validación de timing según modo
- ✅ Validación de duplicados en MT5 antes de ejecutar
- ✅ Bloqueo de operaciones por símbolo
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from decimal import Decimal

# Importar módulos internos
from trading.stops import GestorStops, create_gestor_stops

logger = logging.getLogger('BotTrading.Ejecucion')


class EjecutorOperaciones:
    """
    Ejecuta órdenes de trading con validación robusta.
    V9.65 - REFACTORIZADO DEFINITIVO.
    """
    
    def __init__(self,
                 orquestador: Any,
                 mt5: Any,
                 gestion_riesgo: Any,
                 gestor_stops: Any,
                 notificaciones: Any,
                 modo_backtest: bool = False,
                 almacen: Optional[Any] = None):
        """
        Inicializa el ejecutor de operaciones.
        V9.65 - REFACTORIZADO.
        """
        self.orquestador = orquestador
        self.mt5 = mt5
        self.gestion_riesgo = gestion_riesgo
        self.gestor_stops = gestor_stops
        self.notificaciones = notificaciones
        self.almacen = almacen
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.Ejecutor')
        
        # ✅ NUEVO V9.65: Lock para operaciones pendientes
        self._lock_operaciones = threading.Lock()
        self._operaciones_pendientes: Dict[str, str] = {}
        
        # ✅ NUEVO V9.65: Contador de reintentos por símbolo
        self._reintentos_por_simbolo: Dict[str, int] = {}
        self._max_reintentos = 3
        
        self.logger.info(f"📈 EjecutorOperaciones V9.65 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def ejecutar(self, señal: Dict[str, Any]) -> bool:
        """
        Ejecuta una operación con validación completa.
        V9.65 - CORREGIDO DEFINITIVO:
        - Valida R:R >= 1.5 antes de ejecutar
        - Valida SL/TP según dirección real (COMPRA/VENTA)
        - Previene duplicados con bloqueo atómico
        - Usa capital REAL de MT5
        """
        from config.umbrales import Umbrales
        from datetime import datetime, timezone
        from decimal import Decimal
        
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
        
        # ============================================================
        # 2. VALIDACIONES PREVIAS
        # ============================================================
        if not simbolo or not direccion:
            self.logger.error("❌ Señal incompleta")
            return False
        
        # ✅ CORREGIDO: Normalizar dirección
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
        
        # ============================================================
        # 3. ✅ NUEVO V9.65: PREVENCIÓN DE DUPLICADOS (BLOQUEO ATÓMICO)
        # ============================================================
        
        # 3.1 Verificar si ya hay operación pendiente en el símbolo
        with self._lock_operaciones:
            if simbolo in self._operaciones_pendientes:
                self.logger.error(f"⛔ {simbolo}: Operación YA EN PROCESO (pendiente desde {self._operaciones_pendientes[simbolo]})")
                return False
            
            # Marcar como pendiente
            self._operaciones_pendientes[simbolo] = datetime.now(timezone.utc).isoformat()
        
        try:
            # 3.2 Verificar en MT5 (si no es backtest)
            if not self.modo_backtest:
                valido, razon = self._verificar_posiciones_existentes(simbolo, direccion)
                if not valido:
                    self.logger.error(f"⛔ {razon}")
                    return False
            
            # ============================================================
            # 4. OBTENER CAPITAL REAL
            # ============================================================
            capital = self._obtener_capital_real()
            
            if isinstance(capital, Decimal):
                capital = float(capital)
            
            if capital <= 0:
                self.logger.error(f"❌ Capital insuficiente: ${capital:.2f}")
                return False
            
            # ============================================================
            # 5. ✅ VALIDAR CAPITAL MÍNIMO POR ACTIVO
            # ============================================================
            valido_capital, razon_capital = self._validar_capital_minimo(simbolo, capital)
            
            if not valido_capital:
                self.logger.error(f"❌ {razon_capital}")
                self.logger.info(f"   💡 Recomendación: Esperar a que el capital crezca o operar activos con menor requerimiento")
                return False
            
            self.logger.info(f"✅ {simbolo}: Capital suficiente (${capital:.2f})")
            
            simbolo_upper = simbolo.upper()
            
            # ============================================================
            # 6. OBTENER PARÁMETROS DEL SÍMBOLO
            # ============================================================
            pip_size = self._obtener_pip_size(simbolo)
            valor_pip = self._calcular_valor_pip(simbolo)
            
            if pip_size <= 0 or valor_pip <= 0:
                self.logger.error(f"❌ Parámetros inválidos: pip_size={pip_size}, valor_pip={valor_pip}")
                return False
            
            # ============================================================
            # 7. CALCULAR SL EN PIPS
            # ============================================================
            sl_dist = abs(entry_price - sl)
            sl_pips = sl_dist / pip_size if pip_size > 0 else 10
            
            if sl_pips <= 0:
                self.logger.error(f"❌ SL inválido: {sl_pips:.1f} pips")
                return False
            
            # ============================================================
            # 8. ✅ CALCULAR LOTES DINÁMICOS
            # ============================================================
            lotes_max_por_activo = getattr(Umbrales, 'LOTES_MAX_POR_ACTIVO', {})
            lotes_min_por_activo = getattr(Umbrales, 'LOTES_MIN_POR_ACTIVO', {})
            riesgo_max_por_operacion = getattr(Umbrales, 'RIESGO_MAX_POR_OPERACION', {})
            
            lote_max = lotes_max_por_activo.get(simbolo_upper, 0.10)
            lote_min = lotes_min_por_activo.get(simbolo_upper, 0.01)
            riesgo_pct = riesgo_max_por_operacion.get(simbolo_upper, 0.01)
            
            riesgo_pct = float(riesgo_pct)
            
            # ✅ CALCULAR VALOR DEL PIP REAL
            valor_pip_por_lote = self._calcular_valor_pip(simbolo)
            
            # ✅ VERIFICAR SPREAD ACTUAL
            spread_actual = 0
            if not self.modo_backtest:
                tick = self.mt5.obtener_precio(simbolo)
                if tick:
                    spread_actual = float(tick.get('spread_pips', 0))
            
            # ✅ FACTOR DE SPREAD
            spread_max = {
                'XAUUSD': 30, 'XAGUSD': 30,
                'BTCUSD': 50, 'ETHUSD': 50, 'SOLUSD': 50,
                'US30': 5, 'NAS100': 5, 'US500': 5,
                'EURUSD': 2, 'GBPUSD': 2, 'USDJPY': 2,
            }.get(simbolo_upper, 3)
            
            if spread_actual > spread_max:
                factor_spread = 0.5
                self.logger.warning(f"⚠️ {simbolo}: Spread alto ({spread_actual:.1f} pips > {spread_max} pips) - Reduciendo lote")
            elif spread_actual > spread_max * 0.7:
                factor_spread = 0.7
            else:
                factor_spread = 1.0
            
            # ✅ CALCULAR LOTES POR RIESGO
            riesgo_dinero = capital * riesgo_pct
            lotes_por_riesgo = riesgo_dinero / (sl_pips * valor_pip_por_lote) if sl_pips > 0 and valor_pip_por_lote > 0 else 0
            
            # ✅ APLICAR FACTORES
            lotes = lotes_por_riesgo * factor_spread
            
            # ✅ REDONDEAR Y APLICAR LÍMITES
            lotes = round(lotes / 0.01) * 0.01
            
            if lotes < lote_min:
                lotes = lote_min
            if lotes > lote_max:
                lotes = lote_max
            
            self.logger.info(f"📊 {simbolo}: Lotes calculados dinámicamente:")
            self.logger.info(f"   Capital: ${capital:.2f}")
            self.logger.info(f"   Riesgo: {riesgo_pct*100:.2f}% (${riesgo_dinero:.2f})")
            self.logger.info(f"   SL: {sl_pips:.1f} pips")
            self.logger.info(f"   Valor pip (1 lote): ${valor_pip_por_lote:.4f}")
            self.logger.info(f"   Valor pip (lote actual): ${valor_pip_por_lote * lotes:.4f}")
            self.logger.info(f"   Riesgo real: ${sl_pips * valor_pip_por_lote * lotes:.2f}")
            self.logger.info(f"   Spread: {spread_actual:.1f} pips (factor: {factor_spread:.2f})")
            self.logger.info(f"   Lotes: {lotes:.3f} (min: {lote_min}, max: {lote_max})")
            
            if lotes <= 0:
                self.logger.error(f"❌ {simbolo}: Lotes inválidos ({lotes:.3f})")
                return False
            
            # ============================================================
            # 9. ✅ VALIDAR LOTE MÍNIMO DEL BROKER
            # ============================================================
            lote_minimo_broker = self._obtener_lote_minimo_broker(simbolo)
            
            if lotes < lote_minimo_broker:
                self.logger.warning(f"⚠️ {simbolo}: Lotes calculados ({lotes:.3f}) < mínimo broker ({lote_minimo_broker:.3f})")
                
                capital_necesario = lote_minimo_broker * sl_pips * valor_pip_por_lote / riesgo_pct
                self.logger.info(f"   Capital necesario para lote mínimo: ${capital_necesario:.2f}")
                
                if capital < capital_necesario:
                    self.logger.error(f"❌ {simbolo}: Capital insuficiente para operar (${capital:.2f} < ${capital_necesario:.2f})")
                    self.logger.error(f"   💡 Recomendación: Operar activos con menor requerimiento de capital")
                    return False
                
                lotes = lote_minimo_broker
                self.logger.info(f"📊 {simbolo}: Lotes ajustados a mínimo broker ({lotes:.3f})")
            
            # ✅ NUEVO V9.65: VERIFICAR MARGEN REAL
            valido_margen, razon_margen = self._verificar_margen_real(simbolo, lotes, entry_price)
            if not valido_margen:
                self.logger.error(f"❌ {razon_margen}")
                return False
            
            # ✅ Verificar margen (estimación)
            margen_requerido = self._estimar_margen(simbolo, lotes, entry_price)
            margen_disponible = capital * 0.8
            
            if margen_requerido > margen_disponible and lotes > lote_min:
                self.logger.warning(f"⚠️ {simbolo}: Margen insuficiente (req: ${margen_requerido:.2f}, disp: ${margen_disponible:.2f})")
                while margen_requerido > margen_disponible and lotes > lote_min:
                    lotes = max(lote_min, lotes * 0.8)
                    margen_requerido = self._estimar_margen(simbolo, lotes, entry_price)
                    self.logger.info(f"📊 {simbolo}: Lotes reducidos a {lotes:.3f} por margen")
            
            # ============================================================
            # 10. VALIDAR SL/TP CON EL GESTOR DE STOPS
            # ============================================================
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
            
            self.logger.info(f"✅ SL/TP validado: {simbolo} {direccion} | SL={sl_validado:.5f} | TP={tp_validado:.5f}")
            
            # ============================================================
            # 11. ✅ NUEVO V9.65: VALIDAR SL/TP SEGÚN MODO
            # ============================================================
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
            
            # ============================================================
            # 12. ✅ NUEVO V9.65: VALIDAR TIMING SEGÚN MODO
            # ============================================================
            valido_timing, razon_timing = self._validar_timing_por_modo(
                simbolo=simbolo,
                modo=modo,
                direccion=direccion,
                precio_actual=entry_price
            )
            
            if not valido_timing:
                self.logger.error(f"❌ {razon_timing}")
                return False
            
            # ============================================================
            # 13. ✅ VALIDAR R:R >= 1.5 ANTES DE EJECUTAR
            # ============================================================
            rr = abs(tp_validado - entry_price) / abs(sl_validado - entry_price) if abs(sl_validado - entry_price) > 0 else 0
            
            if rr < 1.5:
                self.logger.error(f"❌ {simbolo}: R:R insuficiente ({rr:.2f} < 1.5)")
                return False
            
            self.logger.info(f"✅ {simbolo}: R:R válido ({rr:.2f} >= 1.5)")
            
            # ============================================================
            # 14. OBTENER TICK ACTUAL
            # ============================================================
            tick = self.mt5.obtener_precio(simbolo) if not self.modo_backtest else None
            if not self.modo_backtest:
                if not tick:
                    self.logger.error(f"❌ No se pudo obtener precio para {simbolo}")
                    return False
                
                bid = tick.get('bid', 0)
                ask = tick.get('ask', 0)
                
                if bid <= 0 or ask <= 0:
                    self.logger.error(f"❌ Precio inválido: bid={bid}, ask={ask}")
                    return False
                
                # ✅ CORREGIDO V9.64: VALIDACIÓN ESTRICTA DE SL/TP SEGÚN DIRECCIÓN
                if direccion == 'COMPRA':
                    if sl_validado >= ask:
                        self.logger.error(f"❌ {simbolo}: SL INVERTIDO para COMPRA (SL={sl_validado:.5f} >= ask={ask:.5f})")
                        self.logger.error(f"   💡 El SL debe estar DEBAJO del precio de entrada")
                        return False
                    if tp_validado <= ask:
                        self.logger.error(f"❌ {simbolo}: TP inválido para COMPRA (TP={tp_validado:.5f} <= ask={ask:.5f})")
                        self.logger.error(f"   💡 El TP debe estar ARRIBA del precio de entrada")
                        return False
                else:  # VENTA
                    if sl_validado <= bid:
                        self.logger.error(f"❌ {simbolo}: SL INVERTIDO para VENTA (SL={sl_validado:.5f} <= bid={bid:.5f})")
                        self.logger.error(f"   💡 El SL debe estar ARRIBA del precio de entrada")
                        return False
                    if tp_validado >= bid:
                        self.logger.error(f"❌ {simbolo}: TP inválido para VENTA (TP={tp_validado:.5f} >= bid={bid:.5f})")
                        self.logger.error(f"   💡 El TP debe estar DEBAJO del precio de entrada")
                        return False
                
                # Determinar precio de ejecución
                if direccion == 'COMPRA':
                    precio_ejecucion = ask
                else:
                    precio_ejecucion = bid
            else:
                precio_ejecucion = entry_price
            
            # ============================================================
            # 15. ENVIAR ORDEN
            # ============================================================
            comentario = f"Bot_{modo}_{score:.0f}"
            
            # ✅ Obtener magic_number
            magic_number = getattr(self.mt5, 'magic_number', None)
            if magic_number is None:
                magic_number = getattr(self.orquestador.config, 'MAGIC_NUMBER', 0)
            
            # ✅ CORREGIDO V9.64: Usar try/except para magic_number
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
                self.logger.warning(f"⚠️ {simbolo}: Conector no acepta magic_number, usando default")
                resultado = self.mt5.enviar_orden(
                    simbolo=simbolo,
                    tipo=direccion,
                    volumen=lotes,
                    sl=sl_validado,
                    tp=tp_validado,
                    comentario=comentario
                )
            
            if not resultado or resultado.get('ticket') is None:
                self.logger.error(f"❌ Falló ejecución de {simbolo}: {resultado.get('comentario', 'Error desconocido')}")
                return False
            
            # ✅ CORREGIDO V9.64: Usar SL/TP REALES del broker
            sl_real = resultado.get('sl', sl_validado)
            tp_real = resultado.get('tp', tp_validado)
            precio_ejecutado = resultado.get('precio', precio_ejecucion)
            
            # ============================================================
            # 16. REGISTRAR OPERACIÓN CON SL/TP REALES
            # ============================================================
            ticket = resultado.get('ticket')
            
            operacion = {
                'ticket': ticket,
                'simbolo': simbolo,
                'direccion': direccion,
                'entrada': precio_ejecutado,
                'lotes': lotes,
                'sl': sl_real,
                'tp': tp_real,
                'tp2': tp2_validado,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'estado': 'ABIERTA',
                'modo': modo,
                'score': score,
                'regimen': regimen,
                'es_sniper': True,
            }
            
            # Guardar en almacenamiento
            if self.almacen:
                try:
                    self.almacen.guardar_operacion(operacion)
                except Exception as e:
                    self.logger.warning(f"⚠️ Error guardando operación: {e}")
            
            # Actualizar estado global
            if hasattr(self, 'orquestador') and self.orquestador:
                self.orquestador.estado.posiciones_abiertas[ticket] = operacion
            
            # ============================================================
            # 17. NOTIFICAR
            # ============================================================
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
            })
            
            self.logger.info(f"✅ ORDEN EJECUTADA: {simbolo} {direccion} {lotes:.3f} @ {precio_ejecutado:.5f} (Ticket: {ticket})")
            
            return True
            
        finally:
            # ✅ SIEMPRE limpiar el bloqueo al finalizar
            with self._lock_operaciones:
                if simbolo in self._operaciones_pendientes:
                    del self._operaciones_pendientes[simbolo]
        
    # ============================================================
    # ✅ NUEVO V9.65: MÉTODOS DE VALIDACIÓN
    # ============================================================
    
    def _verificar_posiciones_existentes(self, simbolo: str, direccion: str) -> Tuple[bool, str]:
        """
        Verifica si ya existe una posición del mismo símbolo y dirección.
        V9.65 - CRÍTICO: Previene duplicados.
        """
        try:
            posiciones = self.mt5.obtener_posiciones()
            
            if not posiciones:
                return True, "Sin posiciones existentes"
            
            for pos in posiciones:
                if pos.get('simbolo') == simbolo:
                    # Determinar dirección de la posición existente
                    tipo = pos.get('tipo')
                    if tipo in ['BUY', 0, 'COMPRA']:
                        direccion_existente = 'COMPRA'
                    elif tipo in ['SELL', 1, 'VENTA']:
                        direccion_existente = 'VENTA'
                    else:
                        direccion_existente = pos.get('direccion', 'DESCONOCIDO')
                    
                    # ✅ Si es la MISMA dirección, bloquear
                    if direccion_existente == direccion:
                        return False, f"⛔ {simbolo}: YA EXISTE posición {direccion} (Ticket: {pos.get('ticket')})"
                    
                    # ✅ Si es dirección OPUESTA, permitir (según configuración)
                    if direccion_existente != direccion:
                        self.logger.info(f"ℹ️ {simbolo}: Posición opuesta existente ({direccion_existente}) - permitiendo {direccion}")
            
            return True, "Sin conflictos"
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error verificando posiciones en MT5: {e}")
            return True, "No se pudo verificar (permitiendo)"
    
    def _obtener_capital_real(self) -> float:
        """
        Obtiene capital REAL desde MT5 (no de memoria).
        V9.65 - CRÍTICO: Capital actualizado en tiempo real.
        """
        if self.modo_backtest:
            return float(self.gestion_riesgo.capital_actual)
        
        try:
            cuenta = self.mt5.info_cuenta()
            if cuenta and cuenta.get('balance', 0) > 0:
                balance_real = float(cuenta['balance'])
                self.logger.info(f"💰 Capital REAL de MT5: ${balance_real:.2f}")
                
                # Actualizar en gestión de riesgo
                try:
                    self.gestion_riesgo.capital_actual = balance_real
                except:
                    pass
                
                return balance_real
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo capital de MT5: {e}")
        
        # Fallback a capital en memoria
        return float(self.gestion_riesgo.capital_actual)
    
    def _verificar_margen_real(self, simbolo: str, lotes: float, precio: float) -> Tuple[bool, str]:
        """
        Verifica si hay margen REAL disponible en la cuenta.
        V9.65 - CRÍTICO: No usar solo estimaciones.
        """
        if self.modo_backtest:
            return True, "Backtest (sin verificación de margen)"
        
        try:
            cuenta = self.mt5.info_cuenta()
            margen_libre = float(cuenta.get('margin_free', 0))
            
            margen_requerido = self._estimar_margen(simbolo, lotes, precio)
            
            self.logger.info(f"📊 {simbolo}: Margen libre: ${margen_libre:.2f} | Requerido: ${margen_requerido:.2f}")
            
            # ✅ Margen de seguridad: requerir 20% adicional
            margen_con_seguridad = margen_requerido * 1.20
            
            if margen_con_seguridad > margen_libre:
                return False, f"Margen insuficiente (req: ${margen_requerido:.2f}, libre: ${margen_libre:.2f})"
            
            return True, "Margen OK"
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error verificando margen: {e}")
            return True, "No se pudo verificar margen (permitiendo)"
    
    def _validar_sl_tp_por_modo(self, simbolo: str, modo: str, sl: float, tp: float, 
                               entry_price: float, direccion: str, regimen: str) -> Tuple[bool, str]:
        """
        Validación específica de SL/TP según el modo de entrada.
        V9.65 - NUEVO.
        """
        pip_val = self._obtener_pip_size(simbolo)
        sl_dist = abs(entry_price - sl)
        sl_pips = sl_dist / pip_val if pip_val > 0 else 0
        tp_dist = abs(tp - entry_price)
        tp_pips = tp_dist / pip_val if pip_val > 0 else 0
        
        # R:R mínimo por modo
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
        
        if rr < rr_min_modo:
            return False, f"R:R insuficiente para {modo} ({rr:.2f} < {rr_min_modo})"
        
        # SL mínimo por tipo de activo
        sl_min_activo = {
            'XAUUSD': 50, 'XAGUSD': 50,
            'US30': 30, 'NAS100': 30, 'US500': 25,
            'BTCUSD': 100, 'ETHUSD': 80, 'SOLUSD': 60,
            'EURUSD': 10, 'GBPUSD': 10, 'USDJPY': 10,
            'AUDUSD': 10, 'USDCAD': 10, 'USDCHF': 10,
            'EURGBP': 10, 'EURJPY': 15, 'GBPJPY': 18,
        }.get(simbolo, 10)
        
        if sl_pips < sl_min_activo:
            return False, f"SL demasiado cerca para {simbolo} ({sl_pips:.0f} < {sl_min_activo} pips)"
        
        # Validación específica por régimen
        if regimen in ['CHOP_VOLATIL', 'RANGO_APRETADO'] and modo in ['RETEST', 'NIVEL_FUERTE']:
            if sl_pips > 50:
                return False, f"SL demasiado amplio para {regimen} ({sl_pips:.0f} pips)"
        
        return True, "SL/TP válido para modo"
    
    def _validar_timing_por_modo(self, simbolo: str, modo: str, direccion: str, precio_actual: float) -> Tuple[bool, str]:
        """
        Validación de timing según modo.
        V9.65 - NUEVO.
        """
        ahora = datetime.now(timezone.utc)
        hora_utc = ahora.hour + ahora.minute / 60.0
        
        # Horarios prohibidos para ciertos modos
        if modo in ['BREAKOUT', 'RUPTURA_FALSA']:
            # No operar en horario asiático para breakouts
            if 0 <= hora_utc < 7:
                return False, f"BREAKOUT no recomendado en horario asiático ({hora_utc:.1f} UTC)"
        
        if modo == 'SNIPER_ELITE':
            # Operar solo en horas de alta liquidez
            if not (7 <= hora_utc < 17):
                return False, f"SNIPER_ELITE requiere alta liquidez (07-17 UTC), actual: {hora_utc:.1f} UTC"
        
        # Verificar noticias próximas si el modo requiere
        if hasattr(self, 'orquestador') and self.orquestador.noticias:
            try:
                noticias = self.orquestador.noticias.obtener_noticias_proximas(simbolo)
                if noticias:
                    for noticia in noticias[:2]:
                        minutos_restantes = (noticia['fecha'] - ahora).total_seconds() / 60
                        if 0 <= minutos_restantes < 30:
                            if modo in ['SNIPER_ELITE', 'BREAKOUT']:
                                return False, f"Noticia en {minutos_restantes:.0f} min - no operar {modo}"
            except:
                pass
        
        return True, "Timing OK"
    
    def _obtener_lote_minimo_broker(self, simbolo: str) -> float:
        """
        Obtiene el lote mínimo del broker para el símbolo.
        V9.59 - NUEVO.
        """
        simbolo_upper = simbolo.upper()
        
        LOTES_MINIMOS_BROKER = {
            'US500': 0.10, 'US30': 0.10, 'NAS100': 0.10, 'SP500': 0.10,
            'XAUUSD': 0.01, 'XAGUSD': 0.01,
            'BTCUSD': 0.01, 'ETHUSD': 0.01, 'SOLUSD': 0.01,
            'EURUSD': 0.01, 'GBPUSD': 0.01, 'USDJPY': 0.01,
            'AUDUSD': 0.01, 'USDCAD': 0.01, 'USDCHF': 0.01,
            'EURGBP': 0.01, 'EURJPY': 0.01, 'GBPJPY': 0.01,
            'AUDJPY': 0.01, 'NZDUSD': 0.01, 'EURNZD': 0.01,
            'GBPAUD': 0.01, 'GBPCHF': 0.01, 'EURCHF': 0.01,
            'AUDCAD': 0.01, 'AUDCHF': 0.01, 'CADJPY': 0.01,
            'CHFJPY': 0.01, 'EURAUD': 0.01, 'EURCAD': 0.01,
            'GBPCAD': 0.01, 'NZDJPY': 0.01,
        }
        
        return LOTES_MINIMOS_BROKER.get(simbolo_upper, 0.01)
    
    def _validar_capital_minimo(self, simbolo: str, capital: float) -> Tuple[bool, str]:
        """
        Valida si el capital es suficiente para operar el símbolo.
        
        Args:
            simbolo: Símbolo a validar
            capital: Capital actual
        
        Returns:
            (es_suficiente, razon)
        """
        simbolo_upper = simbolo.upper()
        
        # Definir capital mínimo por tipo de activo
        CAPITAL_MINIMO = {
            # Índices (apalancamiento 1:500 → margen ~$10-15)
            'US30': 100,
            'NAS100': 100,
            'US500': 100,
            'SP500': 100,
            
            # Metales (apalancamiento 1:500 → margen ~$5-10)
            'XAUUSD': 100,
            'XAGUSD': 100,
            
            # Cripto (apalancamiento 1:10 → margen ~$50-100)
            'BTCUSD': 200,
            'ETHUSD': 200,
            'SOLUSD': 200,
            
            # Forex (apalancamiento 1:500 → margen ~$2-5)
            'EURUSD': 50,
            'GBPUSD': 50,
            'USDJPY': 50,
            'AUDUSD': 50,
            'USDCAD': 50,
            'USDCHF': 50,
            'EURGBP': 50,
            'EURJPY': 50,
            'GBPJPY': 50,
            'AUDJPY': 50,
        }
            
        capital_minimo = CAPITAL_MINIMO.get(simbolo_upper, 50)
        
        if capital < capital_minimo:
            return False, f"Capital insuficiente para {simbolo_upper} (${capital:.2f} < ${capital_minimo})"
        
        return True, "OK"
    
    def _obtener_pip_size(self, simbolo: str) -> float:
        """
        Obtiene el tamaño del pip para el símbolo.
        V9.35 - NUEVO.
        """
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        elif 'XAU' in simbolo_upper:
            return 0.01
        elif 'XAG' in simbolo_upper:
            return 0.1
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        else:
            return 0.0001

    def _calcular_valor_pip(self, simbolo: str) -> float:
        """
        Calcula el valor de 1 pip en USD para 1 lote estándar.
        V9.62 - CORREGIDO: Usa tamaño de contrato y precio real.
        """
        simbolo_upper = simbolo.upper()
        
        # 1. Intentar desde MT5 (fuente primaria)
        if self.mt5 is not None and not self.modo_backtest:
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None:
                    # Obtener tamaño de contrato
                    contract_size = float(getattr(info, 'trade_contract_size', 0))
                    if contract_size > 0:
                        # Obtener tick value y tick size
                        tick_value = float(getattr(info, 'trade_tick_value', 0))
                        tick_size = float(getattr(info, 'trade_tick_size', 0))
                        if tick_value > 0 and tick_size > 0:
                            # Valor de 1 pip = tick_value * (pip_size / tick_size)
                            pip_size = self._obtener_pip_size(simbolo)
                            return tick_value * (pip_size / tick_size)
                        else:
                            # Fallback: calcular con contract_size y precio
                            tick = self.mt5.obtener_precio(simbolo)
                            if tick:
                                precio = float(tick.get('bid', 1.0))
                                pip_size = self._obtener_pip_size(simbolo)
                                # Para pares con USD como base, valor = contract_size * pip_size
                                if 'USD' in simbolo_upper:
                                    return contract_size * pip_size
                                # Para pares con USD como cotización (ej: EURUSD), valor = contract_size * pip_size / precio
                                return contract_size * pip_size / precio
            except Exception as e:
                self.logger.debug(f"⚠️ Error obteniendo valor pip de MT5 para {simbolo}: {e}")
        
        # 2. Fallback estático (más preciso)
        if 'JPY' in simbolo_upper:
            return 0.01 * 100000 / 150
        elif 'XAU' in simbolo_upper:
            return 0.01 * 100
        elif 'XAG' in simbolo_upper:
            return 0.01 * 5000
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0 * 1
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0 * 1
        else:
            return 0.0001 * 100000

    def _estimar_margen(self, simbolo: str, lotes: float, precio: float) -> float:
        """
        Estima el margen requerido para una operación.
        V9.35 - NUEVO.
        """
        simbolo_upper = simbolo.upper()
        
        # Apalancamiento típico
        apalancamiento = 30
        
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            apalancamiento = 20
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            apalancamiento = 20
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            apalancamiento = 10
        
        # Tamaño del contrato
        contract_size = 100000
        
        if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
            contract_size = 100
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            contract_size = 1
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            contract_size = 1
        
        valor_operacion = lotes * contract_size * precio
        margen = valor_operacion / apalancamiento
        
        return margen


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
    """
    Crea una instancia de EjecutorOperaciones.
    
    Args:
        orquestador: Orquestador principal
        mt5: Conector MT5
        gestion_riesgo: Gestión de riesgo
        gestor_stops: Gestor de stops (opcional)
        notificaciones: Sistema de notificaciones
        modo_backtest: Modo backtest
        almacen: Almacenamiento SQLite
    
    Returns:
        EjecutorOperaciones
    """
    return EjecutorOperaciones(
        orquestador=orquestador,
        mt5=mt5,
        gestion_riesgo=gestion_riesgo,
        gestor_stops=gestor_stops,
        notificaciones=notificaciones,
        modo_backtest=modo_backtest,
        almacen=almacen
    )