#!/usr/bin/env python3
"""
analysis/niveles_deteccion.py (V9.1 - CORREGIDO)
Detección de niveles de soporte/resistencia.
RESPONSABILIDAD: Solo detectar niveles, no persistir.
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger('BotTrading.NivelesDeteccion')


class DetectorNiveles:
    """
    Detecta niveles de soporte/resistencia en datos de mercado.
    V9.1 - CORREGIDO: Inicialización de hits y paso de detección mejorados.
    """
    
    # Configuración por timeframe
    CONFIG_POR_TIMEFRAME = {
        'H1': {
            'ventana': 10,
            'lookback': 500,  # Aumentado para cubrir más historia
            'distancia_agrupacion': 0.002,
            'hits_minimos': 2,
            'max_niveles': 15,
        },
        'H4': {
            'ventana': 15,
            'lookback': 300,
            'distancia_agrupacion': 0.003,
            'hits_minimos': 2,
            'max_niveles': 10,
        },
        'D1': {
            'ventana': 20,
            'lookback': 200,
            'distancia_agrupacion': 0.005,
            'hits_minimos': 2,
            'max_niveles': 8,
        },
        'M15': {
            'ventana': 8,
            'lookback': 200,
            'distancia_agrupacion': 0.001,
            'hits_minimos': 1,
            'max_niveles': 5,
        },
        'M5': {
            'ventana': 6,
            'lookback': 150,
            'distancia_agrupacion': 0.001,
            'hits_minimos': 1,
            'max_niveles': 3,
        },
    }
    
    def __init__(self, config: Optional[Any] = None, modo_inicial: bool = False):
        """
        Inicializa el detector de niveles.
        
        Args:
            config: Configuración (opcional)
            modo_inicial: Modo inicial más permisivo
        """
        self.config = config
        self.modo_inicial = modo_inicial
        self.logger = logging.getLogger('BotTrading.NivelesDeteccion')
        
        # Cargar configuración personalizada
        self._cargar_configuracion()
    
    def _cargar_configuracion(self):
        """Carga configuración desde Config."""
        if self.config and hasattr(self.config, 'UMBRALES_DETECCION_NIVELES'):
            umbrales = getattr(self.config, 'UMBRALES_DETECCION_NIVELES', {})
            
            # Actualizar configuración por timeframe
            for tf in self.CONFIG_POR_TIMEFRAME:
                if tf in umbrales:
                    self.CONFIG_POR_TIMEFRAME[tf].update(umbrales[tf])
    
    # ============================================================
    # MÉTODOS PRINCIPALES DE DETECCIÓN
    # ============================================================
    
    def detectar_niveles(self, df: pd.DataFrame, simbolo: str, timeframe: str = 'H1') -> Dict[str, List[Dict]]:
        """
        Detecta niveles en un DataFrame.
        
        Args:
            df: DataFrame con High, Low, Close
            simbolo: Símbolo
            timeframe: Timeframe ('H1', 'H4', 'D1', 'M15', 'M5')
        
        Returns:
            Diccionario con 'soportes' y 'resistencias'
        """
        if df is None or len(df) < 30:
            return {'soportes': [], 'resistencias': []}
        
        # Obtener configuración para este timeframe
        config = self.CONFIG_POR_TIMEFRAME.get(timeframe, self.CONFIG_POR_TIMEFRAME['H1']).copy()
        
        # ✅ SI ESTAMOS EN MODO INICIAL, REDUCIR REQUISITOS
        if self.modo_inicial:
            config['hits_minimos'] = 1
            config['fuerza_minima'] = 10
            config['distancia_agrupacion'] = 0.005
        
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            precio_actual = close.iloc[-1]
            
            # Detectar niveles (CON PASO 1 PARA NO PERDER NINGUNO)
            soportes = self._detectar_soportes(df, config)
            resistencias = self._detectar_resistencias(df, config)
            
            # Contar hits
            soportes = self._contar_hits(df, soportes, 'soporte', config)
            resistencias = self._contar_hits(df, resistencias, 'resistencia', config)
            
            # Calcular fuerza
            soportes = self._calcular_fuerza(df, soportes, 'soporte', config)
            resistencias = self._calcular_fuerza(df, resistencias, 'resistencia', config)
            
            # Ordenar y limitar
            soportes.sort(key=lambda x: x.get('hits', 0), reverse=True)
            resistencias.sort(key=lambda x: x.get('hits', 0), reverse=True)
            
            soportes = soportes[:config['max_niveles']]
            resistencias = resistencias[:config['max_niveles']]
            
            # Añadir metadata
            for s in soportes:
                s['timeframe'] = timeframe
                s['ultima_fecha'] = datetime.now(timezone.utc).isoformat()
                s['simbolo'] = simbolo
            
            for r in resistencias:
                r['timeframe'] = timeframe
                r['ultima_fecha'] = datetime.now(timezone.utc).isoformat()
                r['simbolo'] = simbolo
            
            return {
                'soportes': soportes,
                'resistencias': resistencias,
            }
            
        except Exception as e:
            self.logger.error(f"Error detectando niveles para {simbolo} ({timeframe}): {e}")
            return {'soportes': [], 'resistencias': []}
    
    # ============================================================
    # DETECCIÓN DE SOPORTES (CORREGIDO)
    # ============================================================
    
    def _detectar_soportes(self, df: pd.DataFrame, config: Dict) -> List[Dict]:
        """
        Detecta niveles de soporte (mínimos locales).
        CORREGIDO: Paso 1, hits iniciales 1.
        """
        soportes = []
        low = df['Low']
        ventana = config['ventana']
        distancia_agrupacion = config['distancia_agrupacion']
        
        # CORREGIDO: step=1 para no perder niveles
        for i in range(ventana, len(df) - ventana, 1):
            if low.iloc[i] == low.iloc[i-ventana:i+ventana].min():
                precio = low.iloc[i]
                
                # Verificar si ya existe un soporte cercano
                if not self._nivel_existe(soportes, precio, distancia_agrupacion):
                    soportes.append({
                        'precio': precio,
                        'hits': 1,  # CORREGIDO: inicializar con 1
                        'fuerza': 10,
                        'idx': i,
                        'tipo': 'soporte'
                    })
        
        return soportes
    
    def _detectar_resistencias(self, df: pd.DataFrame, config: Dict) -> List[Dict]:
        """
        Detecta niveles de resistencia (máximos locales).
        CORREGIDO: Paso 1, hits iniciales 1.
        """
        resistencias = []
        high = df['High']
        ventana = config['ventana']
        distancia_agrupacion = config['distancia_agrupacion']
        
        # CORREGIDO: step=1 para no perder niveles
        for i in range(ventana, len(df) - ventana, 1):
            if high.iloc[i] == high.iloc[i-ventana:i+ventana].max():
                precio = high.iloc[i]
                
                if not self._nivel_existe(resistencias, precio, distancia_agrupacion):
                    resistencias.append({
                        'precio': precio,
                        'hits': 1,  # CORREGIDO: inicializar con 1
                        'fuerza': 10,
                        'idx': i,
                        'tipo': 'resistencia'
                    })
        
        return resistencias
    
    # ============================================================
    # CONTEO DE HITS (CORREGIDO)
    # ============================================================
    
    def _contar_hits(self, 
                     df: pd.DataFrame, 
                     niveles: List[Dict],
                     tipo: str,
                     config: Dict) -> List[Dict]:
        """
        Cuenta cuántas veces se ha probado un nivel.
        CORREGIDO: Lookback más amplio.
        """
        lookback = config['lookback']  # Ahora 500 en H1
        tolerancia = config['distancia_agrupacion']
        precio_actual = df['Close'].iloc[-1]
        
        for nivel in niveles:
            precio = nivel['precio']
            hits = nivel.get('hits', 1)  # Mantener el hit inicial
            
            # Contar hits en la ventana (desde el inicio del lookback hasta el final)
            for j in range(max(0, len(df) - lookback), len(df) - 1):
                if tipo == 'soporte':
                    if self._es_hit_soporte(df, j, precio, tolerancia):
                        hits += 1
                else:
                    if self._es_hit_resistencia(df, j, precio, tolerancia):
                        hits += 1
            
            # Ajustar por cercanía al precio actual (bonificar)
            if tipo == 'soporte' and precio < precio_actual:
                distancia = (precio_actual - precio) / precio_actual * 100
                if distancia < 0.5:
                    hits += 1
            elif tipo == 'resistencia' and precio > precio_actual:
                distancia = (precio - precio_actual) / precio_actual * 100
                if distancia < 0.5:
                    hits += 1
            
            nivel['hits'] = min(hits, 20)
        
        return niveles
    
    def _es_hit_soporte(self, df: pd.DataFrame, idx: int, precio: float, tolerancia: float) -> bool:
        """Verifica si es un hit de soporte."""
        if abs(df['Low'].iloc[idx] - precio) / max(precio, 0.0001) < tolerancia:
            return df['Close'].iloc[idx] > precio
        return False
    
    def _es_hit_resistencia(self, df: pd.DataFrame, idx: int, precio: float, tolerancia: float) -> bool:
        """Verifica si es un hit de resistencia."""
        if abs(df['High'].iloc[idx] - precio) / max(precio, 0.0001) < tolerancia:
            return df['Close'].iloc[idx] < precio
        return False
    
    # ============================================================
    # CÁLCULO DE FUERZA
    # ============================================================
    
    def _calcular_fuerza(self,
                         df: pd.DataFrame,
                         niveles: List[Dict],
                         tipo: str,
                         config: Dict) -> List[Dict]:
        """
        Calcula la fuerza de cada nivel (0-100).
        """
        for nivel in niveles:
            hits = nivel.get('hits', 0)
            precio = nivel['precio']
            fuerza = 10
            
            # 1. Fuerza por hits
            if hits >= 5:
                fuerza += 50
            elif hits >= 3:
                fuerza += 35
            elif hits >= 2:
                fuerza += 20
            
            # 2. Fuerza por antigüedad
            antiguedad = self._calcular_antiguedad(df, precio, tipo)
            if antiguedad > 70:
                fuerza += 20
            elif antiguedad > 40:
                fuerza += 10
            
            # 3. Fuerza por volumen en el nivel
            volumen_fuerza = self._calcular_volumen_en_nivel(df, precio, tipo)
            fuerza += volumen_fuerza
            
            # 4. Fuerza por cercanía a precio actual
            precio_actual = df['Close'].iloc[-1]
            if tipo == 'soporte' and precio < precio_actual:
                distancia = (precio_actual - precio) / precio_actual * 100
                if distancia < 0.3:
                    fuerza += 15
                elif distancia < 1.0:
                    fuerza += 10
            elif tipo == 'resistencia' and precio > precio_actual:
                distancia = (precio - precio_actual) / precio_actual * 100
                if distancia < 0.3:
                    fuerza += 15
                elif distancia < 1.0:
                    fuerza += 10
            
            nivel['fuerza'] = min(100, max(10, fuerza))
        
        return niveles
    
    def _calcular_antiguedad(self, df: pd.DataFrame, precio: float, tipo: str) -> int:
        """
        Calcula la antigüedad de un nivel (0-100).
        """
        try:
            if tipo == 'soporte':
                col = df['Low']
            else:
                col = df['High']
            
            # Buscar la última vez que se tocó el nivel
            for i in range(len(df) - 1, max(0, len(df) - 200), -1):
                if abs(col.iloc[i] - precio) / max(precio, 0.0001) < 0.002:
                    antiguedad = (len(df) - i) / len(df) * 100
                    return int(min(100, antiguedad))
            
            return 0
            
        except Exception:
            return 0
    
    def _calcular_volumen_en_nivel(self, df: pd.DataFrame, precio: float, tipo: str) -> int:
        """
        Calcula la fuerza por volumen en un nivel.
        """
        try:
            if 'Volume' not in df.columns:
                return 0
            
            vol_promedio = df['Volume'].rolling(50).mean()
            vol_en_nivel = 0
            
            for i in range(max(0, len(df) - 100), len(df)):
                if tipo == 'soporte':
                    if abs(df['Low'].iloc[i] - precio) / max(precio, 0.0001) < 0.002:
                        vol_en_nivel += df['Volume'].iloc[i]
                else:
                    if abs(df['High'].iloc[i] - precio) / max(precio, 0.0001) < 0.002:
                        vol_en_nivel += df['Volume'].iloc[i]
            
            vol_ratio = vol_en_nivel / vol_promedio.iloc[-1] if vol_promedio.iloc[-1] > 0 else 0
            
            if vol_ratio > 3:
                return 20
            elif vol_ratio > 2:
                return 15
            elif vol_ratio > 1:
                return 10
            
            return 0
            
        except Exception:
            return 0
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def _nivel_existe(self, niveles: List[Dict], precio: float, distancia: float) -> bool:
        """Verifica si un nivel ya existe en la lista."""
        for n in niveles:
            if abs(n['precio'] - precio) / max(precio, 0.0001) < distancia:
                return True
        return False
    
    def encontrar_nivel_cercano(self,
                                niveles: List[Dict],
                                precio_actual: float,
                                tipo: Optional[str] = None,
                                max_distancia: float = 3.0) -> Optional[Dict]:
        """
        Encuentra el nivel más cercano al precio actual.
        """
        mejor_nivel = None
        mejor_distancia = float('inf')
        
        for nivel in niveles:
            precio = nivel.get('precio', 0)
            if precio <= 0:
                continue
            
            if tipo and nivel.get('tipo') != tipo:
                continue
            
            if nivel.get('tipo') == 'soporte' and precio < precio_actual:
                distancia = (precio_actual - precio) / precio_actual * 100
            elif nivel.get('tipo') == 'resistencia' and precio > precio_actual:
                distancia = (precio - precio_actual) / precio_actual * 100
            else:
                continue
            
            if distancia < mejor_distancia and distancia <= max_distancia:
                mejor_distancia = distancia
                mejor_nivel = nivel
        
        return mejor_nivel
    
    def agrupar_niveles_cercanos(self, 
                                  niveles: List[Dict], 
                                  distancia: float) -> List[Dict]:
        """
        Agrupa niveles cercanos en uno solo.
        """
        if not niveles:
            return []
        
        agrupados = []
        ordenados = sorted(niveles, key=lambda x: x.get('precio', 0))
        
        for nivel in ordenados:
            precio = nivel.get('precio', 0)
            encontrado = False
            
            for grupo in agrupados:
                if abs(grupo['precio'] - precio) / max(precio, 0.0001) < distancia:
                    grupo['hits'] = grupo.get('hits', 0) + nivel.get('hits', 0)
                    grupo['fuerza'] = max(grupo.get('fuerza', 0), nivel.get('fuerza', 0))
                    grupo['veces_tocado'] = grupo.get('veces_tocado', 0) + 1
                    encontrado = True
                    break
            
            if not encontrado:
                agrupados.append(nivel.copy())
        
        return agrupados