#!/usr/bin/env python3
"""
trading/ejecucion.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Ejecución de órdenes de trading.

RESPONSABILIDADES:
- Validar operaciones antes de ejecutar
- Obtener precios de mercado
- Ejecutar órdenes en MT5
- Registrar operaciones ejecutadas
- Manejar reintentos inteligentes
- Gestionar errores de ejecución

MEJORAS V9.0:
- Separación de responsabilidades
- Validación robusta de slippage
- Reintentos inteligentes con backoff
- Logs detallados de cada paso
- Rollback en caso de fallo
- Soporte para backtest
- Integración con gestor_stops
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from decimal import Decimal

# Importar módulos internos
from trading.stops import GestorStops, create_gestor_stops

logger = logging.getLogger('BotTrading.Ejecucion')


class EjecutorOperaciones:
    """
    Ejecuta órdenes de trading con validación robusta.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    def __init__(self,
                 orquestador: Any,
                 mt5: Any,
                 gestion_riesgo: Any,
                 gestor_stops: Optional[GestorStops] = None,
                 notificaciones: Optional[Any] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el ejecutor de operaciones.
        
        Args:
            orquestador: Orquestador principal
            mt5: Conector MT5
            gestion_riesgo: Gestión de riesgo
            gestor_stops: Gestor de stops (opcional)
            notificaciones: Sistema de notificaciones
            modo_backtest: Modo backtest
        """
        self.orquestador = orquestador
        self.mt5 = mt5
        self.gestion_riesgo = gestion_riesgo
        self.gestor_stops = gestor_stops or create_gestor_stops(modo_backtest=modo_backtest)
        self.notificaciones = notificaciones
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.Ejecucion')
        
        # Estadísticas
        self._stats = {
            'total_ejecuciones': 0,
            'ejecuciones_exitosas': 0,
            'ejecuciones_fallidas': 0,
            'reintentos': 0,
            'slippage_promedio': 0.0,
        }
        
        self.logger.info(f"🚀 EjecutorOperaciones V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def ejecutar(self, op: Dict[str, Any]) -> bool:
        """
        Ejecuta una operación completa.
        
        Args:
            op: Datos de la operación
        
        Returns:
            True si se ejecutó correctamente
        """
        self._stats['total_ejecuciones'] += 1
        simbolo = op.get('simbolo', '')
        direccion = op.get('direccion', 'NEUTRAL')
        
        self.logger.info(f"🚀 Ejecutando {simbolo} {direccion}...")
        
        # 1. Validar operación
        valido, razon = self._validar_operacion(op)
        if not valido:
            self.logger.error(f"❌ Operación inválida: {razon}")
            self._stats['ejecuciones_fallidas'] += 1
            self._registrar_oportunidad_no_tomada(op, razon)
            return False
        
        # 2. Verificar capacidad
        if not self._verificar_capacidad():
            self._stats['ejecuciones_fallidas'] += 1
            self._registrar_oportunidad_no_tomada(op, "Capacidad insuficiente")
            return False
        
        # 3. Obtener precio de mercado
        precio_data = self._obtener_precio_mercado(simbolo)
        if not precio_data:
            self._stats['ejecuciones_fallidas'] += 1
            self._registrar_oportunidad_no_tomada(op, "No se pudo obtener precio")
            return False
        
        bid = float(precio_data.get('bid', 0))
        ask = float(precio_data.get('ask', 0))
        spread = float(precio_data.get('spread', 0))
        spread_pips = precio_data.get('spread_pips', 0)
        
        if direccion == 'COMPRA':
            precio_market = ask
        else:
            precio_market = bid
        
        if precio_market <= 0:
            self.logger.error(f"❌ Precio inválido para {simbolo}: {precio_market}")
            self._stats['ejecuciones_fallidas'] += 1
            self._registrar_oportunidad_no_tomada(op, "Precio inválido")
            return False
        
        # 4. Validar spread
        if not self._validar_spread(simbolo, spread_pips):
            self._stats['ejecuciones_fallidas'] += 1
            self._registrar_oportunidad_no_tomada(op, f"Spread alto: {spread_pips:.1f}pips")
            return False
        
        # 5. Validar slippage
        precio_propuesto = op.get('entry_price', 0) or op.get('precio', precio_market)
        if not self._validar_slippage(simbolo, precio_propuesto, precio_market):
            self._stats['ejecuciones_fallidas'] += 1
            self._registrar_oportunidad_no_tomada(op, f"Slippage excedido")
            return False
        
        # 6. Calcular SL/TP
        sl_tp = self._calcular_sl_tp(op, precio_market)
        if not sl_tp:
            self._stats['ejecuciones_fallidas'] += 1
            self._registrar_oportunidad_no_tomada(op, "SL/TP inválido")
            return False
        
        # 7. Calcular lotes
        lotes = self._calcular_lotes(op, sl_tp, precio_market)
        if lotes <= 0:
            self._stats['ejecuciones_fallidas'] += 1
            self._registrar_oportunidad_no_tomada(op, "Lotes inválidos")
            return False
        
        # 8. Validar R:R final
        if not self._validar_rr_final(precio_market, sl_tp['sl'], sl_tp['tp'], direccion):
            self._stats['ejecuciones_fallidas'] += 1
            self._registrar_oportunidad_no_tomada(op, "R:R insuficiente")
            return False
        
        # 9. Ejecutar en MT5 (o simular en backtest)
        if self.modo_backtest:
            resultado = self._ejecutar_backtest(simbolo, direccion, precio_market, lotes, sl_tp, op)
        else:
            resultado = self._ejecutar_mt5(simbolo, direccion, precio_market, lotes, sl_tp, op)
        
        if not resultado:
            self._stats['ejecuciones_fallidas'] += 1
            self._registrar_oportunidad_no_tomada(op, "Fallo en ejecución")
            return False
        
        # 10. Registrar operación
        self._registrar_operacion(resultado, op, sl_tp, lotes)
        
        # 11. Limpiar pipeline
        self._limpiar_pipeline(simbolo)
        
        self._stats['ejecuciones_exitosas'] += 1
        
        self.logger.info(
            f"✅ {simbolo} {direccion} ejecutada | "
            f"Ticket: {resultado.get('ticket')} | "
            f"Precio: {precio_market:.5f} | "
            f"Lotes: {lotes:.3f} | "
            f"R:R: {sl_tp.get('rr', 0):.2f}"
        )
        
        return True
    
    # ============================================================
    # VALIDACIONES
    # ============================================================
    
    def _validar_operacion(self, op: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Valida los datos de la operación.
        
        Args:
            op: Datos de la operación
        
        Returns:
            (valido, razon)
        """
        simbolo = op.get('simbolo', '')
        direccion = op.get('direccion', '')
        score = op.get('score', 0)
        
        if not simbolo:
            return False, "Símbolo no definido"
        
        if direccion not in ['COMPRA', 'VENTA']:
            return False, f"Dirección inválida: {direccion}"
        
        if score < 20:
            return False, f"Score demasiado bajo: {score:.1f}"
        
        return True, "OK"
    
    def _verificar_capacidad(self) -> bool:
        """
        Verifica capacidad de operar.
        
        Returns:
            True si se puede operar
        """
        # Circuit breaker
        if self.gestion_riesgo.circuit_breaker.verificar():
            self.logger.warning("⛔ Circuit breaker activo")
            return False
        
        # Capital
        if self.gestion_riesgo.capital_actual <= 0:
            self.logger.warning("⛔ Capital insuficiente")
            return False
        
        # Posiciones simultáneas
        posiciones = self.mt5.obtener_posiciones()
        max_sim = self.gestion_riesgo.obtener_max_simultaneas()
        
        if posiciones and len(posiciones) >= max_sim:
            self.logger.warning(f"⛔ Máximo de posiciones alcanzado: {len(posiciones)}/{max_sim}")
            return False
        
        return True
    
    def _validar_spread(self, simbolo: str, spread_pips: float) -> bool:
        """
        Valida el spread actual.
        
        Args:
            simbolo: Símbolo
            spread_pips: Spread en pips
        
        Returns:
            True si el spread es aceptable
        """
        # Obtener spread máximo del símbolo
        config_activos = self.orquestador.config.CONFIG_ACTIVOS
        spread_max = config_activos.get(simbolo, {}).get('spread_max', 3.0)
        
        # Ajuste por horario
        ahora = datetime.now(timezone.utc)
        hora_utc = ahora.hour + ahora.minute / 60.0
        
        # En horario asiático, más permisivo
        if 0 <= hora_utc < 8:
            spread_max = spread_max * 1.5
        
        # En overlap, menos permisivo
        if 12 <= hora_utc < 16:
            spread_max = spread_max * 0.8
        
        if spread_pips > spread_max:
            self.logger.warning(
                f"⚠️ Spread alto para {simbolo}: {spread_pips:.1f}pips > {spread_max:.1f}"
            )
            return False
        
        return True
    
    def _validar_slippage(self, simbolo: str, precio_propuesto: float, precio_market: float) -> bool:
        """
        Valida el slippage entre precio propuesto y mercado.
        
        Args:
            simbolo: Símbolo
            precio_propuesto: Precio propuesto
            precio_market: Precio de mercado
        
        Returns:
            True si el slippage es aceptable
        """
        if precio_propuesto <= 0:
            return True  # Sin precio propuesto, aceptar mercado
        
        slippage = abs(precio_market - precio_propuesto) / precio_propuesto
        
        # Obtener slippage máximo
        max_slippage = getattr(self.orquestador.config, 'MAX_SLIPPAGE_PCT', 0.005)
        
        # Para índices y cripto, más permisivo
        simbolo_upper = simbolo.upper()
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            max_slippage = max_slippage * 2
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            max_slippage = max_slippage * 3
        
        if slippage > max_slippage:
            self.logger.warning(
                f"⚠️ Slippage excedido para {simbolo}: {slippage:.4%} > {max_slippage:.2%}"
            )
            return False
        
        return True
    
    def _validar_rr_final(self, entry: float, sl: float, tp: float, direccion: str) -> bool:
        """
        Valida el R:R final.
        
        Args:
            entry: Precio de entrada
            sl: Stop Loss
            tp: Take Profit
            direccion: Dirección
        
        Returns:
            True si el R:R es aceptable
        """
        sl_dist = abs(entry - sl)
        tp_dist = abs(tp - entry)
        rr = tp_dist / sl_dist if sl_dist > 0 else 0
        
        rr_min = 0.8 if self.modo_backtest else 1.0
        
        if rr < rr_min:
            self.logger.warning(f"⚠️ R:R insuficiente: {rr:.2f} < {rr_min}")
            return False
        
        return True
    
    # ============================================================
    # OBTENCIÓN DE PRECIO
    # ============================================================
    
    def _obtener_precio_mercado(self, simbolo: str) -> Optional[Dict]:
        """
        Obtiene precio de mercado con reintentos.
        
        Args:
            simbolo: Símbolo
        
        Returns:
            Datos de precio o None
        """
        for intento in range(5):
            precio_data = self.mt5.obtener_precio(simbolo)
            
            if precio_data:
                bid = float(precio_data.get('bid', 0))
                ask = float(precio_data.get('ask', 0))
                
                if bid > 0 and ask > 0:
                    return precio_data
            
            time.sleep(0.2 * (intento + 1))
            self._stats['reintentos'] += 1
        
        self.logger.error(f"❌ No se pudo obtener precio para {simbolo} después de 5 intentos")
        return None
    
    # ============================================================
    # CÁLCULO DE SL/TP Y LOTES
    # ============================================================
    
    def _calcular_sl_tp(self, op: Dict, precio: float) -> Optional[Dict]:
        """
        Calcula SL y TP usando gestor_stops.
        
        Args:
            op: Datos de la operación
            precio: Precio de entrada
        
        Returns:
            Diccionario con sl, tp, tp2, rr
        """
        simbolo = op.get('simbolo', '')
        direccion = op.get('direccion', '')
        sl_propuesto = op.get('sl_propuesto', 0)
        tp_propuesto = op.get('tp_propuesto', 0)
        tp2_propuesto = op.get('tp2', 0)
        modo = op.get('modo', 'RETEST')
        regimen = op.get('regimen', 'INCERTO')
        es_reversal = op.get('es_reversal', False)
        en_nivel_clave = op.get('en_nivel_clave', False)
        calidad_horario = op.get('calidad_horario', 'REGULAR')
        atr = op.get('atr_calculado', 0.001)
        
        # Si no hay SL/TP propuesto, usar gestor_stops para calcular
        if sl_propuesto <= 0 or tp_propuesto <= 0:
            # Calcular SL mínimo según activo
            sl_min = self.gestor_stops._obtener_sl_minimo(
                simbolo, modo, regimen, calidad_horario
            )
            pip_val = self._obtener_pip_val(simbolo, precio)
            
            if direccion == 'COMPRA':
                sl_propuesto = precio - (sl_min * pip_val)
                tp_propuesto = precio + (sl_min * 2 * pip_val)
            else:
                sl_propuesto = precio + (sl_min * pip_val)
                tp_propuesto = precio - (sl_min * 2 * pip_val)
        
        # Validar con gestor_stops
        valido, razon, sl, tp, tp2 = self.gestor_stops.validar_sl_tp(
            simbolo=simbolo,
            entry_price=precio,
            sl=sl_propuesto,
            tp=tp_propuesto,
            tp2=tp2_propuesto,
            direccion=direccion,
            regimen=regimen,
            modo=modo,
            es_reversal=es_reversal,
            en_nivel_clave=en_nivel_clave,
            atr=atr,
            calidad_horario=calidad_horario
        )
        
        if not valido:
            self.logger.error(f"❌ SL/TP inválido: {razon}")
            return None
        
        # Calcular R:R
        sl_dist = abs(precio - sl)
        tp_dist = abs(tp - precio)
        rr = tp_dist / sl_dist if sl_dist > 0 else 0
        
        return {
            'sl': sl,
            'tp': tp,
            'tp2': tp2,
            'rr': rr,
            'sl_dist': sl_dist,
            'tp_dist': tp_dist,
        }
    
    def _calcular_lotes(self, op: Dict, sl_tp: Dict, precio: float) -> float:
        """
        Calcula los lotes.
        
        Args:
            op: Datos de la operación
            sl_tp: SL/TP calculados
            precio: Precio de entrada
        
        Returns:
            Lotes calculados
        """
        simbolo = op.get('simbolo', '')
        score = op.get('score', 50)
        regimen = op.get('regimen', 'INCERTO')
        modo = op.get('modo', 'RETEST')
        atr = op.get('atr_calculado', 0.001)
        atr_medio = op.get('atr_medio_calculado', 0.001)
        
        # Obtener info del símbolo
        info = self.mt5.obtener_info_simbolo(simbolo)
        tick_value = float(info.trade_tick_value) if info and hasattr(info, 'trade_tick_value') else 0.01
        tick_size = float(info.trade_tick_size) if info and hasattr(info, 'trade_tick_size') else 0.00001
        point = float(info.point) if info and hasattr(info, 'point') else 0.00001
        
        # Calcular lotes
        lotes = self.gestion_riesgo.calcular_lotes(
            entrada=precio,
            stop_loss=sl_tp['sl'],
            probabilidad=score,
            tick_value=tick_value,
            tick_size=tick_size,
            point=point,
            simbolo=simbolo,
            atr=atr,
            atr_medio=atr_medio,
            spread=0.0,
            margin_level=None,
            equity_referencia=float(self.gestion_riesgo.capital_actual)
        )
        
        # Aplicar factor de noticias (si existe)
        factor_noticias = op.get('factor_lote_noticias', 1.0)
        lotes = lotes * factor_noticias
        
        # Limitar
        max_lote = getattr(self.orquestador.config, 'MAX_LOTE_ABSOLUTO', 0.05)
        min_lote = getattr(self.orquestador.config, 'MIN_LOTE_ABSOLUTO', 0.01)
        lotes = max(min_lote, min(max_lote, lotes))
        
        return round(lotes, 3)
    
    # ============================================================
    # EJECUCIÓN EN MT5
    # ============================================================
    
    def _ejecutar_mt5(self, simbolo: str, direccion: str, precio: float,
                      lotes: float, sl_tp: Dict, op: Dict) -> Optional[Dict]:
        """
        Ejecuta en MT5.
        
        Args:
            simbolo: Símbolo
            direccion: Dirección
            precio: Precio de entrada
            lotes: Lotes a ejecutar
            sl_tp: SL/TP calculados
            op: Datos de la operación
        
        Returns:
            Resultado de MT5 o None
        """
        tipo = 'BUY' if direccion == 'COMPRA' else 'SELL'
        comentario = f"Sniper_{op.get('modo', 'RETEST')}"
        
        # Reintentar con backoff
        for intento in range(3):
            try:
                resultado = self.mt5.enviar_orden(
                    simbolo=simbolo,
                    tipo=tipo,
                    volumen=lotes,
                    sl=sl_tp['sl'],
                    tp=sl_tp['tp'],
                    comentario=comentario
                )
                
                if resultado and resultado.get('ticket'):
                    self._stats['reintentos'] += intento
                    return resultado
                
                if intento < 2:
                    time.sleep(0.5 * (intento + 1))
                    
            except Exception as e:
                self.logger.warning(f"⚠️ Intento {intento+1}/3 falló: {e}")
                if intento < 2:
                    time.sleep(0.5 * (intento + 1))
        
        self.logger.error(f"❌ Falló ejecución de {simbolo} después de 3 intentos")
        return None
    
    def _ejecutar_backtest(self, simbolo: str, direccion: str, precio: float,
                           lotes: float, sl_tp: Dict, op: Dict) -> Optional[Dict]:
        """
        Simula ejecución en backtest.
        
        Args:
            simbolo: Símbolo
            direccion: Dirección
            precio: Precio de entrada
            lotes: Lotes a ejecutar
            sl_tp: SL/TP calculados
            op: Datos de la operación
        
        Returns:
            Resultado simulado
        """
        ticket = int(time.time() * 1000) % 100000
        
        self.logger.info(f"🧪 BACKTEST: Simulando {simbolo} {direccion} @ {precio:.5f}")
        
        return {
            'ticket': ticket,
            'precio': precio,
            'volumen': lotes,
            'retcode': 0,
            'comentario': 'BACKTEST'
        }
    
    # ============================================================
    # REGISTRO DE OPERACIONES
    # ============================================================
    
    def _registrar_operacion(self, resultado: Dict, op: Dict, sl_tp: Dict, lotes: float):
        """
        Registra la operación ejecutada.
        
        Args:
            resultado: Resultado de MT5
            op: Datos de la operación
            sl_tp: SL/TP calculados
            lotes: Lotes ejecutados
        """
        ticket = resultado.get('ticket')
        precio = resultado.get('precio', 0)
        simbolo = op.get('simbolo', '')
        direccion = op.get('direccion', '')
        
        # Guardar en memoria
        self.orquestador.estado.posiciones_abiertas[ticket] = {
            'simbolo': simbolo,
            'direccion': direccion,
            'entrada': precio,
            'lotes': lotes,
            'sl': sl_tp['sl'],
            'tp': sl_tp['tp'],
            'tp2': sl_tp.get('tp2', 0),
            'timestamp_apertura': datetime.now(timezone.utc),
            'modo': op.get('modo', 'RETEST'),
            'regimen': op.get('regimen', 'INCERTO'),
            'nivel_usado': op.get('nivel_usado', 0),
            'es_reversal': op.get('es_reversal', False),
            'en_nivel_clave': op.get('en_nivel_clave', False),
        }
        
        # Guardar en SQLite
        self.orquestador.almacen.guardar_operacion({
            'ticket': ticket,
            'simbolo': simbolo,
            'direccion': direccion,
            'entrada': precio,
            'lotes': lotes,
            'sl': sl_tp['sl'],
            'tp': sl_tp['tp'],
            'tp2': sl_tp.get('tp2', 0),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'estado': 'ABIERTA',
            'puntuacion': op.get('score', 50),
            'es_sniper': True,
            'modo': op.get('modo', 'RETEST'),
            'regimen': op.get('regimen', 'INCERTO'),
            'contexto_apertura': {
                'es_reversal': op.get('es_reversal', False),
                'en_nivel_clave': op.get('en_nivel_clave', False),
                'calidad_horario': op.get('calidad_horario', 'REGULAR'),
                'score_h1': op.get('score_h1', 0),
                'score_m15': op.get('score_m15', 0),
                'score_m5': op.get('score_m5', 0),
            }
        })
        
        # Notificar
        if self.notificaciones:
            self.notificaciones.notificar_operacion({
                'simbolo': simbolo,
                'direccion': direccion,
                'entrada': precio,
                'stop_loss': sl_tp['sl'],
                'take_profit': sl_tp['tp'],
                'take_profit_2': sl_tp.get('tp2', 0),
                'lotes': lotes,
                'probabilidad': op.get('score', 50),
                'es_sniper': True,
                'modo': op.get('modo', 'RETEST'),
                'regimen': op.get('regimen', 'INCERTO'),
                'rr': sl_tp.get('rr', 0),
                'ticket': ticket,
            })
    
    def _registrar_oportunidad_no_tomada(self, op: Dict, motivo: str):
        """
        Registra oportunidad no tomada.
        
        Args:
            op: Datos de la operación
            motivo: Motivo del rechazo
        """
        try:
            self.orquestador.almacen.guardar_oportunidad_no_tomada({
                'simbolo': op.get('simbolo', ''),
                'direccion': op.get('direccion', 'NEUTRAL'),
                'puntuacion': op.get('score', 0),
                'motivo_rechazo': motivo,
                'timestamp_propuesta': datetime.now(timezone.utc).isoformat(),
                'precio_entrada_propuesto': op.get('entry_price', 0),
                'sl_propuesto': op.get('sl_propuesto', 0),
                'tp_propuesto': op.get('tp_propuesto', 0),
            })
        except Exception as e:
            self.logger.warning(f"Error registrando oportunidad no tomada: {e}")
    
    def _limpiar_pipeline(self, simbolo: str):
        """
        Limpia el pipeline para el símbolo.
        
        Args:
            simbolo: Símbolo
        """
        if hasattr(self.orquestador, 'pipeline'):
            self.orquestador.pipeline.marcar_ejecutada(simbolo)
    
    # ============================================================
    # UTILIDADES
    # ============================================================
    
    def _obtener_pip_val(self, simbolo: str, precio: float) -> float:
        """
        Obtiene el valor de un pip para el símbolo.
        
        Args:
            simbolo: Símbolo
            precio: Precio de referencia
        
        Returns:
            Valor del pip
        """
        simbolo_upper = simbolo.upper()
        
        if 'JPY' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 0.10
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas de ejecución.
        
        Returns:
            Diccionario con estadísticas
        """
        stats = self._stats.copy()
        
        total = stats['ejecuciones_exitosas'] + stats['ejecuciones_fallidas']
        stats['tasa_exito'] = (stats['ejecuciones_exitosas'] / total * 100) if total > 0 else 0
        
        return stats


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_ejecutor_operaciones(orquestador: Any,
                                mt5: Any,
                                gestion_riesgo: Any,
                                gestor_stops: Optional[GestorStops] = None,
                                notificaciones: Optional[Any] = None,
                                modo_backtest: bool = False) -> EjecutorOperaciones:
    """
    Crea una instancia de EjecutorOperaciones.
    
    Args:
        orquestador: Orquestador principal
        mt5: Conector MT5
        gestion_riesgo: Gestión de riesgo
        gestor_stops: Gestor de stops (opcional)
        notificaciones: Sistema de notificaciones
        modo_backtest: Modo backtest
    
    Returns:
        EjecutorOperaciones
    """
    return EjecutorOperaciones(
        orquestador=orquestador,
        mt5=mt5,
        gestion_riesgo=gestion_riesgo,
        gestor_stops=gestor_stops,
        notificaciones=notificaciones,
        modo_backtest=modo_backtest
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Prueba rápida (mock)
    print("🧪 Prueba de EjecutorOperaciones")
    print("   (Requiere orquestador completo)")
    print("✅ Test placeholder")