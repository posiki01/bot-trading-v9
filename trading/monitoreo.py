#!/usr/bin/env python3
"""
trading/monitoreo.py (V9.74 - SIN DECISOR DE CIERRE)
Monitoreo de posiciones abiertas y gestión de stops.

V9.74 - CORRECCIONES DEFINITIVAS:
- ✅ Eliminado DecisorCierre (trailing V9.73 se encarga)
- ✅ SL nunca retrocede - solo avanza hacia ganancia
- ✅ Método unificado _aplicar_trailing_sl() para todas las fases
- ✅ Protección contra retrocesos normales del mercado
- ✅ Umbrales dinámicos basados en ATR (no pips fijos)
- ✅ Distancia del trailing basada en ATR (1.5x ATR)
- ✅ Regla de "No Tocar" durante retrocesos normales
- ✅ Umbrales ajustados por lotes (mínimo $1-$2 USD)
- ✅ Trailing monotónico (nunca oscila entre valores)
"""

import logging
import time
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta

from trading.trailing import TrailingEngine

# ✅ ELIMINAR IMPORTACIÓN DE decision_cierre
# from trading.decision_cierre import DecisorCierre  # ❌ ELIMINADO

logger = logging.getLogger('BotTrading.Monitoreo')


class MonitorPosiciones:
    """
    Monitorea posiciones abiertas y gestiona stops.
    V9.74 - SIN DECISOR DE CIERRE.
    """
    
    def __init__(self,
                 orquestador: Any,
                 mt5: Any,
                 gestion_riesgo: Any,
                 trailing_engine: Optional[TrailingEngine] = None,
                 decisor_cierre: Optional[Any] = None,  # ✅ ACEPTA PERO NO USA
                 monitorear_manuales: bool = False):
        """
        Inicializa el monitor de posiciones.
        
        Args:
            orquestador: Orquestador principal
            mt5: Conector MT5
            gestion_riesgo: Gestión de riesgo
            trailing_engine: Motor de trailing (opcional)
            decisor_cierre: Decisor de cierre (opcional - NO USADO)
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
        
        # ✅ DECISOR DE CIERRE DESACTIVADO
        self.decisor_cierre = None  # ✅ NO SE USA
        
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
            'sl_retrocesos_evitados': 0,
        }
        
        # ✅ Contadores de fallos de análisis
        self._fallos_analisis_rapido = 0
        self._fallos_analisis_medio = 0
        self._max_fallos_antes_alerta = 5
        
        # ✅ Configuración de protección contra retrocesos
        self.ATR_PERIODO = 14
        self.ATR_MULTIPLICADOR_BREAKEVEN = 2.0
        self.ATR_MULTIPLICADOR_TRAILING = 3.0
        self.ATR_MULTIPLICADOR_AGRESSIVO = 4.0
        self.DISTANCIA_TRAILING_MULTIPLICADOR = 1.5
        
        # ✅ Límites mínimos en USD
        self.MIN_BREAKEVEN_USD = 1.0
        self.MIN_TRAILING_USD = 2.0
        self.MIN_AGRESSIVO_USD = 5.0
        
        self.logger.info("🔍 MonitorPosiciones V9.74 SIN DECISOR DE CIERRE inicializado")
        self.logger.info(f"   Monitorear manuales: {monitorear_manuales}")
        self.logger.info(f"   SL monotónico: ✅ ACTIVADO")
        self.logger.info(f"   Protección contra retrocesos: ✅ ACTIVADO")
        self.logger.info(f"   Decisor de cierre: ❌ DESACTIVADO")
    
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
        V9.74 - CORREGIDO: Soporte para backtest.
        
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
        """
        Obtiene precio simulado para backtest.
        ✅ V1.1 - CORREGIDO: Usa precio de la posición como fallback.
        """
        # 1. Intentar desde el caché
        try:
            df = self.orquestador.cache.get_datos(
                simbolo=simbolo,
                timeframe=5,
                n_velas=10,
                fetch_func=self.mt5.obtener_datos
            )
            if df is not None and len(df) > 0:
                return float(df['Close'].iloc[-1])
        except Exception:
            pass
        
        # 2. ✅ CORREGIDO: Usar precio de la posición como fallback
        try:
            for meta in self.orquestador.estado.posiciones_abiertas.values():
                if meta.get('simbolo') == simbolo:
                    precio_entrada = float(meta.get('entrada', 0))
                    if precio_entrada > 0:
                        return precio_entrada
        except Exception:
            pass
        
        # 3. Último recurso: usar precio de la posición de MT5
        try:
            posiciones = self.mt5.obtener_posiciones(simbolo)
            if posiciones:
                return float(posiciones[0].get('precio_actual', 0)) or float(posiciones[0].get('precio_apertura', 0))
        except Exception:
            pass
        
        # 4. Último recurso
        return 1.0
    
    # ============================================================
    # ✅ NUEVO V9.74: CALCULAR ATR (Average True Range)
    # ============================================================
    
    def _calcular_atr(self, simbolo: str, timeframe: int = 5, n_velas: int = 50) -> float:
        """
        Calcula el ATR para un símbolo.
        V9.74 - NUEVO: Para calcular umbrales de trailing dinámicos.
        
        Args:
            simbolo: Símbolo
            timeframe: Timeframe en minutos (5, 15, 60)
            n_velas: Número de velas a considerar
        
        Returns:
            ATR en pips
        """
        try:
            df = self.orquestador.cache.get_datos(
                simbolo=simbolo,
                timeframe=timeframe,
                n_velas=n_velas,
                fetch_func=self.mt5.obtener_datos
            )
            
            if df is None or len(df) < self.ATR_PERIODO:
                return 15.0  # Fallback
            
            high = df['High']
            low = df['Low']
            close = df['Close']
            
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            
            atr = tr.rolling(self.ATR_PERIODO).mean().iloc[-1]
            
            # Convertir a pips
            pip_val = self._obtener_pip_val(simbolo)
            atr_pips = atr / pip_val if pip_val > 0 else atr
            
            return float(atr_pips) if not pd.isna(atr_pips) else 15.0
            
        except Exception as e:
            self.logger.debug(f"⚠️ Error calculando ATR para {simbolo}: {e}")
            return 15.0
    
    def _obtener_atr_pips(self, simbolo: str) -> float:
        """Obtiene ATR en pips para un símbolo."""
        return self._calcular_atr(simbolo, timeframe=5)
    
    # ============================================================
    # ✅ NUEVO V9.74: CALCULAR VALOR DE 1 PIP EN USD
    # ============================================================
    
    def _calcular_valor_pip_usd(self, simbolo: str, lotes: float) -> float:
        """
        Calcula el valor de 1 pip en USD para la posición.
        V9.74 - NUEVO: Para ajustar umbrales por lotes.
        
        Args:
            simbolo: Símbolo
            lotes: Tamaño de la posición
        
        Returns:
            Valor de 1 pip en USD
        """
        pip_val = self._obtener_pip_val(simbolo)
        tamano_contrato = self._obtener_tamano_contrato(simbolo)
        
        # Valor de 1 pip para 1 lote estándar
        valor_pip_1_lote = tamano_contrato * pip_val
        
        # Para la posición actual
        valor_pip_usd = valor_pip_1_lote * lotes
        
        return valor_pip_usd
    
    def _obtener_tamano_contrato(self, simbolo: str) -> float:
        """Obtiene el tamaño del contrato para cada símbolo."""
        simbolo_upper = simbolo.upper()
        
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        if 'XAU' in simbolo_upper:
            return 100.0
        if 'XAG' in simbolo_upper:
            return 5000.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        return 100000.0
    
    # ============================================================
    # ✅ NUEVO V9.74: CALCULAR UMBRALES DINÁMICOS
    # ============================================================
    
    def _calcular_umbrales_trailing(self, simbolo: str, lotes: float, atr_pips: float) -> Dict[str, int]:
        """
        Calcula umbrales de trailing dinámicos.
        V9.74 - NUEVO: Basado en ATR y valor en USD.
        
        Args:
            simbolo: Símbolo
            lotes: Tamaño de la posición
            atr_pips: ATR en pips
        
        Returns:
            Dict con breakeven_umbral, trailing_umbral, trailing_agresivo_umbral
        """
        # Valor de 1 pip en USD para la posición
        valor_pip_usd = self._calcular_valor_pip_usd(simbolo, lotes)
        
        # ✅ Umbrales basados en ATR (protege contra retrocesos normales)
        breakeven_umbral = max(30, int(atr_pips * self.ATR_MULTIPLICADOR_BREAKEVEN))
        trailing_umbral = max(50, int(atr_pips * self.ATR_MULTIPLICADOR_TRAILING))
        trailing_agresivo_umbral = max(80, int(atr_pips * self.ATR_MULTIPLICADOR_AGRESSIVO))
        
        # ✅ Ajustar por valor en USD (mínimo $1 para breakeven)
        min_breakeven_pips = int(self.MIN_BREAKEVEN_USD / max(valor_pip_usd, 0.01))
        breakeven_umbral = max(breakeven_umbral, min_breakeven_pips)
        
        # ✅ Ajustar por valor en USD (mínimo $2 para trailing)
        min_trailing_pips = int(self.MIN_TRAILING_USD / max(valor_pip_usd, 0.01))
        trailing_umbral = max(trailing_umbral, min_trailing_pips)
        
        # ✅ Ajustar por valor en USD (mínimo $5 para agresivo)
        min_agresivo_pips = int(self.MIN_AGRESSIVO_USD / max(valor_pip_usd, 0.01))
        trailing_agresivo_umbral = max(trailing_agresivo_umbral, min_agresivo_pips)
        
        self.logger.info(f"📊 {simbolo}: Umbrales dinámicos calculados:")
        self.logger.info(f"   ATR M5: {atr_pips:.1f} pips")
        self.logger.info(f"   Valor 1 pip: ${valor_pip_usd:.4f}")
        self.logger.info(f"   Breakeven: {breakeven_umbral} pips (${breakeven_umbral * valor_pip_usd:.2f} USD)")
        self.logger.info(f"   Trailing: {trailing_umbral} pips (${trailing_umbral * valor_pip_usd:.2f} USD)")
        self.logger.info(f"   Agresivo: {trailing_agresivo_umbral} pips (${trailing_agresivo_umbral * valor_pip_usd:.2f} USD)")
        
        return {
            'breakeven_umbral': breakeven_umbral,
            'trailing_umbral': trailing_umbral,
            'trailing_agresivo_umbral': trailing_agresivo_umbral,
        }
    
    # ============================================================
    # ✅ NUEVO V9.74: CALCULAR DISTANCIA DEL TRAILING
    # ============================================================
    
    def _calcular_distancia_trailing(self, simbolo: str, atr_pips: float) -> float:
        """
        Calcula la distancia del trailing basada en ATR.
        V9.74 - NUEVO: Protege contra retrocesos normales.
        
        Args:
            simbolo: Símbolo
            atr_pips: ATR en pips
        
        Returns:
            Distancia en pips para el trailing
        """
        # Distancia = 1.5x ATR (mínimo 15 pips)
        distancia = max(15, atr_pips * self.DISTANCIA_TRAILING_MULTIPLICADOR)
        
        self.logger.info(f"📊 {simbolo}: Distancia trailing = {distancia:.1f} pips (1.5x ATR = {atr_pips:.1f} pips)")
        
        return distancia
    
    # ============================================================
    # ✅ NUEVO V9.74: VERIFICAR SI SE DEBE MOVER EL SL
    # ============================================================
    
    def _debe_mover_sl(self, simbolo: str, ganancia_pips: float,
                       sl_actual: float, precio_actual: float,
                       direccion: str, atr_pips: float) -> Tuple[bool, str]:
        """
        Determina si se debe mover el SL.
        V9.74 - NUEVO: Protege contra retrocesos normales.
        
        Args:
            simbolo: Símbolo
            ganancia_pips: Ganancia actual en pips
            sl_actual: SL actual
            precio_actual: Precio actual
            direccion: Dirección ('COMPRA' o 'VENTA')
            atr_pips: ATR en pips
        
        Returns:
            (debe_mover, razon)
        """
        # 1. Ganancia mínima para considerar mover SL
        ganancia_minima = atr_pips * 2  # 2x ATR
        
        if ganancia_pips < ganancia_minima:
            return False, f"Ganancia insuficiente ({ganancia_pips:.1f} < {ganancia_minima:.1f} pips)"
        
        # 2. Distancia del SL al precio actual (debe ser >= 1.5x ATR)
        pip_val = self._obtener_pip_val(simbolo)
        if pip_val <= 0:
            pip_val = 0.0001
        
        if direccion == 'VENTA':
            distancia_sl = (sl_actual - precio_actual) / pip_val
        else:
            distancia_sl = (precio_actual - sl_actual) / pip_val
        
        # Distancia mínima del SL al precio (protege contra retrocesos)
        distancia_minima = atr_pips * self.DISTANCIA_TRAILING_MULTIPLICADOR
        
        if distancia_sl < distancia_minima:
            return False, f"SL demasiado cerca del precio ({distancia_sl:.1f} < {distancia_minima:.1f} pips)"
        
        # 3. Si todo está bien, mover SL
        return True, "OK"
    
    # ============================================================
    # PROCESAMIENTO DE POSICIÓN (CORREGIDO V9.74)
    # ============================================================
    
    def _procesar_posicion(self, pos: Dict):
        """
        Procesa una posición individual con correcciones V9.74.
        V9.74 - CORREGIDO DEFINITIVO:
        - ✅ SIN DecisorCierre (trailing V9.73 se encarga)
        - ✅ Usa P&L de MT5 (pos['ganancia'])
        - ✅ NO mueve SL con ganancias pequeñas (< 2x ATR)
        - ✅ Protección contra retrocesos normales
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
        # 3. CALCULAR GANANCIA EN PIPS Y USD
        # ============================================================
        pip_val = self._obtener_pip_val(simbolo)
        if pip_val <= 0:
            pip_val = 0.0001
        
        if direccion_correcta == 'COMPRA':
            ganancia_pips = (precio_actual - entry_price) / pip_val
        else:
            ganancia_pips = (entry_price - precio_actual) / pip_val
        
        # ✅ CORRECCIÓN: Usar P&L de MT5 (pos['ganancia'])
        ganancia_usd = pos.get('ganancia', 0.0)
        
        self.logger.info(f"📊 {simbolo}: Dir={direccion_correcta} | Entry={entry_price:.5f} | Actual={precio_actual:.5f} | Pips={ganancia_pips:.1f} | P&L=${ganancia_usd:.2f}")
        
        # ============================================================
        # 4. VALIDAR SL/TP SEGÚN DIRECCIÓN
        # ============================================================
        sl_actual = pos.get('sl', 0)
        tp_actual = pos.get('tp', 0)
        
        if direccion_correcta == 'COMPRA':
            if sl_actual > 0 and sl_actual >= precio_actual:
                self.logger.error(f"❌ {simbolo}: SL INVERTIDO para COMPRA (SL={sl_actual:.5f} >= precio={precio_actual:.5f})")
                self._cerrar_posicion(ticket, "SL invertido para COMPRA")
                return
            if tp_actual > 0 and tp_actual <= precio_actual:
                self.logger.warning(f"⚠️ {simbolo}: TP ya alcanzado para COMPRA (TP={tp_actual:.5f} <= precio={precio_actual:.5f})")
                self._cerrar_posicion(ticket, "TP alcanzado (precio > TP)")
                return
        else:
            if sl_actual > 0 and sl_actual <= precio_actual:
                self.logger.error(f"❌ {simbolo}: SL INVERTIDO para VENTA (SL={sl_actual:.5f} <= precio={precio_actual:.5f})")
                self._cerrar_posicion(ticket, "SL invertido para VENTA")
                return
            if tp_actual > 0 and tp_actual >= precio_actual:
                self.logger.warning(f"⚠️ {simbolo}: TP ya alcanzado para VENTA (TP={tp_actual:.5f} >= precio={precio_actual:.5f})")
                self._cerrar_posicion(ticket, "TP alcanzado (precio < TP)")
                return
        
        # ============================================================
        # 5. VERIFICAR SL/TP ALCANZADOS
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
        # 7. VERIFICAR TIMEOUT (ANTES DEL TRAILING - MÁS CRÍTICO)
        # ============================================================
        fecha_entrada_pos = pos.get('fecha_entrada')
        if fecha_entrada_pos is None and ticket in self.orquestador.estado.posiciones_abiertas:
            fecha_entrada_pos = self.orquestador.estado.posiciones_abiertas[ticket].get('fecha_entrada')
            
        pos_para_timeout = pos.copy()
        if fecha_entrada_pos is not None:
            pos_para_timeout['fecha_entrada'] = fecha_entrada_pos

        debe_cerrar_timeout, razon_timeout = self.trailing_engine.verificar_timeout(
            pos=pos_para_timeout,
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
        # 10. ✅ ELIMINADO: DECIDIR SI CERRAR CON GANANCIA (NO USAR)
        # ============================================================
        # ✅ V9.74: DecisorCierre DESACTIVADO
        # El trailing V9.73 se encarga de proteger la ganancia
        
        # ============================================================
        # 11. VALIDAR R:R DINÁMICO Y AJUSTAR TP
        # ============================================================
        rr_original = 0
        if sl_actual > 0 and entry_price > 0:
            sl_dist = abs(entry_price - sl_actual)
            tp_dist = abs(tp_actual - entry_price)
            rr_original = tp_dist / sl_dist if sl_dist > 0 else 0
        
        rr_actual = 0
        if sl_actual > 0 and entry_price > 0:
            sl_dist = abs(entry_price - sl_actual)
            ganancia_actual = abs(precio_actual - entry_price) if (direccion_correcta == 'COMPRA' and precio_actual > entry_price) or (direccion_correcta == 'VENTA' and precio_actual < entry_price) else 0
            rr_actual = ganancia_actual / sl_dist if sl_dist > 0 else 0
        
        if rr_actual > rr_original * 1.2 and analisis_medio is not None:
            nuevo_tp = self._calcular_tp_dinamico(pos, precio_actual, analisis_medio)
            if nuevo_tp > 0 and nuevo_tp != tp_actual:
                self.logger.info(f"🔄 {simbolo}: TP ajustado dinámicamente de {tp_actual:.5f} a {nuevo_tp:.5f}")
                if self._mover_tp(ticket, nuevo_tp):
                    pos['tp'] = nuevo_tp
                    if ticket in self.orquestador.estado.posiciones_abiertas:
                        self.orquestador.estado.posiciones_abiertas[ticket]['tp'] = nuevo_tp
        
        # ============================================================
        # 12. TRAILING SL CON PROTECCIÓN CONTRA RETROCESOS (V9.74)
        # ============================================================
        from config.umbrales import Umbrales
        trailing_config = getattr(Umbrales, 'TRAILING', {})
        modo = meta.get('modo', 'RETEST')
        modo_lower = modo.lower()
        
        # ✅ CORREGIDO V9.74: Calcular ATR primero
        atr_pips = self._obtener_atr_pips(simbolo)
        
        # ✅ CORREGIDO V9.74: Obtener lotes de la posición
        lotes_posicion = pos.get('volumen', meta.get('lotes', 0.01))
        
        # ✅ CORREGIDO V9.74: Calcular umbrales dinámicos según ATR y lotes
        umbrales_trailing = self._calcular_umbrales_trailing(simbolo, lotes_posicion, atr_pips)
        
        breakeven_umbral = umbrales_trailing['breakeven_umbral']
        trailing_umbral = umbrales_trailing['trailing_umbral']
        trailing_agresivo_umbral = umbrales_trailing['trailing_agresivo_umbral']
        
        # ✅ CORREGIDO V9.74: Calcular distancia del trailing basada en ATR
        distancia_trailing = self._calcular_distancia_trailing(simbolo, atr_pips)
        trailing_distancia = max(15, int(distancia_trailing))
        trailing_agresivo_distancia = max(10, int(distancia_trailing * 0.7))
        
        # Ajustar por régimen (MULTIPLICAR)
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
        
        # ✅ CORRECCIÓN: Asegurar valores MÍNIMOS
        breakeven_umbral = max(30, int(breakeven_umbral * multiplicador))
        trailing_umbral = max(50, int(trailing_umbral * multiplicador))
        trailing_distancia = max(15, int(trailing_distancia * multiplicador))
        trailing_agresivo_umbral = max(80, int(trailing_agresivo_umbral * multiplicador))
        trailing_agresivo_distancia = max(10, int(trailing_agresivo_distancia * multiplicador))
        
        # ✅ CORREGIDO V9.74: Verificar si se debe mover SL
        debe_mover, razon_no_mover = self._debe_mover_sl(
            simbolo, ganancia_pips, sl_actual, precio_actual, 
            direccion_correcta, atr_pips
        )
        
        if debe_mover:
            # ============================================================
            # ✅ NUEVO V9.74: MÉTODO UNIFICADO PARA APLICAR TRAILING
            # ============================================================
            
            # FASE 1: BREAKEVEN (mover SL a entrada + 2 pips)
            if ganancia_pips >= breakeven_umbral and sl_actual < entry_price:
                nuevo_sl = entry_price + (2 * pip_val) if direccion_correcta == 'COMPRA' else entry_price - (2 * pip_val)
                
                # ✅ CORRECCIÓN: SOLO mover si nuevo_sl es MEJOR que sl_actual
                sl_actual = self._aplicar_trailing_sl(
                    ticket=ticket,
                    simbolo=simbolo,
                    direccion=direccion_correcta,
                    sl_actual=sl_actual,
                    nuevo_sl=nuevo_sl,
                    fase="BREAKEVEN",
                    ganancia_pips=ganancia_pips
                )
            
            # FASE 2: TRAILING SUAVE (mover SL detrás del precio)
            elif ganancia_pips >= trailing_umbral:
                if direccion_correcta == 'COMPRA':
                    nuevo_sl = precio_actual - (trailing_distancia * pip_val)
                else:
                    nuevo_sl = precio_actual + (trailing_distancia * pip_val)
                
                # ✅ CORRECCIÓN: Usar método unificado
                sl_actual = self._aplicar_trailing_sl(
                    ticket=ticket,
                    simbolo=simbolo,
                    direccion=direccion_correcta,
                    sl_actual=sl_actual,
                    nuevo_sl=nuevo_sl,
                    fase="TRAILING_SUAVE",
                    ganancia_pips=ganancia_pips
                )
            
            # FASE 3: TRAILING AGRESIVO (mover SL más cerca)
            elif ganancia_pips >= trailing_agresivo_umbral:
                if direccion_correcta == 'COMPRA':
                    nuevo_sl = precio_actual - (trailing_agresivo_distancia * pip_val)
                else:
                    nuevo_sl = precio_actual + (trailing_agresivo_distancia * pip_val)
                
                # ✅ CORRECCIÓN: Usar método unificado
                sl_actual = self._aplicar_trailing_sl(
                    ticket=ticket,
                    simbolo=simbolo,
                    direccion=direccion_correcta,
                    sl_actual=sl_actual,
                    nuevo_sl=nuevo_sl,
                    fase="TRAILING_AGRESIVO",
                    ganancia_pips=ganancia_pips
                )
        else:
            self.logger.debug(f"ℹ️ {simbolo}: NO se mueve SL - {razon_no_mover}")
        
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
            # ✅ CORRECCIÓN: Usar método unificado también aquí
            sl_actual = self._aplicar_trailing_sl(
                ticket=ticket,
                simbolo=simbolo,
                direccion=direccion_correcta,
                sl_actual=sl_actual,
                nuevo_sl=decision.nuevo_sl,
                fase=decision.fase,
                ganancia_pips=ganancia_pips
            )
        
        # Actualizar timestamp de última posición procesada
        self._stats['ultima_posicion_procesada'] = datetime.now(timezone.utc).isoformat()
    
    # ============================================================
    # ✅ NUEVO V9.74: MÉTODO UNIFICADO PARA APLICAR TRAILING SL
    # ============================================================
    
    def _aplicar_trailing_sl(self,
                             ticket: int,
                             simbolo: str,
                             direccion: str,
                             sl_actual: float,
                             nuevo_sl: float,
                             fase: str,
                             ganancia_pips: float) -> float:
        """
        Aplica trailing SL de forma segura.
        V9.74 - CORREGIDO: SOLO mueve si mejora el SL actual.
        
        Args:
            ticket: Ticket de la posición
            simbolo: Símbolo
            direccion: Dirección ('COMPRA' o 'VENTA')
            sl_actual: SL actual
            nuevo_sl: SL propuesto
            fase: Nombre de la fase ('BREAKEVEN', 'TRAILING_SUAVE', etc.)
            ganancia_pips: Ganancia actual en pips
        
        Returns:
            float: Nuevo SL (o el actual si no mejora)
        """
        # ✅ CORRECCIÓN CRÍTICA: Verificar que nuevo_sl MEJORA el SL actual
        if direccion == 'COMPRA' and nuevo_sl <= sl_actual:
            self.logger.debug(f"ℹ️ {simbolo}: {fase} no aplica - nuevo SL ({nuevo_sl:.5f}) no mejora actual ({sl_actual:.5f})")
            self._stats['sl_retrocesos_evitados'] += 1
            return sl_actual
        
        if direccion == 'VENTA' and nuevo_sl >= sl_actual:
            self.logger.debug(f"ℹ️ {simbolo}: {fase} no aplica - nuevo SL ({nuevo_sl:.5f}) no mejora actual ({sl_actual:.5f})")
            self._stats['sl_retrocesos_evitados'] += 1
            return sl_actual
        
        # Mover SL
        self.logger.info(f"🔄 {simbolo}: {fase} - Moviendo SL de {sl_actual:.5f} a {nuevo_sl:.5f} (ganancia: {ganancia_pips:.1f} pips)")
        
        if self._mover_sl(ticket, nuevo_sl):
            # Actualizar estado
            if ticket in self.orquestador.estado.posiciones_abiertas:
                self.orquestador.estado.posiciones_abiertas[ticket]['sl'] = nuevo_sl
            return nuevo_sl
        
        return sl_actual
    
    # ============================================================
    # ✅ NUEVO V9.74: RECUPERACIÓN DE DATOS M5
    # ============================================================
    
    def _obtener_datos_m5_recuperable(self, simbolo: str) -> Optional[Any]:
        """
        Obtiene datos M5 con múltiples estrategias de recuperación.
        V9.74 - NUEVO: Si MT5 falla, intenta desde caché o construir.
        
        Returns:
            DataFrame o None
        """
        # 1. Intentar desde caché (puede tener datos antiguos)
        try:
            df = self.orquestador.cache.get_datos(
                simbolo=simbolo,
                timeframe=5,
                n_velas=100,
                fetch_func=self.mt5.obtener_datos
            )
            if df is not None and len(df) > 20:
                return df
        except Exception:
            pass
        
        # 2. Intentar descargar directamente de MT5
        try:
            df = self.mt5.obtener_datos(simbolo, n_velas=100, timeframe=5)
            if df is not None and len(df) > 20:
                # Guardar en caché para futuros usos
                try:
                    self.orquestador.cache.set((simbolo, 5, 100), df)
                except Exception:
                    pass
                return df
        except Exception:
            pass
        
        # 3. Intentar desde SQLite (si tiene datos históricos)
        if hasattr(self.orquestador, 'almacen') and self.orquestador.almacen:
            try:
                df = self.orquestador.almacen.obtener_datos_historicos(simbolo, 5)
                if df is not None and len(df) > 20:
                    return df
            except Exception:
                pass
        
        # 4. Fallback: crear DataFrame mínimo desde datos de posición
        try:
            import pandas as pd
            import numpy as np
            
            # Obtener precio actual
            precio_actual = 0.0
            if hasattr(self.mt5, 'obtener_precio'):
                tick = self.mt5.obtener_precio(simbolo)
                if tick:
                    precio_actual = float(tick.get('bid', tick.get('ask', 0)))
            
            if precio_actual <= 0:
                return None
            
            # Crear DataFrame mínimo (20 velas sintéticas alrededor del precio)
            fechas = pd.date_range(end=datetime.now(timezone.utc), periods=20, freq='5min')
            precio = precio_actual
            
            df = pd.DataFrame({
                'Open': [precio * (1 + np.random.normal(0, 0.0005)) for _ in range(20)],
                'High': [precio * (1 + abs(np.random.normal(0, 0.001))) for _ in range(20)],
                'Low': [precio * (1 - abs(np.random.normal(0, 0.001))) for _ in range(20)],
                'Close': [precio * (1 + np.random.normal(0, 0.0005)) for _ in range(20)],
                'Volume': [100 + np.random.randint(0, 100) for _ in range(20)],
            }, index=fechas)
            
            self.logger.warning(f"⚠️ {simbolo}: Datos M5 sintéticos creados (fallback)")
            return df
        except Exception:
            pass
        
        return None
    
    # ============================================================
    # ✅ NUEVO V9.74: RECUPERACIÓN DE DATOS H1
    # ============================================================
    
    def _obtener_datos_h1_recuperable(self, simbolo: str) -> Optional[Any]:
        """
        Obtiene datos H1 con múltiples estrategias de recuperación.
        V9.74 - NUEVO: Si MT5 falla, intenta desde caché o construir.
        
        Returns:
            DataFrame o None
        """
        # 1. Intentar desde caché
        try:
            df = self.orquestador.cache.get_datos(
                simbolo=simbolo,
                timeframe=60,
                n_velas=100,
                fetch_func=self.mt5.obtener_datos
            )
            if df is not None and len(df) > 50:
                return df
        except Exception:
            pass
        
        # 2. Intentar descargar directamente de MT5
        try:
            df = self.mt5.obtener_datos(simbolo, n_velas=100, timeframe=60)
            if df is not None and len(df) > 50:
                try:
                    self.orquestador.cache.set((simbolo, 60, 100), df)
                except Exception:
                    pass
                return df
        except Exception:
            pass
        
        # 3. Intentar construir desde M5
        try:
            df_m5 = self._obtener_datos_m5_recuperable(simbolo)
            if df_m5 is not None and len(df_m5) > 50:
                from utils.construir_timeframes import construir_h1_desde_m5
                df_h1 = construir_h1_desde_m5(df_m5)
                if df_h1 is not None and len(df_h1) > 50:
                    return df_h1
        except Exception:
            pass
        
        # 4. Intentar desde SQLite
        if hasattr(self.orquestador, 'almacen') and self.orquestador.almacen:
            try:
                df = self.orquestador.almacen.obtener_datos_historicos(simbolo, 60)
                if df is not None and len(df) > 50:
                    return df
            except Exception:
                pass
        
        return None
    
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

    def _obtener_pip_val(self, simbolo: str) -> float:
        """Obtiene pip_val dinámicamente para el símbolo."""
        # ✅ 1. Usar módulo unificado (SIEMPRE PRIMERO)
        try:
            from utils.parametros_simbolo import get_pip_val
            pip_val = get_pip_val(simbolo, self.mt5)
            # ✅ VERIFICAR: Si es XAUUSD y devuelve 0.0001, forzar 0.10
            if 'XAU' in simbolo.upper() and pip_val == 0.0001:
                return 0.10
            return pip_val
        except (ImportError, RecursionError):
            pass
        
        # ✅ 2. Intentar desde MT5
        if self.mt5 and hasattr(self.mt5, '_pip_size_simbolo'):
            try:
                info = self.mt5.obtener_info_simbolo(simbolo)
                if info is not None:
                    pip_val = float(self.mt5._pip_size_simbolo(simbolo, info))
                    # ✅ VERIFICAR: Si es XAUUSD y devuelve 0.0001, forzar 0.10
                    if 'XAU' in simbolo.upper() and pip_val == 0.0001:
                        return 0.10
                    return pip_val
            except Exception:
                pass
        
        # ✅ 3. Fallback CORRECTO
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.10  # ✅ CORREGIDO: 0.10 para oro
        if 'XAG' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001  # ✅ Forex estándar

    def _calcular_tp_dinamico(self, pos: Dict, precio_actual: float, analisis_medio: Any = None) -> float:
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
        if analisis_medio is None:
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
    # ✅ CORRECCIÓN V9.74: Reanálisis de mercado con recuperación
    # ============================================================
    
    def _reanalizar_mercado(self, simbolo: str, precio_actual: float) -> tuple:
        """
        Reanaliza el mercado en tiempo real con contadores de fallos.
        V9.74 - CORREGIDO: Usa recuperación de datos.
        
        Args:
            simbolo: Símbolo
            precio_actual: Precio actual
        
        Returns:
            (analisis_rapido, analisis_medio) - Pueden ser None
        """
        # Análisis rápido M5 (con recuperación)
        analisis_rapido = self._analizar_rapido_con_fallos(simbolo, precio_actual)
        
        # Análisis medio H1 (con recuperación)
        analisis_medio = self._analizar_medio_con_fallos(simbolo, precio_actual)
        
        return analisis_rapido, analisis_medio
    
    def _analizar_rapido_con_fallos(self, simbolo: str, precio_actual: float) -> Optional[Any]:
        """
        Ejecuta análisis rápido con contador de fallos.
        V9.74 - CORREGIDO: INTENTA RECUPERAR DATOS SI FALLAN.
        """
        try:
            # ✅ V9.74: Usar método de recuperación
            df_m5 = self._obtener_datos_m5_recuperable(simbolo)
            
            if df_m5 is not None and len(df_m5) > 20:
                resultado = self.orquestador.analisis_capas.analisis_rapido(df_m5, simbolo, precio_actual)
                # ✅ RESET contador
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
        V9.74 - CORREGIDO: INTENTA RECUPERAR DATOS SI FALLAN.
        """
        try:
            # ✅ V9.74: Usar método de recuperación
            df_h1 = self._obtener_datos_h1_recuperable(simbolo)
            
            if df_h1 is not None and len(df_h1) > 50:
                # ✅ CORRECCIÓN: Verificar frescura de datos
                ultima_fecha = df_h1.index[-1]
                if hasattr(ultima_fecha, 'tzinfo') and ultima_fecha.tzinfo is None:
                    ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
                
                antiguedad_horas = (datetime.now(timezone.utc) - ultima_fecha).total_seconds() / 3600
                
                if antiguedad_horas > 2.0:
                    self.logger.debug(f"⚠️ {simbolo}: Datos H1 desactualizados ({antiguedad_horas:.1f}h)")
                    # ✅ V9.74: SI los datos están desactualizados pero existen, usar igualmente
                    # (mejor datos antiguos que None)
                    pass
                
                try:
                    resultado = self.orquestador.analisis_capas.analisis_medio(df_h1, simbolo)
                    # ✅ RESET contador
                    self._fallos_analisis_medio = 0
                    return resultado
                except Exception as e:
                    self.logger.error(f"❌ {simbolo}: Error en analisis_medio() - {type(e).__name__}: {e}")
                    self._fallos_analisis_medio += 1
                    self._verificar_alertas_fallos(simbolo, 'medio', e)
                    return None
            else:
                self._fallos_analisis_medio += 1
                self._verificar_alertas_fallos(simbolo, 'medio')
                
        except Exception as e:
            self._fallos_analisis_medio += 1
            self._verificar_alertas_fallos(simbolo, 'medio', e)
        
        return None
    
    # ============================================================
    # ✅ CORREGIDO V9.74: Verificar alertas de fallos
    # ============================================================
    
    def _verificar_alertas_fallos(self, simbolo: str, tipo: str, error: Optional[Exception] = None):
        """
        Verifica si se debe notificar al operador por fallos de análisis.
        V9.74 - CORREGIDO: Notifica SOLO si el fallo es persistente.
        """
        fallos = 0
        if tipo == 'rápido':
            fallos = self._fallos_analisis_rapido
        else:
            fallos = self._fallos_analisis_medio
        
        # ✅ CORREGIDO: Notificar a los 5 (más temprano para diagnóstico)
        if fallos == 5:
            mensaje = f"Análisis {tipo} está fallando para {simbolo} ({fallos} intentos)"
            if error:
                mensaje += f" - Último error: {error}"
            
            self.logger.warning(f"⚠️ {mensaje}")
            
            if self.orquestador.notificaciones:
                self.orquestador.notificaciones.enviar(
                    "⚠️ MONITOREO FALLANDO",
                    mensaje,
                    tipo='alerta'
                )
        
        # ✅ CORREGIDO: Notificar a los 10 SOLO si sigue fallando
        elif fallos == 10:
            mensaje = f"Análisis {tipo} FALLO PERSISTENTE para {simbolo} ({fallos} intentos)"
            if error:
                mensaje += f" - Último error: {error}"
            
            self.logger.error(f"❌ {mensaje}")
            
            if self.orquestador.notificaciones:
                self.orquestador.notificaciones.enviar(
                    "❌ MONITOREO CRÍTICO",
                    mensaje,
                    tipo='error'
                )
    
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
        return self._obtener_datos_h1_recuperable(simbolo)
    
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
            'sl_retrocesos_evitados': 0,
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
                              decisor_cierre: Optional[Any] = None,
                              monitorear_manuales: bool = False) -> MonitorPosiciones:
    """
    Crea una instancia de MonitorPosiciones.
    
    Args:
        orquestador: Orquestador principal
        mt5: Conector MT5
        gestion_riesgo: Gestión de riesgo
        trailing_engine: Motor de trailing (opcional)
        decisor_cierre: Decisor de cierre (opcional - NO USADO)
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