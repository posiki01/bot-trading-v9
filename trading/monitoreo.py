#!/usr/bin/env python3
"""
trading/monitoreo.py (V9.3 - REFACTORIZADO Y CORREGIDO)
Monitoreo de posiciones abiertas y gestión de stops.

V9.3 - CORRECCIONES CRÍTICAS:
- ✅ Corregido bug de dirección (BUY/SELL → COMPRA/VENTA)
- ✅ Precio en tiempo real desde MT5 (no de caché)
- ✅ Simulación de monitoreo en backtest
- ✅ Contadores de fallos de análisis con alertas
- ✅ Logs más informativos y detallados
- ✅ Verificación de frescura de datos antes de usar análisis
- ✅ Gestión de posiciones manuales con flag configurable
"""

import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

from trading.trailing import TrailingEngine
from trading.decision_cierre import DecisorCierre

logger = logging.getLogger('BotTrading.Monitoreo')


class MonitorPosiciones:
    """
    Monitorea posiciones abiertas y gestiona stops.
    V9.3 - REFACTORIZADO Y CORREGIDO.
    """
    
    def __init__(self,
                 orquestador: Any,
                 mt5: Any,
                 gestion_riesgo: Any,
                 trailing_engine: Optional[TrailingEngine] = None,
                 decisor_cierre: Optional[DecisorCierre] = None,
                 monitorear_manuales: bool = False):
        """
        Inicializa el monitor de posiciones.
        
        Args:
            orquestador: Orquestador principal
            mt5: Conector MT5
            gestion_riesgo: Gestión de riesgo
            trailing_engine: Motor de trailing (opcional)
            decisor_cierre: Decisor de cierre (opcional)
            monitorear_manuales: Si True, monitorea también posiciones manuales
        """
        self.orquestador = orquestador
        self.mt5 = mt5
        self.gestion_riesgo = gestion_riesgo
        self.monitorear_manuales = monitorear_manuales
        self.logger = logging.getLogger('BotTrading.Monitoreo')
        
        # Inyección de dependencia
        self.trailing_engine = trailing_engine or TrailingEngine(
            config=getattr(orquestador, 'config', None),
            modo_backtest=getattr(orquestador, 'modo_backtest', False)
        )
        
        self.decisor_cierre = decisor_cierre or DecisorCierre(
            analisis_capas=getattr(orquestador, 'analisis_capas', None)
        )
        
        # Estadísticas
        self._stats = {
            'total_procesadas': 0,
            'cerradas': 0,
            'sl_movidos': 0,
            'cierres_parciales': 0,
            'timeouts': 0,
            'cierres_por_decision': 0,
            'fallos_analisis': 0,
            'ultima_posicion_procesada': None,
        }
        
        # ✅ Contadores de fallos de análisis
        self._fallos_analisis_rapido = 0
        self._fallos_analisis_medio = 0
        self._max_fallos_antes_alerta = 10
        
        self.logger.info("🔍 MonitorPosiciones V9.3 REFACTORIZADO inicializado")
        self.logger.info(f"   Monitorear manuales: {monitorear_manuales}")
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def ejecutar_ciclo(self):
        """Ejecuta un ciclo de monitoreo."""
        posiciones = self._obtener_posiciones()
        
        if not posiciones:
            self.logger.debug("📭 No hay posiciones para monitorear")
            return
        
        self.logger.info(f"🔍 Monitoreando {len(posiciones)} posiciones...")
        
        for pos in posiciones:
            try:
                self._procesar_posicion(pos)
            except Exception as e:
                self.logger.error(f"❌ Error procesando posición {pos.get('ticket', 'N/A')}: {e}", exc_info=True)
    
    def procesar(self, pos: Dict):
        """Procesa una posición individual."""
        self._procesar_posicion(pos)
    
    # ============================================================
    # OBTENER POSICIONES (CON SOPORTE PARA BACKTEST)
    # ============================================================
    
    def _obtener_posiciones(self) -> List[Dict]:
        """
        Obtiene posiciones para monitorear.
        V9.3 - CORREGIDO: Soporte para backtest.
        
        Returns:
            Lista de posiciones
        """
        # ✅ CORRECCIÓN: Si está en backtest, usar posiciones simuladas
        if self.orquestador.modo_backtest:
            # Convertir el estado de posiciones abiertas a formato de posición
            posiciones = []
            for ticket, meta in self.orquestador.estado.posiciones_abiertas.items():
                pos = {
                    'ticket': ticket,
                    'simbolo': meta.get('simbolo', ''),
                    'tipo': 'BUY' if meta.get('direccion', 'COMPRA') == 'COMPRA' else 'SELL',
                    'precio_apertura': meta.get('entrada', 0),
                    'precio_actual': self._obtener_precio_simulado(meta.get('simbolo', '')),
                    'sl': meta.get('sl', 0),
                    'tp': meta.get('tp', 0),
                    'volumen': meta.get('lotes', 0),
                    'magic': self.orquestador.config.MAGIC_NUMBER,
                    'time': int(datetime.now(timezone.utc).timestamp()),
                }
                posiciones.append(pos)
            return posiciones
        
        # Obtener posiciones reales de MT5
        posiciones = self.mt5.obtener_posiciones()
        return posiciones or []
    
    def _obtener_precio_simulado(self, simbolo: str) -> float:
        """Obtiene precio simulado para backtest."""
        # Usar el último precio conocido del caché
        df = self.orquestador.cache.get_datos(
            simbolo=simbolo,
            timeframe=5,
            n_velas=10,
            fetch_func=self.mt5.obtener_datos
        )
        if df is not None and len(df) > 0:
            return float(df['Close'].iloc[-1])
        return 1.0
    
    # ============================================================
    # PROCESAMIENTO DE POSICIÓN (CORREGIDO V9.3)
    # ============================================================
    
    def _procesar_posicion(self, pos: Dict):
        """
        Procesa una posición individual con correcciones V9.56.
        V9.56 - CORREGIDO DEFINITIVO:
        - Valida SL/TP según dirección real (COMPRA/VENTA)
        - Monitoreo de R:R dinámico
        - Trailing SL automático para asegurar ganancia
        """
        self._stats['total_procesadas'] += 1
        
        ticket = pos['ticket']
        simbolo = pos['simbolo']
        
        self.logger.info(f"🔍 MONITOR: Procesando {simbolo} (Ticket: {ticket})")
        
        # Verificar si es manual
        meta = self.orquestador.estado.posiciones_abiertas.get(ticket, {})
        
        if meta.get('es_manual', False) and not self.monitorear_manuales:
            self.logger.debug(f"⏭️ Posición {ticket} manual, ignorando")
            return
        
        # ============================================================
        # 1. OBTENER PRECIO ACTUALIZADO EN TIEMPO REAL
        # ============================================================
        precio_actual = self._obtener_precio_actualizado(simbolo, pos)
        
        if precio_actual is None:
            self.logger.warning(f"⚠️ {simbolo}: No se pudo obtener precio actualizado, usando caché")
            precio_actual = pos.get('precio_actual', 0)
        
        if precio_actual <= 0:
            self.logger.error(f"❌ {simbolo}: Precio inválido para monitoreo ({precio_actual})")
            return
        
        # ============================================================
        # 2. DETERMINAR DIRECCIÓN CORRECTAMENTE
        # ============================================================
        direccion_correcta = self._determinar_direccion(pos, meta)
        
        entry_price = pos.get('precio_apertura', meta.get('entrada', 0))
        
        # ============================================================
        # 3. CALCULAR GANANCIA EN PIPS
        # ============================================================
        pip_val = self._obtener_pip_val(simbolo)
        if pip_val <= 0:
            pip_val = 0.0001
        
        if direccion_correcta == 'COMPRA':
            ganancia_pips = (precio_actual - entry_price) / pip_val
        else:
            ganancia_pips = (entry_price - precio_actual) / pip_val
        
        self.logger.info(f"📊 {simbolo}: Dir={direccion_correcta} | Entry={entry_price:.5f} | Actual={precio_actual:.5f} | Pips={ganancia_pips:.1f}")
        
        # ============================================================
        # 4. ✅ CORREGIDO V9.56: VALIDAR SL/TP SEGÚN DIRECCIÓN
        # ============================================================
        sl_actual = pos.get('sl', 0)
        tp_actual = pos.get('tp', 0)
        
        if direccion_correcta == 'COMPRA':
            # COMPRA: SL DEBE estar DEBAJO del precio, TP ARRIBA
            if sl_actual > 0 and sl_actual >= precio_actual:
                self.logger.error(f"❌ {simbolo}: SL INVERTIDO para COMPRA (SL={sl_actual:.5f} >= precio={precio_actual:.5f})")
                self.logger.error(f"   💡 Cerrando operación por SL invertido")
                self._cerrar_posicion(ticket, "SL invertido para COMPRA")
                return
            if tp_actual > 0 and tp_actual <= precio_actual:
                self.logger.warning(f"⚠️ {simbolo}: TP ya alcanzado para COMPRA (TP={tp_actual:.5f} <= precio={precio_actual:.5f})")
                # Si el precio ya superó el TP, es posible que el TP se haya ejecutado
                # Pero si no se ha cerrado, cerrar manualmente
                self._cerrar_posicion(ticket, "TP alcanzado (precio > TP)")
                return
        else:  # VENTA
            # VENTA: SL DEBE estar ARRIBA del precio, TP DEBAJO
            if sl_actual > 0 and sl_actual <= precio_actual:
                self.logger.error(f"❌ {simbolo}: SL INVERTIDO para VENTA (SL={sl_actual:.5f} <= precio={precio_actual:.5f})")
                self.logger.error(f"   💡 Cerrando operación por SL invertido")
                self._cerrar_posicion(ticket, "SL invertido para VENTA")
                return
            if tp_actual > 0 and tp_actual >= precio_actual:
                self.logger.warning(f"⚠️ {simbolo}: TP ya alcanzado para VENTA (TP={tp_actual:.5f} >= precio={precio_actual:.5f})")
                self._cerrar_posicion(ticket, "TP alcanzado (precio < TP)")
                return
        
        # ============================================================
        # 5. VERIFICAR SL/TP ALCANZADOS (usando precio real)
        # ============================================================
        if self._verificar_sl_tp(pos, ticket, ganancia_pips, precio_actual):
            return
        
        # ============================================================
        # 6. VERIFICAR CIERRE PARCIAL
        # ============================================================
        debe_cerrar_parcial, volumen_parcial = self.trailing_engine.verificar_cierre_parcial(
            pos=pos,
            ganancia_pips=ganancia_pips,
            modo=meta.get('modo', 'RETEST')
        )
        
        if debe_cerrar_parcial and volumen_parcial > 0:
            self.logger.info(f"🔄 {simbolo}: Cierre parcial de {volumen_parcial} lotes (ganancia: {ganancia_pips:.1f} pips)")
            if self._cerrar_parcial(ticket, volumen_parcial):
                self._stats['cierres_parciales'] += 1
                if ticket in self.orquestador.estado.posiciones_abiertas:
                    self.orquestador.estado.posiciones_abiertas[ticket]['lotes'] -= volumen_parcial
        
        # ============================================================
        # 7. VERIFICAR TIMEOUT
        # ============================================================
        debe_cerrar_timeout, razon_timeout = self.trailing_engine.verificar_timeout(
            pos=pos,
            fecha=datetime.now(timezone.utc),
            ganancia_pips=ganancia_pips,
            modo=meta.get('modo', 'RETEST')
        )
        
        if debe_cerrar_timeout:
            self.logger.info(f"⏰ {simbolo}: Cierre por timeout - {razon_timeout}")
            self._cerrar_posicion(ticket, razon_timeout)
            self._stats['timeouts'] += 1
            return
        
        # ============================================================
        # 8. OBTENER RÉGIMEN CORRECTO
        # ============================================================
        regimen = self._obtener_regimen_correcto(simbolo, meta, direccion_correcta)
        
        # ============================================================
        # 9. REANALIZAR MERCADO EN TIEMPO REAL
        # ============================================================
        analisis_rapido, analisis_medio = self._reanalizar_mercado(simbolo, precio_actual)
        
        # ============================================================
        # 10. DECIDIR SI CERRAR CON GANANCIA
        # ============================================================
        if self.decisor_cierre and analisis_medio is not None:
            decision_cierre = self.decisor_cierre.decidir_si_cerrar(
                simbolo=simbolo,
                direccion=direccion_correcta,
                ganancia_pips=ganancia_pips,
                precio_actual=precio_actual,
                entry_price=entry_price,
                sl=sl_actual,
                tp=tp_actual,
                analisis_rapido=analisis_rapido,
                analisis_medio=analisis_medio,
                modo=meta.get('modo', 'RETEST'),
                regimen=regimen
            )
            
            if decision_cierre:
                self.logger.info(f"🎯 {simbolo}: Cierre por decisión - {decision_cierre}")
                self._cerrar_posicion(ticket, decision_cierre)
                self._stats['cierres_por_decision'] += 1
                return
        
        # ============================================================
        # 11. ✅ NUEVO V9.56: VALIDAR R:R DINÁMICO Y AJUSTAR TP
        # ============================================================
        
        # Calcular R:R original
        rr_original = 0
        if sl_actual > 0 and entry_price > 0:
            sl_dist = abs(entry_price - sl_actual)
            tp_dist = abs(tp_actual - entry_price)
            rr_original = tp_dist / sl_dist if sl_dist > 0 else 0
        
        # Calcular R:R actual (si se cerrara ahora)
        rr_actual = 0
        if sl_actual > 0 and entry_price > 0:
            sl_dist = abs(entry_price - sl_actual)
            ganancia_actual = abs(precio_actual - entry_price) if (direccion_correcta == 'COMPRA' and precio_actual > entry_price) or (direccion_correcta == 'VENTA' and precio_actual < entry_price) else 0
            rr_actual = ganancia_actual / sl_dist if sl_dist > 0 else 0
        
        # Si el R:R ha mejorado significativamente, ajustar TP
        if rr_actual > rr_original * 1.2 and analisis_medio is not None:
            nuevo_tp = self._calcular_tp_dinamico(pos, precio_actual, analisis_medio)
            if nuevo_tp > 0 and nuevo_tp != tp_actual:
                self.logger.info(f"🔄 {simbolo}: TP ajustado dinámicamente de {tp_actual:.5f} a {nuevo_tp:.5f}")
                if self._mover_tp(ticket, nuevo_tp):
                    pos['tp'] = nuevo_tp
                    if ticket in self.orquestador.estado.posiciones_abiertas:
                        self.orquestador.estado.posiciones_abiertas[ticket]['tp'] = nuevo_tp
        
        # ============================================================
        # 12. ✅ NUEVO V9.56: TRAILING SL PARA ASEGURAR GANANCIA
        # ============================================================
        
        # Obtener configuración del modo
        from config.umbrales import Umbrales
        sniper_config = getattr(Umbrales, 'SNIPER_CONFIG', {})
        modo = meta.get('modo', 'RETEST')
        cfg_modo = sniper_config.get(modo, {})
        
        # Obtener umbrales de trailing
        breakeven_umbral = cfg_modo.get('breakeven_umbral', 20)
        trailing_umbral = cfg_modo.get('trailing_umbral', 40)
        trailing_distancia = cfg_modo.get('trailing_distancia', 15)
        
        # Ajustar por régimen
        multiplicador_regimen = {
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
        multiplicador = multiplicador_regimen.get(regimen, 1.0)
        
        breakeven_umbral = int(breakeven_umbral * multiplicador)
        trailing_umbral = int(trailing_umbral * multiplicador)
        trailing_distancia = int(trailing_distancia * multiplicador)
        
        # ============================================================
        # FASE 1: BREAKEVEN (mover SL a entrada + 2 pips)
        # ============================================================
        if ganancia_pips >= breakeven_umbral and sl_actual < entry_price:
            nuevo_sl = entry_price + (2 * pip_val) if direccion_correcta == 'COMPRA' else entry_price - (2 * pip_val)
            
            self.logger.info(f"🛡️ {simbolo}: BREAKEVEN - Moviendo SL de {sl_actual:.5f} a {nuevo_sl:.5f} (ganancia: {ganancia_pips:.1f} pips)")
            
            if self._mover_sl(ticket, nuevo_sl):
                sl_actual = nuevo_sl
                if ticket in self.orquestador.estado.posiciones_abiertas:
                    self.orquestador.estado.posiciones_abiertas[ticket]['sl'] = nuevo_sl
        
        # ============================================================
        # FASE 2: TRAILING SUAVE (mover SL detrás del precio)
        # ============================================================
        elif ganancia_pips >= trailing_umbral:
            if direccion_correcta == 'COMPRA':
                nuevo_sl = precio_actual - (trailing_distancia * pip_val)
            else:
                nuevo_sl = precio_actual + (trailing_distancia * pip_val)
            
            # Solo mover si mejora el SL actual
            if (direccion_correcta == 'COMPRA' and nuevo_sl > sl_actual) or \
            (direccion_correcta == 'VENTA' and nuevo_sl < sl_actual):
                
                self.logger.info(f"🔄 {simbolo}: TRAILING - Moviendo SL de {sl_actual:.5f} a {nuevo_sl:.5f} (ganancia: {ganancia_pips:.1f} pips)")
                
                if self._mover_sl(ticket, nuevo_sl):
                    sl_actual = nuevo_sl
                    if ticket in self.orquestador.estado.posiciones_abiertas:
                        self.orquestador.estado.posiciones_abiertas[ticket]['sl'] = nuevo_sl
        
        # ============================================================
        # FASE 3: TRAILING AGRESIVO (mover SL más cerca)
        # ============================================================
        elif ganancia_pips >= trailing_umbral * 2:
            trailing_agresivo_distancia = int(trailing_distancia * 0.7)
            
            if direccion_correcta == 'COMPRA':
                nuevo_sl = precio_actual - (trailing_agresivo_distancia * pip_val)
            else:
                nuevo_sl = precio_actual + (trailing_agresivo_distancia * pip_val)
            
            if (direccion_correcta == 'COMPRA' and nuevo_sl > sl_actual) or \
            (direccion_correcta == 'VENTA' and nuevo_sl < sl_actual):
                
                self.logger.info(f"🔥 {simbolo}: TRAILING AGRESIVO - Moviendo SL de {sl_actual:.5f} a {nuevo_sl:.5f} (ganancia: {ganancia_pips:.1f} pips)")
                
                if self._mover_sl(ticket, nuevo_sl):
                    sl_actual = nuevo_sl
                    if ticket in self.orquestador.estado.posiciones_abiertas:
                        self.orquestador.estado.posiciones_abiertas[ticket]['sl'] = nuevo_sl
        
        # ============================================================
        # 13. CALCULAR MOVIMIENTO DE SL (USANDO TRAILING ENGINE)
        # ============================================================
        df_h1 = self._obtener_datos_h1(simbolo)
        
        decision = self.trailing_engine.calcular_movimiento_sl(
            pos=pos,
            df_h1=df_h1,
            precio_actual=precio_actual,
            fecha=datetime.now(timezone.utc),
            regimen=regimen,
            modo=meta.get('modo', 'RETEST')
        )
        
        # ============================================================
        # 14. APLICAR DECISIÓN DE TRAILING
        # ============================================================
        if decision.cerrar:
            self._cerrar_posicion(ticket, decision.motivo_cierre or decision.razon)
            self._stats['cerradas'] += 1
        elif decision.mover_sl and decision.nuevo_sl is not None:
            if self._mover_sl(ticket, decision.nuevo_sl):
                self._stats['sl_movidos'] += 1
        
        # Actualizar timestamp de última posición procesada
        self._stats['ultima_posicion_procesada'] = datetime.now(timezone.utc).isoformat()
    # ============================================================
    # ✅ CORRECCIÓN V9.3: Obtener precio actualizado
    # ============================================================

    def _obtener_regimen_correcto(self, simbolo: str, meta: Dict, direccion: str) -> str:
        """
        Obtiene el régimen correcto para la operación.
        V9.4 - CORREGIDO: Busca en meta, pipeline, y usa fallback seguro.
        """
        # 1. Intentar desde meta (memoria)
        regimen = meta.get('regimen', 'INCERTO')
        
        if regimen != 'INCERTO':
            return regimen
        
        # 2. Intentar desde el pipeline
        if self.orquestador.pipeline:
            estado = self.orquestador.pipeline.obtener_estado(simbolo)
            if estado and estado.contexto_h1:
                contexto = estado.contexto_h1
                regimen = contexto.get('regimen', 'INCERTO')
                if regimen != 'INCERTO':
                    return regimen
        
        # 3. Fallback: usar régimen según dirección
        if direccion == 'COMPRA':
            return 'TREND_ALCISTA_FUERTE'
        elif direccion == 'VENTA':
            return 'TREND_BAJISTA_FUERTE'
        
        return 'INCERTO'

    def _calcular_tp_dinamico(self, pos: Dict, precio_actual: float) -> float:
        """
        Calcula TP dinámico basado en estructura.
        V9.47 - NUEVO: Ajusta TP cuando el precio se mueve a favor.
        """
        simbolo = pos.get('simbolo', '')
        direccion = pos.get('direccion', 'COMPRA')
        entry = pos.get('entrada', 0)
        sl = pos.get('sl', 0)
        tp_original = pos.get('tp', 0)
        
        if entry <= 0 or sl <= 0:
            return tp_original
        
        sl_dist = abs(entry - sl)
        
        # Buscar siguiente nivel de estructura
        # Usar el análisis medio para obtener niveles
        analisis_medio = self._analizar_medio(simbolo, precio_actual)
        
        if analisis_medio is None:
            return tp_original
        
        # Buscar siguiente resistencia/soporte
        if direccion == 'COMPRA':
            siguiente_resistencia = getattr(analisis_medio, 'resistencia_cercana', 0)
            if siguiente_resistencia and siguiente_resistencia > precio_actual:
                # TP en la siguiente resistencia
                return siguiente_resistencia
        else:
            siguiente_soporte = getattr(analisis_medio, 'soporte_cercano', 0)
            if siguiente_soporte and siguiente_soporte < precio_actual:
                # TP en el siguiente soporte
                return siguiente_soporte
        
        return tp_original

    def _calcular_rr_actual(self, pos: Dict, precio_actual: float) -> float:
        """Calcula R:R actual."""
        entry = pos.get('entrada', 0)
        sl = pos.get('sl', 0)
        tp = pos.get('tp', 0)
        
        if entry <= 0 or sl <= 0 or tp <= 0:
            return 0
        
        sl_dist = abs(entry - sl)
        tp_dist = abs(tp - entry)
        
        return tp_dist / sl_dist if sl_dist > 0 else 0

    def _calcular_rr_original(self, pos: Dict) -> float:
        """Calcula R:R original."""
        return self._calcular_rr_actual(pos, pos.get('entrada', 0))

    def _calcular_rr_actual_minimo(self, pos: Dict, precio_actual: float) -> float:
        """Calcula R:R actual mínimo (si se cierra ahora)."""
        entry = pos.get('entrada', 0)
        sl = pos.get('sl', 0)
        
        if entry <= 0 or sl <= 0:
            return 0
        
        sl_dist = abs(entry - sl)
        ganancia_actual = abs(precio_actual - entry) if (pos.get('direccion') == 'COMPRA' and precio_actual > entry) or (pos.get('direccion') == 'VENTA' and precio_actual < entry) else 0
        
        return ganancia_actual / sl_dist if sl_dist > 0 else 0

    def _mover_tp(self, ticket: int, nuevo_tp: float) -> bool:
        """Mueve el TP de una posición."""
        if self.orquestador.modo_backtest:
            return True
        
        try:
            return self.mt5.modificar_tp(ticket, nuevo_tp)
        except Exception as e:
            self.logger.error(f"❌ Error moviendo TP para {ticket}: {e}")
            return False
    
    def _obtener_precio_actualizado(self, simbolo: str, pos: Dict) -> Optional[float]:
        """
        Obtiene precio actualizado en tiempo real para el símbolo.
        V9.3 - CORREGIDO: Usa MT5 directamente, no caché.
        
        Args:
            simbolo: Símbolo
            pos: Datos de posición (para dirección)
        
        Returns:
            Precio actual o None
        """
        # ✅ En backtest, usar precio del caché
        if self.orquestador.modo_backtest:
            return self._obtener_precio_simulado(simbolo)
        
        # ✅ Obtener tick en tiempo real
        try:
            tick = self.mt5.obtener_precio(simbolo)
            if tick:
                bid = float(tick.get('bid', 0))
                ask = float(tick.get('ask', 0))
                
                # Usar el precio correcto según la dirección
                if pos.get('tipo') == 'BUY':
                    return ask if ask > 0 else bid
                else:
                    return bid if bid > 0 else ask
                    
        except Exception as e:
            self.logger.warning(f"⚠️ Error obteniendo precio para {simbolo}: {e}")
        
        # Fallback: usar precio actual de la posición (puede estar desactualizado)
        return pos.get('precio_actual', 0)
    
    # ============================================================
    # ✅ CORRECCIÓN V9.3: Determinar dirección correctamente
    # ============================================================
    
    def _determinar_direccion(self, pos: Dict, meta: Dict) -> str:
        """
        Determina la dirección de la posición de forma unificada.
        V9.3 - CORREGIDO: Maneja BUY/SELL y COMPRA/VENTA.
        
        Args:
            pos: Datos de posición de MT5
            meta: Metadata de la posición en memoria
        
        Returns:
            'COMPRA' o 'VENTA'
        """
        # 1. Intentar desde meta (memoria)
        if meta.get('direccion'):
            direccion = meta['direccion']
            if direccion in ['COMPRA', 'VENTA']:
                return direccion
        
        # 2. Intentar desde pos (MT5)
        tipo = pos.get('tipo')
        if tipo == 'BUY' or tipo == 0:
            return 'COMPRA'
        if tipo == 'SELL' or tipo == 1:
            return 'VENTA'
        
        # 3. Intentar desde direccion en pos
        if pos.get('direccion'):
            direccion = pos['direccion']
            if direccion in ['COMPRA', 'VENTA']:
                return direccion
            if direccion == 'BUY':
                return 'COMPRA'
            if direccion == 'SELL':
                return 'VENTA'
        
        # Fallback
        self.logger.warning(f"⚠️ No se pudo determinar dirección para posición {pos.get('ticket', 'N/A')}")
        return 'COMPRA'  # Default seguro
    
    # ============================================================
    # ✅ CORRECCIÓN V9.3: Obtener pip_val dinámicamente
    # ============================================================
    
    def _obtener_pip_val(self, simbolo: str) -> float:
        """Obtiene pip_val dinámicamente para el símbolo."""
        # Intentar desde MT5
        if self.mt5 and hasattr(self.mt5, '_pip_size_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None:
                    return float(self.mt5._pip_size_simbolo(simbolo, info))
            except Exception:
                pass
        
        # Fallback estático
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.01
        if 'XAG' in simbolo_upper:
            return 0.1
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001
    
    # ============================================================
    # ✅ CORRECCIÓN V9.3: Reanálisis de mercado con contadores
    # ============================================================
    
    def _reanalizar_mercado(self, simbolo: str, precio_actual: float) -> tuple:
        """
        Reanaliza el mercado en tiempo real con contadores de fallos.
        V9.3 - CORREGIDO: Añade contadores de fallos y alertas.
        
        Args:
            simbolo: Símbolo
            precio_actual: Precio actual
        
        Returns:
            (analisis_rapido, analisis_medio) - Pueden ser None
        """
        # Análisis rápido M5
        analisis_rapido = self._analizar_rapido_con_fallos(simbolo, precio_actual)
        
        # Análisis medio H1
        analisis_medio = self._analizar_medio_con_fallos(simbolo, precio_actual)
        
        return analisis_rapido, analisis_medio
    
    def _analizar_rapido_con_fallos(self, simbolo: str, precio_actual: float) -> Optional[Any]:
        """
        Ejecuta análisis rápido con contador de fallos.
        V9.3 - CORREGIDO.
        """
        try:
            df_m5 = self.orquestador.cache.get_datos(
                simbolo=simbolo,
                timeframe=5,
                n_velas=100,
                fetch_func=self.mt5.obtener_datos
            )
            
            if df_m5 is not None and len(df_m5) > 20:
                resultado = self.orquestador.analisis_capas.analisis_rapido(df_m5, simbolo, precio_actual)
                self._fallos_analisis_rapido = 0
                return resultado
            else:
                self._fallos_analisis_rapido += 1
                self._verificar_alertas_fallos(simbolo, 'rápido')
                
        except Exception as e:
            self._fallos_analisis_rapido += 1
            self._verificar_alertas_fallos(simbolo, 'rápido', e)
        
        return None
    
    def _analizar_medio_con_fallos(self, simbolo: str, precio_actual: float) -> Optional[Any]:
        """
        Ejecuta análisis medio con contador de fallos.
        V9.3 - CORREGIDO: Verifica frescura de datos.
        """
        try:
            df_h1 = self.orquestador.cache.get_datos(
                simbolo=simbolo,
                timeframe=60,
                n_velas=100,
                fetch_func=self.mt5.obtener_datos
            )
            
            if df_h1 is not None and len(df_h1) > 50:
                # ✅ CORRECCIÓN: Verificar frescura de datos
                ultima_fecha = df_h1.index[-1]
                if hasattr(ultima_fecha, 'tzinfo') and ultima_fecha.tzinfo is None:
                    ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
                
                antiguedad_horas = (datetime.now(timezone.utc) - ultima_fecha).total_seconds() / 3600
                
                if antiguedad_horas > 2.0:
                    self.logger.debug(f"⚠️ {simbolo}: Datos H1 desactualizados ({antiguedad_horas:.1f}h)")
                    self._fallos_analisis_medio += 1
                    self._verificar_alertas_fallos(simbolo, 'medio')
                    return None
                
                resultado = self.orquestador.analisis_capas.analisis_medio(df_h1, simbolo)
                self._fallos_analisis_medio = 0
                return resultado
            else:
                self._fallos_analisis_medio += 1
                self._verificar_alertas_fallos(simbolo, 'medio')
                
        except Exception as e:
            self._fallos_analisis_medio += 1
            self._verificar_alertas_fallos(simbolo, 'medio', e)
        
        return None
    
    def _verificar_alertas_fallos(self, simbolo: str, tipo: str, error: Optional[Exception] = None):
        """
        Verifica si se debe notificar al operador por fallos de análisis.
        V9.3 - CORREGIDO.
        """
        fallos = 0
        if tipo == 'rápido':
            fallos = self._fallos_analisis_rapido
        else:
            fallos = self._fallos_analisis_medio
        
        if fallos == self._max_fallos_antes_alerta:
            mensaje = f"Análisis {tipo} falló {fallos} veces para {simbolo}"
            if error:
                mensaje += f" - Último error: {error}"
            
            self.logger.warning(f"⚠️ {mensaje}")
            
            if self.orquestador.notificaciones:
                self.orquestador.notificaciones.enviar(
                    "⚠️ MONITOREO FALLANDO",
                    mensaje,
                    tipo='alerta'
                )
        elif fallos > self._max_fallos_antes_alerta and fallos % 10 == 0:
            self.logger.warning(f"⚠️ Análisis {tipo} para {simbolo} con {fallos} fallos acumulados")
    
    # ============================================================
    # MÉTODOS DE ANÁLISIS (COMPATIBILIDAD)
    # ============================================================
    
    def _analizar_rapido(self, simbolo: str, precio_actual: float) -> Optional[Any]:
        """Versión legacy de análisis rápido."""
        return self._analizar_rapido_con_fallos(simbolo, precio_actual)
    
    def _analizar_medio(self, simbolo: str, precio_actual: float) -> Optional[Any]:
        """Versión legacy de análisis medio."""
        return self._analizar_medio_con_fallos(simbolo, precio_actual)
    
    # ============================================================
    # OBTENER DATOS H1
    # ============================================================
    
    def _obtener_datos_h1(self, simbolo: str) -> Optional[Any]:
        """Obtiene datos H1 para trailing."""
        try:
            return self.orquestador.cache.get_datos(
                simbolo=simbolo,
                timeframe=60,
                n_velas=50,
                fetch_func=self.mt5.obtener_datos
            )
        except Exception as e:
            self.logger.debug(f"⚠️ Error obteniendo H1: {e}")
            return None
    
    # ============================================================
    # VERIFICAR SL/TP (CORREGIDO)
    # ============================================================
    
    def _verificar_sl_tp(self, pos: Dict, ticket: int, ganancia_pips: float, precio_actual: float) -> bool:
        """Verifica si SL o TP fueron alcanzados con precio actualizado."""
        sl = pos.get('sl', 0)
        tp = pos.get('tp', 0)
        entry_price = pos.get('precio_apertura', 0)
        direccion = self._determinar_direccion(pos, {})
        
        if direccion == 'COMPRA':
            if sl > 0 and precio_actual <= sl:
                self.logger.info(f"🎯 {pos.get('simbolo')}: SL alcanzado ({precio_actual:.5f} <= {sl:.5f})")
                self._cerrar_posicion(ticket, "SL alcanzado")
                return True
            if tp > 0 and precio_actual >= tp:
                self.logger.info(f"🎯 {pos.get('simbolo')}: TP alcanzado ({precio_actual:.5f} >= {tp:.5f})")
                self._cerrar_posicion(ticket, "TP alcanzado")
                return True
        else:
            if sl > 0 and precio_actual >= sl:
                self.logger.info(f"🎯 {pos.get('simbolo')}: SL alcanzado ({precio_actual:.5f} >= {sl:.5f})")
                self._cerrar_posicion(ticket, "SL alcanzado")
                return True
            if tp > 0 and precio_actual <= tp:
                self.logger.info(f"🎯 {pos.get('simbolo')}: TP alcanzado ({precio_actual:.5f} <= {tp:.5f})")
                self._cerrar_posicion(ticket, "TP alcanzado")
                return True
        
        return False
    
    # ============================================================
    # CERRAR POSICIÓN (CON MANEJO DE ERRORES)
    # ============================================================
    
    def _cerrar_posicion(self, ticket: int, razon: str):
        """Cierra una posición con logging detallado."""
        self.logger.info(f"🔒 Cerrando posición {ticket} - Razón: {razon}")
        
        # Obtener símbolo antes de cerrar
        simbolo = self._obtener_simbolo_de_ticket(ticket)
        
        # Intentar cerrar
        if self.orquestador.modo_backtest:
            # Simular cierre en backtest
            exito = self._cerrar_backtest(ticket)
        else:
            exito = self.mt5.cerrar_posicion(ticket)
        
        if exito:
            self.logger.info(f"✅ Posición {ticket} cerrada: {razon}")
            self._stats['cerradas'] += 1
            
            # Obtener detalle del cierre
            detalle = self._obtener_detalle_cierre(ticket)
            
            # Registrar en gestión de riesgo
            if detalle:
                ganancia = detalle.get('ganancia', 0)
                self.gestion_riesgo.registrar_operacion({
                    'ticket': ticket,
                    'simbolo': simbolo,
                    'ganancia': ganancia,
                    'comision': detalle.get('comision', 0),
                    'swap': detalle.get('swap', 0),
                    'motivo_cierre': razon
                })
                
                # ✅ PATRON TRACKER: Registrar resultado
                if self.orquestador.patron_tracker:
                    self.orquestador.patron_tracker.registrar_resultado(
                        simbolo=simbolo,
                        ganancia=ganancia
                    )
            
            # Eliminar de memoria
            if ticket in self.orquestador.estado.posiciones_abiertas:
                del self.orquestador.estado.posiciones_abiertas[ticket]
            
            # Notificar
            if self.orquestador.notificaciones:
                self.orquestador.notificaciones.enviar(
                    "🔒 CIERRE DE POSICIÓN",
                    f"Ticket: {ticket} | Símbolo: {simbolo} | Razón: {razon}",
                    tipo='info'
                )
        else:
            self.logger.error(f"❌ Fallo al cerrar posición {ticket}")
            
            # Notificar fallo
            if self.orquestador.notificaciones:
                self.orquestador.notificaciones.enviar(
                    "❌ FALLO EN CIERRE",
                    f"No se pudo cerrar la posición {ticket} ({simbolo})",
                    tipo='error'
                )
    
    def _cerrar_backtest(self, ticket: int) -> bool:
        """Simula cierre en backtest."""
        if ticket in self.orquestador.estado.posiciones_abiertas:
            meta = self.orquestador.estado.posiciones_abiertas[ticket]
            
            # Simular ganancia basada en precio actual
            simbolo = meta.get('simbolo', '')
            precio_actual = self._obtener_precio_simulado(simbolo)
            entry = meta.get('entrada', 0)
            direccion = meta.get('direccion', 'COMPRA')
            lotes = meta.get('lotes', 0)
            
            pip_val = self._obtener_pip_val(simbolo)
            ganancia_pips = (precio_actual - entry) / pip_val if direccion == 'COMPRA' else (entry - precio_actual) / pip_val
            ganancia_usd = ganancia_pips * pip_val * lotes * 100000
            
            # Actualizar estado
            del self.orquestador.estado.posiciones_abiertas[ticket]
            
            return True
        return False
    
    def _obtener_simbolo_de_ticket(self, ticket: int) -> str:
        """Obtiene símbolo de un ticket."""
        if ticket in self.orquestador.estado.posiciones_abiertas:
            return self.orquestador.estado.posiciones_abiertas[ticket].get('simbolo', '')
        
        # Intentar desde MT5
        try:
            posiciones = self.mt5.obtener_posiciones()
            for pos in posiciones:
                if pos.get('ticket') == ticket:
                    return pos.get('simbolo', '')
        except:
            pass
        
        return ''
    
    def _obtener_detalle_cierre(self, ticket: int) -> Optional[Dict]:
        """Obtiene detalle del cierre."""
        try:
            return self.mt5.obtener_detalle_cierre(ticket)
        except Exception as e:
            self.logger.debug(f"Error obteniendo detalle de cierre: {e}")
            return None
    
    # ============================================================
    # CERRAR PARCIAL (CORREGIDO)
    # ============================================================
    
    def _cerrar_parcial(self, ticket: int, volumen_a_cerrar: float) -> bool:
        """Cierra parcialmente una posición."""
        if self.orquestador.modo_backtest:
            return True
        
        try:
            return self.mt5.cerrar_parcial(ticket, volumen_a_cerrar)
        except Exception as e:
            self.logger.error(f"❌ Error cerrando parcialmente {ticket}: {e}")
            return False
    
    # ============================================================
    # MOVER SL (CORREGIDO)
    # ============================================================
    
    def _mover_sl(self, ticket: int, nuevo_sl: float) -> bool:
        """Mueve el Stop Loss de una posición."""
        self.logger.info(f"🔄 Moviendo SL para {ticket} a {nuevo_sl:.5f}")
        
        if self.orquestador.modo_backtest:
            # Actualizar estado en memoria
            if ticket in self.orquestador.estado.posiciones_abiertas:
                self.orquestador.estado.posiciones_abiertas[ticket]['sl'] = nuevo_sl
            return True
        
        try:
            if self.mt5.modificar_sl(ticket, nuevo_sl):
                # Actualizar memoria
                if ticket in self.orquestador.estado.posiciones_abiertas:
                    self.orquestador.estado.posiciones_abiertas[ticket]['sl'] = nuevo_sl
                return True
        except Exception as e:
            self.logger.error(f"❌ Error moviendo SL para {ticket}: {e}")
        
        return False
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del monitor."""
        stats = self._stats.copy()
        
        # Calcular tasas
        total = stats['total_procesadas']
        if total > 0:
            stats['tasa_cierre'] = (stats['cerradas'] / total * 100)
            stats['tasa_trailing'] = (stats['sl_movidos'] / total * 100)
            stats['tasa_parcial'] = (stats['cierres_parciales'] / total * 100)
        else:
            stats['tasa_cierre'] = 0
            stats['tasa_trailing'] = 0
            stats['tasa_parcial'] = 0
        
        stats['fallos_analisis_total'] = self._fallos_analisis_rapido + self._fallos_analisis_medio
        
        return stats
    
    def reset_stats(self):
        """Reinicia estadísticas."""
        self._stats = {
            'total_procesadas': 0,
            'cerradas': 0,
            'sl_movidos': 0,
            'cierres_parciales': 0,
            'timeouts': 0,
            'cierres_por_decision': 0,
            'fallos_analisis': 0,
            'ultima_posicion_procesada': None,
        }
        self._fallos_analisis_rapido = 0
        self._fallos_analisis_medio = 0


# ============================================================
# FUNCIÓN DE UTILIDAD (ACTUALIZADA)
# ============================================================

def create_monitor_posiciones(orquestador: Any,
                              mt5: Any,
                              gestion_riesgo: Any,
                              trailing_engine: Optional[TrailingEngine] = None,
                              decisor_cierre: Optional[DecisorCierre] = None,
                              monitorear_manuales: bool = False) -> MonitorPosiciones:
    """
    Crea una instancia de MonitorPosiciones.
    
    Args:
        orquestador: Orquestador principal
        mt5: Conector MT5
        gestion_riesgo: Gestión de riesgo
        trailing_engine: Motor de trailing (opcional)
        decisor_cierre: Decisor de cierre (opcional)
        monitorear_manuales: Si True, monitorea también posiciones manuales
    
    Returns:
        MonitorPosiciones
    """
    return MonitorPosiciones(
        orquestador=orquestador,
        mt5=mt5,
        gestion_riesgo=gestion_riesgo,
        trailing_engine=trailing_engine,
        decisor_cierre=decisor_cierre,
        monitorear_manuales=monitorear_manuales
    )