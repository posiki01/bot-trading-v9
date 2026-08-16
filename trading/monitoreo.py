#!/usr/bin/env python3
"""
trading/monitoreo.py (V9.0)
Monitoreo de posiciones abiertas y gestión de stops.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger('BotTrading.Monitoreo')


class MonitorPosiciones:
    """
    Monitorea posiciones abiertas y gestiona trailing stops.
    RESPONSABILIDAD: Solo monitorear y gestionar stops.
    """
    
    def __init__(self, orquestador, mt5, gestion_riesgo, trailing_engine):
        self.orquestador = orquestador
        self.mt5 = mt5
        self.gestion_riesgo = gestion_riesgo
        self.trailing_engine = trailing_engine
        self.logger = logging.getLogger('BotTrading.Monitoreo')
    
    def ejecutar_ciclo(self):
        """Ejecuta un ciclo de monitoreo."""
        posiciones = self.mt5.obtener_posiciones()
        
        if not posiciones:
            return
        
        for pos in posiciones:
            self._procesar_posicion(pos)
    
    def _procesar_posicion(self, pos: Dict):
        """Procesa una posición individual."""
        ticket = pos['ticket']
        simbolo = pos['simbolo']
        
        # Verificar si es manual
        meta = self.orquestador.estado.posiciones_abiertas.get(ticket, {})
        if meta.get('es_manual', False):
            return
        
        # Calcular ganancia en pips
        entry_price = pos['precio_apertura']
        precio_actual = pos['precio_actual']
        direccion = pos['tipo']
        
        pip_val = self._obtener_pip_val(simbolo)
        if direccion == 'BUY':
            ganancia_pips = (precio_actual - entry_price) / pip_val
        else:
            ganancia_pips = (entry_price - precio_actual) / pip_val
        
        # Verificar SL/TP alcanzados
        if self._verificar_sl_tp(pos, ticket, ganancia_pips):
            return
        
        # Obtener configuración
        modo = meta.get('modo', 'RETEST')
        regimen = meta.get('regimen', 'INCERTO')
        
        # Calcular movimiento de SL
        df_h1 = self.orquestador.obtener_datos_cached(simbolo, n_velas=50, timeframe=60)
        
        decision = self.trailing_engine.calcular_movimiento_sl(
            pos=pos,
            df_h1=df_h1,
            precio_actual=precio_actual,
            fecha=datetime.now(timezone.utc),
            regimen=regimen,
            modo=modo
        )
        
        # Aplicar decisión
        if decision.get('cerrar', False):
            self._cerrar_posicion(ticket, decision.get('razon', 'Cierre por trailing'))
        elif decision.get('mover_sl', False):
            self._mover_sl(ticket, decision['nuevo_sl'])
    
    def _verificar_sl_tp(self, pos: Dict, ticket: int, ganancia_pips: float) -> bool:
        """Verifica si SL o TP fueron alcanzados."""
        sl = pos.get('sl', 0)
        tp = pos.get('tp', 0)
        precio_actual = pos['precio_actual']
        entry_price = pos['precio_apertura']
        direccion = pos['tipo']
        
        if direccion == 'BUY':
            if sl > 0 and precio_actual <= sl:
                self._cerrar_posicion(ticket, "SL alcanzado")
                return True
            if tp > 0 and precio_actual >= tp:
                self._cerrar_posicion(ticket, "TP alcanzado")
                return True
        else:
            if sl > 0 and precio_actual >= sl:
                self._cerrar_posicion(ticket, "SL alcanzado")
                return True
            if tp > 0 and precio_actual <= tp:
                self._cerrar_posicion(ticket, "TP alcanzado")
                return True
        
        return False
    
    def _cerrar_posicion(self, ticket: int, razon: str):
        """Cierra una posición."""
        if self.mt5.cerrar_posicion(ticket):
            self.logger.info(f"🔒 Posición {ticket} cerrada: {razon}")
            
            # Registrar en gestión de riesgo
            detalle = self.mt5.obtener_detalle_cierre(ticket)
            if detalle:
                self.gestion_riesgo.registrar_operacion({
                    'ticket': ticket,
                    'ganancia': detalle.get('ganancia', 0),
                    'comision': detalle.get('comision', 0),
                    'swap': detalle.get('swap', 0),
                    'motivo_cierre': razon
                })
            
            # Eliminar de memoria
            if ticket in self.orquestador.estado.posiciones_abiertas:
                del self.orquestador.estado.posiciones_abiertas[ticket]
    
    def _mover_sl(self, ticket: int, nuevo_sl: float):
        """Mueve el Stop Loss de una posición."""
        if self.mt5.modificar_sl(ticket, nuevo_sl):
            self.logger.info(f"🔄 SL movido a {nuevo_sl:.5f} para ticket {ticket}")
            
            # Actualizar memoria
            if ticket in self.orquestador.estado.posiciones_abiertas:
                self.orquestador.estado.posiciones_abiertas[ticket]['sl'] = nuevo_sl
    
    def _obtener_pip_val(self, simbolo: str) -> float:
        """Obtiene el valor de un pip para el símbolo."""
        if 'JPY' in simbolo:
            return 0.01
        if 'XAU' in simbolo:
            return 0.10
        if any(x in simbolo for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        return 0.0001