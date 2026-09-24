#!/usr/bin/env python3
"""
config/umbrales.py (V10.0 - REFACTORIZADO Y CORREGIDO)
Centralización de TODOS los umbrales del sistema.

CORRECCIONES V10.0:
- ✅ RIESGO_MAX_POR_OPERACION movido a atributo de clase (estaba mal indentado dentro de SNIPER_CONFIG)
- ✅ LOTES_MIN_POR_ACTIVO definido (referenciado pero no existía → AttributeError)
- ✅ Sintaxis cerrada correctamente
- ✅ Horarios de mercado centralizados aquí
- ✅ Métodos de consulta con fallback seguro
"""

from typing import Dict, Any, Optional


class Umbrales:
    """
    Todos los umbrales del sistema centralizados.
    V10.0 - CORREGIDO DEFINITIVO.
    """

    # ============================================================
    # 1. SCORES MÍNIMOS POR FASE Y CALIDAD
    # ============================================================

    SCORES = {
        'score_minimo_general': 35,
        'score_minimo_backtest': 25,
        'score_minimo_fase_1': 40,
        'score_minimo_fase_2': 45,
        'score_minimo_fase_3': 50,
        'score_minimo_excelente': 0,
        'score_minimo_buena': 0,
        'score_minimo_regular': 45,
        'score_minimo_mala': 65,
        'score_minimo_pesima': 80,
    }

    # ============================================================
    # 2. RIESGO / BENEFICIO
    # ============================================================

    RR = {
        'rr_minimo_absoluto': 0.8,
        'rr_minimo_recomendado': 1.0,
        'rr_minimo_backtest': 0.8,
        'rr_retest': 1.2,
        'rr_breakout': 1.5,
        'rr_pullback': 1.3,
        'rr_nivel_fuerte': 1.2,
        'rr_patron': 1.2,
        'rr_ruptura_falsa': 1.0,
        'rr_vela_borde': 1.1,
        'rr_fallback': 1.0,
        'rr_sniper_elite': 1.5,
    }

    # ============================================================
    # 3. SL / TP
    # ============================================================

    SL = {
        'sl_minimo_general': 10,
        'sl_minimo_backtest': 10,
        'sl_maximo_general': 200,
        'sl_maximo_backtest': 250,
        'sl_min_forex': 10,
        'sl_min_forex_cruzado': 12,
        'sl_min_metales': 60,
        'sl_min_indices': 35,
        'sl_min_cripto': 40,
        'sl_min_forex_jpy': 15,
    }

    # ============================================================
    # 4. VOLUMEN
    # ============================================================

    VOLUMEN = {
        'volumen_minimo_general': 0.05,
        'volumen_minimo_backtest': 0.03,
        'volumen_minimo_overlap': 0.05,
        'volumen_minimo_londres': 0.08,
        'volumen_minimo_ny': 0.08,
        'volumen_minimo_asiatico': 0.03,
    }

    # ============================================================
    # 5. ADX
    # ============================================================

    ADX = {
        'adx_minimo_general': 10,
        'adx_minimo_backtest': 5,
        'adx_tendencia_fuerte': 25,
        'adx_tendencia_debil': 15,
        'adx_rango': 10,
        'adx_chop': 5,
    }

    # ============================================================
    # 6. RSI
    # ============================================================

    RSI = {
        'rsi_minimo': 20,
        'rsi_maximo': 80,
        'rsi_minimo_backtest': 15,
        'rsi_maximo_backtest': 85,
        'rsi_extremo_bajo': 15,
        'rsi_extremo_alto': 85,
    }

    # ============================================================
    # 7. DISTANCIAS A NIVELES
    # ============================================================

    DISTANCIAS = {
        'distancia_max_retest': 3.0,
        'distancia_max_breakout': 1.0,
        'distancia_max_pullback': 2.0,
        'distancia_max_nivel_fuerte': 2.0,
        'distancia_max_patron': 2.0,
        'distancia_max_ruptura_falsa': 2.0,
        'distancia_max_vela_borde': 2.0,
        'distancia_max_fallback': 4.0,
        'distancia_max_sniper_elite': 2.0,
    }

    # ============================================================
    # 8. HITS DE NIVELES
    # ============================================================

    HITS = {
        'hits_min_h1': 2,
        'hits_min_h4': 2,
        'hits_min_d1': 2,
        'hits_min_m15': 1,
        'hits_min_m5': 1,
        'hits_nivel_fuerte': 3,
        'hits_nivel_muy_fuerte': 5,
        'fuerza_por_hit': 10,
        'fuerza_maxima': 100,
    }

    # ============================================================
    # 9. MODOS DE ENTRADA
    # ============================================================

    MODOS = {
        'modos_tendencia_fuerte': ['PULLBACK', 'BREAKOUT', 'SNIPER_ELITE', 'RETEST'],
        'modos_tendencia_debil': ['PULLBACK', 'RETEST', 'NIVEL_FUERTE', 'SNIPER_ELITE'],
        'modos_rango_amplio': ['RETEST', 'NIVEL_FUERTE', 'VELA_BORDE', 'RUPTURA_FALSA'],
        'modos_rango_apretado': ['NIVEL_FUERTE', 'RETEST', 'SNIPER_ELITE'],
        'modos_chop': ['SNIPER_ELITE', 'RETEST_FALLBACK'],
        'modos_breakout': ['BREAKOUT', 'SNIPER_ELITE', 'RUPTURA_FALSA'],
        'modos_incierto': ['SNIPER_ELITE', 'RETEST_FALLBACK', 'RETEST'],
        'score_modo_retest': 40,
        'score_modo_breakout': 50,
        'score_modo_pullback': 45,
        'score_modo_nivel_fuerte': 60,
        'score_modo_patron': 40,
        'score_modo_ruptura_falsa': 30,
        'score_modo_vela_borde': 30,
        'score_modo_fallback': 35,
        'score_modo_sniper_elite': 50,
    }

    # ============================================================
    # 10. CONFIANZA
    # ============================================================

    CONFIANZA = {
        'confianza_minima_general': 40,
        'confianza_minima_backtest': 25,
        'confianza_elite': 80,
        'confianza_optimo': 65,
        'confianza_operable': 50,
        'confianza_marginal': 35,
        'confianza_bono_nivel': 8,
        'confianza_bono_volumen_alto': 5,
        'confianza_bono_adx_fuerte': 7,
        'confianza_bono_regimen': 10,
        'confianza_bono_nivel_clave': 5,
    }

    # ============================================================
    # 11. TIEMPOS
    # ============================================================

    TIEMPO = {
        'timeout_retest': 480,
        'timeout_breakout': 360,
        'timeout_pullback': 480,
        'timeout_nivel_fuerte': 360,
        'timeout_patron': 360,
        'timeout_ruptura_falsa': 240,
        'timeout_vela_borde': 240,
        'timeout_fallback': 360,
        'timeout_sniper_elite': 480,
        'timeout_backtest_mult': 0.5,
        'espera_minima_retest': 5,
        'espera_maxima': 30,
    }

    # ============================================================
    # 12. TRAILING
    # ============================================================

    TRAILING = {
        'trailing_breakeven_retest': 20,
        'trailing_distancia_retest': 15,
        'trailing_agresivo_umbral_retest': 70,
        'trailing_agresivo_distancia_retest': 10,

        'trailing_breakeven_breakout': 25,
        'trailing_distancia_breakout': 20,
        'trailing_agresivo_umbral_breakout': 80,
        'trailing_agresivo_distancia_breakout': 15,

        'trailing_breakeven_pullback': 25,
        'trailing_distancia_pullback': 18,
        'trailing_agresivo_umbral_pullback': 80,
        'trailing_agresivo_distancia_pullback': 12,

        'trailing_breakeven_nivel_fuerte': 15,
        'trailing_distancia_nivel_fuerte': 12,
        'trailing_agresivo_umbral_nivel_fuerte': 60,
        'trailing_agresivo_distancia_nivel_fuerte': 8,

        'trailing_breakeven_sniper_elite': 15,
        'trailing_distancia_sniper_elite': 12,
        'trailing_agresivo_umbral_sniper_elite': 60,
        'trailing_agresivo_distancia_sniper_elite': 8,

        'trailing_breakeven_patron': 20,
        'trailing_distancia_patron': 15,
        'trailing_agresivo_umbral_patron': 70,
        'trailing_agresivo_distancia_patron': 10,

        'trailing_breakeven_ruptura_falsa': 15,
        'trailing_distancia_ruptura_falsa': 12,
        'trailing_agresivo_umbral_ruptura_falsa': 50,
        'trailing_agresivo_distancia_ruptura_falsa': 8,

        'trailing_breakeven_vela_borde': 15,
        'trailing_distancia_vela_borde': 12,
        'trailing_agresivo_umbral_vela_borde': 50,
        'trailing_agresivo_distancia_vela_borde': 8,

        'trailing_breakeven_retest_fallback': 20,
        'trailing_distancia_retest_fallback': 15,
        'trailing_agresivo_umbral_retest_fallback': 70,
        'trailing_agresivo_distancia_retest_fallback': 10,
    }

    # ============================================================
    # 13. PIP Y DIGITS
    # ============================================================

    PIP = {
        'forex': 0.0001,
        'forex_jpy': 0.01,
        'metales': 0.10,
        'indices': 1.0,
        'cripto': 1.0,
    }

    DIGITS = {
        'forex': 5,
        'forex_jpy': 3,
        'metales': 2,
        'indices': 1,
        'cripto': 2,
    }

    # ============================================================
    # 14. APRENDIZAJE (para ModoSelector dinámico)
    # ============================================================

    APRENDIZAJE = {
        'min_operaciones_para_aprender': 5,
        'peso_winrate': 0.5,
        'peso_factor_beneficio': 0.5,
        'usar_prioridad_base_si_datos_insuficientes': True,
        'penalizacion_falta_datos': 0.3,
    }

    # ============================================================
    # 15. HORARIOS POR TIPO DE ACTIVO
    # ============================================================

    HORARIOS_POR_TIPO_ACTIVO = {
        'FOREX': {
            'preparacion': (3.0, 7.0),
            'normal': (7.0, 12.0),
            'selectiva': (12.0, 16.0),
            'cerrado': (16.0, 3.0),
        },
        'METALES': {
            'normal': (7.0, 12.0),
            'selectiva': (12.0, 16.0),
            'cerrado': (16.0, 7.0),
        },
        'INDICES': {
            'preparacion': (8.0, 8.5),
            'normal': (8.5, 11.5),
            'selectiva': (11.5, 15.5),
            'cerrado': (15.5, 8.0),
        },
        'CRYPTO': {
            'normal': (0.0, 24.0),
        },
    }

    # ============================================================
    # 16. RIESGO POR SÍMBOLO (% del capital)
    # ============================================================

    RIESGO_POR_SIMBOLO = {
        'EURUSD': 1.0, 'GBPUSD': 1.0, 'USDJPY': 1.0,
        'AUDUSD': 1.0, 'USDCAD': 1.0, 'USDCHF': 1.0,
        'EURGBP': 1.0, 'EURJPY': 1.0, 'GBPJPY': 0.8,
        'AUDJPY': 1.0, 'EURNZD': 0.8, 'GBPAUD': 0.8,
        'EURCHF': 0.8, 'GBPCHF': 0.8,
        'XAUUSD': 0.5, 'XAGUSD': 0.5,
        'US30': 0.5, 'NAS100': 0.5, 'US500': 0.8,
        'BTCUSD': 0.3, 'ETHUSD': 0.4, 'SOLUSD': 0.4,
    }

    # ============================================================
    # 17. LÍMITES DE LOTES POR ACTIVO
    # ============================================================

    LOTES_MAX_POR_ACTIVO = {
        # Forex Mayores
        'EURUSD': 0.03, 'GBPUSD': 0.02, 'USDJPY': 0.03,
        'AUDUSD': 0.02, 'USDCAD': 0.02, 'USDCHF': 0.02,

        # Forex Cruzados
        'EURJPY': 0.01, 'GBPJPY': 0.01, 'AUDJPY': 0.01,

        # Metales
        'XAUUSD': 0.01, 'XAGUSD': 0.01,

        # Índices
        'US30': 0.01, 'NAS100': 0.01, 'US500': 0.01,

        # Cripto
        'BTCUSD': 0.01, 'ETHUSD': 0.01, 'SOLUSD': 0.01,
    }

    # ✅ NUEVO V10.0: LOTES MÍNIMOS POR ACTIVO (faltaba)
    LOTES_MIN_POR_ACTIVO = {
        # Forex Mayores
        'EURUSD': 0.01, 'GBPUSD': 0.01, 'USDJPY': 0.01,
        'AUDUSD': 0.01, 'USDCAD': 0.01, 'USDCHF': 0.01,

        # Forex Cruzados
        'EURJPY': 0.01, 'GBPJPY': 0.01, 'AUDJPY': 0.01,

        # Metales
        'XAUUSD': 0.01, 'XAGUSD': 0.01,

        # Índices
        'US30': 0.01, 'NAS100': 0.01, 'US500': 0.01,

        # Cripto
        'BTCUSD': 0.01, 'ETHUSD': 0.01, 'SOLUSD': 0.01,
    }

    # ✅ NUEVO V10.0: RIESGO MÁXIMO POR OPERACIÓN (faltaba como atributo de clase)
    RIESGO_MAX_POR_OPERACION = {
        # Forex Mayores
        'EURUSD': 0.01, 'GBPUSD': 0.01, 'USDJPY': 0.01,
        'AUDUSD': 0.01, 'USDCAD': 0.01, 'USDCHF': 0.01,

        # Forex Cruzados
        'EURJPY': 0.005, 'GBPJPY': 0.005, 'AUDJPY': 0.005,

        # Metales
        'XAUUSD': 0.005, 'XAGUSD': 0.005,

        # Índices
        'US30': 0.005, 'NAS100': 0.005, 'US500': 0.005,

        # Cripto
        'BTCUSD': 0.005, 'ETHUSD': 0.01, 'SOLUSD': 0.01,
    }

    # ============================================================
    # 18. SPREAD MÁXIMO POR ACTIVO
    # ============================================================

    SPREAD_MAX_POR_ACTIVO = {
        'EURUSD': 2.0, 'GBPUSD': 2.0, 'USDJPY': 2.0,
        'AUDUSD': 2.0, 'USDCAD': 2.0, 'USDCHF': 2.0,
        'EURGBP': 2.0, 'EURJPY': 3.0, 'GBPJPY': 3.0,
        'AUDJPY': 3.0, 'NZDUSD': 2.0, 'EURNZD': 3.0,
        'GBPAUD': 3.0, 'EURCHF': 2.0, 'GBPCHF': 3.0,
        'XAUUSD': 30.0, 'XAGUSD': 30.0,
        'US30': 5.0, 'NAS100': 5.0, 'US500': 5.0, 'SP500': 5.0,
        'BTCUSD': 50.0, 'ETHUSD': 50.0, 'SOLUSD': 50.0,
    }

    # ============================================================
    # 19. CONFIGURACIÓN POR MODO PARA SL/TP
    # ============================================================

    SNIPER_CONFIG = {
        'RETEST': {
            'sl_mult': 1.0,
            'sl_buffer_pips': 3,
            'rr_target': 1.5,
            'rr_min': 1.0,
            'rr_max': 2.5,
            'tp_modo': 'ESTRUCTURA',
            'tp_prioridad': 'RESISTENCIA',
            'tp_min_pips': 30,
            'tp_max_pips': 300,
        },
        'BREAKOUT': {
            'sl_mult': 1.5,
            'sl_buffer_pips': 5,
            'rr_target': 2.0,
            'rr_min': 1.5,
            'rr_max': 3.5,
            'tp_modo': 'RR_PURO',
            'tp_prioridad': 'NINGUNA',
            'tp_min_pips': 50,
            'tp_max_pips': 500,
        },
        'PULLBACK': {
            'sl_mult': 1.8,
            'sl_buffer_pips': 2,
            'rr_target': 1.8,
            'rr_min': 1.2,
            'rr_max': 3.0,
            'tp_modo': 'ESTRUCTURA',
            'tp_prioridad': 'SOPORTE_RESISTENCIA',
            'tp_min_pips': 40,
            'tp_max_pips': 400,
        },
        'NIVEL_FUERTE': {
            'sl_mult': 1.2,
            'sl_buffer_pips': 2,
            'rr_target': 1.5,
            'rr_min': 1.2,
            'rr_max': 2.5,
            'tp_modo': 'ESTRUCTURA',
            'tp_prioridad': 'RESISTENCIA',
            'tp_min_pips': 50,
            'tp_max_pips': 400,
        },
        'PATRON': {
            'sl_mult': 1.3,
            'sl_buffer_pips': 3,
            'rr_target': 1.5,
            'rr_min': 1.0,
            'rr_max': 2.5,
            'tp_modo': 'ESTRUCTURA',
            'tp_prioridad': 'SOPORTE_RESISTENCIA',
            'tp_min_pips': 30,
            'tp_max_pips': 300,
        },
        'RUPTURA_FALSA': {
            'sl_mult': 1.1,
            'sl_buffer_pips': 3,
            'rr_target': 1.2,
            'rr_min': 0.8,
            'rr_max': 2.0,
            'tp_modo': 'ESTRUCTURA',
            'tp_prioridad': 'RESISTENCIA',
            'tp_min_pips': 25,
            'tp_max_pips': 200,
        },
        'VELA_BORDE': {
            'sl_mult': 0.9,
            'sl_buffer_pips': 2,
            'rr_target': 1.2,
            'rr_min': 0.8,
            'rr_max': 2.0,
            'tp_modo': 'ESTRUCTURA',
            'tp_prioridad': 'RESISTENCIA',
            'tp_min_pips': 25,
            'tp_max_pips': 200,
        },
        'RETEST_FALLBACK': {
            'sl_mult': 1.8,
            'sl_buffer_pips': 3,
            'rr_target': 1.3,
            'rr_min': 0.8,
            'rr_max': 2.0,
            'tp_modo': 'RR_PURO',
            'tp_prioridad': 'NINGUNA',
            'tp_min_pips': 25,
            'tp_max_pips': 200,
        },
        'SNIPER_ELITE': {
            'sl_mult': 1.0,
            'sl_buffer_pips': 2,
            'rr_target': 2.0,
            'rr_min': 1.5,
            'rr_max': 4.0,
            'tp_modo': 'ESTRUCTURA',
            'tp_prioridad': 'RESISTENCIA',
            'tp_min_pips': 50,
            'tp_max_pips': 600,
        },
    }

    # ============================================================
    # 20. HORARIOS POR ACTIVO (HORA COLOMBIA)
    # ============================================================

    HORARIOS_POR_ACTIVO = {
        # FOREX
        'EURUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'GBPUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'USDJPY': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'AUDUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'USDCAD': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'USDCHF': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'EURGBP': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'EURJPY': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'GBPJPY': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'AUDJPY': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},

        # METALES
        'XAUUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'XAGUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},

        # ÍNDICES
        'US30': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'NAS100': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
        'US500': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},

        # CRIPTO (24/7)
        'BTCUSD': {'inicio': 0, 'fin': 24, 'dias': [0, 1, 2, 3, 4, 5, 6]},
        'ETHUSD': {'inicio': 0, 'fin': 24, 'dias': [0, 1, 2, 3, 4, 5, 6]},
        'SOLUSD': {'inicio': 0, 'fin': 24, 'dias': [0, 1, 2, 3, 4, 5, 6]},
    }

    # ============================================================
    # MÉTODOS DE CONSULTA
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
            'riesgo_por_simbolo': cls.RIESGO_POR_SIMBOLO,
            'lotes_max': cls.LOTES_MAX_POR_ACTIVO,
            'lotes_min': cls.LOTES_MIN_POR_ACTIVO,
            'riesgo_max_operacion': cls.RIESGO_MAX_POR_OPERACION,
            'spread_max': cls.SPREAD_MAX_POR_ACTIVO,
            'sniper_config': cls.SNIPER_CONFIG,
            'horarios_por_activo': cls.HORARIOS_POR_ACTIVO,
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
            'lotes_max': cls.LOTES_MAX_POR_ACTIVO,
            'lotes_min': cls.LOTES_MIN_POR_ACTIVO,
            'riesgo_max': cls.RIESGO_MAX_POR_OPERACION,
            'spread_max': cls.SPREAD_MAX_POR_ACTIVO,
            'sniper_config': cls.SNIPER_CONFIG,
        }

    # ============================================================
    # HELPERS DE ACCESO SEGURO
    # ============================================================

    @classmethod
    def get_score_minimo(cls, fase: int = 1, backtest: bool = False) -> int:
        """Obtiene el score mínimo para una fase."""
        if backtest:
            return cls.SCORES.get('score_minimo_backtest', 25)
        key = f'score_minimo_fase_{fase}'
        return cls.SCORES.get(key, cls.SCORES.get('score_minimo_general', 35))

    @classmethod
    def get_lote_max(cls, simbolo: str, default: float = 0.10) -> float:
        """Obtiene el lote máximo para un símbolo."""
        return cls.LOTES_MAX_POR_ACTIVO.get(simbolo.upper(), default)

    @classmethod
    def get_lote_min(cls, simbolo: str, default: float = 0.01) -> float:
        """Obtiene el lote mínimo para un símbolo."""
        return cls.LOTES_MIN_POR_ACTIVO.get(simbolo.upper(), default)

    @classmethod
    def get_riesgo_max(cls, simbolo: str, default: float = 0.01) -> float:
        """Obtiene el riesgo máximo por operación para un símbolo."""
        return cls.RIESGO_MAX_POR_OPERACION.get(simbolo.upper(), default)

    @classmethod
    def get_spread_max(cls, simbolo: str, default: float = 3.0) -> float:
        """Obtiene el spread máximo para un símbolo."""
        return cls.SPREAD_MAX_POR_ACTIVO.get(simbolo.upper(), default)

    @classmethod
    def get_sniper_config(cls, modo: str) -> Dict[str, Any]:
        """Obtiene la configuración de SL/TP para un modo."""
        return cls.SNIPER_CONFIG.get(modo, cls.SNIPER_CONFIG['RETEST']).copy()

    @classmethod
    def get_horario(cls, simbolo: str) -> Optional[Dict[str, Any]]:
        """Obtiene el horario de un símbolo."""
        return cls.HORARIOS_POR_ACTIVO.get(simbolo.upper())