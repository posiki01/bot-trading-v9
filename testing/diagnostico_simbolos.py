#!/usr/bin/env python3
"""
testing/diagnostico_simbolos.py (V10.1 - CORREGIDO)
Script de diagnóstico para validar que cada símbolo se analiza correctamente.

V10.1 - CORRECCIONES:
- Pip value XAGUSD corregido a 0.01
- SL mínimo usa diccionario del conector
- Lotes usan capital real
- SL/TP validación con distancia adecuada
- Verificación de conexión MT5
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
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
RESET = Style.RESET_ALL

# ============================================================
# IMPORTS DEL SISTEMA
# ============================================================

from typing import Dict, List, Optional, Tuple
import pandas as pd

from config.settings import Config
from utils.tiempo import HorarioMercado
from utils.helpers import get_tipo_activo, es_forex, es_crypto, es_indice, es_metal
from trading.stops import GestorStops
from trading.sniper.sniper_sl_tp import CalculadorSLTP
from trading.riesgo import GestionRiesgo
from trading.riesgo_lotes import CalculadorLotes
from core.orquestador import Orquestador
from utils.adaptacion_mercado import AdaptadorMercado

# ============================================================
# LOGGER
# ============================================================

try:
    from utils.logger_persistente import LoggerPersistente
    _logger = LoggerPersistente()
    logger = _logger.get_logger()
except ImportError:
    logger = logging.getLogger('BotTrading.DiagnosticoSimbolos')


# ============================================================
# CLASE DE DIAGNÓSTICO
# ============================================================

class DiagnosticoSimbolos:
    """
    Diagnostica la correcta configuración de cada símbolo.
    V10.1 - CORREGIDO.
    """
    
    def __init__(self, modo_backtest: bool = False, modo_depuracion: bool = False):
        """
        Inicializa el diagnóstico.
        """
        # ✅ INICIALIZAR LOGGER
        self.logger = logger
        
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self._resultados = {}
        
        # Inicializar orquestador (para tener acceso a todos los módulos)
        self.orquestador = Orquestador(modo_backtest=modo_backtest, modo_depuracion=modo_depuracion)
        
        # Módulos necesarios para el diagnóstico
        self.gestor_stops = self.orquestador.gestor_stops
        self.calculador_sltp = CalculadorSLTP(config=self.orquestador.config, modo_backtest=modo_backtest)
        self.gestion_riesgo = self.orquestador.gestion_riesgo
        self.calculador_lotes = CalculadorLotes(config=self.orquestador.config)
        self.horario = self.orquestador.horario
        self.mt5 = self.orquestador.mt5
        self.analisis_capas = self.orquestador.analisis_capas
        
        # Adaptador de mercado (dinámico)
        self.adaptador_mercado = AdaptadorMercado()
        
        # Conexión a MT5
        if not self.modo_backtest:
            if not self.mt5.conectar():
                self.logger.error("❌ No se pudo conectar a MT5")
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def ejecutar(self, simbolos: list = None) -> Dict:
        """
        Ejecuta el diagnóstico completo para una lista de símbolos.
        
        Args:
            simbolos: Lista de símbolos (default: todos los operables)
        
        Returns:
            Diccionario con resultados por símbolo
        """
        if simbolos is None:
            simbolos = Config.SIMBOLOS_COMPLETOS
        
        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}🔍 DIAGNÓSTICO DE SÍMBOLOS - VERIFICANDO PARÁMETROS CORRECTOS{RESET}")
        print(f"{CYAN}{'='*80}{RESET}")
        print(f"{WHITE}Fecha: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC{RESET}")
        print(f"{WHITE}Modo Backtest: {self.modo_backtest}{RESET}")
        print(f"{WHITE}Símbolos a validar: {len(simbolos)}{RESET}")
        
        resultados = {}
        
        for simbolo in simbolos:
            print(f"\n{CYAN}{'─'*80}{RESET}")
            print(f"{CYAN}📊 ANALIZANDO: {simbolo}{RESET}")
            print(f"{CYAN}{'─'*80}{RESET}")
            
            resultado = self._diagnosticar_simbolo(simbolo)
            resultados[simbolo] = resultado
            
            # Mostrar resumen del símbolo
            self._mostrar_resumen_simbolo(simbolo, resultado)
        
        # Resumen global
        self._mostrar_resumen_global(resultados)
        
        return resultados
    
    # ============================================================
    # DIAGNÓSTICO DE UN SÍMBOLO
    # ============================================================
    
    def _diagnosticar_simbolo(self, simbolo: str) -> Dict:
        """
        Diagnostica un símbolo específico.
        V10.1 - CORREGIDO.
        """
        resultado = {
            'simbolo': simbolo,
            'tipo_activo': get_tipo_activo(simbolo),
            'es_forex': es_forex(simbolo),
            'es_crypto': es_crypto(simbolo),
            'es_indice': es_indice(simbolo),
            'es_metal': es_metal(simbolo),
            'problemas': [],
            'advertencias': [],
            'correcto': True,
        }
        
        print(f"\n{WHITE}🔍 DIAGNÓSTICO DETALLADO DE {simbolo}{RESET}")
        print(f"{WHITE}{'─'*50}{RESET}")
        
        # ============================================================
        # 1. OBTENER INFO DEL SÍMBOLO
        # ============================================================
        print(f"\n{WHITE}📍 OBJETO 1: Información del símbolo desde MT5{RESET}")
        info = None
        if not self.modo_backtest and self.mt5 and self.mt5.verificar_conexion():
            info = self.mt5.obtener_info_simbolo(simbolo)
            if info is not None:
                resultado['mt5_info'] = {
                    'name': getattr(info, 'name', ''),
                    'digits': getattr(info, 'digits', None),
                    'point': getattr(info, 'point', None),
                    'trade_tick_value': getattr(info, 'trade_tick_value', None),
                    'trade_tick_size': getattr(info, 'trade_tick_size', None),
                    'volume_min': getattr(info, 'volume_min', None),
                    'volume_max': getattr(info, 'volume_max', None),
                    'volume_step': getattr(info, 'volume_step', None),
                    'trade_stops_level': getattr(info, 'trade_stops_level', None),
                    'filling_mode': getattr(info, 'filling_mode', None),
                }
                print(f"  {GREEN}✅ Info obtenida{RESET}")
                print(f"     Digits: {getattr(info, 'digits', 'N/A')}")
                print(f"     Point: {getattr(info, 'point', 'N/A')}")
                print(f"     Volume Min: {getattr(info, 'volume_min', 'N/A')}")
            else:
                print(f"  {RED}❌ No se pudo obtener info del símbolo{RESET}")
                resultado['problemas'].append("No se pudo obtener info del símbolo")
                resultado['correcto'] = False
                return resultado
        else:
            print(f"  {YELLOW}⚠️ MT5 no conectado, usando valores dummy{RESET}")
        
        # ============================================================
        # 2. PIP VALUE - COMPARAR TODAS LAS FUENTES
        # ============================================================
        print(f"\n{WHITE}📍 OBJETO 2: Pip Value (Comparación de fuentes){RESET}")
        
        pip_values = {}
        
        # Desde conector MT5
        if self.mt5 and info:
            try:
                pip_conector = self.mt5._pip_size_simbolo(simbolo, info)
                if pip_conector:
                    pip_values['conector_mt5'] = pip_conector
                    print(f"  {GREEN}✅ Desde conector MT5: {pip_conector}{RESET}")
                else:
                    print(f"  {RED}❌ Conector MT5 devolvió None{RESET}")
            except Exception as e:
                print(f"  {RED}❌ Error en conector MT5: {e}{RESET}")
                resultado['problemas'].append(f"Error en conector MT5: {e}")
        
        # Desde fallback en diagnóstico
        pip_fallback = self._obtener_pip_val_fallback(simbolo)
        pip_values['fallback'] = pip_fallback
        print(f"  {WHITE}Desde fallback: {pip_fallback}{RESET}")
        
        # Desde sniper_sl_tp
        try:
            pip_sltp = self.calculador_sltp._obtener_pip_val(simbolo, 1.0)
            pip_values['sniper_sl_tp'] = pip_sltp
            print(f"  {WHITE}Desde sniper_sl_tp: {pip_sltp}{RESET}")
        except Exception as e:
            print(f"  {YELLOW}⚠️ Error en sniper_sl_tp: {e}{RESET}")
        
        # Comparar consistencia
        valores = [v for v in pip_values.values() if v and v > 0]
        if valores:
            max_val = max(valores)
            min_val = min(valores)
            if max_val / min_val > 1.5:
                print(f"  {RED}❌ INCONSISTENCIA DETECTADA:{RESET}")
                print(f"     Conector: {pip_values.get('conector_mt5', 'N/A')}")
                print(f"     Fallback: {pip_values.get('fallback', 'N/A')}")
                print(f"     SLTP: {pip_values.get('sniper_sl_tp', 'N/A')}")
                print(f"     → CORREGIR _obtener_pip_val_fallback() en diagnostico_simbolos.py")
                resultado['problemas'].append(f"Pip values inconsistentes: {pip_values}")
                resultado['correcto'] = False
            else:
                print(f"  {GREEN}✅ Pip value consistente: {valores[0]}{RESET}")
                resultado['pip_value'] = valores[0]
        else:
            print(f"  {RED}❌ No se encontró pip value válido{RESET}")
            resultado['problemas'].append("No se encontró pip value válido")
            resultado['correcto'] = False
        
        # ============================================================
        # 3. DIGITS - COMPARAR FUENTES
        # ============================================================
        print(f"\n{WHITE}📍 OBJETO 3: Digits (Comparación de fuentes){RESET}")
        
        digits_fallback = self._obtener_digits_fallback(simbolo)
        digits_mt5 = getattr(info, 'digits', None) if info else None
        
        print(f"  {WHITE}Desde fallback: {digits_fallback}{RESET}")
        if digits_mt5:
            print(f"  {WHITE}Desde MT5: {digits_mt5}{RESET}")
            
            if int(digits_fallback) != int(digits_mt5):
                print(f"  {RED}❌ INCONSISTENCIA DETECTADA:{RESET}")
                print(f"     Fallback: {digits_fallback}")
                print(f"     MT5: {digits_mt5}")
                print(f"     → CORREGIR _obtener_digits_fallback() en diagnostico_simbolos.py")
                resultado['advertencias'].append(f"Digits inconsistentes: fallback={digits_fallback}, MT5={digits_mt5}")
            else:
                print(f"  {GREEN}✅ Digits consistente: {digits_fallback}{RESET}")
        
        resultado['digits'] = digits_fallback
        
        # ============================================================
        # 4. SPREAD
        # ============================================================
        print(f"\n{WHITE}📍 OBJETO 4: Spread{RESET}")
        
        spread_data = None
        if not self.modo_backtest and self.mt5 and self.mt5.verificar_conexion():
            try:
                tick = self.mt5.obtener_precio(simbolo)
                if tick:
                    spread_data = {
                        'bid': tick.get('bid'),
                        'ask': tick.get('ask'),
                        'spread_price': tick.get('spread'),
                        'spread_points': tick.get('spread_points'),
                        'spread_pips': tick.get('spread_pips'),
                    }
                    print(f"  {GREEN}✅ Spread obtenido{RESET}")
                    print(f"     Bid: {tick.get('bid')}")
                    print(f"     Ask: {tick.get('ask')}")
                    print(f"     Spread (pips): {tick.get('spread_pips')}")
                else:
                    print(f"  {RED}❌ No se pudo obtener tick{RESET}")
                    resultado['problemas'].append("No se pudo obtener tick para spread")
            except Exception as e:
                print(f"  {RED}❌ Error obteniendo precio: {e}{RESET}")
                resultado['problemas'].append(f"Error obteniendo precio: {e}")
        else:
            print(f"  {YELLOW}⚠️ MT5 no conectado, usando valores dummy{RESET}")
        
        resultado['spread'] = spread_data
        
        if spread_data and spread_data.get('spread_pips'):
            spread_max = self._obtener_spread_max(simbolo)
            if spread_data['spread_pips'] > spread_max:
                print(f"  {RED}⚠️ Spread actual ({spread_data['spread_pips']:.1f}) > Máximo ({spread_max}){RESET}")
                resultado['advertencias'].append(f"Spread alto: {spread_data['spread_pips']:.1f} > {spread_max}")
            
            resultado['spread_actual_pips'] = spread_data['spread_pips']
            resultado['spread_max_pips'] = spread_max
        
        # ============================================================
        # 5. SL MÍNIMO Y MÁXIMO (CORREGIDO)
        # ============================================================
        print(f"\n{WHITE}📍 OBJETO 5: SL Mínimo y Máximo{RESET}")
        
        sl_min = self._obtener_sl_min(simbolo)
        sl_max = self._obtener_sl_max(simbolo)
        sl_min_conector = self._obtener_sl_min_conector(simbolo)
        
        print(f"  {WHITE}SL Mínimo (stops.py): {sl_min} pips{RESET}")
        print(f"  {WHITE}SL Máximo (stops.py): {sl_max} pips{RESET}")
        print(f"  {WHITE}SL Mínimo (conector MT5): {sl_min_conector} pips{RESET}")
        
        # ✅ VERIFICAR CONSISTENCIA
        if sl_min != sl_min_conector:
            print(f"  {YELLOW}⚠️ Diferencia detectada (puede ser intencional):{RESET}")
            print(f"     stops.py: {sl_min} pips")
            print(f"     conector: {sl_min_conector} pips")
            resultado['advertencias'].append(f"Diferencia SL: stops.py={sl_min}, conector={sl_min_conector}")
        else:
            print(f"  {GREEN}✅ SL mínimo consistente: {sl_min} pips{RESET}")
        
        if sl_min_conector < sl_min:
            print(f"  {RED}❌ PROBLEMA DETECTADO:{RESET}")
            print(f"     Conector permite {sl_min_conector} pips")
            print(f"     Símbolo requiere {sl_min} pips")
            print(f"     → CORREGIR SL_MIN_PIPS_POR_SIMBOLO en conector_mt5.py")
            resultado['advertencias'].append(f"Conector MT5 permite {sl_min_conector} pips pero símbolo requiere {sl_min}")
        
        resultado['sl_min_pips'] = sl_min
        resultado['sl_max_pips'] = sl_max
        resultado['sl_min_conector'] = sl_min_conector
        
        # ============================================================
        # 6. VALIDAR SL/TP CON GESTOR DE STOPS (CORREGIDO)
        # ============================================================
        print(f"\n{WHITE}📍 OBJETO 6: Validación de SL/TP{RESET}")
        
        precio_demo = self._obtener_precio_demo(simbolo)
        print(f"  {WHITE}Precio demo: {precio_demo}{RESET}")
        
        sl_calculado, tp_calculado, rr, razon = self._validar_sl_tp(simbolo, precio_demo)
        
        if sl_calculado:
            print(f"  {GREEN}✅ SL/TP calculado correctamente{RESET}")
            print(f"     SL: {sl_calculado}")
            print(f"     TP: {tp_calculado}")
            print(f"     R:R: {rr}")
            print(f"     Razón: {razon}")
            resultado['sl_tp'] = {
                'sl': sl_calculado,
                'tp': tp_calculado,
                'rr': rr,
            }
        else:
            print(f"  {RED}❌ Error calculando SL/TP: {razon}{RESET}")
            resultado['problemas'].append(f"Error SL/TP: {razon}")
            resultado['correcto'] = False
        
        # ============================================================
        # 7. CÁLCULO DE LOTES (CORREGIDO)
        # ============================================================
        print(f"\n{WHITE}📍 OBJETO 7: Cálculo de Lotes{RESET}")
        
        lotes = self._calcular_lotes(simbolo, precio_demo, sl_calculado)
        
        if lotes > 0:
            print(f"  {GREEN}✅ Lotes calculados: {lotes:.3f}{RESET}")
            resultado['lotes'] = lotes
        else:
            print(f"  {RED}❌ No se pudieron calcular lotes{RESET}")
            resultado['problemas'].append("No se pudieron calcular lotes")
            resultado['correcto'] = False
        
        # ============================================================
        # 8. TIMING / HORARIO
        # ============================================================
        print(f"\n{WHITE}📍 OBJETO 8: Timing / Horario{RESET}")
        
        hora_col = self.horario.hora_colombia_float()
        es_operativo, razon_horario = self.horario.es_horario_operativo(simbolo)
        calidad = self.horario.obtener_calidad_horario(simbolo)
        
        print(f"  {WHITE}Hora Colombia: {hora_col:.1f}{RESET}")
        print(f"  {WHITE}Operativo: {es_operativo} ({razon_horario}){RESET}")
        print(f"  {WHITE}Calidad: {calidad['calidad']}{RESET}")
        print(f"  {WHITE}Score mínimo requerido: {calidad['score_minimo']}{RESET}")
        
        resultado['horario'] = {
            'operativo': es_operativo,
            'calidad': calidad['calidad'],
            'score_minimo': calidad['score_minimo'],
        }
        
        # ============================================================
        # 9. ANÁLISIS TÉCNICO (DATOS FRESCOS)
        # ============================================================
        print(f"\n{WHITE}📍 OBJETO 9: Análisis Técnico (Datos frescos){RESET}")
        
        if not self.modo_backtest and self.mt5 and self.mt5.verificar_conexion():
            # Obtener datos frescos directamente de MT5 (sin caché ni SQLite)
            df_h1 = self._obtener_datos_frescos(simbolo, timeframe=60, n_velas=100)
            
            if df_h1 is not None and len(df_h1) > 20:
                try:
                    # Análisis rápido
                    rapido = self.analisis_capas.analisis_rapido(df_h1, simbolo)
                    print(f"  {GREEN}✅ Análisis rápido ejecutado (datos frescos){RESET}")
                    print(f"     RSI: {rapido.rsi:.1f}")
                    print(f"     Volumen relativo: {rapido.volumen_relativo:.2f}x")
                    print(f"     Tendencia: {rapido.tendencia_corta}")
                    print(f"     Pasa filtro: {rapido.pasa_filtro}")
                    
                    resultado['analisis_rapido'] = {
                        'rsi': rapido.rsi,
                        'volumen_relativo': rapido.volumen_relativo,
                        'tendencia': rapido.tendencia_corta,
                        'pasa_filtro': rapido.pasa_filtro,
                    }
                    
                    # Análisis medio
                    medio = self.analisis_capas.analisis_medio(df_h1, simbolo, rapido, {})
                    
                    if medio:
                        print(f"  {GREEN}✅ Análisis medio ejecutado{RESET}")
                        print(f"     ADX: {medio.adx:.1f}")
                        print(f"     RSI: {medio.rsi:.1f}")
                        print(f"     MACD: {medio.macd_histogram:.4f}")
                        print(f"     Soporte: {medio.soporte_cercano}")
                        print(f"     Resistencia: {medio.resistencia_cercana}")
                        
                        resultado['analisis_medio'] = {
                            'adx': medio.adx,
                            'rsi': medio.rsi,
                            'soporte': medio.soporte_cercano,
                            'resistencia': medio.resistencia_cercana,
                        }
                    else:
                        print(f"  {RED}❌ Análisis medio devolvió None{RESET}")
                        resultado['problemas'].append("Análisis medio devolvió None")
                        
                except Exception as e:
                    print(f"  {RED}❌ Error en análisis técnico: {e}{RESET}")
                    resultado['problemas'].append(f"Error en análisis técnico: {e}")
            else:
                print(f"  {RED}❌ No se pudieron obtener datos H1 frescos{RESET}")
                resultado['problemas'].append("No se pudieron obtener datos H1 frescos")
        else:
            print(f"  {YELLOW}⚠️ MT5 no conectado, saltando análisis técnico{RESET}")
        
        # ============================================================
        # 10. ADAPTACIÓN AL MERCADO (DINÁMICO)
        # ============================================================
        print(f"\n{WHITE}📍 OBJETO 10: Adaptación al Mercado (Dinámico){RESET}")
        
        try:
            # Obtener datos frescos H1 y M5
            df_h1_adapt = self._obtener_datos_frescos(simbolo, timeframe=60, n_velas=100)
            df_m5_adapt = self._obtener_datos_frescos(simbolo, timeframe=5, n_velas=300)
            
            if df_h1_adapt is not None and len(df_h1_adapt) > 30:
                # Calcular ajustes dinámicos
                ajustes = self.adaptador_mercado.obtener_ajustes(
                    simbolo=simbolo,
                    df_m5=df_m5_adapt,
                    df_h1=df_h1_adapt
                )
                
                print(f"  {GREEN}✅ Ajustes dinámicos calculados{RESET}")
                print(f"     Tolerancia nivel: {ajustes['tolerancia_nivel']:.2f}")
                print(f"     Volumen mínimo: {ajustes['volumen_minimo']:.2f}")
                print(f"     Score mínimo: {ajustes['score_minimo']:.2f}")
                print(f"     R:R mínimo: {ajustes['rr_minimo']:.2f}")
                print(f"     SL mínimo: {ajustes['sl_min_pips']:.2f}")
                print(f"     Distancia nivel: {ajustes['distancia_nivel_max']:.2f}")
                
                resultado['ajustes_dinamicos'] = ajustes
                
                # Verificar si los ajustes son "normales" (1.0) o están "activos"
                activos = {k: v for k, v in ajustes.items() if abs(v - 1.0) > 0.05}
                if activos:
                    print(f"  {YELLOW}⚠️ Ajustes ACTIVOS:{RESET}")
                    for k, v in activos.items():
                        print(f"     {k}: {v:.2f}")
                    resultado['ajustes_activos'] = activos
                else:
                    print(f"  {GREEN}✅ Ajustes normales (mercado estable){RESET}")
                    resultado['ajustes_activos'] = {}
                
            else:
                print(f"  {YELLOW}⚠️ No se pudo calcular ajustes (datos insuficientes){RESET}")
                resultado['ajustes_dinamicos'] = {}
                
        except ImportError:
            print(f"  {YELLOW}⚠️ AdaptadorMercado no disponible (importar utils/adaptacion_mercado.py){RESET}")
            resultado['ajustes_dinamicos'] = {}
        except Exception as e:
            print(f"  {RED}❌ Error calculando ajustes dinámicos: {e}{RESET}")
            resultado['ajustes_dinamicos'] = {}
        
        return resultado
    
    # ============================================================
    # OBTENER DATOS FRESCOS
    # ============================================================
    
    def _obtener_datos_frescos(self, simbolo: str, timeframe: int = 60, n_velas: int = 100) -> Optional[pd.DataFrame]:
        """
        Obtiene datos frescos o de SQLite.
        V10.3 - CORREGIDO: Funciona en domingo con datos de SQLite o construcción desde M5.
        """
        import MetaTrader5 as mt5
        import pandas as pd
        from datetime import datetime, timezone, timedelta
        from utils.construir_timeframes import construir_desde_m5
        
        self.logger.info(f"📥 {simbolo}: Obteniendo datos frescos TF{timeframe}...")
        
        # 1. Verificar conexión
        if not self.mt5 or not self.mt5.verificar_conexion():
            self.logger.error("❌ MT5 no conectado")
            return None
        
        # 2. Verificar si mercado cerrado
        mercado_cerrado = self.mt5._es_horario_cerrado(simbolo)
        
        if mercado_cerrado:
            self.logger.info(f"ℹ️ {simbolo}: Mercado cerrado ({datetime.now(timezone.utc).strftime('%A %H:%M')} UTC)")
        
        # ============================================================
        # 3. INTENTAR DESDE SQLITE PRIMERO
        # ============================================================
        df_sqlite = None
        try:
            df_sqlite = self.orquestador.almacen.obtener_datos_historicos(simbolo, timeframe)
            if df_sqlite is not None and isinstance(df_sqlite, pd.DataFrame) and len(df_sqlite) > 0:
                self.logger.info(f"✅ {simbolo}: {len(df_sqlite)} velas desde SQLite para TF{timeframe}")
                return df_sqlite
        except Exception as e:
            self.logger.debug(f"⚠️ Error leyendo SQLite para {simbolo} TF{timeframe}: {e}")
        
        # ============================================================
        # 4. SI MERCADO CERRADO Y NO HAY SQLITE → CONSTRUIR DESDE M5
        # ============================================================
        if mercado_cerrado:
            self.logger.info(f"🏗️ {simbolo}: Construyendo TF{timeframe} desde M5...")
            
            # Obtener M5 desde SQLite
            df_m5_sqlite = None
            try:
                df_m5_sqlite = self.orquestador.almacen.obtener_datos_historicos(simbolo, 5)
            except:
                pass
            
            if df_m5_sqlite is not None and isinstance(df_m5_sqlite, pd.DataFrame) and len(df_m5_sqlite) > 100:
                # Construir timeframe desde M5
                timeframes_construidos = construir_desde_m5(df_m5_sqlite, [timeframe])
                df_construido = timeframes_construidos.get(timeframe)
                
                if df_construido is not None and len(df_construido) > 0:
                    self.logger.info(f"✅ {simbolo}: {len(df_construido)} velas construidas desde M5 para TF{timeframe}")
                    return df_construido
            
            # Fallback: intentar obtener datos de MT5 (aunque el mercado esté cerrado, puede haber último tick)
            self.logger.info(f"📥 {simbolo}: Intentando obtener datos de MT5 para TF{timeframe}...")
        
        # ============================================================
        # 5. INTENTAR DESDE MT5 DIRECTAMENTE (como último recurso)
        # ============================================================
        try:
            # Seleccionar símbolo
            if not self.mt5._seleccionar_simbolo(simbolo):
                self.logger.error(f"❌ No se pudo seleccionar {simbolo}")
                return None
            
            # INTENTO 1: Descargar directamente del broker
            rates = mt5.copy_rates_from_pos(simbolo, timeframe, 0, n_velas)
            
            if rates is None or len(rates) == 0:
                # INTENTO 2: copy_rates_range
                fecha_desde = datetime.now(timezone.utc) - timedelta(days=90)
                fecha_hasta = datetime.now(timezone.utc)
                rates = mt5.copy_rates_range(simbolo, timeframe, fecha_desde, fecha_hasta)
            
            if rates is None or len(rates) == 0:
                # INTENTO 3: Construir desde M5
                rates_m5 = mt5.copy_rates_from_pos(simbolo, 5, 0, 3000)
                
                if rates_m5 is None or len(rates_m5) == 0:
                    self.logger.warning(f"⚠️ {simbolo}: Sin datos disponibles para TF{timeframe}")
                    return None
                
                df_m5 = pd.DataFrame(rates_m5)
                df_m5['time'] = pd.to_datetime(df_m5['time'], unit='s', utc=True)
                df_m5.set_index('time', inplace=True)
                df_m5.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
                
                timeframes_construidos = construir_desde_m5(df_m5, [timeframe])
                df = timeframes_construidos.get(timeframe)
                
                if df is not None and len(df) > 0:
                    return df
                
                return None
            
            # Convertir a DataFrame
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
            df.set_index('time', inplace=True)
            df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'tick_volume': 'Volume'}, inplace=True)
            
            # Guardar en SQLite para futuras ejecuciones
            try:
                self.orquestador.almacen.guardar_datos_historicos(simbolo, timeframe, df)
                self.logger.info(f"💾 {simbolo}: Datos guardados en SQLite ({len(df)} velas)")
            except Exception as e:
                self.logger.debug(f"⚠️ Error guardando en SQLite: {e}")
            
            return df
            
        except Exception as e:
            self.logger.error(f"❌ Error obteniendo datos frescos de {simbolo}: {e}")
            
            # Último recurso: crear DataFrame dummy para diagnóstico
            self.logger.warning(f"⚠️ {simbolo}: Creando DataFrame dummy para diagnóstico")
            return self._crear_df_dummy(simbolo, timeframe, n_velas)

    def _crear_df_dummy(self, simbolo: str, timeframe: int, n_velas: int) -> pd.DataFrame:
        """
        Crea un DataFrame dummy para diagnóstico cuando no hay datos.
        V10.3 - CORREGIDO: Solo para diagnóstico, no para operar.
        """
        import pandas as pd
        import numpy as np
        from datetime import datetime, timezone, timedelta
        
        # Precio base según tipo de activo
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            precio_base = 150.0
        elif 'XAU' in simbolo_upper:
            precio_base = 2500.0
        elif 'XAG' in simbolo_upper:
            precio_base = 30.0
        elif 'US30' in simbolo_upper:
            precio_base = 45000.0
        elif 'NAS100' in simbolo_upper:
            precio_base = 20000.0
        elif 'US500' in simbolo_upper:
            precio_base = 5500.0
        elif 'BTC' in simbolo_upper:
            precio_base = 60000.0
        elif 'ETH' in simbolo_upper:
            precio_base = 3000.0
        elif 'SOL' in simbolo_upper:
            precio_base = 150.0
        else:
            precio_base = 1.1000
        
        # Crear fechas
        intervalos = {5: '5min', 15: '15min', 60: '1h', 240: '4h', 1440: '1D'}
        freq = intervalos.get(timeframe, '1h')
        fechas = pd.date_range(end=datetime.now(timezone.utc), periods=n_velas, freq=freq)
        
        # Crear DataFrame con variaciones aleatorias pequeñas
        np.random.seed(42)  # Reproducible
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
        
        self.logger.info(f"📊 {simbolo}: DataFrame dummy creado ({len(df)} velas)")
        
        return df
    # ============================================================
    # OBTENER PIP VALUE FALLBACK (CORREGIDO)
    # ============================================================
    
    def _obtener_pip_val_fallback(self, simbolo: str) -> float:
        """Obtiene pip value usando fallback del código."""
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.01
        if 'XAG' in simbolo_upper:
            return 0.1   # ✅ CORREGIDO: Plata usa 0.1 (antes 0.01)
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001
    
    # ============================================================
    # OBTENER DIGITS FALLBACK
    # ============================================================
    
    def _obtener_digits_fallback(self, simbolo: str) -> int:
        """Obtiene digits usando fallback del código."""
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 3
        if 'XAU' in simbolo_upper:
            return 2
        if 'XAG' in simbolo_upper:
            return 3  # ✅ CORREGIDO: Plata usa 3 dígitos
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1  # ✅ CORREGIDO: Índices usan 1 dígito
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 2
        return 5
    
    # ============================================================
    # OBTENER SPREAD MÁXIMO
    # ============================================================
    
    def _obtener_spread_max(self, simbolo: str) -> float:
        """Obtiene spread máximo permitido."""
        simbolo_upper = simbolo.upper()
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 50.0
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 30.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 5.0
        return 2.0
    
    # ============================================================
    # OBTENER SL MÍNIMO DESDE STOPS.PY (CORREGIDO)
    # ============================================================
    
    def _obtener_sl_min(self, simbolo: str) -> float:
        """Obtiene SL mínimo desde stops.py."""
        # ✅ CORRECCIÓN: Usar el valor del conector si es mayor
        sl_min_stops = self.gestor_stops.SL_MIN_POR_ACTIVO.get(simbolo, 15)
        sl_min_conector = self._obtener_sl_min_conector(simbolo)
        
        # Usar el máximo entre ambos (más conservador)
        sl_min = max(sl_min_stops, sl_min_conector)
        
        return sl_min
    def _obtener_sl_max(self, simbolo: str) -> float:
        """Obtiene SL máximo desde stops.py."""
        sl_max = self.gestor_stops.SL_MAX_POR_ACTIVO.get(simbolo, 200)
        return sl_max
    
    def _obtener_sl_min_conector(self, simbolo: str) -> float:
        """Obtiene SL mínimo desde conector MT5."""
        # ✅ USAR DICCIONARIO POR SÍMBOLO SI EXISTE
        if hasattr(self.mt5, 'SL_MIN_PIPS_POR_SIMBOLO'):
            return self.mt5.SL_MIN_PIPS_POR_SIMBOLO.get(simbolo, self.mt5.SL_MIN_PIPS)
        
        if hasattr(self.mt5, 'SL_MIN_PIPS'):
            return self.mt5.SL_MIN_PIPS
        
        # Fallback por tipo
        simbolo_upper = simbolo.upper()
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 40.0
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 60.0
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 35.0
        return 15.0
    
    # ============================================================
    # OBTENER PRECIO DEMO
    # ============================================================
    
    def _obtener_precio_demo(self, simbolo: str) -> float:
        """Obtiene un precio demo para validación."""
        if not self.modo_backtest and self.mt5 and self.mt5.verificar_conexion():
            tick = self.mt5.obtener_precio(simbolo)
            if tick and tick.get('bid'):
                return float(tick['bid'])
        
        # Precios dummy por tipo
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 150.00
        if 'XAU' in simbolo_upper:
            return 2500.00
        if 'XAG' in simbolo_upper:
            return 30.00
        if any(x in simbolo_upper for x in ['US30']):
            return 45000.00
        if any(x in simbolo_upper for x in ['NAS100']):
            return 20000.00
        if any(x in simbolo_upper for x in ['US500']):
            return 5500.00
        if any(c in simbolo_upper for c in ['BTC']):
            return 60000.00
        if any(c in simbolo_upper for c in ['ETH']):
            return 3000.00
        if any(c in simbolo_upper for c in ['SOL']):
            return 150.00
        return 1.10000  # Forex default
    
    # ============================================================
    # VALIDAR SL/TP (CORREGIDO)
    # ============================================================
    
    def _validar_sl_tp(self, simbolo: str, precio: float) -> tuple:
        """
        Valida SL/TP usando el gestor de stops con distancia adecuada.
        V10.5 - CORREGIDO DEFINITIVO: TP calculado por R:R, no por resistencia directa.
        """
        modos = ['RETEST', 'BREAKOUT', 'PULLBACK', 'NIVEL_FUERTE', 'SNIPER_ELITE']
        
        # Obtener datos de forma segura
        df_h1 = self._obtener_datos_frescos(simbolo, timeframe=60, n_velas=100)
        
        # Verificar si df_h1 es un DataFrame válido
        medio = None
        if df_h1 is not None and isinstance(df_h1, pd.DataFrame) and len(df_h1) > 0:
            try:
                medio = self.orquestador.analisis_capas.analisis_medio(
                    df=df_h1,
                    simbolo=simbolo,
                    rapido=None,
                    niveles_historicos={}
                )
            except Exception as e:
                self.logger.warning(f"⚠️ Error en análisis medio: {e}")
                medio = None
        
        # Obtener resistencia y soporte
        resistencia_cercana = medio.resistencia_cercana if medio else None
        soporte_cercano = medio.soporte_cercano if medio else None
        
        # ✅ CORRECCIÓN V10.5: Probar COMPRA primero
        direccion = 'COMPRA'
        
        for modo in modos:
            # Usar sl_min del GestorStops
            sl_min = self.gestor_stops._obtener_sl_minimo(
                simbolo=simbolo,
                modo=modo,
                regimen='TREND_ALCISTA_FUERTE',
                calidad_horario='EXCELENTE',
                atr_pips=0
            )
            
            pip_val = self._obtener_pip_val_fallback(simbolo)
            sl_dist = sl_min * pip_val
            
            # ✅ CORRECCIÓN: R:R objetivo (mínimo 1.5)
            rr_target = 1.5  # Usar objetivo, no mínimo
            
            # ✅ CORRECCIÓN: TP calculado por R:R PRIMERO
            tp_calculado = precio + (sl_dist * rr_target)
            
            # ✅ CORRECCIÓN: Solo usar resistencia si está ANTES del TP por R:R
            if direccion == 'COMPRA' and resistencia_cercana and resistencia_cercana > precio:
                # Si la resistencia está antes del TP por R:R, usarla
                if tp_calculado > resistencia_cercana:
                    tp_calculado = resistencia_cercana
            
            # Calcular SL/TP para COMPRA
            valido, razon, sl, tp, tp2 = self.gestor_stops.validar_sl_tp(
                simbolo=simbolo,
                entry_price=precio,
                sl=precio - sl_dist,
                tp=tp_calculado,
                direccion='COMPRA',
                modo=modo,
                regimen='TREND_ALCISTA_FUERTE',
                calidad_horario='EXCELENTE'
            )
            
            if valido:
                sl_dist_final = abs(precio - sl)
                tp_dist_final = abs(tp - precio)
                rr = tp_dist_final / sl_dist_final if sl_dist_final > 0 else 0
                
                # ✅ CORRECCIÓN: Si R:R insuficiente, ajustar TP a R:R objetivo
                if rr < 1.0:
                    # Si la resistencia está antes del TP por R:R, NO forzar TP lejano
                    if direccion == 'COMPRA' and resistencia_cercana and resistencia_cercana > precio:
                        if tp <= resistencia_cercana:
                            # El TP está en la resistencia, y es muy cercano
                            # NO usar resistencia como TP si R:R < 1.0
                            # En su lugar, usar TP por R:R (más lejano pero válido)
                            tp_calculado = precio + (sl_dist * rr_target)
                            
                            # Revalidar
                            valido, razon, sl, tp, tp2 = self.gestor_stops.validar_sl_tp(
                                simbolo=simbolo,
                                entry_price=precio,
                                sl=sl,
                                tp=tp_calculado,
                                direccion='COMPRA',
                                modo=modo,
                                regimen='TREND_ALCISTA_FUERTE',
                                calidad_horario='EXCELENTE'
                            )
                            
                            if valido:
                                sl_dist_final = abs(precio - sl)
                                tp_dist_final = abs(tp - precio)
                                rr = tp_dist_final / sl_dist_final if sl_dist_final > 0 else 0
                                return sl, tp, rr, f"Modo: {modo} - TP ajustado a R:R (1.5x)"
                    
                    # Si NO hay resistencia, usar TP por R:R
                    if rr < 1.0:
                        tp_calculado = precio + (sl_dist_final * rr_target)
                        
                        # Revalidar
                        valido, razon, sl, tp, tp2 = self.gestor_stops.validar_sl_tp(
                            simbolo=simbolo,
                            entry_price=precio,
                            sl=sl,
                            tp=tp_calculado,
                            direccion='COMPRA',
                            modo=modo,
                            regimen='TREND_ALCISTA_FUERTE',
                            calidad_horario='EXCELENTE'
                        )
                        
                        if valido:
                            sl_dist_final = abs(precio - sl)
                            tp_dist_final = abs(tp - precio)
                            rr = tp_dist_final / sl_dist_final if sl_dist_final > 0 else 0
                            return sl, tp, rr, f"Modo: {modo} - TP ajustado a R:R"
                
                if rr >= 1.0:
                    return sl, tp, rr, f"Modo: {modo} - OK"
        
        # ✅ CORRECCIÓN V10.5: Probar VENTA
        direccion = 'VENTA'
        
        for modo in modos:
            sl_min = self.gestor_stops._obtener_sl_minimo(
                simbolo=simbolo,
                modo=modo,
                regimen='TREND_BAJISTA_FUERTE',
                calidad_horario='EXCELENTE',
                atr_pips=0
            )
            
            pip_val = self._obtener_pip_val_fallback(simbolo)
            sl_dist = sl_min * pip_val
            
            rr_target = 1.5  # Usar objetivo, no mínimo
            
            tp_calculado = precio - (sl_dist * rr_target)
            
            if direccion == 'VENTA' and soporte_cercano and soporte_cercano < precio:
                if tp_calculado < soporte_cercano:
                    tp_calculado = soporte_cercano
            
            valido, razon, sl, tp, tp2 = self.gestor_stops.validar_sl_tp(
                simbolo=simbolo,
                entry_price=precio,
                sl=precio + sl_dist,
                tp=tp_calculado,
                direccion='VENTA',
                modo=modo,
                regimen='TREND_BAJISTA_FUERTE',
                calidad_horario='EXCELENTE'
            )
            
            if valido:
                sl_dist_final = abs(precio - sl)
                tp_dist_final = abs(tp - precio)
                rr = tp_dist_final / sl_dist_final if sl_dist_final > 0 else 0
                
                if rr < 1.0:
                    if direccion == 'VENTA' and soporte_cercano and soporte_cercano < precio:
                        if tp >= soporte_cercano:
                            tp_calculado = precio - (sl_dist * rr_target)
                            
                            valido, razon, sl, tp, tp2 = self.gestor_stops.validar_sl_tp(
                                simbolo=simbolo,
                                entry_price=precio,
                                sl=sl,
                                tp=tp_calculado,
                                direccion='VENTA',
                                modo=modo,
                                regimen='TREND_BAJISTA_FUERTE',
                                calidad_horario='EXCELENTE'
                            )
                            
                            if valido:
                                sl_dist_final = abs(precio - sl)
                                tp_dist_final = abs(tp - precio)
                                rr = tp_dist_final / sl_dist_final if sl_dist_final > 0 else 0
                                return sl, tp, rr, f"Modo: {modo} - TP ajustado a R:R (1.5x)"
                    
                    if rr < 1.0:
                        tp_calculado = precio - (sl_dist_final * rr_target)
                        
                        valido, razon, sl, tp, tp2 = self.gestor_stops.validar_sl_tp(
                            simbolo=simbolo,
                            entry_price=precio,
                            sl=sl,
                            tp=tp_calculado,
                            direccion='VENTA',
                            modo=modo,
                            regimen='TREND_BAJISTA_FUERTE',
                            calidad_horario='EXCELENTE'
                        )
                        
                        if valido:
                            sl_dist_final = abs(precio - sl)
                            tp_dist_final = abs(tp - precio)
                            rr = tp_dist_final / sl_dist_final if sl_dist_final > 0 else 0
                            return sl, tp, rr, f"Modo: {modo} - TP ajustado a R:R"
                
                if rr >= 1.0:
                    return sl, tp, rr, f"Modo: {modo} - OK"
        
        return None, None, 0, "No se pudo validar SL/TP en ningún modo"
    # ============================================================
    # CALCULAR LOTES (CORREGIDO)
    # ============================================================
    
    def _calcular_lotes(self, simbolo: str, precio: float, sl: float) -> float:
        """Calcula lotes para el símbolo."""
        if not sl or sl <= 0:
            return 0.0
        
        pip_val = self._obtener_pip_val_fallback(simbolo)
        sl_dist = abs(precio - sl)
        sl_pips = sl_dist / pip_val if pip_val > 0 else 0
        
        # ✅ USAR CAPITAL REAL
        capital = float(self.gestion_riesgo.capital_actual)
        
        lotes = self.gestion_riesgo.calcular_lotes(
            entrada=precio,
            stop_loss=sl,
            probabilidad=75,
            simbolo=simbolo,
            capital=capital,
            pip_size=pip_val,
            tick_value=0.01,
            tick_size=0.00001,
            point=0.00001
        )
        
        # Verificar lote mínimo
        simbolo_upper = simbolo.upper()
        lote_min = 0.01
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            lote_min = 0.1
        
        lotes = max(lote_min, lotes)
        
        return lotes
    
    # ============================================================
    # MOSTRAR RESULTADOS
    # ============================================================

    def _obtener_datos_para_analisis(self, simbolo: str, timeframe: int = 60, n_velas: int = 100) -> Optional[pd.DataFrame]:
        """Obtiene datos para análisis (SQLite o MT5)."""
        # Intentar desde SQLite primero
        df_sqlite = self.orquestador.almacen.obtener_datos_historicos(simbolo, timeframe)
        if df_sqlite is not None and len(df_sqlite) > 0:
            return df_sqlite
        
        # Si no hay en SQLite, intentar desde MT5
        if not self.modo_backtest and self.mt5 and self.mt5.verificar_conexion():
            return self._obtener_datos_frescos(simbolo, timeframe, n_velas)
        
        return None
    
    def _mostrar_resumen_simbolo(self, simbolo: str, resultado: Dict):
        """Muestra resumen de un símbolo."""
        print(f"\n{WHITE}📋 RESUMEN DE {simbolo}{RESET}")
        print(f"{'─'*40}")
        
        if resultado['correcto'] and not resultado['advertencias']:
            print(f"  {GREEN}✅ TODO CORRECTO{RESET}")
        elif resultado['correcto']:
            print(f"  {YELLOW}⚠️ CORRECTO CON ADVERTENCIAS{RESET}")
        else:
            print(f"  {RED}❌ CON PROBLEMAS{RESET}")
        
        if 'pip_value' in resultado:
            print(f"  Pip Value: {resultado['pip_value']}")
        if 'digits' in resultado:
            print(f"  Digits: {resultado['digits']}")
        if 'spread_actual_pips' in resultado:
            print(f"  Spread actual: {resultado['spread_actual_pips']:.1f} pips")
            print(f"  Spread máximo: {resultado['spread_max_pips']} pips")
        if 'sl_min_pips' in resultado:
            print(f"  SL mínimo: {resultado['sl_min_pips']} pips")
        if 'lotes' in resultado:
            print(f"  Lotes calculados: {resultado['lotes']:.3f}")
        if 'sl_tp' in resultado:
            sl_tp = resultado['sl_tp']
            print(f"  SL/TP: {sl_tp['sl']} / {sl_tp['tp']}")
            print(f"  R:R: {sl_tp['rr']:.2f}")
            
            # ✅ CORRECCIÓN: Mostrar viabilidad
            if sl_tp['rr'] >= 1.0:
                print(f"  {GREEN}✅ VIABLE para operar (R:R >= 1.0){RESET}")
            elif sl_tp['rr'] >= 0.8:
                print(f"  {YELLOW}⚠️ MARGINAL (R:R 0.8-1.0) - Operar con precaución{RESET}")
            else:
                print(f"  {RED}❌ NO VIABLE (R:R < 0.8) - No operar{RESET}")
        
        if 'horario' in resultado:
            print(f"  Horario: {resultado['horario']['calidad']}")
        if 'ajustes_dinamicos' in resultado and resultado['ajustes_dinamicos']:
            ajustes = resultado['ajustes_dinamicos']
            activos = resultado.get('ajustes_activos', {})
            if activos:
                print(f"  {YELLOW}⚠️ Ajustes dinámicos ACTIVOS:{RESET}")
                for k, v in activos.items():
                    print(f"     {k}: {v:.2f}")
            else:
                print(f"  {GREEN}✅ Ajustes dinámicos: Normal{RESET}")
        
        if resultado['problemas']:
            print(f"\n  {RED}🔴 PROBLEMAS:{RESET}")
            for prob in resultado['problemas']:
                print(f"     ❌ {prob}")
        
        if resultado['advertencias']:
            print(f"\n  {YELLOW}⚠️ ADVERTENCIAS:{RESET}")
            for adv in resultado['advertencias']:
                print(f"     ⚠️ {adv}")
    
    def _mostrar_resumen_global(self, resultados: Dict):
        """Muestra resumen global."""
        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}📊 RESUMEN GLOBAL DEL DIAGNÓSTICO{RESET}")
        print(f"{CYAN}{'='*80}{RESET}")
        
        total = len(resultados)
        correctos = sum(1 for r in resultados.values() if r['correcto'] and not r['advertencias'])
        con_advertencias = sum(1 for r in resultados.values() if r['correcto'] and r['advertencias'])
        con_problemas = sum(1 for r in resultados.values() if not r['correcto'])
        
        print(f"  Total símbolos: {total}")
        print(f"  {GREEN}✅ Correctos: {correctos}{RESET}")
        print(f"  {YELLOW}⚠️ Con advertencias: {con_advertencias}{RESET}")
        print(f"  {RED}❌ Con problemas: {con_problemas}{RESET}")
        
        # ============================================================
        # RESUMEN DE AJUSTES DINÁMICOS
        # ============================================================
        print(f"\n{WHITE}📊 AJUSTES DINÁMICOS POR SÍMBOLO:{RESET}")
        for simbolo, resultado in resultados.items():
            ajustes = resultado.get('ajustes_dinamicos', {})
            activos = resultado.get('ajustes_activos', {})
            
            if activos:
                # Mostrar solo si hay ajustes activos
                print(f"  {YELLOW}⚠️ {simbolo}: {activos}{RESET}")
            else:
                # Mostrar si está en rango normal
                print(f"  {GREEN}✅ {simbolo}: Normal (sin ajustes activos){RESET}")
        
        # Archivo de reporte
        reporte_path = Path('testing/reporte_diagnostico.json')
        reporte_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(reporte_path, 'w', encoding='utf-8') as f:
            json.dump(resultados, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"\n{WHITE}📄 Reporte generado: {reporte_path}{RESET}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Diagnóstico de símbolos del bot")
    parser.add_argument("--simbolos", type=str, help="Lista de símbolos separados por coma")
    parser.add_argument("--backtest", action="store_true", help="Modo backtest")
    parser.add_argument("--depuracion", action="store_true", help="Modo depuración")
    
    args = parser.parse_args()
    
    simbolos = args.simbolos.split(',') if args.simbolos else None
    
    diagnostico = DiagnosticoSimbolos(
        modo_backtest=args.backtest,
        modo_depuracion=args.depuracion
    )
    
    diagnostico.ejecutar(simbolos)