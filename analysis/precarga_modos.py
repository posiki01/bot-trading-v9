#!/usr/bin/env python3
"""
core/precarga_modos.py (V1.0)
Sistema de precarga de datos para activar todos los modos desde el día 1.

ESTRATEGIA:
1. Usar datos históricos extendidos (60-90 días) para acumular hits
2. Identificar patrones en el periodo de precarga
3. Detectar rupturas y tendencias
4. Simular confluencias para SNIPER_ELITE
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from collections import defaultdict

logger = logging.getLogger('BotTrading.PrecargaModos')


class PrecargaModos:
    """
    Precarga datos históricos para activar todos los modos desde el día 1.
    """
    
    # Umbrales mínimos para precarga
    UMBRALES_PRECARGA = {
        'nivel_hits_min': 2,
        'patron_calidad_min': 30,
        'breakout_volumen_min': 0.8,
        'pullback_fib_min': 0.236,
        'pullback_fib_max': 0.786,
        'elite_score_min': 40,
        'elite_confluencias_min': 2,
    }
    
    def __init__(self, config=None, analysis_cache=None, analisis_capas=None):
        self.config = config
        self.analysis_cache = analysis_cache
        self.analisis_capas = analisis_capas
        
        # Almacenamiento de datos precargados
        self.niveles_precargados: Dict[str, Dict] = {}
        self.patrones_precargados: Dict[str, List] = {}
        self.rupturas_precargadas: Dict[str, List] = {}
        self.tendencias_precargadas: Dict[str, Dict] = {}
        self.confluencias_precargadas: Dict[str, List] = {}
        self.pullback_puntos_precargados: Dict[str, List] = {}
        
        self._stats = {
            'simbolos_procesados': 0,
            'niveles_detectados': 0,
            'patrones_detectados': 0,
            'rupturas_detectadas': 0,
            'confluencias_detectadas': 0,
            'pullback_puntos': 0,
        }
        
        logger.info("📦 PrecargaModos V1.0 inicializado")
    
    # ================================================================
    # MÉTODO PRINCIPAL: PRECARGAR TODOS LOS DATOS
    # ================================================================
    
    def precargar_para_backtest(self, dataframes: Dict[str, Dict[str, pd.DataFrame]], 
                                dias_precarga: int = 60) -> Dict[str, Any]:
        """
        Precarga todos los datos necesarios para activar los modos.
        """
        logger.info(f"📦 INICIANDO PRECARGA DE {dias_precarga} DÍAS...")
        
        for simbolo, dfs in dataframes.items():
            logger.info(f"   📊 Procesando {simbolo}...")
            
            # Obtener dataframes
            df_h1 = dfs.get('H1')
            df_h4 = dfs.get('H4')
            df_d1 = dfs.get('D1')
            df_m5 = dfs.get('M5')
            df_m15 = dfs.get('M15')
            
            if df_h1 is None or len(df_h1) < 100:
                logger.warning(f"   ⚠️ {simbolo}: Datos insuficientes para precarga")
                continue
            
            # ============================================================
            # 1. PRECARGAR NIVELES CON HITS
            # ============================================================
            niveles = self._precargar_niveles(simbolo, df_h1, df_m5)
            if niveles:
                self.niveles_precargados[simbolo] = niveles
                self._stats['niveles_detectados'] += len(niveles.get('soportes', [])) + len(niveles.get('resistencias', []))
            
            # ============================================================
            # 2. PRECARGAR PATRONES
            # ============================================================
            patrones = self._precargar_patrones(simbolo, df_m5)
            if patrones:
                self.patrones_precargados[simbolo] = patrones
                self._stats['patrones_detectados'] += len(patrones)
            
            # ============================================================
            # 3. PRECARGAR RUPTURAS
            # ============================================================
            rupturas = self._precargar_rupturas(simbolo, df_m5)
            if rupturas:
                self.rupturas_precargadas[simbolo] = rupturas
                self._stats['rupturas_detectadas'] += len(rupturas)
            
            # ============================================================
            # 4. PRECARGAR TENDENCIAS Y PULLBACKS
            # ============================================================
            tendencias, pullbacks = self._precargar_tendencias_y_pullbacks(simbolo, df_h1, df_h4, df_d1)
            if tendencias:
                self.tendencias_precargadas[simbolo] = tendencias
            if pullbacks:
                self.pullback_puntos_precargados[simbolo] = pullbacks
                self._stats['pullback_puntos'] += len(pullbacks)
            
            # ============================================================
            # 5. PRECARGAR CONFLUENCIAS
            # ============================================================
            confluencias = self._precargar_confluencias(simbolo, df_h1, df_m5, df_m15)
            if confluencias:
                self.confluencias_precargadas[simbolo] = confluencias
                self._stats['confluencias_detectadas'] += len(confluencias)
            
            self._stats['simbolos_procesados'] += 1
        
        logger.info(f"✅ PRECARGA COMPLETADA:")
        logger.info(f"   Símbolos procesados: {self._stats['simbolos_procesados']}")
        logger.info(f"   Niveles detectados: {self._stats['niveles_detectados']}")
        logger.info(f"   Patrones detectados: {self._stats['patrones_detectados']}")
        logger.info(f"   Rupturas detectadas: {self._stats['rupturas_detectadas']}")
        logger.info(f"   Pullback puntos: {self._stats['pullback_puntos']}")
        logger.info(f"   Confluencias detectadas: {self._stats['confluencias_detectadas']}")
        
        return {
            'niveles': self.niveles_precargados,
            'patrones': self.patrones_precargados,
            'rupturas': self.rupturas_precargadas,
            'tendencias': self.tendencias_precargadas,
            'pullbacks': self.pullback_puntos_precargados,
            'confluencias': self.confluencias_precargadas,
            'stats': self._stats
        }
    
    # ================================================================
    # 1. PRECARGA DE NIVELES
    # ================================================================
    
    def _precargar_niveles(self, simbolo: str, df_h1: pd.DataFrame, 
                           df_m5: pd.DataFrame) -> Dict[str, List]:
        """Precarga niveles con hits acumulados."""
        if df_h1 is None or len(df_h1) < 50:
            return {'soportes': [], 'resistencias': []}
        
        soportes = []
        resistencias = []
        
        # Usar mínimos y máximos de ventanas deslizantes
        window = 20
        for i in range(window, len(df_h1) - window):
            # Soporte (mínimo local)
            if df_h1['Low'].iloc[i] == df_h1['Low'].iloc[i-window:i+window].min():
                precio = df_h1['Low'].iloc[i]
                existente = next((s for s in soportes if abs(s['precio'] - precio) / max(precio, 0.0001) < 0.001), None)
                if existente:
                    existente['hits'] += 1
                else:
                    soportes.append({'precio': precio, 'hits': 1, 'tipo': 'soporte'})
            
            # Resistencia (máximo local)
            if df_h1['High'].iloc[i] == df_h1['High'].iloc[i-window:i+window].max():
                precio = df_h1['High'].iloc[i]
                existente = next((r for r in resistencias if abs(r['precio'] - precio) / max(precio, 0.0001) < 0.001), None)
                if existente:
                    existente['hits'] += 1
                else:
                    resistencias.append({'precio': precio, 'hits': 1, 'tipo': 'resistencia'})
        
        # Filtrar niveles con suficientes hits
        soportes_filtrados = [s for s in soportes if s['hits'] >= 2]
        resistencias_filtradas = [r for r in resistencias if r['hits'] >= 2]
        
        # Ordenar por hits (los más fuertes primero)
        soportes_filtrados.sort(key=lambda x: x['hits'], reverse=True)
        resistencias_filtradas.sort(key=lambda x: x['hits'], reverse=True)
        
        logger.debug(f"   📊 {simbolo}: {len(soportes_filtrados)} soportes, {len(resistencias_filtradas)} resistencias precargados")
        
        return {
            'soportes': soportes_filtrados[:10],  # Limitar a los 10 mejores
            'resistencias': resistencias_filtradas[:10]
        }
    
    # ================================================================
    # 2. PRECARGA DE PATRONES
    # ================================================================
    
    def _precargar_patrones(self, simbolo: str, df_m5: pd.DataFrame) -> List[Dict]:
        """Precarga patrones chartistas de alta calidad."""
        if df_m5 is None or len(df_m5) < 100:
            return []
        
        patrones_encontrados = []
        
        # Buscar patrones en ventanas deslizantes
        for i in range(50, len(df_m5) - 10, 5):  # Muestrear cada 5 velas para eficiencia
            ventana = df_m5.iloc[i-50:i+10]
            patrones = self._detectar_patrones_en_ventana(ventana)
            
            for patron in patrones:
                if patron['calidad'] >= 30:
                    patron['timestamp'] = ventana.index[-1]
                    patron['simbolo'] = simbolo
                    patrones_encontrados.append(patron)
        
        # Limitar a los mejores por tipo
        patrones_por_tipo = {}
        for p in patrones_encontrados:
            tipo = p['nombre']
            if tipo not in patrones_por_tipo or p['calidad'] > patrones_por_tipo[tipo]['calidad']:
                patrones_por_tipo[tipo] = p
        
        resultado = list(patrones_por_tipo.values())
        logger.debug(f"   📊 {simbolo}: {len(resultado)} patrones precargados")
        
        return resultado[:5]  # Limitar a 5 patrones
    
    def _detectar_patrones_en_ventana(self, df: pd.DataFrame) -> List[Dict]:
        """Detecta patrones en una ventana de datos."""
        patrones = []
        
        if len(df) < 5:
            return patrones
        
        try:
            vela = df.iloc[-1]
            rango = vela['High'] - vela['Low']
            
            if rango > 0:
                sombra_sup = vela['High'] - max(vela['Open'], vela['Close'])
                sombra_inf = min(vela['Open'], vela['Close']) - vela['Low']
                cuerpo = abs(vela['Close'] - vela['Open'])
                
                # Pin Bar Alcista
                if sombra_inf / rango > 0.6 and cuerpo / rango < 0.3:
                    patrones.append({
                        'nombre': 'PIN_BAR_ALCISTA',
                        'calidad': 70 + min(30, (sombra_inf / rango) * 100),
                        'direccion': 'COMPRA',
                        'precio': vela['Close']
                    })
                
                # Pin Bar Bajista
                if sombra_sup / rango > 0.6 and cuerpo / rango < 0.3:
                    patrones.append({
                        'nombre': 'PIN_BAR_BAJISTA',
                        'calidad': 70 + min(30, (sombra_sup / rango) * 100),
                        'direccion': 'VENTA',
                        'precio': vela['Close']
                    })
            
            # Engulfing
            if len(df) > 1:
                vela_actual = df.iloc[-1]
                vela_anterior = df.iloc[-2]
                
                if (vela_actual['Close'] > vela_anterior['Open'] and 
                    vela_actual['Open'] < vela_anterior['Close'] and
                    vela_anterior['Close'] < vela_anterior['Open']):
                    patrones.append({
                        'nombre': 'ENGULFING_ALCISTA',
                        'calidad': 75,
                        'direccion': 'COMPRA',
                        'precio': vela_actual['Close']
                    })
                
                if (vela_actual['Close'] < vela_anterior['Open'] and 
                    vela_actual['Open'] > vela_anterior['Close'] and
                    vela_anterior['Close'] > vela_anterior['Open']):
                    patrones.append({
                        'nombre': 'ENGULFING_BAJISTA',
                        'calidad': 75,
                        'direccion': 'VENTA',
                        'precio': vela_actual['Close']
                    })
            
            # Doji
            if cuerpo / rango < 0.1 and rango > 0:
                patrones.append({
                    'nombre': 'DOJI',
                    'calidad': 60,
                    'direccion': 'NEUTRAL',
                    'precio': vela['Close']
                })
                
        except Exception:
            pass
        
        return patrones
    
    # ================================================================
    # 3. PRECARGA DE RUPTURAS
    # ================================================================
    
    def _precargar_rupturas(self, simbolo: str, df_m5: pd.DataFrame) -> List[Dict]:
        """Precarga rupturas históricas."""
        if df_m5 is None or len(df_m5) < 100:
            return []
        
        rupturas = []
        vol_promedio = df_m5['Volume'].rolling(50).mean()
        
        for i in range(50, len(df_m5) - 5, 5):  # Muestrear cada 5 velas
            ventana = df_m5.iloc[i-50:i]
            precio_actual = df_m5['Close'].iloc[i]
            volumen_actual = df_m5['Volume'].iloc[i]
            vol_rel = volumen_actual / vol_promedio.iloc[i] if vol_promedio.iloc[i] > 0 else 0
            
            if vol_rel > 0.8:
                max_anterior = ventana['High'].max()
                if precio_actual > max_anterior * 1.0005:
                    rupturas.append({
                        'tipo': 'ALCISTA',
                        'precio': precio_actual,
                        'volumen': vol_rel,
                        'nivel': max_anterior,
                        'timestamp': df_m5.index[i],
                        'fuerza': min(100, vol_rel * 50)
                    })
                
                min_anterior = ventana['Low'].min()
                if precio_actual < min_anterior * 0.9995:
                    rupturas.append({
                        'tipo': 'BAJISTA',
                        'precio': precio_actual,
                        'volumen': vol_rel,
                        'nivel': min_anterior,
                        'timestamp': df_m5.index[i],
                        'fuerza': min(100, vol_rel * 50)
                    })
        
        rupturas.sort(key=lambda x: x['fuerza'], reverse=True)
        logger.debug(f"   📊 {simbolo}: {len(rupturas)} rupturas precargadas")
        
        return rupturas[:5]  # Limitar a 5 rupturas
    
    # ================================================================
    # 4. PRECARGA DE TENDENCIAS Y PULLBACKS
    # ================================================================
    
    def _precargar_tendencias_y_pullbacks(self, simbolo: str, df_h1: pd.DataFrame, 
                                          df_h4: pd.DataFrame, df_d1: pd.DataFrame) -> Tuple[Dict, List]:
        """Precarga tendencias y puntos de pullback."""
        if df_h1 is None or len(df_h1) < 100:
            return {'tendencia': 'LATERAL', 'fuerza': 0}, []
        
        # Detectar tendencia con EMAs
        ema20 = df_h1['Close'].ewm(span=20, adjust=False).mean()
        ema50 = df_h1['Close'].ewm(span=50, adjust=False).mean()
        ema200 = df_h1['Close'].ewm(span=200, adjust=False).mean() if len(df_h1) >= 200 else None
        
        if ema20.iloc[-1] > ema50.iloc[-1] and (ema200 is None or ema50.iloc[-1] > ema200.iloc[-1]):
            tendencia = 'ALCISTA'
            fuerza = min(100, (ema20.iloc[-1] / ema50.iloc[-1] - 1) * 1000)
        elif ema20.iloc[-1] < ema50.iloc[-1] and (ema200 is None or ema50.iloc[-1] < ema200.iloc[-1]):
            tendencia = 'BAJISTA'
            fuerza = min(100, (ema50.iloc[-1] / ema20.iloc[-1] - 1) * 1000)
        else:
            tendencia = 'LATERAL'
            fuerza = 0
        
        # Encontrar puntos de pullback
        puntos_pullback = []
        for i in range(50, len(df_h1) - 10):
            if tendencia == 'ALCISTA':
                if df_h1['Close'].iloc[i] < ema20.iloc[i] * 0.99:
                    max_prev = df_h1['High'].iloc[i-50:i].max()
                    min_prev = df_h1['Low'].iloc[i-50:i].min()
                    fib = (max_prev - df_h1['Close'].iloc[i]) / (max_prev - min_prev) if (max_prev - min_prev) > 0 else 0.5
                    if 0.236 <= fib <= 0.786:
                        puntos_pullback.append({
                            'precio': df_h1['Close'].iloc[i],
                            'fib': fib,
                            'timestamp': df_h1.index[i]
                        })
            elif tendencia == 'BAJISTA':
                if df_h1['Close'].iloc[i] > ema20.iloc[i] * 1.01:
                    max_prev = df_h1['High'].iloc[i-50:i].max()
                    min_prev = df_h1['Low'].iloc[i-50:i].min()
                    fib = (df_h1['Close'].iloc[i] - min_prev) / (max_prev - min_prev) if (max_prev - min_prev) > 0 else 0.5
                    if 0.236 <= fib <= 0.786:
                        puntos_pullback.append({
                            'precio': df_h1['Close'].iloc[i],
                            'fib': fib,
                            'timestamp': df_h1.index[i]
                        })
        
        # Mantener los mejores puntos de pullback
        puntos_pullback = puntos_pullback[-5:]
        
        logger.debug(f"   📊 {simbolo}: Tendencia {tendencia} (fuerza {fuerza:.1f}) - {len(puntos_pullback)} puntos")
        
        return {
            'tendencia': tendencia,
            'fuerza': fuerza
        }, puntos_pullback
    
    # ================================================================
    # 5. PRECARGA DE CONFLUENCIAS
    # ================================================================
    
    def _precargar_confluencias(self, simbolo: str, df_h1: pd.DataFrame, 
                               df_m5: pd.DataFrame, df_m15: pd.DataFrame) -> List[Dict]:
        """Precarga confluencias para SNIPER_ELITE."""
        if df_h1 is None or len(df_h1) < 100:
            return []
        
        confluencias = []
        niveles = self.niveles_precargados.get(simbolo, {'soportes': [], 'resistencias': []})
        patrones = self.patrones_precargados.get(simbolo, [])
        rupturas = self.rupturas_precargadas.get(simbolo, [])
        pullbacks = self.pullback_puntos_precargados.get(simbolo, [])
        
        for i in range(50, len(df_h1) - 10, 5):  # Muestrear cada 5 velas
            precio_actual = df_h1['Close'].iloc[i]
            confluencia_actual = []
            score = 0
            
            # 1. Nivel clave
            for s in niveles.get('soportes', []):
                if abs(s['precio'] - precio_actual) / max(precio_actual, 0.0001) < 0.005:
                    confluencia_actual.append(f'NIVEL_SOPORTE_{s["hits"]}hits')
                    score += 20 + s['hits'] * 2
                    break
            
            for r in niveles.get('resistencias', []):
                if abs(r['precio'] - precio_actual) / max(precio_actual, 0.0001) < 0.005:
                    confluencia_actual.append(f'NIVEL_RESISTENCIA_{r["hits"]}hits')
                    score += 20 + r['hits'] * 2
                    break
            
            # 2. Patrón
            for p in patrones:
                if abs(p['precio'] - precio_actual) / max(precio_actual, 0.0001) < 0.003:
                    confluencia_actual.append(f'PATRON_{p["nombre"]}')
                    score += p['calidad'] / 2
                    break
            
            # 3. Ruptura
            for r in rupturas:
                if abs(r['precio'] - precio_actual) / max(precio_actual, 0.0001) < 0.003:
                    confluencia_actual.append('RUPTURA')
                    score += r['fuerza'] / 2
                    break
            
            # 4. Pullback
            for p in pullbacks:
                if abs(p['precio'] - precio_actual) / max(precio_actual, 0.0001) < 0.005:
                    confluencia_actual.append(f'PULLBACK_FIB_{p["fib"]:.1%}')
                    score += 30
                    break
            
            # Si hay al menos 2 confluencias y score >= 40, guardar
            if len(confluencia_actual) >= 2 and score >= 40:
                confluencias.append({
                    'precio': precio_actual,
                    'timestamp': df_h1.index[i],
                    'confluencias': confluencia_actual,
                    'score': score,
                    'simbolo': simbolo
                })
        
        confluencias.sort(key=lambda x: x['score'], reverse=True)
        logger.debug(f"   📊 {simbolo}: {len(confluencias)} confluencias precargadas")
        
        return confluencias[:5]  # Limitar a 5 confluencias
    
    # ================================================================
    # MÉTODOS DE ACCESO PARA EL SNIPER
    # ================================================================
    
    def obtener_niveles_precargados(self, simbolo: str) -> Dict:
        """Obtiene niveles precargados para un símbolo."""
        return self.niveles_precargados.get(simbolo, {'soportes': [], 'resistencias': []})
    
    def obtener_patron_precargado(self, simbolo: str) -> Optional[Dict]:
        """Obtiene el mejor patrón precargado para un símbolo."""
        patrones = self.patrones_precargados.get(simbolo, [])
        return patrones[0] if patrones else None
    
    def obtener_ruptura_precargada(self, simbolo: str) -> Optional[Dict]:
        """Obtiene la mejor ruptura precargada para un símbolo."""
        rupturas = self.rupturas_precargadas.get(simbolo, [])
        return rupturas[0] if rupturas else None
    
    def obtener_tendencia_precargada(self, simbolo: str) -> Dict:
        """Obtiene tendencia precargada para un símbolo."""
        return self.tendencias_precargadas.get(simbolo, {'tendencia': 'LATERAL', 'fuerza': 0})
    
    def obtener_pullback_precargado(self, simbolo: str) -> Optional[Dict]:
        """Obtiene el mejor pullback precargado para un símbolo."""
        pullbacks = self.pullback_puntos_precargados.get(simbolo, [])
        return pullbacks[0] if pullbacks else None
    
    def obtener_confluencias_precargadas(self, simbolo: str) -> List[Dict]:
        """Obtiene confluencias precargadas para un símbolo."""
        return self.confluencias_precargadas.get(simbolo, [])
    
    def get_stats(self) -> Dict:
        """Obtiene estadísticas de la precarga."""
        return self._stats.copy()