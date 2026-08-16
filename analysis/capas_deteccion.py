#!/usr/bin/env python3
"""
analysis/capas_deteccion.py (V9.0)
Detección local de niveles de soporte/resistencia (fallback).
"""

import logging
import pandas as pd
from typing import Dict, List, Any

logger = logging.getLogger('BotTrading.CapasDeteccion')


class DetectorNivelesLocal:
    """
    Detector local de niveles (fallback cuando NivelTracker no está disponible).
    V9.0 - INDEPENDIENTE.
    """
    
    def __init__(self, umbrales: Dict[str, float]):
        """
        Inicializa el detector local.
        
        Args:
            umbrales: Diccionario con umbrales
        """
        self.umbrales = umbrales
        self.logger = logging.getLogger('BotTrading.CapasDeteccion')
    
    def detectar(self, df: pd.DataFrame, simbolo: str) -> Dict[str, List[Dict]]:
        """
        Detecta niveles localmente.
        
        Args:
            df: DataFrame con datos
            simbolo: Símbolo
        
        Returns:
            Diccionario con soportes y resistencias
        """
        if df is None or len(df) < 50:
            return {'soportes': [], 'resistencias': []}
        
        try:
            high = df['High']
            low = df['Low']
            close = df['Close']
            precio_actual = close.iloc[-1]
            
            # Parámetros
            ventana = 10
            distancia_minima = 0.002
            max_niveles = 10
            
            soportes = []
            resistencias = []
            
            # Detectar mínimos locales (soportes)
            for i in range(ventana, len(df) - ventana, 3):
                if low.iloc[i] == low.iloc[i-ventana:i+ventana].min():
                    precio = low.iloc[i]
                    if self._nivel_existe(soportes, precio, distancia_minima):
                        continue
                    
                    hits = self._contar_hits(df, precio, 'soporte')
                    soportes.append({
                        'precio': precio,
                        'hits': hits,
                        'fuerza': min(100, 20 + hits * 10),
                        'tipo': 'soporte',
                        'timeframe': 'H1'
                    })
            
            # Detectar máximos locales (resistencias)
            for i in range(ventana, len(df) - ventana, 3):
                if high.iloc[i] == high.iloc[i-ventana:i+ventana].max():
                    precio = high.iloc[i]
                    if self._nivel_existe(resistencias, precio, distancia_minima):
                        continue
                    
                    hits = self._contar_hits(df, precio, 'resistencia')
                    resistencias.append({
                        'precio': precio,
                        'hits': hits,
                        'fuerza': min(100, 20 + hits * 10),
                        'tipo': 'resistencia',
                        'timeframe': 'H1'
                    })
            
            # Ordenar y limitar
            soportes.sort(key=lambda x: x['hits'], reverse=True)
            resistencias.sort(key=lambda x: x['hits'], reverse=True)
            
            return {
                'soportes': soportes[:max_niveles],
                'resistencias': resistencias[:max_niveles]
            }
            
        except Exception as e:
            self.logger.warning(f"Error detectando niveles para {simbolo}: {e}")
            return {'soportes': [], 'resistencias': []}
    
    def _nivel_existe(self, niveles: List[Dict], precio: float, distancia: float) -> bool:
        """Verifica si un nivel ya existe en la lista."""
        for n in niveles:
            if abs(n['precio'] - precio) / max(precio, 0.0001) < distancia:
                return True
        return False
    
    def _contar_hits(self, df: pd.DataFrame, precio: float, tipo: str) -> int:
        """Cuenta hits de un nivel."""
        try:
            hits = 0
            lookback = 100
            tolerancia = 0.002
            
            for i in range(max(0, len(df) - lookback), len(df) - 1):
                if tipo == 'soporte':
                    if abs(df['Low'].iloc[i] - precio) / max(precio, 0.0001) < tolerancia:
                        if df['Close'].iloc[i] > precio:
                            hits += 1
                else:
                    if abs(df['High'].iloc[i] - precio) / max(precio, 0.0001) < tolerancia:
                        if df['Close'].iloc[i] < precio:
                            hits += 1
            
            return min(hits, 20)
        except Exception:
            return 1