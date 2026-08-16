#!/usr/bin/env python3
"""
config/umbrales.py (V9.0)
Centralización de TODOS los umbrales del sistema.

PROPÓSITO:
- Un solo lugar para todos los umbrales
- Fácil ajuste y optimización
- Consistencia entre módulos
- Soporte para diferentes entornos
"""

from typing import Dict, Any


class Umbrales:
    """
    Todos los umbrales del sistema centralizados.
    V9.0 - UNIFICADO.
    """
    
    # ============================================================
    # 1. SCORES MÍNIMOS
    # ============================================================
    
    SCORES = {
        # Score mínimo general
        'score_minimo_general': 45,
        'score_minimo_backtest': 25,
        
        # Por fase
        'score_minimo_fase_1': 50,
        'score_minimo_fase_2': 55,
        'score_minimo_fase_3': 60,
        
        # Por horario
        'score_minimo_excelente': 0,
        'score_minimo_buena': 0,
        'score_minimo_regular': 55,
        'score_minimo_mala': 75,
        'score_minimo_pesima': 90,
        
        # Por régimen
        'score_minimo_tendencia_fuerte': 50,
        'score_minimo_tendencia_debil': 55,
        'score_minimo_rango_amplio': 45,
        'score_minimo_rango_apretado': 55,
        'score_minimo_chop': 65,
        'score_minimo_breakout': 50,
        'score_minimo_incierto': 55,
    }
    
    # ============================================================
    # 2. R:R (RELACIÓN RIESGO/BENEFICIO)
    # ============================================================
    
    RR = {
        # R:R mínimos absolutos
        'rr_minimo_absoluto': 1.0,
        'rr_minimo_recomendado': 1.2,
        'rr_minimo_backtest': 0.8,
        
        # R:R por modo
        'rr_retest': 1.5,
        'rr_breakout': 1.8,
        'rr_pullback': 1.6,
        'rr_nivel_fuerte': 1.4,
        'rr_patron': 1.5,
        'rr_ruptura_falsa': 1.2,
        'rr_vela_borde': 1.3,
        'rr_fallback': 1.3,
        'rr_sniper_elite': 2.0,
        
        # R:R por régimen
        'rr_tendencia_fuerte': 1.2,
        'rr_tendencia_debil': 1.0,
        'rr_rango_amplio': 0.8,
        'rr_rango_apretado': 0.8,
        'rr_chop': 0.8,
        'rr_breakout_inminente': 1.0,
        
        # Límites
        'rr_maximo': 3.0,
        'rr_minimo': 1.0,
    }
    
    # ============================================================
    # 3. SL (STOP LOSS) EN PIPS
    # ============================================================
    
    SL = {
        # SL mínimos absolutos
        'sl_minimo_general': 15,
        'sl_minimo_backtest': 10,
        'sl_maximo_general': 200,
        'sl_maximo_backtest': 250,
        
        # SL mínimo por tipo de activo
        'sl_min_forex': 10,
        'sl_min_forex_cruzado': 15,
        'sl_min_metales': 60,
        'sl_min_indices': 35,
        'sl_min_cripto': 80,
        
        # SL por modo (multiplicador sobre mínimo)
        'sl_mult_retest': 1.0,
        'sl_mult_breakout': 1.2,
        'sl_mult_pullback': 1.1,
        'sl_mult_nivel_fuerte': 0.9,
        'sl_mult_patron': 1.0,
        'sl_mult_ruptura_falsa': 1.0,
        'sl_mult_vela_borde': 0.9,
        'sl_mult_fallback': 1.1,
        'sl_mult_sniper_elite': 1.0,
        
        # SL por régimen
        'sl_tendencia_fuerte': 15,
        'sl_tendencia_debil': 12,
        'sl_rango_amplio': 12,
        'sl_rango_apretado': 15,
        'sl_chop': 18,
        'sl_breakout_inminente': 12,
        
        # SL por calidad de horario
        'sl_mult_excelente': 0.9,
        'sl_mult_buena': 1.0,
        'sl_mult_regular': 1.0,
        'sl_mult_mala': 1.1,
        'sl_mult_pesima': 1.2,
    }
    
    # ============================================================
    # 4. VOLUMEN
    # ============================================================
    
    VOLUMEN = {
        # Volumen mínimo general
        'volumen_minimo_general': 0.30,
        'volumen_minimo_backtest': 0.10,
        
        # Por sesión
        'volumen_minimo_overlap': 0.15,
        'volumen_minimo_londres': 0.25,
        'volumen_minimo_ny': 0.20,
        'volumen_minimo_asiatico': 0.05,
        
        # Por modo
        'volumen_minimo_retest': 0.20,
        'volumen_minimo_breakout': 0.30,
        'volumen_minimo_pullback': 0.25,
        'volumen_minimo_sniper_elite': 0.25,
        
        # Por tipo de activo
        'volumen_minimo_forex': 0.20,
        'volumen_minimo_indices': 0.15,
        'volumen_minimo_metales': 0.25,
        'volumen_minimo_cripto': 0.10,
        
        # Umbrales de volumen alto
        'volumen_alto': 1.5,
        'volumen_muy_alto': 2.5,
    }
    
    # ============================================================
    # 5. ADX
    # ============================================================
    
    ADX = {
        # ADX mínimo general
        'adx_minimo_general': 15,
        'adx_minimo_backtest': 5,
        
        # Por régimen
        'adx_tendencia_fuerte': 30,
        'adx_tendencia_debil': 20,
        'adx_rango': 15,
        'adx_chop': 10,
        
        # Por modo
        'adx_minimo_retest': 10,
        'adx_minimo_breakout': 15,
        'adx_minimo_pullback': 15,
        'adx_minimo_sniper_elite': 10,
    }
    
    # ============================================================
    # 6. RSI
    # ============================================================
    
    RSI = {
        # Límites generales
        'rsi_minimo': 25,
        'rsi_maximo': 75,
        'rsi_minimo_backtest': 15,
        'rsi_maximo_backtest': 85,
        
        # Límites extremos
        'rsi_extremo_bajo': 20,
        'rsi_extremo_alto': 80,
        
        # Tolerancias
        'rsi_tolerancia': 10,
        'rsi_tolerancia_backtest': 20,
        
        # Por régimen
        'rsi_tendencia_fuerte': 15,
        'rsi_tendencia_debil': 10,
        'rsi_rango': 10,
        'rsi_chop': 5,
    }
    
    # ============================================================
    # 7. DISTANCIAS A NIVELES (%)
    # ============================================================
    
    DISTANCIAS = {
        # Distancias máximas por modo
        'distancia_max_retest': 2.0,
        'distancia_max_breakout': 0.5,
        'distancia_max_pullback': 1.5,
        'distancia_max_nivel_fuerte': 1.0,
        'distancia_max_patron': 1.5,
        'distancia_max_ruptura_falsa': 1.5,
        'distancia_max_vela_borde': 1.0,
        'distancia_max_fallback': 3.0,
        'distancia_max_sniper_elite': 1.0,
        
        # Distancias por tipo de nivel
        'distancia_soporte_valido': 2.0,
        'distancia_resistencia_valida': 2.0,
        
        # Distancias para backtest (más permisivas)
        'distancia_max_backtest': 4.0,
    }
    
    # ============================================================
    # 8. HITS DE NIVELES
    # ============================================================
    
    HITS = {
        # Hits mínimos por timeframe
        'hits_min_h1': 2,
        'hits_min_h4': 2,
        'hits_min_d1': 2,
        'hits_min_m15': 1,
        'hits_min_m5': 1,
        
        # Hits para nivel fuerte
        'hits_nivel_fuerte': 3,
        'hits_nivel_muy_fuerte': 5,
        
        # Fuerza por hits
        'fuerza_por_hit': 10,
        'fuerza_maxima': 100,
    }
    
    # ============================================================
    # 9. CONFIGURACIÓN DE MODOS
    # ============================================================
    
    MODOS = {
        # Modos por prioridad según régimen
        'modos_tendencia_fuerte': ['PULLBACK', 'BREAKOUT', 'SNIPER_ELITE', 'RETEST'],
        'modos_tendencia_debil': ['PULLBACK', 'RETEST', 'NIVEL_FUERTE', 'SNIPER_ELITE'],
        'modos_rango_amplio': ['RETEST', 'NIVEL_FUERTE', 'VELA_BORDE', 'RUPTURA_FALSA'],
        'modos_rango_apretado': ['NIVEL_FUERTE', 'RETEST', 'SNIPER_ELITE'],
        'modos_chop': ['SNIPER_ELITE', 'RETEST_FALLBACK'],
        'modos_breakout': ['BREAKOUT', 'SNIPER_ELITE', 'RUPTURA_FALSA'],
        'modos_incierto': ['SNIPER_ELITE', 'RETEST_FALLBACK', 'RETEST'],
        
        # Score mínimo por modo
        'score_modo_retest': 50,
        'score_modo_breakout': 60,
        'score_modo_pullback': 55,
        'score_modo_nivel_fuerte': 50,
        'score_modo_patron': 50,
        'score_modo_ruptura_falsa': 40,
        'score_modo_vela_borde': 40,
        'score_modo_fallback': 45,
        'score_modo_sniper_elite': 65,
    }
    
    # ============================================================
    # 10. CONFIANZA
    # ============================================================
    
    CONFIANZA = {
        # Confianza mínima
        'confianza_minima_general': 40,
        'confianza_minima_backtest': 25,
        
        # Confianza por nivel de operabilidad
        'confianza_elite': 80,
        'confianza_optimo': 65,
        'confianza_operable': 50,
        'confianza_marginal': 35,
        
        # Bonos de confianza
        'confianza_bono_nivel': 8,
        'confianza_bono_volumen_alto': 5,
        'confianza_bono_adx_fuerte': 7,
        'confianza_bono_regimen': 10,
        'confianza_bono_nivel_clave': 5,
    }
    
    # ============================================================
    # 11. TIEMPO (TIMEOUTS)
    # ============================================================
    
    TIEMPO = {
        # Timeouts por modo (minutos)
        'timeout_retest': 480,
        'timeout_breakout': 360,
        'timeout_pullback': 480,
        'timeout_nivel_fuerte': 360,
        'timeout_patron': 360,
        'timeout_ruptura_falsa': 240,
        'timeout_vela_borde': 240,
        'timeout_fallback': 360,
        'timeout_sniper_elite': 480,
        
        # Timeouts en backtest (50% más permisivo)
        'timeout_backtest_mult': 0.5,
        
        # Tiempos de espera
        'espera_minima_retest': 5,
        'espera_maxima': 30,
    }
    
    # ============================================================
    # 12. TRAILING STOP
    # ============================================================
    
    TRAILING = {
        # Umbrales por modo (pips)
        'trailing_breakeven_retest': 20,
        'trailing_breakeven_breakout': 25,
        'trailing_breakeven_pullback': 25,
        'trailing_breakeven_nivel_fuerte': 15,
        'trailing_breakeven_sniper_elite': 15,
        
        # Distancias de trailing (pips)
        'trailing_distancia_retest': 15,
        'trailing_distancia_breakout': 20,
        'trailing_distancia_pullback': 18,
        'trailing_distancia_nivel_fuerte': 12,
        'trailing_distancia_sniper_elite': 12,
        
        # Trailing agresivo
        'trailing_agresivo_umbral_retest': 70,
        'trailing_agresivo_distancia_retest': 10,
    }
    
    # ============================================================
    # 13. PIP VALUES
    # ============================================================
    
    PIP = {
        'forex': 0.0001,
        'forex_jpy': 0.01,
        'metales': 0.10,
        'indices': 1.0,
        'cripto': 1.0,
    }
    
    # ============================================================
    # 14. DIGITS
    # ============================================================
    
    DIGITS = {
        'forex': 5,
        'forex_jpy': 3,
        'metales': 2,
        'indices': 2,
        'cripto': 2,
    }
    
    # ============================================================
    # MÉTODO PARA OBTENER CONFIGURACIÓN COMBINADA
    # ============================================================
    
    @classmethod
    def obtener_todos(cls) -> Dict[str, Any]:
        """Obtiene todos los umbrales como un solo diccionario."""
        return {
            'scores': cls.SCORES,
            'rr': cls.RR,
            'sl': cls.SL,
            'volumen': cls.VOLUMEN,
            'adx': cls.ADX,
            'rsi': cls.RSI,
            'distancias': cls.DISTANCIAS,
            'hits': cls.HITS,
            'modos': cls.MODOS,
            'confianza': cls.CONFIANZA,
            'tiempo': cls.TIEMPO,
            'trailing': cls.TRAILING,
            'pip': cls.PIP,
            'digits': cls.DIGITS,
        }
    
    @classmethod
    def obtener_para_sniper(cls) -> Dict[str, Any]:
        """Obtiene umbrales específicos para el sniper."""
        return {
            'score_minimo': cls.SCORES['score_minimo_general'],
            'score_minimo_backtest': cls.SCORES['score_minimo_backtest'],
            'volumen_minimo': cls.VOLUMEN['volumen_minimo_general'],
            'volumen_minimo_backtest': cls.VOLUMEN['volumen_minimo_backtest'],
            'rsi_minimo': cls.RSI['rsi_minimo'],
            'rsi_maximo': cls.RSI['rsi_maximo'],
            'adx_minimo': cls.ADX['adx_minimo_general'],
            'adx_minimo_backtest': cls.ADX['adx_minimo_backtest'],
            'rr_minimo': cls.RR['rr_minimo_recomendado'],
            'rr_minimo_backtest': cls.RR['rr_minimo_backtest'],
            'sl_minimo': cls.SL['sl_minimo_general'],
            'sl_minimo_backtest': cls.SL['sl_minimo_backtest'],
        }