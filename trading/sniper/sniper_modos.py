#!/usr/bin/env python3
"""
trading/sniper/sniper_modos.py (V9.0)
Detección de modos de entrada para el sniper.
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

logger = logging.getLogger('BotTrading.SniperModos')


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


class DetectorModos:
    """
    Detector de modos de entrada.
    V9.0 - INDEPENDIENTE.
    """
    
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
    
    def __init__(self, config: Optional[Any] = None, modo_backtest: bool = False):
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.SniperModos')
    
    def detectar(self,
                 simbolo: str,
                 df_m5: Any,
                 precio_actual: float,
                 direccion: str,
                 analisis_rapido: Any,
                 analisis_medio: Any,
                 analisis_pesado: Any,
                 contexto_h1: Dict,
                 contexto_m15: Optional[Dict] = None) -> Tuple[ModoEntrada, str, List[str], float]:
        """
        Detecta el mejor modo de entrada.
        
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
            contexto_m15=contexto_m15
        )
        
        if not candidatos:
            # Fallback: usar dirección H1
            if score_h1 > 50 and direccion != 'NEUTRAL':
                return ModoEntrada.RETEST_FALLBACK, "Fallback por dirección H1", ["Dirección H1 definida"], 0.5
            
            return ModoEntrada.DESCONOCIDO, "No se detectó modo válido", [], 0.0
        
        # Ordenar por prioridad según régimen
        orden = self.ORDEN_MODOS.get(regimen, self.ORDEN_DEFECTO)
        
        for modo in orden:
            if modo in candidatos:
                razon, confluencias, puntuacion = candidatos[modo]
                ponderacion = max(0.3, min(1.5, puntuacion / 35))
                return modo, razon, confluencias, ponderacion
        
        return ModoEntrada.DESCONOCIDO, "No se encontró modo en orden", [], 0.0
    
    def _evaluar_candidatos(self, **kwargs) -> Dict[ModoEntrada, Tuple[str, List[str], float]]:
        """Evalúa todos los modos candidatos."""
        candidatos = {}
        
        # Evaluar cada modo
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
    
    def _evaluar_retest(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo RETEST."""
        analisis_medio = kwargs.get('analisis_medio')
        direccion = kwargs.get('direccion')
        precio_actual = kwargs.get('precio_actual')
        
        if not analisis_medio:
            return None
        
        soporte = analisis_medio.soporte_cercano
        resistencia = analisis_medio.resistencia_cercana
        
        nivel_valido = False
        razon = ""
        
        if direccion == 'COMPRA' and soporte:
            distancia = (precio_actual - soporte) / precio_actual * 100
            if distancia < 2.0:
                nivel_valido = True
                razon = f"Soporte a {distancia:.2f}%"
        elif direccion == 'VENTA' and resistencia:
            distancia = (resistencia - precio_actual) / precio_actual * 100
            if distancia < 2.0:
                nivel_valido = True
                razon = f"Resistencia a {distancia:.2f}%"
        
        if not nivel_valido:
            return None
        
        hits = analisis_medio.soporte_hits if direccion == 'COMPRA' else analisis_medio.resistencia_hits
        puntuacion = 40 + min(10, hits * 3)
        
        return ModoEntrada.RETEST, f"RETEST: {razon}", [razon], puntuacion
    
    def _evaluar_nivel_fuerte(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo NIVEL_FUERTE."""
        analisis_medio = kwargs.get('analisis_medio')
        direccion = kwargs.get('direccion')
        precio_actual = kwargs.get('precio_actual')
        
        if not analisis_medio:
            return None
        
        soporte = analisis_medio.soporte_cercano
        resistencia = analisis_medio.resistencia_cercana
        
        if direccion == 'COMPRA' and soporte:
            distancia = (precio_actual - soporte) / precio_actual * 100
            if distancia < 1.0:
                hits = analisis_medio.soporte_hits
                puntuacion = 45 + hits * 2
                return ModoEntrada.NIVEL_FUERTE, f"Nivel fuerte a {distancia:.2f}%", [f"Soporte {hits}hits"], puntuacion
        
        elif direccion == 'VENTA' and resistencia:
            distancia = (resistencia - precio_actual) / precio_actual * 100
            if distancia < 1.0:
                hits = analisis_medio.resistencia_hits
                puntuacion = 45 + hits * 2
                return ModoEntrada.NIVEL_FUERTE, f"Nivel fuerte a {distancia:.2f}%", [f"Resistencia {hits}hits"], puntuacion
        
        return None
    
    def _evaluar_breakout(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo BREAKOUT."""
        df_m5 = kwargs.get('df_m5')
        direccion = kwargs.get('direccion')
        analisis_rapido = kwargs.get('analisis_rapido')
        
        if df_m5 is None or len(df_m5) < 5:
            return None
        
        if direccion == 'COMPRA':
            max_anterior = df_m5['High'].iloc[-5:-1].max()
            if df_m5['Close'].iloc[-1] > max_anterior * 1.0005:
                vol_min = 0.25
                if analisis_rapido and analisis_rapido.volumen_relativo >= vol_min:
                    puntuacion = 45 + min(10, analisis_rapido.volumen_relativo * 2)
                    return ModoEntrada.BREAKOUT, "Breakout alcista", ["Volumen confirmado"], puntuacion
        
        elif direccion == 'VENTA':
            min_anterior = df_m5['Low'].iloc[-5:-1].min()
            if df_m5['Close'].iloc[-1] < min_anterior * 0.9995:
                vol_min = 0.25
                if analisis_rapido and analisis_rapido.volumen_relativo >= vol_min:
                    puntuacion = 45 + min(10, analisis_rapido.volumen_relativo * 2)
                    return ModoEntrada.BREAKOUT, "Breakout bajista", ["Volumen confirmado"], puntuacion
        
        return None
    
    def _evaluar_pullback(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo PULLBACK."""
        df_m5 = kwargs.get('df_m5')
        direccion = kwargs.get('direccion')
        
        if df_m5 is None or len(df_m5) < 10:
            return None
        
        ema9 = df_m5['Close'].ewm(span=9, adjust=False).mean()
        ema21 = df_m5['Close'].ewm(span=21, adjust=False).mean()
        
        if direccion == 'COMPRA':
            if ema9.iloc[-1] > ema21.iloc[-1] and df_m5['Close'].iloc[-1] < ema9.iloc[-3]:
                fib = self._calcular_fib(df_m5, 'COMPRA')
                if fib and 0.10 <= fib <= 0.90:
                    puntuacion = 40 + (1 - abs(fib - 0.5) * 2) * 10
                    return ModoEntrada.PULLBACK, f"Pullback Fib {fib:.1%}", [f"Fib {fib:.1%}"], puntuacion
        
        elif direccion == 'VENTA':
            if ema9.iloc[-1] < ema21.iloc[-1] and df_m5['Close'].iloc[-1] > ema9.iloc[-3]:
                fib = self._calcular_fib(df_m5, 'VENTA')
                if fib and 0.10 <= fib <= 0.90:
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
    
    def _evaluar_patron(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo PATRON."""
        analisis_pesado = kwargs.get('analisis_pesado')
        
        if not analisis_pesado:
            return None
        
        if analisis_pesado.calidad_patron >= 10:
            patron = analisis_pesado.patron_principal
            if patron and patron != 'N/A':
                puntuacion = 35 + analisis_pesado.calidad_patron * 0.15
                return ModoEntrada.PATRON, f"Patrón {patron}", [patron], puntuacion
        
        return None
    
    def _evaluar_vela_borde(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo VELA_BORDE."""
        df_m5 = kwargs.get('df_m5')
        direccion = kwargs.get('direccion')
        analisis_medio = kwargs.get('analisis_medio')
        
        if df_m5 is None or len(df_m5) < 2:
            return None
        
        vela = df_m5.iloc[-1]
        rango = vela['High'] - vela['Low']
        
        if rango == 0:
            return None
        
        if direccion == 'COMPRA':
            sombra_inf = min(vela['Open'], vela['Close']) - vela['Low']
            if sombra_inf / rango > 0.3:
                puntuacion = 25
                if analisis_medio and analisis_medio.en_nivel_clave:
                    puntuacion += 10
                return ModoEntrada.VELA_BORDE, "Vela en borde de soporte", ["Vela borde"], puntuacion
        
        else:
            sombra_sup = vela['High'] - max(vela['Open'], vela['Close'])
            if sombra_sup / rango > 0.3:
                puntuacion = 25
                if analisis_medio and analisis_medio.en_nivel_clave:
                    puntuacion += 10
                return ModoEntrada.VELA_BORDE, "Vela en borde de resistencia", ["Vela borde"], puntuacion
        
        return None
    
    def _evaluar_ruptura_falsa(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo RUPTURA_FALSA."""
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
        """Evalúa modo SNIPER_ELITE."""
        analisis_pesado = kwargs.get('analisis_pesado')
        analisis_medio = kwargs.get('analisis_medio')
        contexto_h1 = kwargs.get('contexto_h1')
        direccion = kwargs.get('direccion')
        
        if not analisis_pesado:
            return None
        
        confluencias = []
        puntuacion = 30
        
        # Nivel clave
        if analisis_medio and analisis_medio.en_nivel_clave:
            confluencias.append("Nivel clave")
            puntuacion += 15
        
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
        
        if len(confluencias) >= 2 and puntuacion >= 40:
            return ModoEntrada.SNIPER_ELITE, f"Élite con {len(confluencias)} confluencias", confluencias, puntuacion
        
        return None
    
    def _evaluar_fallback(self, **kwargs) -> Optional[Tuple[ModoEntrada, str, List[str], float]]:
        """Evalúa modo RETEST_FALLBACK."""
        contexto_h1 = kwargs.get('contexto_h1')
        direccion = kwargs.get('direccion')
        
        if not contexto_h1:
            return None
        
        score_h1 = contexto_h1.get('score', 0)
        
        if score_h1 > 55 and direccion != 'NEUTRAL':
            puntuacion = 20 + (score_h1 - 55) * 0.2
            return ModoEntrada.RETEST_FALLBACK, f"Fallback (score: {score_h1:.0f})", [f"Score {score_h1:.0f}"], puntuacion
        
        return None