#!/usr/bin/env python3
"""
analysis/niveles.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Sistema de niveles persistente con historial y multi-timeframe.

RESPONSABILIDADES:
- Persistencia de niveles en SQLite
- Validación de niveles
- Caché en memoria
- Limpieza de niveles antiguos
- Integración con detector de niveles

MEJORAS V9.0:
- Separación de detección y persistencia
- Integración con umbrales centralizados
- Caché mejorada con invalidación
- Validación más robusta
- Limpieza automática de niveles antiguos
- Logs más informativos
"""

import logging
import time
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta

# Importar submódulos
from analysis.niveles_deteccion import DetectorNiveles

# Importar umbrales centralizados
try:
    from config.umbrales import Umbrales
except ImportError:
    Umbrales = None

logger = logging.getLogger('BotTrading.Niveles')


class NivelTracker:
    """
    Sistema de niveles persistente multi-timeframe.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    # ============================================================
    # CONFIGURACIÓN POR TIMEFRAME
    # ============================================================
    
    CONFIG_POR_TIMEFRAME = {
        'H1': {
            'dias_antiguedad_max': 10,
            'hits_minimos': 2,
            'fuerza_minima': 30,
            'distancia_agrupacion': 0.002,
            'max_niveles': 15,
            'fuerza_inicial': 20,
        },
        'H4': {
            'dias_antiguedad_max': 30,
            'hits_minimos': 2,
            'fuerza_minima': 40,
            'distancia_agrupacion': 0.003,
            'max_niveles': 10,
            'fuerza_inicial': 35,
        },
        'D1': {
            'dias_antiguedad_max': 90,
            'hits_minimos': 2,
            'fuerza_minima': 50,
            'distancia_agrupacion': 0.005,
            'max_niveles': 8,
            'fuerza_inicial': 50,
        },
        'M15': {
            'dias_antiguedad_max': 2,
            'hits_minimos': 1,
            'fuerza_minima': 15,
            'distancia_agrupacion': 0.001,
            'max_niveles': 5,
            'fuerza_inicial': 10,
        },
        'M5': {
            'dias_antiguedad_max': 1,
            'hits_minimos': 1,
            'fuerza_minima': 10,
            'distancia_agrupacion': 0.001,
            'max_niveles': 3,
            'fuerza_inicial': 5,
        },
    }
    
    TIMEFRAME_DEFAULT = 'H1'
    
    def __init__(self,
                 almacen: Optional[Any] = None,
                 config: Optional[Any] = None,
                 detector: Optional[DetectorNiveles] = None,
                 modo_backtest: bool = False,
                 timeframe_default: str = 'H1'):
        """
        Inicializa el tracker de niveles.
        
        Args:
            almacen: Almacenamiento SQLite
            config: Configuración
            detector: Detector de niveles (opcional)
            modo_backtest: Modo backtest
            timeframe_default: Timeframe por defecto
        """
        self.almacen = almacen
        self.config = config
        self.modo_backtest = modo_backtest
        self.timeframe_default = timeframe_default
        self.logger = logging.getLogger('BotTrading.Niveles')
        
        # Inicializar detector
        self.detector = detector or DetectorNiveles(config)
        
        # Cargar configuración desde umbrales
        self._cargar_configuracion()
        
        # Caché
        self._cache_niveles: Dict[str, Dict] = {}
        self._cache_timestamp: Dict[str, float] = {}
        self._cache_ttl = 60  # segundos
        
        # Cargar niveles iniciales desde almacenamiento
        self._cargar_niveles_iniciales()
        
        self.logger.info(f"📊 NivelTracker V9.0 inicializado")
        self.logger.info(f"   Timeframe principal: {timeframe_default}")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Caché TTL: {self._cache_ttl}s")
    
    def _cargar_configuracion(self):
        """Carga configuración desde umbrales centralizados."""
        if Umbrales is not None:
            # Actualizar configuración por timeframe desde umbrales
            for tf in self.CONFIG_POR_TIMEFRAME:
                if hasattr(Umbrales, 'HITS'):
                    self.CONFIG_POR_TIMEFRAME[tf]['hits_minimos'] = \
                        Umbrales.HITS.get(f'hits_min_{tf.lower()}', 
                                          self.CONFIG_POR_TIMEFRAME[tf]['hits_minimos'])
        
        # Cargar desde config
        if self.config and hasattr(self.config, 'UMBRALES_DETECCION_NIVELES'):
            umbrales = getattr(self.config, 'UMBRALES_DETECCION_NIVELES', {})
            for tf in self.CONFIG_POR_TIMEFRAME:
                if tf in umbrales:
                    self.CONFIG_POR_TIMEFRAME[tf].update(umbrales[tf])
    
    def _cargar_niveles_iniciales(self):
        """Carga niveles iniciales desde almacenamiento."""
        if not self.almacen:
            return
        
        try:
            # Cargar para todos los símbolos (si es posible)
            if hasattr(self.almacen, 'obtener_todos_simbolos'):
                simbolos = self.almacen.obtener_todos_simbolos()
                for simbolo in simbolos:
                    self._cargar_niveles_desde_almacen(simbolo)
        except Exception as e:
            self.logger.debug(f"Error cargando niveles iniciales: {e}")
    
    # ============================================================
    # MÉTODOS PRINCIPALES
    # ============================================================
    
    def detectar_y_actualizar_niveles(self,
                                      simbolo: str,
                                      df: pd.DataFrame,
                                      precio_actual: float,
                                      timeframe: str = 'H1') -> Dict[str, List]:
        """
        Detecta niveles y los actualiza en el historial.
        
        Args:
            simbolo: Símbolo
            df: DataFrame del timeframe correspondiente
            precio_actual: Precio actual
            timeframe: Timeframe usado
        
        Returns:
            Niveles válidos del timeframe
        """
        # 1. Detectar niveles usando el detector
        niveles_detectados = self.detector.detectar_niveles(df, simbolo, timeframe)
        
        if not niveles_detectados.get('soportes') and not niveles_detectados.get('resistencias'):
            # Si no se detectaron niveles, usar detección de respaldo
            niveles_detectados = self._detectar_niveles_fallback(df, simbolo, timeframe)
        
        # 2. Actualizar en almacenamiento
        for nivel in niveles_detectados.get('soportes', []):
            self._actualizar_nivel(simbolo, nivel, timeframe)
        
        for nivel in niveles_detectados.get('resistencias', []):
            self._actualizar_nivel(simbolo, nivel, timeframe)
        
        # 3. Limpiar caché
        self._invalidar_cache(simbolo, timeframe)
        
        # 4. Obtener niveles válidos
        return self.obtener_niveles_validos(simbolo, timeframe=timeframe)
    
    def _detectar_niveles_fallback(self,
                                   df: pd.DataFrame,
                                   simbolo: str,
                                   timeframe: str) -> Dict[str, List]:
        """
        Detección de niveles simplificada (fallback).
        """
        if df is None or len(df) < 30:
            return {'soportes': [], 'resistencias': []}
        
        config = self.CONFIG_POR_TIMEFRAME.get(timeframe, self.CONFIG_POR_TIMEFRAME['H1'])
        
        soportes = []
        resistencias = []
        
        # Usar mínimos y máximos de ventanas
        window = config.get('ventana', 10)
        
        for i in range(window, len(df) - window, 3):
            if df['Low'].iloc[i] == df['Low'].iloc[i-window:i+window].min():
                precio = df['Low'].iloc[i]
                soportes.append({
                    'precio': precio,
                    'hits': 1,
                    'fuerza': config.get('fuerza_inicial', 20),
                    'tipo': 'soporte',
                    'timeframe': timeframe,
                })
            
            if df['High'].iloc[i] == df['High'].iloc[i-window:i+window].max():
                precio = df['High'].iloc[i]
                resistencias.append({
                    'precio': precio,
                    'hits': 1,
                    'fuerza': config.get('fuerza_inicial', 20),
                    'tipo': 'resistencia',
                    'timeframe': timeframe,
                })
        
        # Agrupar niveles cercanos
        soportes = self.detector.agrupar_niveles_cercanos(
            soportes, config.get('distancia_agrupacion', 0.002)
        )
        resistencias = self.detector.agrupar_niveles_cercanos(
            resistencias, config.get('distancia_agrupacion', 0.002)
        )
        
        return {
            'soportes': soportes[:config.get('max_niveles', 10)],
            'resistencias': resistencias[:config.get('max_niveles', 10)],
        }
    
    # ============================================================
    # VALIDACIÓN DE NIVELES
    # ============================================================
    
    def validar_nivel(self,
                      simbolo: str,
                      precio: float,
                      tipo: str,
                      fecha_actual: Optional[datetime] = None,
                      timeframe: str = 'H1') -> Tuple[bool, str, Dict]:
        """
        Valida si un nivel sigue siendo válido.
        
        Args:
            simbolo: Símbolo
            precio: Precio del nivel
            tipo: 'soporte' o 'resistencia'
            fecha_actual: Fecha de referencia
            timeframe: Timeframe
        
        Returns:
            (es_valido, razon, nivel_data)
        """
        if fecha_actual is None:
            fecha_actual = datetime.now(timezone.utc)
        if fecha_actual.tzinfo is None:
            fecha_actual = fecha_actual.replace(tzinfo=timezone.utc)
        
        # Buscar nivel en caché o almacenamiento
        nivel = self._buscar_nivel(simbolo, precio, tipo, timeframe)
        
        if not nivel:
            return False, "Nivel no encontrado", {}
        
        # Obtener configuración para este timeframe
        config = self.CONFIG_POR_TIMEFRAME.get(timeframe, self.CONFIG_POR_TIMEFRAME['H1'])
        
        hits = nivel.get('hits', 0)
        fuerza = nivel.get('fuerza', 0)
        
        # 1. Validar hits
        if hits < config.get('hits_minimos', 2):
            return False, f"Hits insuficientes ({hits} < {config.get('hits_minimos', 2)})", nivel
        
        # 2. Validar fuerza
        if fuerza < config.get('fuerza_minima', 30):
            return False, f"Fuerza insuficiente ({fuerza} < {config.get('fuerza_minima', 30)})", nivel
        
        # 3. Validar antigüedad
        try:
            ultima_fecha_str = nivel.get('ultima_fecha')
            if ultima_fecha_str:
                ultima_fecha = datetime.fromisoformat(ultima_fecha_str)
                if ultima_fecha.tzinfo is None:
                    ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
                
                dias = (fecha_actual - ultima_fecha).days
                dias_max = config.get('dias_antiguedad_max', 10)
                
                if dias > dias_max:
                    return False, f"Nivel muy antiguo ({dias} días > {dias_max})", nivel
        except Exception as e:
            self.logger.debug(f"Error validando antigüedad: {e}")
        
        return True, "Nivel válido", nivel
    
    # ============================================================
    # CONSULTA DE NIVELES
    # ============================================================
    
    def obtener_niveles_validos(self,
                                simbolo: str,
                                fecha_actual: Optional[datetime] = None,
                                timeframe: str = 'H1') -> Dict[str, List]:
        """
        Obtiene todos los niveles válidos para un símbolo.
        
        Args:
            simbolo: Símbolo
            fecha_actual: Fecha de referencia
            timeframe: Timeframe
        
        Returns:
            Diccionario con 'soportes' y 'resistencias'
        """
        if fecha_actual is None:
            fecha_actual = datetime.now(timezone.utc)
        if fecha_actual.tzinfo is None:
            fecha_actual = fecha_actual.replace(tzinfo=timezone.utc)
        
        # Verificar caché
        cache_key = f"{simbolo}_{timeframe}"
        if cache_key in self._cache_niveles:
            if time.time() - self._cache_timestamp.get(cache_key, 0) < self._cache_ttl:
                return self._cache_niveles[cache_key].copy()
        
        # Cargar desde almacenamiento
        niveles = self._cargar_niveles_desde_almacen(simbolo, timeframe)
        
        # Validar cada nivel
        soportes_validos = []
        resistencias_validas = []
        
        for nivel in niveles.get('soportes', []):
            valido, _, data = self.validar_nivel(
                simbolo, nivel.get('precio', 0), 'soporte',
                fecha_actual, timeframe
            )
            if valido:
                soportes_validos.append(data)
        
        for nivel in niveles.get('resistencias', []):
            valido, _, data = self.validar_nivel(
                simbolo, nivel.get('precio', 0), 'resistencia',
                fecha_actual, timeframe
            )
            if valido:
                resistencias_validas.append(data)
        
        # Ordenar por hits
        soportes_validos.sort(key=lambda x: x.get('hits', 0), reverse=True)
        resistencias_validas.sort(key=lambda x: x.get('hits', 0), reverse=True)
        
        # Limitar cantidad
        config = self.CONFIG_POR_TIMEFRAME.get(timeframe, self.CONFIG_POR_TIMEFRAME['H1'])
        max_niveles = config.get('max_niveles', 15)
        
        soportes_validos = soportes_validos[:max_niveles]
        resistencias_validas = resistencias_validas[:max_niveles]
        
        resultado = {
            'soportes': soportes_validos,
            'resistencias': resistencias_validas
        }
        
        # Guardar en caché
        self._cache_niveles[cache_key] = resultado
        self._cache_timestamp[cache_key] = time.time()
        
        return resultado
    
    def obtener_nivel_mas_cercano(self,
                                  simbolo: str,
                                  precio_actual: float,
                                  tipo: Optional[str] = None,
                                  timeframe: str = 'H1',
                                  max_distancia: float = 3.0) -> Optional[Dict]:
        """
        Obtiene el nivel más cercano al precio actual.
        
        Args:
            simbolo: Símbolo
            precio_actual: Precio actual
            tipo: 'soporte' o 'resistencia' (None = ambos)
            timeframe: Timeframe
            max_distancia: Distancia máxima en porcentaje
        
        Returns:
            Nivel más cercano o None
        """
        niveles = self.obtener_niveles_validos(simbolo, timeframe=timeframe)
        
        return self.detector.encontrar_nivel_cercano(
            niveles.get('soportes', []) + niveles.get('resistencias', []),
            precio_actual,
            tipo,
            max_distancia
        )
    
    # ============================================================
    # PERSISTENCIA
    # ============================================================
    
    def _cargar_niveles_desde_almacen(self,
                                      simbolo: str,
                                      timeframe: str = 'H1') -> Dict[str, List]:
        """
        Carga niveles desde almacenamiento filtrando por timeframe.
        
        Args:
            simbolo: Símbolo
            timeframe: Timeframe
        
        Returns:
            Diccionario con 'soportes' y 'resistencias'
        """
        if not self.almacen:
            return {'soportes': [], 'resistencias': []}
        
        try:
            niveles = self.almacen.obtener_niveles(simbolo)
            if not niveles:
                return {'soportes': [], 'resistencias': []}
            
            # Filtrar por timeframe
            for tipo in ['soportes', 'resistencias']:
                lista = niveles.get(tipo, [])
                lista_filtrada = []
                
                for n in lista:
                    if n.get('timeframe', 'H1') == timeframe:
                        # Asegurar campos
                        if 'hits' not in n:
                            n['hits'] = 1
                        if 'fuerza' not in n:
                            n['fuerza'] = 20
                        if 'ultima_fecha' not in n:
                            n['ultima_fecha'] = datetime.now(timezone.utc).isoformat()
                        lista_filtrada.append(n)
                
                niveles[tipo] = lista_filtrada
            
            return niveles
            
        except Exception as e:
            self.logger.warning(f"Error cargando niveles de {simbolo}: {e}")
            return {'soportes': [], 'resistencias': []}
    
    def _actualizar_nivel(self,
                          simbolo: str,
                          nivel: Dict,
                          timeframe: str = 'H1'):
        """
        Actualiza un nivel en el historial.
        
        Args:
            simbolo: Símbolo
            nivel: Datos del nivel
            timeframe: Timeframe
        """
        if not self.almacen:
            return
        
        try:
            # Buscar nivel existente
            nivel_existente = self._buscar_nivel(
                simbolo, nivel['precio'], nivel['tipo'], timeframe
            )
            
            ahora = datetime.now(timezone.utc)
            
            if nivel_existente:
                # Actualizar
                nivel_existente['hits'] = nivel_existente.get('hits', 0) + nivel.get('hits', 1)
                nivel_existente['fuerza'] = min(100, nivel_existente.get('fuerza', 0) + nivel.get('fuerza', 0))
                nivel_existente['ultima_fecha'] = ahora.isoformat()
                nivel_existente['veces_tocado'] = nivel_existente.get('veces_tocado', 0) + 1
            else:
                # Crear nuevo
                nivel['fecha_creacion'] = ahora.isoformat()
                nivel['ultima_fecha'] = ahora.isoformat()
                nivel['veces_tocado'] = 1
                nivel['timeframe'] = timeframe
            
            # Guardar todos los niveles del símbolo
            self._guardar_niveles(simbolo)
            
        except Exception as e:
            self.logger.warning(f"Error actualizando nivel para {simbolo}: {e}")
    
    def _guardar_niveles(self, simbolo: str):
        """
        Guarda todos los niveles de un símbolo en almacenamiento.
        
        Args:
            simbolo: Símbolo
        """
        if not self.almacen:
            return
        
        try:
            # Obtener todos los niveles del símbolo (todos los timeframes)
            niveles = self._obtener_todos_los_timeframes(simbolo)
            
            self.almacen.guardar_niveles(
                simbolo,
                niveles.get('soportes', []),
                niveles.get('resistencias', [])
            )
            
        except Exception as e:
            self.logger.warning(f"Error guardando niveles para {simbolo}: {e}")
    
    def _obtener_todos_los_timeframes(self, simbolo: str) -> Dict[str, List]:
        """
        Obtiene todos los niveles de todos los timeframes.
        
        Args:
            simbolo: Símbolo
        
        Returns:
            Diccionario con 'soportes' y 'resistencias'
        """
        if not self.almacen:
            return {'soportes': [], 'resistencias': []}
        
        try:
            return self.almacen.obtener_niveles(simbolo) or {'soportes': [], 'resistencias': []}
        except Exception:
            return {'soportes': [], 'resistencias': []}
    
    def _buscar_nivel(self,
                      simbolo: str,
                      precio: float,
                      tipo: str,
                      timeframe: str = 'H1') -> Optional[Dict]:
        """
        Busca un nivel en el historial.
        
        Args:
            simbolo: Símbolo
            precio: Precio del nivel
            tipo: 'soporte' o 'resistencia'
            timeframe: Timeframe
        
        Returns:
            Datos del nivel o None
        """
        niveles = self._cargar_niveles_desde_almacen(simbolo, timeframe)
        lista = niveles.get(f'{tipo}s', [])
        config = self.CONFIG_POR_TIMEFRAME.get(timeframe, self.CONFIG_POR_TIMEFRAME['H1'])
        distancia = config.get('distancia_agrupacion', 0.002)
        
        for nivel in lista:
            if abs(nivel.get('precio', 0) - precio) / max(precio, 0.0001) < distancia:
                return nivel
        
        return None
    
    def _invalidar_cache(self, simbolo: str, timeframe: Optional[str] = None):
        """
        Invalida la caché para un símbolo.
        
        Args:
            simbolo: Símbolo
            timeframe: Timeframe (None = todos)
        """
        keys_to_remove = []
        for key in self._cache_niveles.keys():
            if key.startswith(simbolo):
                if timeframe is None or key.endswith(timeframe):
                    keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self._cache_niveles[key]
            if key in self._cache_timestamp:
                del self._cache_timestamp[key]
    
    # ============================================================
    # MANTENIMIENTO
    # ============================================================
    
    def limpiar_niveles_antiguos(self,
                                 dias: Optional[int] = None,
                                 timeframe: Optional[str] = None):
        """
        Limpia niveles antiguos de todos los símbolos.
        
        Args:
            dias: Días de antigüedad máxima
            timeframe: Timeframe específico (None = todos)
        """
        if dias is None:
            dias = self.CONFIG_POR_TIMEFRAME.get(
                timeframe or 'H1', {}
            ).get('dias_antiguedad_max', 10)
        
        fecha_limite = datetime.now(timezone.utc) - timedelta(days=dias)
        
        if not self.almacen:
            return
        
        try:
            simbolos = self._obtener_todos_simbolos()
            if not simbolos:
                return
            
            limpiados = 0
            
            for simbolo in simbolos:
                niveles = self._obtener_todos_los_timeframes(simbolo)
                cambios = False
                
                for tipo in ['soportes', 'resistencias']:
                    lista = niveles.get(tipo, [])
                    lista_filtrada = []
                    
                    for nivel in lista:
                        # Filtrar por timeframe
                        if timeframe is not None and nivel.get('timeframe', 'H1') != timeframe:
                            lista_filtrada.append(nivel)
                            continue
                        
                        try:
                            ultima_fecha_str = nivel.get('ultima_fecha')
                            if ultima_fecha_str:
                                ultima_fecha = datetime.fromisoformat(ultima_fecha_str)
                                if ultima_fecha.tzinfo is None:
                                    ultima_fecha = ultima_fecha.replace(tzinfo=timezone.utc)
                                
                                if ultima_fecha > fecha_limite:
                                    lista_filtrada.append(nivel)
                                else:
                                    cambios = True
                                    limpiados += 1
                            else:
                                lista_filtrada.append(nivel)
                        except Exception:
                            lista_filtrada.append(nivel)
                    
                    niveles[tipo] = lista_filtrada
                
                if cambios:
                    self.almacen.guardar_niveles(
                        simbolo,
                        niveles.get('soportes', []),
                        niveles.get('resistencias', [])
                    )
                    self._invalidar_cache(simbolo)
            
            if limpiados > 0:
                self.logger.info(f"🧹 {limpiados} niveles antiguos limpiados")
            
        except Exception as e:
            self.logger.error(f"Error limpiando niveles antiguos: {e}")
    
    def _obtener_todos_simbolos(self) -> List[str]:
        """Obtiene todos los símbolos con niveles guardados."""
        if not self.almacen:
            return []
        
        try:
            if hasattr(self.almacen, 'obtener_todos_simbolos'):
                return self.almacen.obtener_todos_simbolos()
            return []
        except Exception:
            return []
    
    # ============================================================
    # ESTADÍSTICAS
    # ============================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del tracker."""
        total_niveles = 0
        for cache in self._cache_niveles.values():
            total_niveles += len(cache.get('soportes', [])) + len(cache.get('resistencias', []))
        
        return {
            'timeframe_default': self.timeframe_default,
            'cache_size': len(self._cache_niveles),
            'total_niveles_cached': total_niveles,
            'config_timeframes': len(self.CONFIG_POR_TIMEFRAME),
            'modo_backtest': self.modo_backtest,
        }
    
    def print_stats(self):
        """Imprime estadísticas en formato legible."""
        stats = self.get_stats()
        self.logger.info("📊 ESTADÍSTICAS DE NIVELTRACKER")
        self.logger.info(f"   Timeframe principal: {stats['timeframe_default']}")
        self.logger.info(f"   Caché size: {stats['cache_size']}")
        self.logger.info(f"   Total niveles en caché: {stats['total_niveles_cached']}")
        self.logger.info(f"   Timeframes configurados: {stats['config_timeframes']}")


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_nivel_tracker(almacen: Optional[Any] = None,
                         config: Optional[Any] = None,
                         detector: Optional[DetectorNiveles] = None,
                         modo_backtest: bool = False,
                         timeframe_default: str = 'H1') -> NivelTracker:
    """
    Crea una instancia de NivelTracker.
    
    Args:
        almacen: Almacenamiento SQLite
        config: Configuración
        detector: Detector de niveles (opcional)
        modo_backtest: Modo backtest
        timeframe_default: Timeframe por defecto
    
    Returns:
        NivelTracker
    """
    return NivelTracker(
        almacen=almacen,
        config=config,
        detector=detector,
        modo_backtest=modo_backtest,
        timeframe_default=timeframe_default
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Prueba rápida con datos mock
    import pandas as pd
    import numpy as np
    
    # Crear datos mock
    np.random.seed(42)
    n = 200
    dates = pd.date_range('2024-01-01', periods=n, freq='H')
    df = pd.DataFrame({
        'Open': np.random.randn(n) * 10 + 100,
        'High': np.random.randn(n) * 10 + 102,
        'Low': np.random.randn(n) * 10 + 98,
        'Close': np.random.randn(n) * 10 + 100,
        'Volume': np.random.randint(100, 1000, n)
    }, index=dates)
    df['Close'] = df['Close'].cumsum() / 10 + 100
    df['High'] = df['Close'] + np.abs(np.random.randn(n) * 2)
    df['Low'] = df['Close'] - np.abs(np.random.randn(n) * 2)
    df['Open'] = df['Close'] + np.random.randn(n) * 0.5
    
    # Crear tracker sin almacenamiento
    tracker = NivelTracker(modo_backtest=True)
    
    # Detectar niveles
    resultado = tracker.detectar_y_actualizar_niveles(
        simbolo='EURUSD',
        df=df,
        precio_actual=df['Close'].iloc[-1],
        timeframe='H1'
    )
    
    print(f"Soportes: {len(resultado.get('soportes', []))}")
    for s in resultado.get('soportes', [])[:3]:
        print(f"  Soporte: {s.get('precio', 0):.2f} (hits: {s.get('hits', 0)})")
    
    print(f"Resistencias: {len(resultado.get('resistencias', []))}")
    for r in resultado.get('resistencias', [])[:3]:
        print(f"  Resistencia: {r.get('precio', 0):.2f} (hits: {r.get('hits', 0)})")
    
    # Probar nivel más cercano
    nivel = tracker.obtener_nivel_mas_cercano(
        simbolo='EURUSD',
        precio_actual=df['Close'].iloc[-1],
        max_distancia=5.0
    )
    if nivel:
        print(f"Nivel más cercano: {nivel.get('tipo')} a {nivel.get('precio', 0):.2f}")
    
    print("\n✅ Prueba completada")