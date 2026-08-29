#!/usr/bin/env python3
"""
testing/diagnostico_sl_tp_simbolos.py (V9.38 - COMPLETO)
DIAGNÓSTICO DE SL/TP POR SÍMBOLO
Valida que el SL y TP calculados sean los óptimos para cada símbolo,
mostrando por qué se selecciona cada modo.

USO:
    python testing/diagnostico_sl_tp_simbolos.py --simbolo EURUSD
    python testing/diagnostico_sl_tp_simbolos.py --todos
    python testing/diagnostico_sl_tp_simbolos.py --modo BREAKOUT
    python testing/diagnostico_sl_tp_simbolos.py --todos --backtest
"""

import sys
import os
import argparse
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from colorama import Fore, Style, init

# Añadir directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

init(autoreset=True)

# ============================================================
# COLORES
# ============================================================

CYAN = Fore.CYAN
GREEN = Fore.GREEN
YELLOW = Fore.YELLOW
RED = Fore.RED
WHITE = Fore.WHITE
MAGENTA = Fore.MAGENTA
RESET = Style.RESET_ALL

# ============================================================
# IMPORTS DEL SISTEMA
# ============================================================

import pandas as pd
import numpy as np

from config.settings import Config
from config.umbrales import Umbrales
from core.orquestador import Orquestador
from utils.tiempo import HorarioMercado
from utils.helpers import get_tipo_activo, es_forex, es_crypto, es_indice, es_metal, get_pip_val, get_digits
from trading.stops import GestorStops
from trading.sniper.sniper_sl_tp import CalculadorSLTP
from trading.sniper.sniper_checklist import SniperChecklist
from trading.sniper.sniper_modos import DetectorModos, ModoEntrada

logger = logging.getLogger('BotTrading.DiagnosticoSLTP')


class DiagnosticoSLTP:
    """
    Diagnóstico de SL/TP por símbolo.
    V9.38 - COMPLETO CON ANÁLISIS DE SELECCIÓN DE MODO.
    """
    
    # Modos a probar
    MODOS = ['RETEST', 'BREAKOUT', 'PULLBACK', 'NIVEL_FUERTE', 'PATRON', 'SNIPER_ELITE', 'RUPTURA_FALSA', 'VELA_BORDE']
    
    # Régimenes a probar
    REGIMENES = ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE', 'TREND_ALCISTA_DEBIL', 'TREND_BAJISTA_DEBIL', 'RANGO_AMPLIO', 'INCERTO']
    
    # Prioridad de modos (1 = más alta)
    PRIORIDAD_MODOS = {
        'SNIPER_ELITE': 1,
        'BREAKOUT': 2,
        'PULLBACK': 3,
        'RETEST': 4,
        'NIVEL_FUERTE': 5,
        'PATRON': 6,
        'RUPTURA_FALSA': 7,
        'VELA_BORDE': 8,
        'RETEST_FALLBACK': 9,
    }
    
    def __init__(self, modo_backtest: bool = False, modo_depuracion: bool = False):
        """
        Inicializa el diagnóstico.
        """
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        
        # Inicializar orquestador
        self.orquestador = Orquestador(
            modo_backtest=modo_backtest,
            modo_depuracion=modo_depuracion
        )
        
        # Módulos necesarios
        self.gestor_stops = self.orquestador.gestor_stops
        self.calculador_sltp = CalculadorSLTP(
            config=self.orquestador.config,
            modo_backtest=modo_backtest
        )
        self.horario = self.orquestador.horario
        self.mt5 = self.orquestador.mt5
        self.analisis_capas = self.orquestador.analisis_capas
        
        # Conectar a MT5
        if not self.modo_backtest:
            if not self.mt5.conectar():
                logger.error("❌ No se pudo conectar a MT5")
        
        # Resultados
        self.resultados: Dict[str, Dict] = {}
        
        # Archivo de reporte
        self.reporte_dir = Path(__file__).parent / "reportes"
        self.reporte_dir.mkdir(parents=True, exist_ok=True)
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def ejecutar(self, simbolos: Optional[List[str]] = None, 
                 modo: Optional[str] = None,
                 regimen: Optional[str] = None,
                 guardar_reporte: bool = True) -> Dict[str, Dict]:
        """
        Ejecuta el diagnóstico para los símbolos especificados.
        
        Args:
            simbolos: Lista de símbolos (default: todos los completos)
            modo: Modo específico (default: todos)
            regimen: Régimen específico (default: todos)
            guardar_reporte: Guardar reporte en JSON
        
        Returns:
            Diccionario con resultados por símbolo
        """
        if simbolos is None:
            simbolos = Config.SIMBOLOS_COMPLETOS
        
        modos_a_probar = [modo] if modo else self.MODOS
        regimenes_a_probar = [regimen] if regimen else self.REGIMENES
        
        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}🔍 DIAGNÓSTICO DE SL/TP POR SÍMBOLO (V9.38){RESET}")
        print(f"{CYAN}{'='*80}{RESET}")
        print(f"{WHITE}Fecha: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC{RESET}")
        print(f"{WHITE}Símbolos: {len(simbolos)}{RESET}")
        print(f"{WHITE}Modos: {modos_a_probar}{RESET}")
        print(f"{WHITE}Regímenes: {regimenes_a_probar}{RESET}")
        
        resultados = {}
        
        for simbolo in simbolos:
            print(f"\n{CYAN}{'─'*80}{RESET}")
            print(f"{CYAN}📊 ANALIZANDO: {simbolo}{RESET}")
            print(f"{CYAN}{'─'*80}{RESET}")
            
            resultado = self._diagnosticar_simbolo(
                simbolo=simbolo,
                modos=modos_a_probar,
                regimenes=regimenes_a_probar
            )
            
            if resultado:
                resultados[simbolo] = resultado
                self._mostrar_resumen_simbolo(simbolo, resultado)
        
        self.resultados = resultados
        
        # Resumen global
        self._mostrar_resumen_global(resultados)
        
        # Guardar reporte
        if guardar_reporte and resultados:
            self._guardar_reporte(resultados)
        
        return resultados
    
    # ============================================================
    # DIAGNÓSTICO DE UN SÍMBOLO
    # ============================================================
    
    def _diagnosticar_simbolo(self, 
                              simbolo: str,
                              modos: List[str],
                              regimenes: List[str]) -> Optional[Dict]:
        """
        Diagnostica un símbolo específico.
        """
        resultado = {
            'simbolo': simbolo,
            'tipo_activo': get_tipo_activo(simbolo),
            'pip_val': get_pip_val(simbolo),
            'digits': get_digits(simbolo),
            'fecha': datetime.now(timezone.utc).isoformat(),
            'modos_analizados': {},
            'sl_tp_recomendado': None,
            'mejor_modo': None,
            'mejor_rr': 0,
            'advertencias': [],
            'errores': [],
            'contexto': {},
        }
        
        print(f"\n{WHITE}🔍 DIAGNÓSTICO DETALLADO DE {simbolo}{RESET}")
        print(f"{WHITE}{'─'*50}{RESET}")
        
        # ============================================================
        # 1. OBTENER INFO DEL SÍMBOLO
        # ============================================================
        print(f"\n{WHITE}📍 INFO DEL SÍMBOLO:{RESET}")
        
        info = None
        if not self.modo_backtest and self.mt5:
            info = self.mt5.obtener_info_simbolo(simbolo)
        
        if info:
            resultado['mt5_info'] = {
                'digits': getattr(info, 'digits', None),
                'point': getattr(info, 'point', None),
                'trade_tick_value': getattr(info, 'trade_tick_value', None),
                'trade_tick_size': getattr(info, 'trade_tick_size', None),
                'volume_min': getattr(info, 'volume_min', None),
                'volume_max': getattr(info, 'volume_max', None),
                'trade_stops_level': getattr(info, 'trade_stops_level', None),
            }
            print(f"  {GREEN}✅ Info obtenida desde MT5{RESET}")
            print(f"     Digits: {getattr(info, 'digits', 'N/A')}")
            print(f"     Point: {getattr(info, 'point', 'N/A')}")
            print(f"     Stop Level: {getattr(info, 'trade_stops_level', 'N/A')}")
        else:
            print(f"  {YELLOW}⚠️ Usando valores fallback{RESET}")
            print(f"     Digits: {get_digits(simbolo)}")
            print(f"     Pip Val: {get_pip_val(simbolo)}")
        
        # ============================================================
        # 2. OBTENER DATOS DE MERCADO
        # ============================================================
        print(f"\n{WHITE}📍 DATOS DE MERCADO:{RESET}")
        
        df_h1 = self._obtener_datos(simbolo, timeframe=60, n_velas=250)
        if df_h1 is None or len(df_h1) < 50:
            resultado['errores'].append("Datos H1 insuficientes")
            print(f"  {RED}❌ Datos H1 insuficientes{RESET}")
            return resultado
        
        precio_actual = df_h1['Close'].iloc[-1]
        resultado['precio_actual'] = precio_actual
        print(f"  {GREEN}✅ Precio actual: {precio_actual:.{get_digits(simbolo)}f}{RESET}")
        
        # Obtener tick actual (si disponible)
        tick = None
        if not self.modo_backtest:
            tick = self.mt5.obtener_precio(simbolo)
            if tick:
                resultado['tick'] = {
                    'bid': tick.get('bid'),
                    'ask': tick.get('ask'),
                    'spread_pips': tick.get('spread_pips'),
                }
                print(f"  {GREEN}✅ Tick obtenido: bid={tick.get('bid')}, ask={tick.get('ask')}{RESET}")
                print(f"     Spread: {tick.get('spread_pips')} pips")
            else:
                print(f"  {YELLOW}⚠️ No se pudo obtener tick (mercado cerrado?){RESET}")
        
        # ============================================================
        # 3. ANÁLISIS RÁPIDO
        # ============================================================
        print(f"\n{WHITE}📍 ANÁLISIS RÁPIDO (H1):{RESET}")
        
        rapido = self.analisis_capas.analisis_rapido(df_h1, simbolo, precio_actual)
        if not rapido or not rapido.pasa_filtro:
            resultado['errores'].append("Filtro rápido falló")
            print(f"  {RED}❌ Filtro rápido falló: {rapido.razon_rechazo if rapido else 'N/A'}{RESET}")
            return resultado
        
        resultado['rapido'] = {
            'rsi': rapido.rsi,
            'volumen_relativo': rapido.volumen_relativo,
            'tendencia': rapido.tendencia_corta,
            'atr': rapido.atr,
        }
        print(f"  {GREEN}✅ Análisis rápido aprobado{RESET}")
        print(f"     RSI: {rapido.rsi:.1f}")
        print(f"     Volumen: {rapido.volumen_relativo:.2f}x")
        print(f"     Tendencia: {rapido.tendencia_corta}")
        print(f"     ATR: {rapido.atr:.5f}")
        
        # ============================================================
        # 4. DETECTAR NIVELES
        # ============================================================
        print(f"\n{WHITE}📍 DETECCIÓN DE NIVELES:{RESET}")
        
        niveles = self.orquestador.nivel_tracker.detectar_y_actualizar_niveles(
            simbolo=simbolo,
            df=df_h1,
            precio_actual=precio_actual
        )
        
        soportes = niveles.get('soportes', [])
        resistencias = niveles.get('resistencias', [])
        
        resultado['niveles'] = {
            'soportes': soportes[:3],
            'resistencias': resistencias[:3],
        }
        
        print(f"  {GREEN}✅ Niveles detectados{RESET}")
        if soportes:
            soporte_precio = soportes[0].get('precio', 'N/A') if isinstance(soportes[0], dict) else soportes[0]
            print(f"     Soportes: {len(soportes)} (más cercano: {soporte_precio})")
        if resistencias:
            resistencia_precio = resistencias[0].get('precio', 'N/A') if isinstance(resistencias[0], dict) else resistencias[0]
            print(f"     Resistencias: {len(resistencias)} (más cercana: {resistencia_precio})")
        
        # ============================================================
        # 5. ANÁLISIS MEDIO
        # ============================================================
        print(f"\n{WHITE}📍 ANÁLISIS MEDIO (H1):{RESET}")
        
        medio = self.analisis_capas.analisis_medio(df_h1, simbolo, rapido, niveles)
        if not medio or not medio.pasa_filtro:
            resultado['errores'].append("Filtro medio falló")
            print(f"  {RED}❌ Filtro medio falló: {medio.razon_rechazo if medio else 'N/A'}{RESET}")
            return resultado
        
        resultado['medio'] = {
            'adx': medio.adx,
            'rsi': medio.rsi,
            'macd': medio.macd_histogram,
            'atr': medio.atr,
            'soporte_cercano': medio.soporte_cercano,
            'resistencia_cercana': medio.resistencia_cercana,
            'soporte_hits': medio.soporte_hits,
            'resistencia_hits': medio.resistencia_hits,
            'en_nivel_clave': medio.en_nivel_clave,
        }
        
        print(f"  {GREEN}✅ Análisis medio aprobado{RESET}")
        print(f"     ADX: {medio.adx:.1f}")
        print(f"     RSI: {medio.rsi:.1f}")
        print(f"     ATR: {medio.atr:.5f}")
        print(f"     Soporte: {medio.soporte_cercano}")
        print(f"     Resistencia: {medio.resistencia_cercana}")
        
        # ============================================================
        # 6. ANÁLISIS PESADO
        # ============================================================
        print(f"\n{WHITE}📍 ANÁLISIS PESADO (H1):{RESET}")
        
        pesado = self.analisis_capas.analisis_pesado(df_h1, simbolo, None, None, niveles, medio)
        if not pesado:
            resultado['errores'].append("Análisis pesado falló")
            print(f"  {RED}❌ Análisis pesado falló{RESET}")
            return resultado
        
        resultado['pesado'] = {
            'score_estructura': pesado.score_estructura,
            'score_momentum': pesado.score_momentum,
            'score_confluencia': pesado.score_confluencia,
            'score_institucional': pesado.score_institucional,
            'patron_principal': pesado.patron_principal,
            'wyckoff_fase': pesado.wyckoff_fase,
            'divergencia_rsi': pesado.divergencia_rsi,
        }
        
        print(f"  {GREEN}✅ Análisis pesado aprobado{RESET}")
        print(f"     Score estructura: {pesado.score_estructura:.1f}")
        print(f"     Score momentum: {pesado.score_momentum:.1f}")
        print(f"     Patrón: {pesado.patron_principal}")
        
        # ============================================================
        # 7. PROBAR MODOS Y REGÍMENES
        # ============================================================
        print(f"\n{WHITE}📍 PROBANDO MODOS Y REGÍMENES:{RESET}")
        print(f"{WHITE}{'─'*40}{RESET}")
        
        mejores_resultados = []
        contexto_completo = {
            'score_h1': pesado.score_estructura + pesado.score_momentum + pesado.score_confluencia + pesado.score_institucional,
            'regimen': 'TREND_ALCISTA_FUERTE',
            'en_nivel_clave': medio.en_nivel_clave,
            'volumen_relativo': rapido.volumen_relativo,
            'adx': medio.adx,
            'rsi': medio.rsi,
            'hits': medio.soporte_hits if medio.soporte_cercano else medio.resistencia_hits,
            'fib': 0.5,
            'falsa_ruptura': False,
            'patron_calidad': pesado.calidad_patron if hasattr(pesado, 'calidad_patron') else 0,
            'confluencias_favorables': [],
            'confluencias_conflictos': [],
        }
        
        for modo in modos:
            for regimen in regimenes:
                # Probar COMPRA
                resultado_compra = self._probar_sl_tp(
                    simbolo=simbolo,
                    precio=precio_actual,
                    direccion='COMPRA',
                    modo=modo,
                    regimen=regimen,
                    medio=medio,
                    pesado=pesado,
                    contextos={'soporte': medio.soporte_cercano, 'resistencia': medio.resistencia_cercana},
                    volumen_relativo=rapido.volumen_relativo
                )
                
                if resultado_compra:
                    resultado_compra['direccion'] = 'COMPRA'
                    resultado_compra['condiciones'] = contexto_completo.copy()
                    mejores_resultados.append(resultado_compra)
                
                # Probar VENTA
                resultado_venta = self._probar_sl_tp(
                    simbolo=simbolo,
                    precio=precio_actual,
                    direccion='VENTA',
                    modo=modo,
                    regimen=regimen,
                    medio=medio,
                    pesado=pesado,
                    contextos={'soporte': medio.soporte_cercano, 'resistencia': medio.resistencia_cercana},
                    volumen_relativo=rapido.volumen_relativo
                )
                
                if resultado_venta:
                    resultado_venta['direccion'] = 'VENTA'
                    resultado_venta['condiciones'] = contexto_completo.copy()
                    mejores_resultados.append(resultado_venta)
        
        if not mejores_resultados:
            resultado['errores'].append("No se encontró SL/TP válido en ningún modo")
            print(f"  {RED}❌ No se encontró SL/TP válido{RESET}")
            return resultado
        
        # ============================================================
        # 8. ENCONTRAR EL MEJOR RESULTADO
        # ============================================================
        mejores_resultados.sort(key=lambda x: x.get('rr', 0), reverse=True)
        
        mejor = mejores_resultados[0]
        resultado['mejor_modo'] = mejor.get('modo')
        resultado['mejor_regimen'] = mejor.get('regimen')
        resultado['mejor_direccion'] = mejor.get('direccion')
        resultado['mejor_rr'] = mejor.get('rr', 0)
        resultado['sl_tp_recomendado'] = {
            'direccion': mejor.get('direccion'),
            'modo': mejor.get('modo'),
            'regimen': mejor.get('regimen'),
            'entry': precio_actual,
            'sl': mejor.get('sl'),
            'tp': mejor.get('tp'),
            'sl_pips': mejor.get('sl_pips'),
            'tp_pips': mejor.get('tp_pips'),
            'rr': mejor.get('rr'),
            'sl_minimo_requerido': mejor.get('sl_minimo'),
        }
        resultado['contexto'] = mejor.get('condiciones', {})
        
        # Guardar todos los modos analizados
        for r in mejores_resultados:
            key = f"{r.get('modo')}_{r.get('regimen')}_{r.get('direccion')}"
            resultado['modos_analizados'][key] = r
        
        print(f"\n{WHITE}📍 MEJOR RESULTADO ENCONTRADO:{RESET}")
        print(f"  {GREEN}✅ Modo: {mejor.get('modo')}{RESET}")
        print(f"     Régimen: {mejor.get('regimen')}")
        print(f"     Dirección: {mejor.get('direccion')}")
        print(f"     SL: {mejor.get('sl')} ({mejor.get('sl_pips'):.1f} pips)")
        print(f"     TP: {mejor.get('tp')} ({mejor.get('tp_pips'):.1f} pips)")
        print(f"     R:R: {mejor.get('rr'):.2f}")
        print(f"     SL mínimo requerido: {mejor.get('sl_minimo')} pips")
        
        # ============================================================
        # 9. VALIDACIÓN DEL MEJOR RESULTADO
        # ============================================================
        if mejor.get('rr', 0) < 1.5:
            resultado['advertencias'].append(f"R:R bajo ({mejor.get('rr'):.2f} < 1.5)")
            print(f"  {YELLOW}⚠️ R:R bajo ({mejor.get('rr'):.2f} < 1.5){RESET}")
        
        if mejor.get('sl_pips', 0) < 10:
            resultado['advertencias'].append(f"SL muy cercano ({mejor.get('sl_pips'):.1f} pips)")
            print(f"  {YELLOW}⚠️ SL muy cercano ({mejor.get('sl_pips'):.1f} pips){RESET}")
        
        if mejor.get('tp_pips', 0) < 10:
            resultado['advertencias'].append(f"TP muy cercano ({mejor.get('tp_pips'):.1f} pips)")
            print(f"  {YELLOW}⚠️ TP muy cercano ({mejor.get('tp_pips'):.1f} pips){RESET}")
        
        return resultado
    
    # ============================================================
    # PROBAR SL/TP PARA UN MODO
    # ============================================================
    
    def _probar_sl_tp(self,
                  simbolo: str,
                  precio: float,
                  direccion: str,
                  modo: str,
                  regimen: str,
                  medio: Any,
                  pesado: Any,
                  contextos: Dict,
                  volumen_relativo: float = 1.0) -> Optional[Dict]:
        """
        Prueba SL/TP para un modo, régimen y dirección específicos.
        V9.38 - CORREGIDO: Métodos independientes sin dependencias externas.
        """
        try:
            # Obtener parámetros
            pip_val = get_pip_val(simbolo)
            digits = get_digits(simbolo)
            
            # Obtener SL mínimo
            sl_minimo = self._obtener_sl_minimo(simbolo, modo, regimen)
            
            # Crear contexto H1 simulado
            contexto_h1 = {
                'soporte_cercano': contextos.get('soporte'),
                'resistencia_cercana': contextos.get('resistencia'),
                'regimen': regimen,
                'en_nivel_clave': medio.en_nivel_clave if medio else False,
                'volumen_relativo': volumen_relativo,
            }
            
            # ============================================================
            # 1. CALCULAR SL DINÁMICO (MÉTODO INDEPENDIENTE)
            # ============================================================
            sl_result = self._calcular_sl_dinamico_independiente(
                simbolo=simbolo,
                precio=precio,
                direccion=direccion,
                modo=modo,
                regimen=regimen,
                volumen_relativo=volumen_relativo,
                atr=medio.atr if medio else 0.001,
                pip_val=pip_val,
                digits=digits
            )
            
            if not sl_result or sl_result.get('sl', 0) == 0.0:
                return None
            
            sl_propuesto = sl_result['sl']
            sl_pips = sl_result['sl_pips']
            
            # ============================================================
            # 2. VALIDAR SL/TP CON GESTOR STOPS (usando lógica simplificada)
            # ============================================================
            valido, razon, sl_final, tp_final, tp2_final = self._validar_sl_tp_simplificado(
                simbolo=simbolo,
                entry_price=precio,
                sl=sl_propuesto,
                direccion=direccion,
                regimen=regimen,
                modo=modo,
                en_nivel_clave=medio.en_nivel_clave if medio else False,
                sl_minimo=sl_minimo,
                pip_val=pip_val,
                digits=digits
            )
            
            if not valido:
                return None
            
            # ============================================================
            # 3. CALCULAR TP REALISTA (MÉTODO INDEPENDIENTE)
            # ============================================================
            tp_result = self._calcular_tp_realista_independiente(
                simbolo=simbolo,
                precio=precio,
                direccion=direccion,
                sl=sl_final,
                modo=modo,
                regimen=regimen,
                contexto_h1=contexto_h1,
                volumen_relativo=volumen_relativo,
                pip_val=pip_val,
                digits=digits
            )
            
            if tp_result and tp_result.get('tp', 0) > 0:
                tp_final = tp_result['tp']
                tp_pips = tp_result['tp_pips']
                rr = tp_result['rr']
            else:
                return None
            
            # ============================================================
            # 4. VALIDACIÓN FINAL
            # ============================================================
            if rr < 1.0:
                return None
            
            return {
                'modo': modo,
                'regimen': regimen,
                'direccion': direccion,
                'sl': sl_final,
                'tp': tp_final,
                'sl_pips': sl_pips,
                'tp_pips': tp_pips,
                'rr': rr,
                'sl_minimo': sl_minimo,
                'valido': True,
                'razon': 'OK',
                'digits': digits,
                'pip_val': pip_val,
                'fuente_sl': 'sl_dinamico_independiente',
                'fuente_tp': 'tp_realista_independiente',
            }
            
        except Exception as e:
            if self.modo_depuracion:
                print(f"  ⚠️ Error probando {modo}/{regimen}/{direccion}: {e}")
            return None

    def _calcular_sl_dinamico_independiente(self,
                                        simbolo: str,
                                        precio: float,
                                        direccion: str,
                                        modo: str,
                                        regimen: str,
                                        volumen_relativo: float,
                                        atr: float,
                                        pip_val: float,
                                        digits: int) -> Optional[Dict]:
        """
        Calcula SL dinámico independiente (sin SniperChecklist).
        V9.38 - NUEVO.
        """
        # Multiplicadores de SL por modo
        SL_MULTIPLICADORES = {
            'BREAKOUT': 1.2,
            'SNIPER_ELITE': 0.9,
            'PULLBACK': 1.8,
            'RETEST': 1.0,
            'PATRON': 1.3,
            'RUPTURA_FALSA': 1.1,
            'NIVEL_FUERTE': 0.9,
            'VELA_BORDE': 0.9,
            'RETEST_FALLBACK': 1.8,
        }
        
        sl_mult = SL_MULTIPLICADORES.get(modo, 1.2)
        
        # Ajuste por régimen
        REGIMEN_AJUSTES = {
            'TREND_ALCISTA_FUERTE': 1.1,
            'TREND_BAJISTA_FUERTE': 1.1,
            'TREND_ALCISTA_DEBIL': 1.0,
            'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9,
            'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 0.7,
            'BREAKOUT_INMINENTE': 1.0,
            'INCERTO': 1.0,
        }
        sl_mult = sl_mult * REGIMEN_AJUSTES.get(regimen, 1.0)
        
        # Ajuste por volumen
        if volumen_relativo > 2.0:
            sl_mult = sl_mult * 0.85
        elif volumen_relativo > 1.5:
            sl_mult = sl_mult * 0.90
        elif volumen_relativo < 0.5:
            sl_mult = sl_mult * 1.15
        
        # Calcular SL
        sl_dist = atr * sl_mult
        sl_dist_pips = sl_dist / pip_val if pip_val > 0 else 0
        
        # SL mínimo
        sl_min_pips = self._obtener_sl_minimo(simbolo, modo, regimen)
        if sl_dist_pips < sl_min_pips:
            sl_dist_pips = sl_min_pips
            sl_dist = sl_min_pips * pip_val
        
        if direccion == 'COMPRA':
            sl = precio - sl_dist
        else:
            sl = precio + sl_dist
        
        # Validar dirección
        if direccion == 'COMPRA' and sl >= precio:
            return None
        if direccion == 'VENTA' and sl <= precio:
            return None
        
        return {
            'sl': sl,
            'sl_pips': sl_dist_pips,
            'sl_dist': sl_dist,
            'mult': sl_mult,
        }


    def _validar_sl_tp_simplificado(self,
                                    simbolo: str,
                                    entry_price: float,
                                    sl: float,
                                    direccion: str,
                                    regimen: str,
                                    modo: str,
                                    en_nivel_clave: bool,
                                    sl_minimo: float,
                                    pip_val: float,
                                    digits: int) -> Tuple[bool, str, float, float, float]:
        """
        Valida SL/TP de forma simplificada (sin gestor_stops).
        V9.38 - NUEVO.
        """
        # Validar SL
        sl_dist = abs(entry_price - sl)
        sl_pips = sl_dist / pip_val if pip_val > 0 else 0
        
        if sl_pips < sl_minimo:
            return False, f"SL {sl_pips:.1f}pips < mínimo {sl_minimo:.1f}pips", 0, 0, 0
        
        # Calcular TP por R:R
        RR_TARGET = {
            'BREAKOUT': 2.5,
            'SNIPER_ELITE': 3.0,
            'PULLBACK': 2.0,
            'RETEST': 2.0,
            'PATRON': 1.8,
            'RUPTURA_FALSA': 1.3,
            'NIVEL_FUERTE': 1.5,
            'VELA_BORDE': 1.3,
            'RETEST_FALLBACK': 1.5,
        }
        
        rr_target = RR_TARGET.get(modo, 1.8)
        
        # Ajuste por régimen
        REGIMEN_AJUSTES_RR = {
            'TREND_ALCISTA_FUERTE': 1.1,
            'TREND_BAJISTA_FUERTE': 1.1,
            'TREND_ALCISTA_DEBIL': 1.0,
            'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9,
            'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 0.7,
            'BREAKOUT_INMINENTE': 1.1,
            'INCERTO': 0.9,
        }
        rr_target = rr_target * REGIMEN_AJUSTES_RR.get(regimen, 1.0)
        rr_target = max(1.0, min(3.5, rr_target))
        
        if direccion == 'COMPRA':
            tp = entry_price + (sl_dist * rr_target)
        else:
            tp = entry_price - (sl_dist * rr_target)
        
        tp_dist = abs(tp - entry_price)
        tp_pips = tp_dist / pip_val if pip_val > 0 else 0
        rr = tp_dist / sl_dist if sl_dist > 0 else 0
        
        # Validar R:R mínimo
        if rr < 1.0:
            return False, f"R:R {rr:.2f} < 1.0", 0, 0, 0
        
        return True, "OK", sl, tp, 0


    def _calcular_tp_realista_independiente(self,
                                            simbolo: str,
                                            precio: float,
                                            direccion: str,
                                            sl: float,
                                            modo: str,
                                            regimen: str,
                                            contexto_h1: Dict,
                                            volumen_relativo: float,
                                            pip_val: float,
                                            digits: int) -> Optional[Dict]:
        """
        Calcula TP realista independiente (sin SniperChecklist).
        V9.38 - NUEVO.
        """
        sl_dist = abs(precio - sl)
        
        # R:R objetivo
        RR_TARGET = {
            'BREAKOUT': 2.5,
            'SNIPER_ELITE': 3.0,
            'PULLBACK': 2.0,
            'RETEST': 2.0,
            'PATRON': 1.8,
            'RUPTURA_FALSA': 1.3,
            'NIVEL_FUERTE': 1.5,
            'VELA_BORDE': 1.3,
            'RETEST_FALLBACK': 1.5,
        }
        
        rr_target = RR_TARGET.get(modo, 1.8)
        
        # Ajuste por régimen
        REGIMEN_AJUSTES_RR = {
            'TREND_ALCISTA_FUERTE': 1.1,
            'TREND_BAJISTA_FUERTE': 1.1,
            'TREND_ALCISTA_DEBIL': 1.0,
            'TREND_BAJISTA_DEBIL': 1.0,
            'RANGO_AMPLIO': 0.9,
            'RANGO_APRETADO': 0.8,
            'CHOP_VOLATIL': 0.7,
            'BREAKOUT_INMINENTE': 1.1,
            'INCERTO': 0.9,
        }
        rr_target = rr_target * REGIMEN_AJUSTES_RR.get(regimen, 1.0)
        rr_target = max(1.0, min(3.5, rr_target))
        
        # Ajuste por volumen
        if volumen_relativo > 1.5:
            rr_target = min(3.5, rr_target * 1.05)
        elif volumen_relativo < 0.5:
            rr_target = max(1.0, rr_target * 0.95)
        
        # Calcular TP por R:R
        if direccion == 'COMPRA':
            tp_por_rr = precio + (sl_dist * rr_target)
        else:
            tp_por_rr = precio - (sl_dist * rr_target)
        
        # Verificar estructura (solo si mejora R:R)
        tp_estructura = None
        rr_estructura = 0
        
        if direccion == 'COMPRA':
            resistencia = contexto_h1.get('resistencia_cercana')
            if resistencia and resistencia > precio and resistencia < tp_por_rr:
                rr_estructura = (resistencia - precio) / sl_dist if sl_dist > 0 else 0
                if rr_estructura > rr_target:
                    tp_estructura = resistencia
        else:
            soporte = contexto_h1.get('soporte_cercano')
            if soporte and soporte < precio and soporte > tp_por_rr:
                rr_estructura = (precio - soporte) / sl_dist if sl_dist > 0 else 0
                if rr_estructura > rr_target:
                    tp_estructura = soporte
        
        if tp_estructura:
            tp_final = tp_estructura
            rr_final = rr_estructura
        else:
            tp_final = tp_por_rr
            rr_final = rr_target
        
        tp_dist = abs(tp_final - precio)
        tp_pips = tp_dist / pip_val if pip_val > 0 else 0
        
        return {
            'tp': tp_final,
            'tp_pips': tp_pips,
            'rr': rr_final,
            'rr_target': rr_target,
        }
    
    # ============================================================
    # TABLA COMPARATIVA DE MODOS
    # ============================================================
    
    def _mostrar_tabla_comparativa(self, simbolo: str, modos_analizados: Dict, contexto: Dict):
        """
        Muestra tabla comparativa de modos con condiciones.
        V9.38 - NUEVO.
        """
        if not modos_analizados:
            return
        
        print(f"\n{CYAN}📊 TABLA COMPARATIVA DE MODOS PARA {simbolo}{RESET}")
        print(f"{'─'*110}")
        
        # Encabezado
        header = f"{'MODO':<14} {'DIR':<6} {'R:R':<8} {'SL':<8} {'TP':<8} {'VOL':<6} {'ADX':<6} {'RSI':<6} {'HITS':<5} {'NIVEL':<7} {'VÁLIDO'}"
        print(header)
        print(f"{'─'*110}")
        
        # Ordenar por R:R descendente
        sorted_modos = sorted(
            modos_analizados.items(),
            key=lambda x: x[1].get('rr', 0),
            reverse=True
        )
        
        for key, data in sorted_modos[:10]:
            rr = data.get('rr', 0)
            sl_pips = data.get('sl_pips', 0)
            tp_pips = data.get('tp_pips', 0)
            direccion = data.get('direccion', 'N/A')
            condiciones = data.get('condiciones', {})
            modo = data.get('modo', 'N/A')
            
            vol = condiciones.get('volumen_relativo', 0)
            adx = condiciones.get('adx', 0)
            rsi = condiciones.get('rsi', 50)
            hits = condiciones.get('hits', 0)
            en_nivel = condiciones.get('en_nivel_clave', False)
            valido = data.get('valido', False) and rr >= 1.5
            
            color = GREEN if rr >= 1.5 else YELLOW if rr >= 1.0 else RED
            nivel_str = "✅" if en_nivel else "❌"
            valido_str = "✅" if valido else "❌"
            
            modo_str = f"{modo[:12]:<14}"
            dir_str = f"{direccion[:6]:<6}"
            
            print(f"{modo_str} {dir_str} {color}{rr:>6.2f}{RESET} {sl_pips:>7.1f} {tp_pips:>7.1f} {vol:>5.2f} {adx:>5.0f} {rsi:>5.0f} {hits:>4} {nivel_str:^7} {valido_str}")
        
        print(f"{'─'*110}")
        
        # ============================================================
        # ✅ ANÁLISIS DE SELECCIÓN
        # ============================================================
        self._mostrar_analisis_seleccion(simbolo, sorted_modos, contexto)
    
    def _mostrar_analisis_seleccion(self, simbolo: str, sorted_modos: List, contexto: Dict):
        """
        Muestra el análisis de selección de modo.
        V9.38 - NUEVO.
        """
        print(f"\n{WHITE}🔍 ANÁLISIS DE SELECCIÓN DE MODO{RESET}")
        print(f"{'─'*60}")
        
        if not sorted_modos:
            print(f"  {YELLOW}⚠️ No hay modos válidos para analizar{RESET}")
            return
        
        # Mejor modo por R:R
        mejor_rr = sorted_modos[0]
        modo_seleccionado = mejor_rr[1]
        
        # Mejor modo por prioridad del bot
        mejor_prioridad = None
        for key, data in sorted_modos:
            modo = data.get('modo', '')
            if modo in self.PRIORIDAD_MODOS:
                if mejor_prioridad is None or self.PRIORIDAD_MODOS[modo] < self.PRIORIDAD_MODOS.get(mejor_prioridad, 99):
                    mejor_prioridad = modo
        
        print(f"\n  {GREEN}✅ MODO CON MEJOR R:R: {mejor_rr[1].get('modo')} ({mejor_rr[1].get('rr', 0):.2f}){RESET}")
        print(f"  {WHITE}Dirección: {mejor_rr[1].get('direccion')}{RESET}")
        print(f"  {WHITE}Régimen: {mejor_rr[1].get('regimen')}{RESET}")
        
        if mejor_prioridad:
            print(f"\n  {WHITE}🎯 MODO CON MAYOR PRIORIDAD DEL BOT: {mejor_prioridad}{RESET}")
        
        # ============================================================
        # RAZONES DE SELECCIÓN
        # ============================================================
        print(f"\n  {WHITE}📋 CONDICIONES DEL MERCADO:{RESET}")
        print(f"     Volumen relativo: {contexto.get('volumen_relativo', 0):.2f}x")
        print(f"     ADX: {contexto.get('adx', 0):.1f}")
        print(f"     RSI: {contexto.get('rsi', 0):.1f}")
        print(f"     Nivel clave: {'✅' if contexto.get('en_nivel_clave', False) else '❌'}")
        print(f"     Hits: {contexto.get('hits', 0)}")
        
        # ============================================================
        # EXPLICACIÓN POR MODO
        # ============================================================
        print(f"\n  {WHITE}📊 EXPLICACIÓN DE CADA MODO:{RESET}")
        
        modo_explicaciones = {
            'BREAKOUT': f"Volumen {contexto.get('volumen_relativo', 0):.2f}x > 1.0x + nivel clave",
            'SNIPER_ELITE': f"Score alto + {contexto.get('confluencias', 0)} confluencias",
            'PULLBACK': f"Tendencia definida + Fib + nivel clave",
            'RETEST': f"Nivel con {contexto.get('hits', 0)} hits",
            'NIVEL_FUERTE': f"Nivel con {contexto.get('hits', 0)} hits (fuerte)",
            'PATRON': f"Patrón detectado (calidad > 30)",
            'RUPTURA_FALSA': f"Falsa ruptura en tendencia",
            'VELA_BORDE': f"Vela en borde de nivel",
        }
        
        for key, data in sorted_modos[:5]:
            modo = data.get('modo', 'N/A')
            rr = data.get('rr', 0)
            explicacion = modo_explicaciones.get(modo, "Condiciones generales")
            color = GREEN if rr >= 1.5 else YELLOW if rr >= 1.0 else RED
            
            print(f"     • {modo}: R:R={color}{rr:.2f}{RESET} | {explicacion}")
        
        # ============================================================
        # RECOMENDACIÓN FINAL
        # ============================================================
        print(f"\n  {WHITE}💡 RECOMENDACIÓN:{RESET}")
        
        mejor_modo = mejor_rr[1]
        rr = mejor_modo.get('rr', 0)
        modo = mejor_modo.get('modo', 'N/A')
        direccion = mejor_modo.get('direccion', 'N/A')
        
        if rr >= 1.5:
            print(f"     {GREEN}✅ RECOMENDADO: {modo} {direccion} (R:R {rr:.2f}){RESET}")
        else:
            print(f"     {YELLOW}⚠️ NINGÚN MODO TIENE R:R SUFICIENTE (> 1.5){RESET}")
            print(f"     {WHITE}Considerar: Ajustar SL o esperar mejores condiciones{RESET}")
        
        print(f"{'─'*60}")
    
    # ============================================================
    # MÉTODOS AUXILIARES
    # ============================================================
    
    def _obtener_sl_minimo(self, simbolo: str, modo: str, regimen: str) -> float:
        """Obtiene SL mínimo para el símbolo."""
        return self.gestor_stops._obtener_sl_minimo(
            simbolo=simbolo,
            modo=modo,
            regimen=regimen,
            calidad_horario='REGULAR'
        )
    
    def _obtener_datos(self, simbolo: str, timeframe: int, n_velas: int) -> Optional[pd.DataFrame]:
        """Obtiene datos de mercado."""
        if self.modo_backtest:
            return self._crear_df_dummy(simbolo, timeframe, n_velas)
        
        return self.mt5.obtener_datos(simbolo, n_velas=n_velas, timeframe=timeframe)
    
    def _crear_df_dummy(self, simbolo: str, timeframe: int, n_velas: int) -> pd.DataFrame:
        """Crea DataFrame dummy para diagnóstico."""
        import numpy as np
        
        precio_base = 1.1000
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            precio_base = 150.0
        elif 'XAU' in simbolo_upper:
            precio_base = 2500.0
        elif 'XAG' in simbolo_upper:
            precio_base = 30.0
        elif any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            precio_base = 45000.0
        elif any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            precio_base = 60000.0
        
        intervalos = {5: '5min', 15: '15min', 60: '1h', 240: '4h', 1440: '1D'}
        freq = intervalos.get(timeframe, '1h')
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=n_velas, freq=freq)
        
        np.random.seed(42)
        variaciones = np.random.randn(n_velas) * 0.001 * precio_base
        precios = precio_base + np.cumsum(variaciones)
        
        df = pd.DataFrame({
            'Open': precios,
            'High': precios + abs(np.random.randn(n_velas) * 0.001 * precio_base),
            'Low': precios - abs(np.random.randn(n_velas) * 0.001 * precio_base),
            'Close': precios + np.random.randn(n_velas) * 0.0005 * precio_base,
            'Volume': np.random.randint(100, 1000, n_velas)
        }, index=fechas)
        
        df.index.name = 'time'
        return df
    
    def _crear_df_m5_dummy(self, simbolo: str, precio: float) -> pd.DataFrame:
        """Crea DataFrame M5 dummy con el precio especificado."""
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq='5min')
        
        np.random.seed(42)
        variaciones = np.random.randn(50) * 0.0005 * precio
        
        df = pd.DataFrame({
            'Open': precio + variaciones,
            'High': precio + variaciones + abs(np.random.randn(50) * 0.0005 * precio),
            'Low': precio + variaciones - abs(np.random.randn(50) * 0.0005 * precio),
            'Close': precio + variaciones + np.random.randn(50) * 0.0003 * precio,
            'Volume': np.random.randint(100, 1000, 50)
        }, index=fechas)
        
        return df
    
    # ============================================================
    # MOSTRAR RESULTADOS
    # ============================================================
    
    def _mostrar_resumen_simbolo(self, simbolo: str, resultado: Dict):
        """Muestra resumen de un símbolo con tabla comparativa."""
        print(f"\n{WHITE}📋 RESUMEN DE {simbolo}{RESET}")
        print(f"{'─'*40}")
        
        if resultado.get('errores'):
            print(f"  {RED}❌ ERRORES:{RESET}")
            for err in resultado['errores']:
                print(f"     - {err}")
            return
        
        mejor = resultado.get('sl_tp_recomendado')
        if mejor:
            print(f"  {GREEN}✅ MEJOR CONFIGURACIÓN:{RESET}")
            print(f"     Dirección: {mejor.get('direccion')}")
            print(f"     Modo: {mejor.get('modo')}")
            print(f"     Régimen: {mejor.get('regimen')}")
            print(f"     Entry: {mejor.get('entry'):.{resultado.get('digits', 5)}f}")
            print(f"     SL: {mejor.get('sl'):.{resultado.get('digits', 5)}f} ({mejor.get('sl_pips', 0):.1f} pips)")
            print(f"     TP: {mejor.get('tp'):.{resultado.get('digits', 5)}f} ({mejor.get('tp_pips', 0):.1f} pips)")
            print(f"     R:R: {mejor.get('rr', 0):.2f}")
            print(f"     SL mínimo requerido: {mejor.get('sl_minimo_requerido', 0)} pips")
        
        # ============================================================
        # ✅ MOSTRAR TABLA COMPARATIVA
        # ============================================================
        modos_analizados = resultado.get('modos_analizados', {})
        contexto = resultado.get('contexto', {})
        
        if modos_analizados:
            self._mostrar_tabla_comparativa(simbolo, modos_analizados, contexto)
        
        if resultado.get('advertencias'):
            print(f"\n  {YELLOW}⚠️ ADVERTENCIAS:{RESET}")
            for adv in resultado['advertencias']:
                print(f"     - {adv}")
    
    def _mostrar_resumen_global(self, resultados: Dict):
        """Muestra resumen global."""
        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}📊 RESUMEN GLOBAL{RESET}")
        print(f"{CYAN}{'='*80}{RESET}")
        
        total = len(resultados)
        con_errores = sum(1 for r in resultados.values() if r.get('errores'))
        con_advertencias = sum(1 for r in resultados.values() if r.get('advertencias'))
        
        print(f"  Total símbolos: {total}")
        print(f"  {GREEN}✅ Correctos: {total - con_errores}{RESET}")
        print(f"  {YELLOW}⚠️ Con advertencias: {con_advertencias}{RESET}")
        print(f"  {RED}❌ Con errores: {con_errores}{RESET}")
        
        # Tabla de mejores R:R por símbolo
        print(f"\n{WHITE}📊 MEJOR R:R POR SÍMBOLO:{RESET}")
        print(f"{'Símbolo':<12} {'Dirección':<10} {'Modo':<14} {'R:R':<8} {'SL':<8} {'TP':<8}")
        print(f"{'─'*60}")
        
        for simbolo, resultado in sorted(resultados.items(), key=lambda x: x[1].get('mejor_rr', 0), reverse=True):
            if resultado.get('errores'):
                print(f"{simbolo:<12} {RED}ERROR{RESET}")
                continue
            
            mejor = resultado.get('sl_tp_recomendado')
            if mejor:
                rr = mejor.get('rr', 0)
                color = GREEN if rr >= 1.5 else YELLOW if rr >= 1.0 else RED
                print(f"{simbolo:<12} {mejor.get('direccion', 'N/A'):<10} {mejor.get('modo', 'N/A'):<14} {color}{rr:>6.2f}{RESET} {mejor.get('sl_pips', 0):>6.1f} {mejor.get('tp_pips', 0):>6.1f}")
    
    # ============================================================
    # GUARDAR REPORTE
    # ============================================================
    
    def _guardar_reporte(self, resultados: Dict):
        """Guarda el reporte en JSON y CSV."""
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        archivo = self.reporte_dir / f"diagnostico_sl_tp_{timestamp}.json"
        
        # Convertir a formato serializable
        reporte = {
            'fecha': datetime.now(timezone.utc).isoformat(),
            'modo_backtest': self.modo_backtest,
            'resultados': {}
        }
        
        for simbolo, resultado in resultados.items():
            resultado_clean = {}
            for key, value in resultado.items():
                if key == 'modos_analizados':
                    modos_clean = {}
                    for k, v in value.items():
                        modos_clean[k] = {kk: vv for kk, vv in v.items() if not callable(vv)}
                    resultado_clean[key] = modos_clean
                elif isinstance(value, (pd.DataFrame, pd.Series)):
                    continue
                elif isinstance(value, (datetime,)):
                    resultado_clean[key] = value.isoformat()
                else:
                    resultado_clean[key] = value
            reporte['resultados'][simbolo] = resultado_clean
        
        with open(archivo, 'w', encoding='utf-8') as f:
            json.dump(reporte, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"\n{GREEN}✅ Reporte guardado: {archivo}{RESET}")
        
        # Guardar CSV
        csv_archivo = self.reporte_dir / f"diagnostico_sl_tp_{timestamp}.csv"
        self._guardar_csv(resultados, csv_archivo)
    
    def _guardar_csv(self, resultados: Dict, archivo: Path):
        """Guarda resumen en CSV."""
        import csv
        
        with open(archivo, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Simbolo', 'Direccion', 'Modo', 'Regimen', 'R:R', 'SL_pips', 'TP_pips', 'Entry', 'SL', 'TP', 'Advertencias'])
            
            for simbolo, resultado in resultados.items():
                mejor = resultado.get('sl_tp_recomendado')
                if mejor:
                    writer.writerow([
                        simbolo,
                        mejor.get('direccion', ''),
                        mejor.get('modo', ''),
                        mejor.get('regimen', ''),
                        f"{mejor.get('rr', 0):.2f}",
                        f"{mejor.get('sl_pips', 0):.1f}",
                        f"{mejor.get('tp_pips', 0):.1f}",
                        f"{mejor.get('entry', 0):.5f}",
                        f"{mejor.get('sl', 0):.5f}",
                        f"{mejor.get('tp', 0):.5f}",
                        '; '.join(resultado.get('advertencias', []))
                    ])
        
        print(f"{GREEN}✅ CSV guardado: {archivo}{RESET}")


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Diagnóstico de SL/TP por símbolo V9.38")
    parser.add_argument("--simbolo", type=str, help="Símbolo específico (ej: EURUSD)")
    parser.add_argument("--simbolos", type=str, help="Lista de símbolos separados por coma")
    parser.add_argument("--todos", action="store_true", help="Analizar todos los símbolos")
    parser.add_argument("--modo", type=str, choices=['RETEST', 'BREAKOUT', 'PULLBACK', 'NIVEL_FUERTE', 'PATRON', 'SNIPER_ELITE'], help="Modo específico")
    parser.add_argument("--regimen", type=str, help="Régimen específico")
    parser.add_argument("--backtest", action="store_true", help="Modo backtest (sin MT5)")
    parser.add_argument("--depuracion", action="store_true", help="Modo depuración")
    
    args = parser.parse_args()
    
    # Determinar símbolos
    simbolos = None
    if args.simbolo:
        simbolos = [args.simbolo]
    elif args.simbolos:
        simbolos = [s.strip() for s in args.simbolos.split(',')]
    elif args.todos:
        simbolos = Config.SIMBOLOS_COMPLETOS
    else:
        # Por defecto, analizar algunos símbolos representativos
        simbolos = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'US30', 'BTCUSD']
    
    # Ejecutar diagnóstico
    diagnostico = DiagnosticoSLTP(
        modo_backtest=args.backtest,
        modo_depuracion=args.depuracion
    )
    
    diagnostico.ejecutar(
        simbolos=simbolos,
        modo=args.modo,
        regimen=args.regimen,
        guardar_reporte=True
    )


if __name__ == "__main__":
    main()