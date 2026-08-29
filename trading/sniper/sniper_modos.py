#!/usr/bin/env python3
"""
trading/sniper/sniper_modos.py (V9.1 - REFACTORIZADO COMPLETAMENTE)
Detección de modos de entrada para el sniper.
RESPONSABILIDAD: ÚNICO LUGAR para la lógica de detección de modos.
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

logger = logging.getLogger('BotTrading.SniperModos')


# ============================================================
# ENUMS
# ============================================================

class ModoEntrada(Enum):
    """Modos de entrada del sniper."""
    RETEST = "RETEST"
    BREAKOUT = "BREAKOUT"
    PULLBACK = "PULLBACK"
    NIVEL_FUERTE = "NIVEL_FUERTE"
    PATRON = "PATRON"
    RUPTURA_FALSA = "RUPTURA_FALSA"
    VELA_BORDE = "VELA_BORDE"
    RETEST_FALLBACK = "RETEST_FALLBACK"
    SNIPER_ELITE = "SNIPER_ELITE"
    DESCONOCIDO = "DESCONOCIDO"


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class DetectorModos:
    """
    Detector de modos de entrada - ALGORITMO PURO.
    V9.1 - REFACTORIZADO: Sin dependencias externas.
    """
    
    # Umbrales por modo (configurables)
    UMBRALES = {
        'RETEST': {'distancia_max': 2.0, 'hits_min': 1},
        'NIVEL_FUERTE': {'distancia_max': 1.0, 'hits_min': 2},  # CORREGIDO: hits_min = 2
        'BREAKOUT': {'volumen_min': 0.6, 'confirmacion_velas': 1},
        'PULLBACK': {'fib_min': 0.10, 'fib_max': 0.90},
        'PATRON': {'calidad_min': 20},
        'VELA_BORDE': {'sombra_min': 0.3},
        'RUPTURA_FALSA': {'confirmacion_velas': 2},
        'SNIPER_ELITE': {'confluencias_min': 2, 'puntuacion_min': 40},
        'RETEST_FALLBACK': {'score_h1_min': 55},
    }
    
    # Orden de modos por régimen
    ORDEN_MODOS = {
        'TREND_ALCISTA_FUERTE': [
            ModoEntrada.PULLBACK,
            ModoEntrada.BREAKOUT,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.PATRON,
        ],
        'TREND_BAJISTA_FUERTE': [
            ModoEntrada.PULLBACK,
            ModoEntrada.BREAKOUT,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.PATRON,
        ],
        'TREND_ALCISTA_DEBIL': [
            ModoEntrada.PULLBACK,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.PATRON,
            ModoEntrada.BREAKOUT,
        ],
        'TREND_BAJISTA_DEBIL': [
            ModoEntrada.PULLBACK,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.PATRON,
            ModoEntrada.BREAKOUT,
        ],
        'RANGO_AMPLIO': [
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.VELA_BORDE,
            ModoEntrada.RUPTURA_FALSA,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.PATRON,
        ],
        'RANGO_APRETADO': [
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.RETEST,
            ModoEntrada.SNIPER_ELITE,
        ],
        'BREAKOUT_INMINENTE': [
            ModoEntrada.BREAKOUT,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.RUPTURA_FALSA,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
        ],
        'CHOP_VOLATIL': [
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.RETEST_FALLBACK,
            ModoEntrada.RETEST,
        ],
        'INCERTO': [
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.RETEST_FALLBACK,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
        ],
    }
    
    ORDEN_DEFECTO = [
        ModoEntrada.RETEST,
        ModoEntrada.SNIPER_ELITE,
        ModoEntrada.NIVEL_FUERTE,
        ModoEntrada.BREAKOUT,
        ModoEntrada.PULLBACK,
        ModoEntrada.PATRON,
        ModoEntrada.RUPTURA_FALSA,
        ModoEntrada.VELA_BORDE,
        ModoEntrada.RETEST_FALLBACK,
    ]
    
    def __init__(self, modo_backtest: bool = False):
        """
        Inicializa el detector de modos.
        
        Args:
            modo_backtest: Modo backtest (umbrales más permisivos)
        """
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.SniperModos')
        
        # Ajustar umbrales para backtest
        if modo_backtest:
            for modo in self.UMBRALES:
                if 'distancia_max' in self.UMBRALES[modo]:
                    self.UMBRALES[modo]['distancia_max'] *= 2.0
                if 'hits_min' in self.UMBRALES[modo]:
                    self.UMBRALES[modo]['hits_min'] = max(1, self.UMBRALES[modo]['hits_min'] - 1)
                if 'volumen_min' in self.UMBRALES[modo]:
                    self.UMBRALES[modo]['volumen_min'] *= 0.3
                if 'calidad_min' in self.UMBRALES[modo]:
                    self.UMBRALES[modo]['calidad_min'] *= 0.5
                if 'score_h1_min' in self.UMBRALES[modo]:
                    self.UMBRALES[modo]['score_h1_min'] = max(30, self.UMBRALES[modo]['score_h1_min'] - 15)
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def detectar(self,
                 simbolo: str,
                 df_m5: Any,
                 precio_actual: float,
                 direccion: str,
                 analisis_rapido: Any,
                 analisis_medio: Any,
                 analisis_pesado: Any,
                 contexto_h1: Dict) -> Tuple[ModoEntrada, str, List[str], float]:
        """
        Detecta el mejor modo de entrada.
        
        Args:
            simbolo: Símbolo
            df_m5: DataFrame M5
            precio_actual: Precio actual
            direccion: Dirección ('COMPRA' o 'VENTA')
            analisis_rapido: Resultado del análisis rápido
            analisis_medio: Resultado del análisis medio
            analisis_pesado: Resultado del análisis pesado
            contexto_h1: Contexto H1 (score, régimen, niveles, etc.)
        
        Returns:
            (modo, razon, confluencias, ponderacion)
        """
        regimen = contexto_h1.get('regimen', 'INCERTO')
        score_h1 = contexto_h1.get('score', 0)
        en_nivel_clave = contexto_h1.get('en_nivel_clave', False)
        
        candidatos = self._evaluar_candidatos(
            simbolo=simbolo,
            df_m5=df_m5,
            precio_actual=precio_actual,
            direccion=direccion,
            analisis_rapido=analisis_rapido,
            analisis_medio=analisis_medio,
            analisis_pesado=analisis_pesado,
            contexto_h1=contexto_h1,
            score_h1=score_h1,
            en_nivel_clave=en_nivel_clave
        )
        
        if not candidatos:
            # Fallback: usar dirección H1 si el score es suficiente
            if score_h1 > self.UMBRALES['RETEST_FALLBACK']['score_h1_min'] and direccion != 'NEUTRAL':
                return ModoEntrada.RETEST_FALLBACK, f"Fallback (score: {score_h1:.0f})", ["Dirección H1"], 0.5
            return ModoEntrada.DESCONOCIDO, "No se detectó modo válido", [], 0.0
        
        orden = self.ORDEN_MODOS.get(regimen, self.ORDEN_DEFECTO)
        
        for modo in orden:
            if modo in candidatos:
                razon, confluencias, puntuacion = candidatos[modo]
                ponderacion = max(0.3, min(1.5, puntuacion / 35))
                return modo, razon, confluencias, ponderacion
        
        return ModoEntrada.DESCONOCIDO, "No se encontró modo en orden", [], 0.0
    
    # ============================================================
    # EVALUACIÓN DE CANDIDATOS
    # ============================================================
    
    def _evaluar_candidatos(self, **kwargs) -> Dict[ModoEntrada, Tuple[str, List[str], float]]:
        """Evalúa todos los modos candidatos."""
        candidatos = {}
        
        evaluadores = [
            self._evaluar_retest,
            self._evaluar_nivel_fuerte,
            self._evaluar_breakout,
            self._evaluar_pullback,
            self._evaluar_patron,
            self._evaluar_vela_borde,
            self._evaluar_ruptura_falsa,
            self._evaluar_sniper_elite,
            self._evaluar_fallback,
        ]
        
        for evaluador in evaluadores:
            resultado = evaluador(**kwargs)
            if resultado:
                modo, razon, confluencias, puntuacion = resultado
                candidatos[modo] = (razon, confluencias, puntuacion)
        
        return candidatos
    
    # ============================================================
    # EVALUADORES POR MODO
    # ============================================================
    
    def _evaluar_retest(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo RETEST - Requiere nivel clave cercano."""
        analisis_medio = kwargs.get('analisis_medio')
        direccion = kwargs.get('direccion')
        precio_actual = kwargs.get('precio_actual')
        umbrales = self.UMBRALES['RETEST']
        
        if not analisis_medio:
            return None
        
        soporte = analisis_medio.soporte_cercano
        resistencia = analisis_medio.resistencia_cercana
        
        if direccion == 'COMPRA' and soporte:
            distancia = (precio_actual - soporte) / precio_actual * 100
            if distancia < umbrales['distancia_max']:
                hits = analisis_medio.soporte_hits
                puntuacion = 40 + min(10, hits * 3)
                return ModoEntrada.RETEST, f"Soporte a {distancia:.2f}%", [f"Soporte {hits}hits"], puntuacion
        
        elif direccion == 'VENTA' and resistencia:
            distancia = (resistencia - precio_actual) / precio_actual * 100
            if distancia < umbrales['distancia_max']:
                hits = analisis_medio.resistencia_hits
                puntuacion = 40 + min(10, hits * 3)
                return ModoEntrada.RETEST, f"Resistencia a {distancia:.2f}%", [f"Resistencia {hits}hits"], puntuacion
        
        return None
    
    def _evaluar_nivel_fuerte(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo NIVEL_FUERTE - Requiere nivel con hits >= 2."""
        analisis_medio = kwargs.get('analisis_medio')
        direccion = kwargs.get('direccion')
        precio_actual = kwargs.get('precio_actual')
        umbrales = self.UMBRALES['NIVEL_FUERTE']
        
        if not analisis_medio:
            return None
        
        soporte = analisis_medio.soporte_cercano
        resistencia = analisis_medio.resistencia_cercana
        
        if direccion == 'COMPRA' and soporte:
            distancia = (precio_actual - soporte) / precio_actual * 100
            hits = analisis_medio.soporte_hits
            if distancia < umbrales['distancia_max'] and hits >= umbrales['hits_min']:
                puntuacion = 45 + hits * 2
                return ModoEntrada.NIVEL_FUERTE, f"Nivel fuerte {hits}hits", [f"Soporte {hits}hits"], puntuacion
        
        elif direccion == 'VENTA' and resistencia:
            distancia = (resistencia - precio_actual) / precio_actual * 100
            hits = analisis_medio.resistencia_hits
            if distancia < umbrales['distancia_max'] and hits >= umbrales['hits_min']:
                puntuacion = 45 + hits * 2
                return ModoEntrada.NIVEL_FUERTE, f"Nivel fuerte {hits}hits", [f"Resistencia {hits}hits"], puntuacion
        
        return None
    
    def _evaluar_breakout(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo BREAKOUT - Requiere volumen y confirmación."""
        df_m5 = kwargs.get('df_m5')
        direccion = kwargs.get('direccion')
        analisis_rapido = kwargs.get('analisis_rapido')
        umbrales = self.UMBRALES['BREAKOUT']
        
        if df_m5 is None or len(df_m5) < 5:
            return None
        
        if direccion == 'COMPRA':
            max_anterior = df_m5['High'].iloc[-5:-1].max()
            if df_m5['Close'].iloc[-1] > max_anterior * 1.0005:
                vol_min = umbrales['volumen_min']
                if analisis_rapido and analisis_rapido.volumen_relativo >= vol_min:
                    puntuacion = 45 + min(10, analisis_rapido.volumen_relativo * 2)
                    return ModoEntrada.BREAKOUT, "Breakout alcista", ["Volumen confirmado"], puntuacion
        
        elif direccion == 'VENTA':
            min_anterior = df_m5['Low'].iloc[-5:-1].min()
            if df_m5['Close'].iloc[-1] < min_anterior * 0.9995:
                vol_min = umbrales['volumen_min']
                if analisis_rapido and analisis_rapido.volumen_relativo >= vol_min:
                    puntuacion = 45 + min(10, analisis_rapido.volumen_relativo * 2)
                    return ModoEntrada.BREAKOUT, "Breakout bajista", ["Volumen confirmado"], puntuacion
        
        return None
    
    def _evaluar_pullback(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo PULLBACK - Requiere pullback a Fibonacci."""
        df_m5 = kwargs.get('df_m5')
        direccion = kwargs.get('direccion')
        umbrales = self.UMBRALES['PULLBACK']
        
        if df_m5 is None or len(df_m5) < 10:
            return None
        
        ema9 = df_m5['Close'].ewm(span=9, adjust=False).mean()
        ema21 = df_m5['Close'].ewm(span=21, adjust=False).mean()
        
        if direccion == 'COMPRA':
            if ema9.iloc[-1] > ema21.iloc[-1] and df_m5['Close'].iloc[-1] < ema9.iloc[-3]:
                fib = self._calcular_fib(df_m5, 'COMPRA')
                if fib and umbrales['fib_min'] <= fib <= umbrales['fib_max']:
                    puntuacion = 40 + (1 - abs(fib - 0.5) * 2) * 10
                    return ModoEntrada.PULLBACK, f"Pullback Fib {fib:.1%}", [f"Fib {fib:.1%}"], puntuacion
        
        elif direccion == 'VENTA':
            if ema9.iloc[-1] < ema21.iloc[-1] and df_m5['Close'].iloc[-1] > ema9.iloc[-3]:
                fib = self._calcular_fib(df_m5, 'VENTA')
                if fib and umbrales['fib_min'] <= fib <= umbrales['fib_max']:
                    puntuacion = 40 + (1 - abs(fib - 0.5) * 2) * 10
                    return ModoEntrada.PULLBACK, f"Pullback Fib {fib:.1%}", [f"Fib {fib:.1%}"], puntuacion
        
        return None
    
    def _calcular_fib(self, df_m5: Any, direccion: str) -> Optional[float]:
        """Calcula nivel de Fibonacci para pullback."""
        if len(df_m5) < 10:
            return None
        
        max_precio = df_m5['High'].iloc[-10:].max()
        min_precio = df_m5['Low'].iloc[-10:].min()
        rango = max_precio - min_precio
        
        if rango <= 0:
            return None
        
        precio_actual = df_m5['Close'].iloc[-1]
        
        if direccion == 'COMPRA':
            return (max_precio - precio_actual) / rango
        else:
            return (precio_actual - min_precio) / rango

    def _clasificar_confluencias(self, contexto: Dict) -> Dict[str, List[str]]:
        """
        Clasifica las confluencias por categorías independientes.
        """
        categorias = {
            'TENDENCIA': [],
            'ESTRUCTURA': [],
            'MOMENTUM': [],
            'PRECIO_VELA': [],
            'CONTEXTO': [],
        }
        
        # Ejemplo: Si hay EMA9 > EMA21 y ADX > 20, solo cuenta una vez en TENDENCIA
        if contexto.get('ema9') > contexto.get('ema21'):
            categorias['TENDENCIA'].append('EMA alcista')
        
        if contexto.get('adx', 0) > 20:
            categorias['TENDENCIA'].append('ADX > 20')  # Ya está en TENDENCIA
        
        # Estructura
        if contexto.get('en_nivel_clave'):
            categorias['ESTRUCTURA'].append('Nivel clave')
        
        # Momentum
        if contexto.get('rsi', 50) > 60:
            categorias['MOMENTUM'].append('RSI > 60')
        
        # Precio/Vela
        if contexto.get('patron_calidad', 0) > 30:
            categorias['PRECIO_VELA'].append(f'Patrón {contexto["patron"]}')
        
        # Contexto
        if contexto.get('volumen_relativo', 0) > 1.2:
            categorias['CONTEXTO'].append('Volumen alto')
        
        return categorias

    def _evaluar_modo(self, modo: str, contexto: Dict) -> float:
        """
        Evalúa un modo y devuelve una puntuación basada en:
        - Calidad del setup base
        - Confirmaciones
        - Conflictos
        """
        # Puntuación base por modo (según jerarquía)
        puntuacion_base = {
            'PULLBACK': 70,
            'RETEST': 65,
            'BREAKOUT': 60,
            'SNIPER_ELITE': 50,  # Se construye con confirmaciones
            'NIVEL_FUERTE': 50,
            'RUPTURA_FALSA': 40,
            'PATRON': 0,  # Confirmador
            'VELA_BORDE': 0,  # Confirmador
            'RETEST_FALLBACK': 0,  # Desactivado
        }.get(modo, 0)
        
        # Bonos por confirmaciones (cada confirmación suma +5 a +10)
        confirmaciones = contexto.get('confirmaciones', [])
        puntuacion_confirmaciones = len(confirmaciones) * 5
        
        # Penalización por conflictos (cada conflicto resta -5 a -10)
        conflictos = contexto.get('conflictos', [])
        puntuacion_conflictos = len(conflictos) * -5
        
        # Puntuación final
        puntuacion_final = puntuacion_base + puntuacion_confirmaciones + puntuacion_conflictos
        
        return max(0, puntuacion_final)
        
    def _evaluar_patron(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo PATRON - Requiere patrón de calidad."""
        analisis_pesado = kwargs.get('analisis_pesado')
        umbrales = self.UMBRALES['PATRON']
        
        if not analisis_pesado:
            return None
        
        if analisis_pesado.calidad_patron >= umbrales['calidad_min']:
            patron = analisis_pesado.patron_principal
            if patron and patron != 'N/A':
                puntuacion = 35 + analisis_pesado.calidad_patron * 0.15
                return ModoEntrada.PATRON, f"Patrón {patron}", [patron], puntuacion
        
        return None
    
    def _evaluar_vela_borde(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo VELA_BORDE - Requiere sombra larga en nivel."""
        df_m5 = kwargs.get('df_m5')
        direccion = kwargs.get('direccion')
        analisis_medio = kwargs.get('analisis_medio')
        umbrales = self.UMBRALES['VELA_BORDE']
        
        if df_m5 is None or len(df_m5) < 2:
            return None
        
        vela = df_m5.iloc[-1]
        rango = vela['High'] - vela['Low']
        
        if rango == 0:
            return None
        
        if direccion == 'COMPRA':
            sombra_inf = min(vela['Open'], vela['Close']) - vela['Low']
            if sombra_inf / rango > umbrales['sombra_min']:
                puntuacion = 25
                if analisis_medio and analisis_medio.en_nivel_clave:
                    puntuacion += 10
                return ModoEntrada.VELA_BORDE, "Vela en borde de soporte", ["Vela borde"], puntuacion
        
        else:
            sombra_sup = vela['High'] - max(vela['Open'], vela['Close'])
            if sombra_sup / rango > umbrales['sombra_min']:
                puntuacion = 25
                if analisis_medio and analisis_medio.en_nivel_clave:
                    puntuacion += 10
                return ModoEntrada.VELA_BORDE, "Vela en borde de resistencia", ["Vela borde"], puntuacion
        
        return None
    
    def _evaluar_ruptura_falsa(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo RUPTURA_FALSA - Requiere falsa ruptura."""
        df_m5 = kwargs.get('df_m5')
        direccion = kwargs.get('direccion')
        
        if df_m5 is None or len(df_m5) < 5:
            return None
        
        if direccion == 'COMPRA':
            max_anterior = df_m5['High'].iloc[-5:-1].max()
            if df_m5['High'].iloc[-1] > max_anterior * 1.0005:
                if df_m5['Close'].iloc[-1] < max_anterior:
                    return ModoEntrada.RUPTURA_FALSA, "Falsa ruptura alcista", ["Falsa ruptura"], 25
        
        elif direccion == 'VENTA':
            min_anterior = df_m5['Low'].iloc[-5:-1].min()
            if df_m5['Low'].iloc[-1] < min_anterior * 0.9995:
                if df_m5['Close'].iloc[-1] > min_anterior:
                    return ModoEntrada.RUPTURA_FALSA, "Falsa ruptura bajista", ["Falsa ruptura"], 25
        
        return None
    
    def _evaluar_sniper_elite(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo SNIPER_ELITE - Requiere múltiples confluencias."""
        analisis_pesado = kwargs.get('analisis_pesado')
        analisis_medio = kwargs.get('analisis_medio')
        contexto_h1 = kwargs.get('contexto_h1')
        score_h1 = kwargs.get('score_h1')
        en_nivel_clave = kwargs.get('en_nivel_clave')
        umbrales = self.UMBRALES['SNIPER_ELITE']
        
        if not analisis_pesado:
            return None
        
        confluencias = []
        puntuacion = 30
        
        # Nivel clave
        if en_nivel_clave:
            confluencias.append("Nivel clave")
            puntuacion += 15
        
        # Score H1 alto
        if score_h1 >= 70:
            confluencias.append("Score H1 alto")
            puntuacion += 10
        
        # Patrón de calidad
        if analisis_pesado.calidad_patron > 20:
            confluencias.append(f"Patrón {analisis_pesado.patron_principal}")
            puntuacion += 10
        
        # Wyckoff
        if analisis_pesado.wyckoff_confianza > 30:
            confluencias.append(f"Wyckoff {analisis_pesado.wyckoff_fase}")
            puntuacion += 10
        
        # Order Block
        if analisis_pesado.ob_cercano:
            confluencias.append("Order Block")
            puntuacion += 5
        
        # Divergencia
        if analisis_pesado.divergencia_rsi:
            confluencias.append("Divergencia RSI")
            puntuacion += 10
        
        if len(confluencias) >= umbrales['confluencias_min'] and puntuacion >= umbrales['puntuacion_min']:
            return ModoEntrada.SNIPER_ELITE, f"Élite con {len(confluencias)} confluencias", confluencias, puntuacion
        
        return None
    
    def _evaluar_fallback(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo RETEST_FALLBACK - Último recurso."""
        contexto_h1 = kwargs.get('contexto_h1')
        score_h1 = kwargs.get('score_h1')
        direccion = kwargs.get('direccion')
        umbrales = self.UMBRALES['RETEST_FALLBACK']
        
        if not contexto_h1:
            return None
        
        if score_h1 > umbrales['score_h1_min'] and direccion != 'NEUTRAL':
            puntuacion = 20 + (score_h1 - umbrales['score_h1_min']) * 0.2
            return ModoEntrada.RETEST_FALLBACK, f"Fallback (score: {score_h1:.0f})", [f"Score {score_h1:.0f}"], puntuacion
        
        return None
    
    # ============================================================
    # UTILIDADES
    # ============================================================
    
    def get_orden_modos(self, regimen: str) -> List[str]:
        """Obtiene la lista de modos en orden de prioridad para un régimen."""
        modos = self.ORDEN_MODOS.get(regimen, self.ORDEN_DEFECTO)
        return [m.value for m in modos]
    
    def set_modo_backtest(self, modo: bool = True):
        """Activa/desactiva modo backtest."""
        self.modo_backtest = modo
        # Reajustar umbrales
        for modo in self.UMBRALES:
            if 'distancia_max' in self.UMBRALES[modo]:
                self.UMBRALES[modo]['distancia_max'] *= 2.0 if modo else 0.5
            if 'hits_min' in self.UMBRALES[modo]:
                self.UMBRALES[modo]['hits_min'] = max(1, self.UMBRALES[modo]['hits_min'] - 1) if modo else self.UMBRALES[modo]['hits_min'] + 1
            if 'volumen_min' in self.UMBRALES[modo]:
                self.UMBRALES[modo]['volumen_min'] *= 0.3 if modo else 3.33
            if 'calidad_min' in self.UMBRALES[modo]:
                self.UMBRALES[modo]['calidad_min'] *= 0.5 if modo else 2.0
            if 'score_h1_min' in self.UMBRALES[modo]:
                self.UMBRALES[modo]['score_h1_min'] = max(30, self.UMBRALES[modo]['score_h1_min'] - 15) if modo else self.UMBRALES[modo]['score_h1_min'] + 15
        self.logger.info(f"🔧 DetectorModos: modo backtest {'ACTIVADO' if modo else 'DESACTIVADO'}")