#!/usr/bin/env python3
"""
analysis/regimen.py (V9.0 - REFACTORIZADO)
Clasificación de régimen de mercado con sistema de votación.

MEJORAS V9.0:
- Separación de cálculo de indicadores
- Sistema de votación ponderada
- Inyección de dependencias (config, indicadores)
- Caché de resultados
- Logs más informativos
- Métodos de compatibilidad para migración
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, List
import pandas as pd
import logging
import time

# Importar módulos internos
from analysis.regimen_indicadores import RegimenIndicadores

logger = logging.getLogger('BotTrading.Regimen')


class RegimenMercado(Enum):
    """Tipos de régimen de mercado."""
    TREND_ALCISTA_FUERTE = "TREND_ALCISTA_FUERTE"
    TREND_BAJISTA_FUERTE = "TREND_BAJISTA_FUERTE"
    TREND_ALCISTA_DEBIL = "TREND_ALCISTA_DEBIL"
    TREND_BAJISTA_DEBIL = "TREND_BAJISTA_DEBIL"
    RANGO_AMPLIO = "RANGO_AMPLIO"
    RANGO_APRETADO = "RANGO_APRETADO"
    CHOP_VOLATIL = "CHOP_VOLATIL"
    BREAKOUT_INMINENTE = "BREAKOUT_INMINENTE"
    INCERTO = "INCERTO"


@dataclass
class RegimenData:
    """Datos del régimen de mercado."""
    regimen: RegimenMercado
    confianza: float  # 0-100
    
    # Indicadores base
    adx_h4: float
    adx_h1: float
    er_kaufman: float
    bb_width_pct: float
    atr_pct: float
    estructura_swings: str
    direccion_favor: str
    
    # Indicadores avanzados
    ichimoku_tendencia: str = 'NEUTRAL'
    chop_index: float = 50.0
    vix_proxy: float = 0.0
    donchian_posicion: float = 0.5
    elder_fuerza: str = 'NEUTRAL'
    
    # Sistema de votación
    votos: Dict[str, str] = field(default_factory=dict)
    confianza_por_indicador: Dict[str, float] = field(default_factory=dict)
    votos_ponderados: Dict[str, float] = field(default_factory=dict)
    
    # Metadata
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para serialización."""
        return {
            'regimen': self.regimen.value,
            'confianza': self.confianza,
            'adx_h4': self.adx_h4,
            'adx_h1': self.adx_h1,
            'er_kaufman': self.er_kaufman,
            'bb_width_pct': self.bb_width_pct,
            'atr_pct': self.atr_pct,
            'estructura_swings': self.estructura_swings,
            'direccion_favor': self.direccion_favor,
            'ichimoku_tendencia': self.ichimoku_tendencia,
            'chop_index': self.chop_index,
            'vix_proxy': self.vix_proxy,
            'donchian_posicion': self.donchian_posicion,
            'elder_fuerza': self.elder_fuerza,
            'votos': self.votos,
            'confianza_por_indicador': self.confianza_por_indicador,
            'metadata': self.metadata,
        }


class MarketRegimeFilter:
    """
    Filtro de régimen de mercado con sistema de votación.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    # ============================================================
    # UMBRALES (CONFIGURABLES)
    # ============================================================
    
    ADX_TREND_FUERTE = 30
    ADX_TREND_DEBIL = 20
    ER_TREND = 0.3
    BB_APRETADO = 0.8
    BB_AMPLIO = 2.5
    CHOP_TENDENCIA = 38.2
    CHOP_RANGO = 61.8
    VIX_ALTO = 30
    VIX_MEDIO = 20
    
    # ============================================================
    # PESOS DE INDICADORES PARA VOTACIÓN
    # ============================================================
    
    PESOS_INDICADORES = {
        'adx': 0.20,
        'ichimoku': 0.15,
        'bb_width': 0.12,
        'chop_index': 0.10,
        'elder_ray': 0.10,
        'donchian': 0.08,
        'sar': 0.08,
        'estructura': 0.07,
        'vix_proxy': 0.05,
        'er_kaufman': 0.05,
    }
    
    def __init__(self, 
                 config: Optional[Any] = None,
                 indicadores: Optional[RegimenIndicadores] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el filtro de régimen.
        
        Args:
            config: Configuración (opcional)
            indicadores: Instancia de RegimenIndicadores (opcional)
            modo_backtest: Modo backtest
        """
        self.config = config
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.Regimen')
        
        # Usar indicadores proporcionados o crear nuevos
        self.indicadores = indicadores or RegimenIndicadores()
        
        # Cargar configuración desde config
        self._cargar_configuracion()
        
        # Caché de resultados
        self._cache: Dict[str, Tuple[RegimenData, float]] = {}
        self._cache_ttl = 60  # segundos
        
        self.logger.info(f"📊 MarketRegimeFilter V9.0 inicializado")
        self.logger.info(f"   Indicadores: {len(self.PESOS_INDICADORES)}")
        self.logger.info(f"   Backtest: {modo_backtest}")
    
    def _cargar_configuracion(self):
        """Carga configuración desde Config."""
        if self.config is None:
            return
        
        # Cargar umbrales si existen
        if hasattr(self.config, 'REGIMEN_ADX_FUERTE'):
            self.ADX_TREND_FUERTE = getattr(self.config, 'REGIMEN_ADX_FUERTE', 30)
        if hasattr(self.config, 'REGIMEN_ADX_DEBIL'):
            self.ADX_TREND_DEBIL = getattr(self.config, 'REGIMEN_ADX_DEBIL', 20)
        if hasattr(self.config, 'REGIMEN_ER_TREND'):
            self.ER_TREND = getattr(self.config, 'REGIMEN_ER_TREND', 0.3)
        if hasattr(self.config, 'REGIMEN_BB_APRETADO'):
            self.BB_APRETADO = getattr(self.config, 'REGIMEN_BB_APRETADO', 0.8)
        if hasattr(self.config, 'REGIMEN_BB_AMPLIO'):
            self.BB_AMPLIO = getattr(self.config, 'REGIMEN_BB_AMPLIO', 2.5)
        
        # Cargar pesos si existen
        if hasattr(self.config, 'REGIMEN_PESOS_INDICADORES'):
            self.PESOS_INDICADORES.update(getattr(self.config, 'REGIMEN_PESOS_INDICADORES', {}))
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def clasificar(self, simbolo: str, df_h4: pd.DataFrame, 
                   df_h1: pd.DataFrame, force: bool = False) -> RegimenData:
        """
        Clasifica el régimen de mercado.
        
        Args:
            simbolo: Símbolo
            df_h4: DataFrame H4
            df_h1: DataFrame H1
            force: Forzar recálculo
        
        Returns:
            RegimenData
        """
        # Verificar caché
        cache_key = f"{simbolo}_{id(df_h1)}_{id(df_h4)}"
        if not force and cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return data
        
        # 1. Calcular indicadores
        indicadores = self.indicadores.calcular_todos_indicadores(df_h4, df_h1)
        
        if not indicadores:
            logger.warning(f"⚠️ No se pudieron calcular indicadores para {simbolo}")
            return self._crear_regimen_incierto(0)
        
        # 2. Votación
        regimen, confianza, votos, confianzas, ponderados = self._votar(indicadores)
        
        # 3. Crear resultado
        resultado = RegimenData(
            regimen=RegimenMercado(regimen),
            confianza=confianza,
            adx_h4=indicadores.get('adx_h4', 0),
            adx_h1=indicadores.get('adx_h1', 0),
            er_kaufman=indicadores.get('er_kaufman', 0),
            bb_width_pct=indicadores.get('bb_width', 50),
            atr_pct=indicadores.get('atr_pct', 0.5),
            estructura_swings=indicadores.get('estructura', 'DESCONOCIDO'),
            direccion_favor=self._determinar_direccion_favor(indicadores),
            ichimoku_tendencia=indicadores.get('ichimoku', {}).get('tendencia', 'NEUTRAL'),
            chop_index=indicadores.get('chop_index', 50),
            vix_proxy=indicadores.get('vix_proxy', 0),
            donchian_posicion=indicadores.get('donchian', {}).get('posicion', 0.5),
            elder_fuerza=indicadores.get('elder_ray', {}).get('fuerza', 'NEUTRAL'),
            votos=votos,
            confianza_por_indicador=confianzas,
            votos_ponderados=ponderados,
            metadata={
                'simbolo': simbolo,
                'indicadores_activos': list(votos.keys()),
                'total_votos': len(votos),
            }
        )
        
        # Guardar en caché
        self._cache[cache_key] = (resultado, time.time())
        
        # Log (solo en debug)
        if self.modo_backtest:
            logger.debug(f"📊 {simbolo}: {resultado.regimen.value} (conf: {resultado.confianza:.1f}%)")
        
        return resultado
    
    # ============================================================
    # SISTEMA DE VOTACIÓN
    # ============================================================
    
    def _votar(self, indicadores: Dict[str, Any]) -> Tuple[str, float, Dict, Dict, Dict]:
        """
        Ejecuta el sistema de votación.
        
        Returns:
            (regimen_ganador, confianza, votos, confianzas_por_indicador, votos_ponderados)
        """
        contexto = {
            'estructura': indicadores.get('estructura', 'DESCONOCIDO'),
            'precio_actual': 1,
            'adx_h1': indicadores.get('adx_h1', 0),
            'bb_width': indicadores.get('bb_width', 50),
        }
        
        votos = {}
        confianzas = {}
        
        # Votar por cada indicador
        for nombre, valor in indicadores.items():
            if valor is not None and valor != 0 and valor != {}:
                regimen_votado, confianza = self._votar_por_indicador(nombre, valor, contexto)
                if regimen_votado:
                    votos[nombre] = regimen_votado
                    confianzas[nombre] = confianza
        
        # Calcular votos ponderados
        votos_ponderados = {}
        for indicador, regimen in votos.items():
            peso = self.PESOS_INDICADORES.get(indicador, 0.05)
            confianza = confianzas.get(indicador, 50)
            puntaje = peso * confianza
            
            if regimen not in votos_ponderados:
                votos_ponderados[regimen] = 0
            votos_ponderados[regimen] += puntaje
        
        # Régimen ganador
        if votos_ponderados:
            regimen_ganador = max(votos_ponderados, key=votos_ponderados.get)
            confianza_final = min(100, sum(votos_ponderados.values()) * 1.8)
        else:
            regimen_ganador = 'INCERTO'
            confianza_final = 30
        
        return regimen_ganador, confianza_final, votos, confianzas, votos_ponderados
    
    def _votar_por_indicador(self, nombre: str, valor: Any, 
                             contexto: Dict) -> Tuple[Optional[str], float]:
        """
        Cada indicador vota por un régimen.
        
        Args:
            nombre: Nombre del indicador
            valor: Valor del indicador
            contexto: Contexto adicional
        
        Returns:
            (regimen_votado, confianza)
        """
        # --- ADX ---
        if nombre == 'adx_h4' or nombre == 'adx_h1':
            adx = float(valor) if valor is not None else 0
            if adx >= self.ADX_TREND_FUERTE:
                estructura = contexto.get('estructura', 'NEUTRAL')
                if estructura == 'ALCISTA':
                    return 'TREND_ALCISTA_FUERTE', min(95, 70 + adx * 0.5)
                elif estructura == 'BAJISTA':
                    return 'TREND_BAJISTA_FUERTE', min(95, 70 + adx * 0.5)
                return 'INCERTO', 40
            elif adx >= self.ADX_TREND_DEBIL:
                estructura = contexto.get('estructura', 'NEUTRAL')
                if estructura == 'ALCISTA':
                    return 'TREND_ALCISTA_DEBIL', min(80, 50 + adx * 0.8)
                elif estructura == 'BAJISTA':
                    return 'TREND_BAJISTA_DEBIL', min(80, 50 + adx * 0.8)
                return 'INCERTO', 35
            return 'INCERTO', 30
        
        # --- ICHIMOKU ---
        if nombre == 'ichimoku':
            ichimoku = valor if isinstance(valor, dict) else {}
            tendencia = ichimoku.get('tendencia', 'NEUTRAL')
            senkou_ancho = ichimoku.get('senkou_ancho', 0)
            
            if tendencia == 'ALCISTA' and senkou_ancho > 0.01:
                return 'TREND_ALCISTA_FUERTE', 80
            elif tendencia == 'ALCISTA':
                return 'TREND_ALCISTA_DEBIL', 60
            elif tendencia == 'BAJISTA' and senkou_ancho > 0.01:
                return 'TREND_BAJISTA_FUERTE', 80
            elif tendencia == 'BAJISTA':
                return 'TREND_BAJISTA_DEBIL', 60
            return 'RANGO_AMPLIO', 50
        
        # --- BB WIDTH ---
        if nombre == 'bb_width':
            bb = float(valor) if valor is not None else 50
            if bb < self.BB_APRETADO:
                if contexto.get('adx_h1', 0) > 20:
                    return 'BREAKOUT_INMINENTE', 75
                return 'RANGO_APRETADO', 70
            elif bb > self.BB_AMPLIO:
                return 'CHOP_VOLATIL', 60
            return 'RANGO_AMPLIO', 50
        
        # --- CHOP INDEX ---
        if nombre == 'chop_index':
            chop = float(valor) if valor is not None else 50
            if chop < self.CHOP_TENDENCIA:
                estructura = contexto.get('estructura', 'NEUTRAL')
                if estructura == 'ALCISTA':
                    return 'TREND_ALCISTA_FUERTE', 75
                elif estructura == 'BAJISTA':
                    return 'TREND_BAJISTA_FUERTE', 75
                return 'TREND_ALCISTA_DEBIL', 55
            elif chop > self.CHOP_RANGO:
                return 'RANGO_AMPLIO', 65
            return 'INCERTO', 40
        
        # --- ELDER RAY ---
        if nombre == 'elder_ray':
            elder = valor if isinstance(valor, dict) else {}
            fuerza = elder.get('fuerza', 'NEUTRAL')
            bull_ratio = elder.get('bull_ratio', 0.5)
            
            if fuerza == 'BULLISH' and bull_ratio > 0.6:
                return 'TREND_ALCISTA_FUERTE', 80
            elif fuerza == 'BULLISH':
                return 'TREND_ALCISTA_DEBIL', 60
            elif fuerza == 'BEARISH' and bull_ratio < 0.4:
                return 'TREND_BAJISTA_FUERTE', 80
            elif fuerza == 'BEARISH':
                return 'TREND_BAJISTA_DEBIL', 60
            return 'INCERTO', 40
        
        # --- DONCHIAN ---
        if nombre == 'donchian':
            donchian = valor if isinstance(valor, dict) else {}
            posicion = donchian.get('posicion', 0.5)
            ancho = donchian.get('ancho', 0)
            
            if ancho < 0.01:
                return 'RANGO_APRETADO', 70
            elif posicion > 0.7:
                estructura = contexto.get('estructura', 'NEUTRAL')
                if estructura == 'ALCISTA':
                    return 'TREND_ALCISTA_FUERTE', 75
                return 'RANGO_AMPLIO', 55
            elif posicion < 0.3:
                estructura = contexto.get('estructura', 'NEUTRAL')
                if estructura == 'BAJISTA':
                    return 'TREND_BAJISTA_FUERTE', 75
                return 'RANGO_AMPLIO', 55
            return 'RANGO_AMPLIO', 50
        
        # --- SAR ---
        if nombre == 'sar':
            sar = float(valor) if valor is not None else 0
            precio = contexto.get('precio_actual', 1)
            if precio > 0 and sar > 0:
                diff_pct = abs(sar - precio) / precio * 100
                estructura = contexto.get('estructura', 'NEUTRAL')
                
                if diff_pct < 0.2:
                    if estructura == 'ALCISTA' and sar < precio:
                        return 'TREND_ALCISTA_FUERTE', 70
                    elif estructura == 'BAJISTA' and sar > precio:
                        return 'TREND_BAJISTA_FUERTE', 70
                    return 'BREAKOUT_INMINENTE', 65
                elif sar < precio:
                    return 'TREND_ALCISTA_DEBIL', 55
                elif sar > precio:
                    return 'TREND_BAJISTA_DEBIL', 55
            return 'INCERTO', 30
        
        # --- ESTRUCTURA ---
        if nombre == 'estructura':
            estructura = valor if isinstance(valor, str) else 'DESCONOCIDO'
            if estructura == 'ALCISTA':
                return 'TREND_ALCISTA_DEBIL', 60
            elif estructura == 'BAJISTA':
                return 'TREND_BAJISTA_DEBIL', 60
            return 'RANGO_AMPLIO', 50
        
        # --- VIX PROXY ---
        if nombre == 'vix_proxy':
            vix = float(valor) if valor is not None else 0
            if vix > self.VIX_ALTO:
                return 'CHOP_VOLATIL', 65
            elif vix > self.VIX_MEDIO:
                return 'RANGO_AMPLIO', 50
            return 'RANGO_APRETADO', 60
        
        # --- ER KAUFMAN ---
        if nombre == 'er_kaufman':
            er = float(valor) if valor is not None else 0
            estructura = contexto.get('estructura', 'NEUTRAL')
            
            if er > 0.5:
                if estructura == 'ALCISTA':
                    return 'TREND_ALCISTA_FUERTE', 70
                elif estructura == 'BAJISTA':
                    return 'TREND_BAJISTA_FUERTE', 70
                return 'TREND_ALCISTA_DEBIL', 50
            elif er > 0.3:
                if estructura == 'ALCISTA':
                    return 'TREND_ALCISTA_DEBIL', 55
                elif estructura == 'BAJISTA':
                    return 'TREND_BAJISTA_DEBIL', 55
                return 'INCERTO', 40
            return 'RANGO_AMPLIO', 50
        
        return None, 30
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def _determinar_direccion_favor(self, indicadores: Dict) -> str:
        """Determina dirección favorita."""
        estructura = indicadores.get('estructura', 'DESCONOCIDO')
        if estructura == 'ALCISTA':
            return 'ALCISTA'
        elif estructura == 'BAJISTA':
            return 'BAJISTA'
        return 'NONE'
    
    def _crear_regimen_incierto(self, confianza: float = 30) -> RegimenData:
        """Crea un régimen INCERTO."""
        return RegimenData(
            regimen=RegimenMercado.INCERTO,
            confianza=confianza,
            adx_h4=0,
            adx_h1=0,
            er_kaufman=0,
            bb_width_pct=50,
            atr_pct=0.5,
            estructura_swings='DESCONOCIDO',
            direccion_favor='NONE',
            metadata={'error': 'No se pudieron calcular indicadores'}
        )
    
    def limpiar_cache(self):
        """Limpia la caché."""
        self._cache.clear()
        logger.debug("🧹 Caché de régimen limpiada")
    
    # ============================================================
    # MÉTODOS DE COMPATIBILIDAD (LEGACY)
    # ============================================================
    
    def get_pesos_por_fase(self, regimen: Optional[RegimenMercado]) -> Dict[str, float]:
        """Pesos para el score final acumulativo."""
        defecto = {'h1': 0.45, 'm15': 0.25, 'm5': 0.30}
        
        if regimen is None:
            return defecto.copy()
        
        if regimen in (RegimenMercado.TREND_ALCISTA_FUERTE, RegimenMercado.TREND_BAJISTA_FUERTE):
            pesos = {'h1': 0.50, 'm15': 0.25, 'm5': 0.25}
        elif regimen in (RegimenMercado.TREND_ALCISTA_DEBIL, RegimenMercado.TREND_BAJISTA_DEBIL):
            pesos = {'h1': 0.45, 'm15': 0.25, 'm5': 0.30}
        elif regimen in (RegimenMercado.RANGO_AMPLIO, RegimenMercado.RANGO_APRETADO):
            pesos = {'h1': 0.30, 'm15': 0.35, 'm5': 0.35}
        elif regimen == RegimenMercado.CHOP_VOLATIL:
            pesos = {'h1': 0.20, 'm15': 0.30, 'm5': 0.50}
        elif regimen == RegimenMercado.BREAKOUT_INMINENTE:
            pesos = {'h1': 0.35, 'm15': 0.25, 'm5': 0.40}
        else:
            pesos = {'h1': 0.30, 'm15': 0.30, 'm5': 0.40}
        
        total = sum(pesos.values())
        return {k: v / total for k, v in pesos.items()}
    
    def get_ajustes_para_modo(self, modo: str, regimen: Optional[RegimenMercado]) -> Dict[str, float]:
        """Multiplicadores de ATR para SL/TP."""
        base = {
            'RETEST': {'sl_mult': 1.2, 'tp_mult': 2.0},
            'BREAKOUT': {'sl_mult': 1.5, 'tp_mult': 2.5},
            'PULLBACK': {'sl_mult': 1.3, 'tp_mult': 2.2},
            'NIVEL_FUERTE': {'sl_mult': 1.1, 'tp_mult': 2.0},
            'PATRON': {'sl_mult': 1.3, 'tp_mult': 2.3},
            'RUPTURA_FALSA': {'sl_mult': 1.2, 'tp_mult': 1.8},
            'VELA_BORDE': {'sl_mult': 1.0, 'tp_mult': 1.6},
            'RETEST_FALLBACK': {'sl_mult': 1.4, 'tp_mult': 1.8},
            'SNIPER_ELITE': {'sl_mult': 1.2, 'tp_mult': 3.0},
        }.get(modo, {'sl_mult': 1.2, 'tp_mult': 2.0})
        
        ajuste = dict(base)
        ajuste['lote_factor'] = 1.0
        
        if regimen is None:
            return ajuste
        
        if regimen in (RegimenMercado.TREND_ALCISTA_FUERTE, RegimenMercado.TREND_BAJISTA_FUERTE):
            if modo in ('BREAKOUT', 'PULLBACK'):
                ajuste['sl_mult'] *= 1.15
                ajuste['tp_mult'] *= 1.25
                ajuste['lote_factor'] = 1.1
            elif modo in ('RETEST', 'NIVEL_FUERTE'):
                ajuste['lote_factor'] = 0.9
        
        elif regimen in (RegimenMercado.TREND_ALCISTA_DEBIL, RegimenMercado.TREND_BAJISTA_DEBIL):
            if modo in ('BREAKOUT', 'PULLBACK'):
                ajuste['sl_mult'] *= 1.05
                ajuste['tp_mult'] *= 1.10
                ajuste['lote_factor'] = 1.0
            elif modo in ('RETEST', 'NIVEL_FUERTE'):
                ajuste['lote_factor'] = 0.85
        
        elif regimen in (RegimenMercado.RANGO_AMPLIO, RegimenMercado.RANGO_APRETADO):
            ajuste['sl_mult'] *= 0.85
            ajuste['tp_mult'] *= 0.80
            if modo in ('RETEST', 'NIVEL_FUERTE', 'VELA_BORDE'):
                ajuste['lote_factor'] = 1.0
            elif modo in ('BREAKOUT', 'PULLBACK'):
                ajuste['lote_factor'] = 0.6
        
        elif regimen == RegimenMercado.CHOP_VOLATIL:
            ajuste['sl_mult'] *= 0.9
            ajuste['tp_mult'] *= 0.75
            ajuste['lote_factor'] = 0.5
        
        return ajuste
    
    def get_umbrales_para_fase2(self, regimen: Optional[RegimenMercado]) -> Dict[str, float]:
        """Umbrales de validación M15 (Fase 2)."""
        defecto = {'adx_minimo': 3, 'vol_minimo': 0.05, 'rsi_tolerancia': 15}
        
        if regimen is None:
            return defecto.copy()
        
        if regimen in (RegimenMercado.TREND_ALCISTA_FUERTE, RegimenMercado.TREND_BAJISTA_FUERTE):
            return {'adx_minimo': 3, 'vol_minimo': 0.05, 'rsi_tolerancia': 20}
        elif regimen in (RegimenMercado.TREND_ALCISTA_DEBIL, RegimenMercado.TREND_BAJISTA_DEBIL):
            return {'adx_minimo': 4, 'vol_minimo': 0.05, 'rsi_tolerancia': 15}
        elif regimen in (RegimenMercado.RANGO_AMPLIO, RegimenMercado.RANGO_APRETADO):
            return {'adx_minimo': 5, 'vol_minimo': 0.05, 'rsi_tolerancia': 10}
        elif regimen == RegimenMercado.CHOP_VOLATIL:
            return {'adx_minimo': 8, 'vol_minimo': 0.08, 'rsi_tolerancia': 5}
        elif regimen == RegimenMercado.BREAKOUT_INMINENTE:
            return {'adx_minimo': 3, 'vol_minimo': 0.05, 'rsi_tolerancia': 15}
        else:
            return defecto.copy()
    
    def get_umbrales_para_fase3(self, regimen: str, modo_backtest: bool = False) -> Dict:
        """Umbrales adaptativos para Fase 3 (Sniper)."""
        umbrales_base = {
            'TREND_ALCISTA_FUERTE': {
                'volumen_min': 0.3, 'confirmacion_velas': 1, 'sl_min_pips': 25,
                'rr_minimo': 1.2, 'score_min': 35,
            },
            'TREND_BAJISTA_FUERTE': {
                'volumen_min': 0.3, 'confirmacion_velas': 1, 'sl_min_pips': 25,
                'rr_minimo': 1.2, 'score_min': 35,
            },
            'TREND_ALCISTA_DEBIL': {
                'volumen_min': 0.25, 'confirmacion_velas': 1, 'sl_min_pips': 20,
                'rr_minimo': 1.2, 'score_min': 30,
            },
            'TREND_BAJISTA_DEBIL': {
                'volumen_min': 0.25, 'confirmacion_velas': 1, 'sl_min_pips': 20,
                'rr_minimo': 1.2, 'score_min': 30,
            },
            'RANGO_AMPLIO': {
                'volumen_min': 0.2, 'confirmacion_velas': 1, 'sl_min_pips': 20,
                'rr_minimo': 1.0, 'score_min': 25,
            },
            'RANGO_APRETADO': {
                'volumen_min': 0.2, 'confirmacion_velas': 1, 'sl_min_pips': 18,
                'rr_minimo': 1.0, 'score_min': 25,
            },
            'BREAKOUT_INMINENTE': {
                'volumen_min': 0.3, 'confirmacion_velas': 1, 'sl_min_pips': 20,
                'rr_minimo': 1.2, 'score_min': 30,
            },
            'CHOP_VOLATIL': {
                'volumen_min': 0.25, 'confirmacion_velas': 2, 'sl_min_pips': 30,
                'rr_minimo': 1.0, 'score_min': 35,
            },
            'INCERTO': {
                'volumen_min': 0.25, 'confirmacion_velas': 1, 'sl_min_pips': 25,
                'rr_minimo': 1.0, 'score_min': 35,
            },
        }
        
        if modo_backtest:
            for reg in umbrales_base:
                umbrales_base[reg]['volumen_min'] *= 0.5
                umbrales_base[reg]['score_min'] -= 10
                umbrales_base[reg]['sl_min_pips'] -= 5
                umbrales_base[reg]['rr_minimo'] = max(0.8, umbrales_base[reg]['rr_minimo'] - 0.2)
        
        return umbrales_base.get(regimen, umbrales_base['INCERTO'])


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_regime_filter(config=None, modo_backtest: bool = False) -> MarketRegimeFilter:
    """Crea una instancia del filtro de régimen."""
    return MarketRegimeFilter(
        config=config,
        modo_backtest=modo_backtest
    )