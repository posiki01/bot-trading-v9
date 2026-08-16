#!/usr/bin/env python3
"""
core/patron_tracker.py (V8.0 - ACTUALIZADO)
Tracker de patrones y ejecuciones con AlmacenamientoSQLite.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from collections import defaultdict
import pandas as pd

logger = logging.getLogger('BotTrading.PatronTracker')


class PatronTracker:
    """
    Tracker de patrones de trading.
    V8.0: Integración con AlmacenamientoSQLite.
    """
    
    def __init__(self, almacen=None, config=None):
        self.almacen = almacen
        self.config = config
        
        self._patrones_activos: Dict[str, Dict] = {}
        self._ejecuciones: Dict[str, List[Dict]] = defaultdict(list)
        self._perdidas_consecutivas: Dict[str, int] = defaultdict(int)
        
        self._cargar_desde_almacen()
        
        logger.info("📊 PatronTracker V8.0 inicializado")
    
    def _cargar_desde_almacen(self):
        """Carga datos desde almacenamiento."""
        if not self.almacen:
            return
        
        try:
            if hasattr(self.almacen, 'obtener_configuracion'):
                config = self.almacen.obtener_configuracion()
                if config and 'perdidas_consecutivas' in config:
                    self._perdidas_consecutivas = defaultdict(
                        int, config['perdidas_consecutivas']
                    )
                    logger.debug(f"📊 Pérdidas consecutivas cargadas: {dict(self._perdidas_consecutivas)}")
        except Exception as e:
            logger.warning(f"⚠️ Error cargando datos: {e}")
    
    def _guardar_en_almacen(self):
        """Guarda datos en almacenamiento."""
        if not self.almacen:
            return
        
        try:
            if hasattr(self.almacen, 'guardar_configuracion'):
                if hasattr(self.almacen, 'obtener_configuracion'):
                    config = self.almacen.obtener_configuracion()
                    config['perdidas_consecutivas'] = dict(self._perdidas_consecutivas)
                    self.almacen.guardar_configuracion(config)
        except Exception as e:
            logger.warning(f"⚠️ Error guardando datos: {e}")
    
    def detectar_y_actualizar(self, simbolo: str, df: pd.DataFrame, 
                             fecha_referencia: Optional[datetime] = None):
        """
        Detecta patrones en el DataFrame y actualiza el tracker.
        
        Args:
            simbolo: Símbolo
            df: DataFrame con datos
            fecha_referencia: Fecha de referencia (opcional)
        """
        try:
            if df is None or len(df) < 30:
                return
            
            precio_actual = df['Close'].iloc[-1]
            precio_anterior = df['Close'].iloc[-2] if len(df) > 1 else precio_actual
            
            ema9 = df['Close'].ewm(span=9, adjust=False).mean().iloc[-1]
            ema21 = df['Close'].ewm(span=21, adjust=False).mean().iloc[-1]
            
            patrones = []
            
            # Cruce de EMAs
            if len(df) > 21:
                ema9_anterior = df['Close'].ewm(span=9, adjust=False).mean().iloc[-2]
                ema21_anterior = df['Close'].ewm(span=21, adjust=False).mean().iloc[-2]
                
                if ema9_anterior < ema21_anterior and ema9 > ema21:
                    patrones.append('CRUCE_DORADO')
                elif ema9_anterior > ema21_anterior and ema9 < ema21:
                    patrones.append('CRUCE_MUERTE')
            
            # Pin bar
            if len(df) > 1:
                vela = df.iloc[-1]
                rango = vela['High'] - vela['Low']
                if rango > 0:
                    sombra_sup = vela['High'] - max(vela['Open'], vela['Close'])
                    sombra_inf = min(vela['Open'], vela['Close']) - vela['Low']
                    
                    if sombra_inf / rango > 0.6:
                        patrones.append('PIN_BAR_ALCISTA')
                    elif sombra_sup / rango > 0.6:
                        patrones.append('PIN_BAR_BAJISTA')
            
            # Engulfing
            if len(df) > 1:
                vela_actual = df.iloc[-1]
                vela_anterior = df.iloc[-2]
                
                if (vela_actual['Close'] > vela_anterior['Open'] and 
                    vela_actual['Open'] < vela_anterior['Close'] and
                    vela_anterior['Close'] < vela_anterior['Open']):
                    patrones.append('ENGULFING_ALCISTA')
                elif (vela_actual['Close'] < vela_anterior['Open'] and 
                      vela_actual['Open'] > vela_anterior['Close'] and
                      vela_anterior['Close'] > vela_anterior['Open']):
                    patrones.append('ENGULFING_BAJISTA')
            
            # Actualizar si hay patrones
            if patrones:
                fecha = fecha_referencia or datetime.now(timezone.utc)
                for patron in patrones:
                    self.registrar_patron(simbolo, patron, 'NEUTRAL', 60)
                    
        except Exception as e:
            logger.debug(f"Error detectando patrones para {simbolo}: {e}")
    
    def registrar_patron(self, simbolo: str, patron: str, 
                         direccion: str, score: float) -> Dict:
        """Registra un patrón detectado."""
        ahora = datetime.now(timezone.utc)
        
        registro = {
            'simbolo': simbolo,
            'patron': patron,
            'direccion': direccion,
            'score': score,
            'timestamp': ahora.isoformat(),
            'activo': True
        }
        
        self._patrones_activos[simbolo] = registro
        logger.debug(f"📝 Patrón registrado: {simbolo} - {patron}")
        
        return registro
    
    def marcar_ejecutado(self, simbolo: str) -> bool:
        """Marca un patrón como ejecutado."""
        if simbolo in self._patrones_activos:
            self._patrones_activos[simbolo]['activo'] = False
            
            ejecucion = {
                'simbolo': simbolo,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'patron': self._patrones_activos[simbolo]['patron']
            }
            self._ejecuciones[simbolo].append(ejecucion)
            
            if len(self._ejecuciones[simbolo]) > 100:
                self._ejecuciones[simbolo] = self._ejecuciones[simbolo][-50:]
            
            logger.debug(f"✅ Patrón ejecutado: {simbolo}")
            return True
        
        return False
    
    def registrar_resultado(self, simbolo: str, ganancia: float):
        """Registra el resultado de una ejecución."""
        if ganancia < 0:
            self._perdidas_consecutivas[simbolo] += 1
        else:
            self._perdidas_consecutivas[simbolo] = 0
        
        self._guardar_en_almacen()
        logger.debug(f"📊 Resultado registrado: {simbolo} - {ganancia:+.2f}")
    
    def obtener_perdidas_consecutivas(self, simbolo: str) -> int:
        """Obtiene el número de pérdidas consecutivas."""
        return self._perdidas_consecutivas.get(simbolo, 0)
    
    def obtener_patron_activo(self, simbolo: str) -> Optional[Dict]:
        """Obtiene el patrón activo de un símbolo."""
        return self._patrones_activos.get(simbolo)
    
    def limpiar_antiguos(self, horas: int = 48):
        """Limpia patrones antiguos."""
        ahora = datetime.now(timezone.utc)
        to_remove = []
        
        for simbolo, patron in self._patrones_activos.items():
            if patron.get('activo', False):
                try:
                    ts = datetime.fromisoformat(patron['timestamp'])
                    if (ahora - ts).total_seconds() > horas * 3600:
                        to_remove.append(simbolo)
                except Exception:
                    to_remove.append(simbolo)
        
        for simbolo in to_remove:
            del self._patrones_activos[simbolo]
            logger.debug(f"🧹 Patrón antiguo limpiado: {simbolo}")
        
        return len(to_remove)
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del tracker."""
        return {
            'patrones_activos': len(self._patrones_activos),
            'ejecuciones_totales': sum(len(e) for e in self._ejecuciones.values()),
            'simbolos_con_perdidas': len([s for s, p in self._perdidas_consecutivas.items() if p > 0]),
            'perdidas_totales': sum(self._perdidas_consecutivas.values()),
        }