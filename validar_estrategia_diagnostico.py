#!/usr/bin/env python3
"""
validar_estrategia_diagnostico.py (V4.0 - DIAGNÓSTICO)
Versión con logs detallados para identificar dónde falla la estrategia.

EJECUTAR:
python validar_estrategia_diagnostico.py --simbolo EURUSD --velas 500
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path
import logging
import json
import sys
import os
import traceback

# Configurar logging detallado
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-7s | %(message)s'
)
logger = logging.getLogger('ValidarEstrategiaDiagnostico')

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))


class ObtenedorDatosDiagnostico:
    """Obtiene datos con logs detallados."""
    
    def __init__(self, mt5: Any = None, almacen: Any = None):
        self.mt5 = mt5
        self.almacen = almacen
        self.logger = logging.getLogger('Diagnostico.Datos')
    
    def obtener_timeframe(self, simbolo: str, timeframe: int, 
                         n_velas: int = 500) -> Optional[pd.DataFrame]:
        """Obtiene datos de un timeframe específico."""
        self.logger.info(f"📥 Obteniendo {simbolo} TF{timeframe} ({n_velas} velas)...")
        
        if self.mt5:
            try:
                df = self.mt5.obtener_datos(simbolo, n_velas=n_velas, timeframe=timeframe)
                if df is not None and len(df) > 0:
                    self.logger.info(f"   ✅ TF{timeframe}: {len(df)} velas desde MT5")
                    return df
            except Exception as e:
                self.logger.warning(f"   ⚠️ MT5 error: {e}")
        
        if self.almacen:
            try:
                df = self.almacen.obtener_datos_historicos(simbolo, timeframe)
                if df is not None and len(df) > 0:
                    self.logger.info(f"   ✅ TF{timeframe}: {len(df)} velas desde SQLite")
                    return df
            except Exception:
                pass
        
        self.logger.warning(f"   ❌ No se obtuvieron datos para TF{timeframe}")
        return None


class SimuladorDiagnostico:
    """Simulador con logs detallados paso a paso."""
    
    def __init__(self, capital_inicial: float = 1000.0, riesgo_pct: float = 0.01):
        self.capital_inicial = capital_inicial
        self.riesgo_pct = riesgo_pct
        self.logger = logging.getLogger('Diagnostico.Simulador')
        
        # Contadores para diagnóstico
        self.contadores = {
            'velas_procesadas': 0,
            'filtro_rapido_pasa': 0,
            'filtro_rapido_falla': 0,
            'filtro_medio_pasa': 0,
            'filtro_medio_falla': 0,
            'direccion_determinada': 0,
            'direccion_neutral': 0,
            'modo_seleccionado': 0,
            'modo_no_seleccionado': 0,
            'sniper_dispara': 0,
            'sniper_no_dispara': 0,
            'operaciones_ejecutadas': 0,
        }
        
        # Almacenar razones de rechazo
        self.rechazos_detallados = {}
    
    def simular(self, dataframes: Dict[int, pd.DataFrame], simbolo: str) -> Dict:
        """Simula con logs detallados."""
        
        self.logger.info("=" * 70)
        self.logger.info(f"🔍 INICIANDO DIAGNÓSTICO PARA {simbolo}")
        self.logger.info("=" * 70)
        
        # Verificar datos
        if 60 not in dataframes:
            self.logger.error("❌ No hay datos H1")
            return {'valido': False, 'razon': 'Sin datos H1'}
        
        df_h1 = dataframes[60]
        df_m5 = dataframes.get(5)
        df_h4 = dataframes.get(240)
        df_d1 = dataframes.get(1440)
        
        self.logger.info(f"📊 Datos disponibles:")
        self.logger.info(f"   H1: {len(df_h1)} velas")
        self.logger.info(f"   M5: {len(df_m5) if df_m5 is not None else 0} velas")
        self.logger.info(f"   H4: {len(df_h4) if df_h4 is not None else 0} velas")
        self.logger.info(f"   D1: {len(df_d1) if df_d1 is not None else 0} velas")
        
        # Intentar cargar módulos del bot
        modulos = self._cargar_modulos()
        
        if not modulos['disponible']:
            self.logger.warning("⚠️ Módulos del bot NO disponibles, usando modo simplificado")
            return self._simular_simplificado(df_h1, simbolo)
        
        self.logger.info("✅ Módulos del bot cargados correctamente")
        
        # Variables de simulación
        capital = self.capital_inicial
        operaciones = []
        
        # Limitar para diagnóstico rápido
        max_velas = min(len(df_h1) - 10, 500)
        
        self.logger.info(f"📊 Analizando {max_velas - 100} velas (100 a {max_velas})")
        self.logger.info("")
        
        # Bucle principal
        for i in range(100, max_velas):
            self.contadores['velas_procesadas'] += 1
            
            try:
                df_h1_slice = df_h1.iloc[:i+1].copy()
                precio_actual = df_h1_slice['Close'].iloc[-1]
                fecha_actual = df_h1_slice.index[-1]
                
                # Cada 50 velas, mostrar progreso
                if i % 50 == 0:
                    self.logger.info(f"📊 Procesando vela {i}/{max_velas}...")
                
                # ============================================================
                # PASO 1: ANÁLISIS RÁPIDO (Capa 1)
                # ============================================================
                
                try:
                    rapido = modulos['analisis_capas'].analisis_rapido(df_h1_slice, simbolo, precio_actual)
                except Exception as e:
                    self.logger.debug(f"Error en análisis rápido: {e}")
                    continue
                
                if not rapido.pasa_filtro:
                    self.contadores['filtro_rapido_falla'] += 1
                    razon = rapido.razon_rechazo if hasattr(rapido, 'razon_rechazo') else 'Desconocida'
                    self._registrar_rechazo('RAPIDO', razon)
                    continue
                
                self.contadores['filtro_rapido_pasa'] += 1
                
                # ============================================================
                # PASO 2: DETECTAR NIVELES
                # ============================================================
                
                try:
                    from analysis.niveles import NivelTracker
                    tracker = NivelTracker(modo_backtest=True)
                    niveles = tracker.detectar_y_actualizar_niveles(
                        simbolo=simbolo,
                        df=df_h1_slice,
                        precio_actual=precio_actual
                    )
                except Exception as e:
                    self.logger.debug(f"Error detectando niveles: {e}")
                    niveles = {'soportes': [], 'resistencias': []}
                
                # ============================================================
                # PASO 3: ANÁLISIS MEDIO (Capa 2)
                # ============================================================
                
                try:
                    medio = modulos['analisis_capas'].analisis_medio(df_h1_slice, simbolo, rapido, niveles)
                except Exception as e:
                    self.logger.debug(f"Error en análisis medio: {e}")
                    continue
                
                if medio is None or not medio.pasa_filtro:
                    self.contadores['filtro_medio_falla'] += 1
                    razon = medio.razon_rechazo if medio else 'None'
                    self._registrar_rechazo('MEDIO', razon)
                    continue
                
                self.contadores['filtro_medio_pasa'] += 1
                
                # ============================================================
                # PASO 4: ANÁLISIS PESADO (Capa 3)
                # ============================================================
                
                try:
                    df_h4_slice = None
                    if df_h4 is not None:
                        idx_h4 = df_h4.index.get_indexer([fecha_actual], method='ffill')[0]
                        if idx_h4 >= 0:
                            df_h4_slice = df_h4.iloc[:idx_h4+1].copy()
                    
                    df_d1_slice = None
                    if df_d1 is not None:
                        idx_d1 = df_d1.index.get_indexer([fecha_actual], method='ffill')[0]
                        if idx_d1 >= 0:
                            df_d1_slice = df_d1.iloc[:idx_d1+1].copy()
                    
                    pesado = modulos['analisis_capas'].analisis_pesado(
                        df_h1_slice, simbolo, df_h4_slice, df_d1_slice, niveles, medio
                    )
                except Exception as e:
                    self.logger.debug(f"Error en análisis pesado: {e}")
                    continue
                
                # ============================================================
                # PASO 5: SCORE H1
                # ============================================================
                
                try:
                    from analysis.scoring import ScoreEngine
                    score_engine = ScoreEngine(modo_backtest=True)
                    score_h1 = score_engine.calcular_score_h1(
                        score_estructura=pesado.score_estructura,
                        score_momentum=pesado.score_momentum,
                        score_confluencia=pesado.score_confluencia,
                        score_institucional=pesado.score_institucional,
                        simbolo=simbolo
                    ).score
                except Exception:
                    score_h1 = 50
                
                # ============================================================
                # PASO 6: RÉGIMEN
                # ============================================================
                
                try:
                    regimen_data = modulos['regimen_filter'].clasificar(simbolo, df_h4_slice, df_h1_slice)
                    regimen = regimen_data.regimen.value
                except Exception:
                    regimen = 'INCERTO'
                
                # ============================================================
                # PASO 7: DIRECCIÓN
                # ============================================================
                
                direccion = self._determinar_direccion(medio, pesado, regimen)
                
                if direccion == 'NEUTRAL':
                    self.contadores['direccion_neutral'] += 1
                    self._registrar_rechazo('DIRECCION', 'NEUTRAL')
                    continue
                
                self.contadores['direccion_determinada'] += 1
                
                # ============================================================
                # PASO 8: SELECCIONAR MODO
                # ============================================================
                
                try:
                    modo_obj, razon_modo, _ = modulos['modo_selector'].seleccionar_modo(
                        simbolo=simbolo,
                        regimen=regimen,
                        direccion=direccion,
                        score_h1=score_h1,
                        nivel_usado=medio.soporte_cercano if direccion == 'COMPRA' else medio.resistencia_cercana,
                        en_nivel_clave=medio.en_nivel_clave,
                        volumen_relativo=rapido.volumen_relativo,
                        patron_calidad=pesado.calidad_patron if pesado else 0
                    )
                except Exception as e:
                    self.logger.debug(f"Error seleccionando modo: {e}")
                    modo_obj = None
                
                if modo_obj is None:
                    self.contadores['modo_no_seleccionado'] += 1
                    self._registrar_rechazo('MODO', razon_modo if 'razon_modo' in locals() else 'Desconocido')
                    continue
                
                self.contadores['modo_seleccionado'] += 1
                modo = modo_obj.value
                
                # ============================================================
                # PASO 9: SNIPER
                # ============================================================
                
                # Obtener datos M5
                df_m5_slice = None
                if df_m5 is not None:
                    idx_m5 = df_m5.index.get_indexer([fecha_actual], method='ffill')[0]
                    if idx_m5 >= 0:
                        df_m5_slice = df_m5.iloc[:idx_m5+1].copy()
                
                if df_m5_slice is None or len(df_m5_slice) < 20:
                    self.contadores['sniper_no_dispara'] += 1
                    self._registrar_rechazo('SNIPER', 'Sin datos M5')
                    continue
                
                contexto_h1 = {
                    'score': score_h1,
                    'regimen': regimen,
                    'direccion': direccion,
                    'en_nivel_clave': medio.en_nivel_clave,
                    'soporte_cercano': medio.soporte_cercano,
                    'resistencia_cercana': medio.resistencia_cercana,
                    'soporte_hits': medio.soporte_hits,
                    'resistencia_hits': medio.resistencia_hits,
                    'adx': medio.adx,
                    'rsi': medio.rsi,
                    'niveles': niveles,
                }
                
                try:
                    resultado_sniper = modulos['sniper'].evaluar_sniper_optimizado(
                        simbolo=simbolo,
                        df_m5=df_m5_slice,
                        precio_actual=precio_actual,
                        direccion=direccion,
                        estado_pipeline=None,
                        analisis_rapido=rapido,
                        analisis_medio=medio,
                        ejecutar_pesado=False,
                        contexto_h1=contexto_h1,
                        calidad_horario='REGULAR'
                    )
                except Exception as e:
                    self.logger.debug(f"Error en sniper: {e}")
                    resultado_sniper = None
                
                if resultado_sniper is None:
                    self.contadores['sniper_no_dispara'] += 1
                    self._registrar_rechazo('SNIPER', 'No disparó')
                    continue
                
                self.contadores['sniper_dispara'] += 1
                
                # ============================================================
                # PASO 10: EJECUTAR OPERACIÓN
                # ============================================================
                
                sl = resultado_sniper.get('sl', 0)
                tp = resultado_sniper.get('tp', 0)
                
                if sl > 0 and tp > 0:
                    # Calcular lotes
                    pip_val = self._obtener_pip_val(simbolo)
                    sl_dist = abs(precio_actual - sl)
                    
                    if sl_dist > 0:
                        lotes = (capital * self.riesgo_pct) / (sl_dist / pip_val * 100000)
                        lotes = max(0.01, min(0.10, round(lotes, 2)))
                    else:
                        lotes = 0.01
                    
                    # Simular resultado
                    resultado_op = self._simular_operacion(
                        df_h1, i, precio_actual, sl, tp, direccion, lotes, simbolo
                    )
                    
                    op = {
                        'fecha': fecha_actual,
                        'direccion': direccion,
                        'modo': modo,
                        'regimen': regimen,
                        'score': score_h1,
                        'precio_entrada': precio_actual,
                        'sl': sl,
                        'tp': tp,
                        'lotes': lotes,
                        'pnl': resultado_op['pnl'],
                        'resultado': resultado_op['resultado'],
                        'bars_held': resultado_op['bars_held'],
                    }
                    
                    operaciones.append(op)
                    capital += op['pnl']
                    self.contadores['operaciones_ejecutadas'] += 1
                    
                    self.logger.info(f"🎯 OPERACIÓN #{len(operaciones)}: {direccion} {modo} | PnL: ${op['pnl']:.2f} | {resultado_op['resultado']}")
                
            except Exception as e:
                self.logger.debug(f"Error en iteración {i}: {e}")
                continue
        
        # ============================================================
        # MOSTRAR ESTADÍSTICAS DE DIAGNÓSTICO
        # ============================================================
        
        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("📊 ESTADÍSTICAS DE DIAGNÓSTICO")
        self.logger.info("=" * 70)
        self.logger.info(f"   Velas procesadas: {self.contadores['velas_procesadas']}")
        self.logger.info(f"   Filtro Rápido → Pasa: {self.contadores['filtro_rapido_pasa']} | Falla: {self.contadores['filtro_rapido_falla']}")
        self.logger.info(f"   Filtro Medio → Pasa: {self.contadores['filtro_medio_pasa']} | Falla: {self.contadores['filtro_medio_falla']}")
        self.logger.info(f"   Dirección → Determinada: {self.contadores['direccion_determinada']} | Neutral: {self.contadores['direccion_neutral']}")
        self.logger.info(f"   Modo → Seleccionado: {self.contadores['modo_seleccionado']} | No seleccionado: {self.contadores['modo_no_seleccionado']}")
        self.logger.info(f"   Sniper → Dispara: {self.contadores['sniper_dispara']} | No dispara: {self.contadores['sniper_no_dispara']}")
        self.logger.info(f"   Operaciones ejecutadas: {self.contadores['operaciones_ejecutadas']}")
        
        # Mostrar razones de rechazo más comunes
        self.logger.info("")
        self.logger.info("📋 RAZONES DE RECHAZO MÁS COMUNES:")
        
        for etapa, razones in sorted(self.rechazos_detallados.items()):
            total = sum(razones.values())
            self.logger.info(f"   {etapa}: {total} rechazos")
            for razon, count in sorted(razones.items(), key=lambda x: x[1], reverse=True)[:3]:
                self.logger.info(f"      - {razon}: {count}")
        
        # Métricas finales
        self.logger.info("")
        self.logger.info("📈 RESULTADOS DE LA SIMULACIÓN:")
        self.logger.info(f"   Operaciones: {len(operaciones)}")
        self.logger.info(f"   Capital final: ${capital:.2f}")
        
        return {
            'simbolo': simbolo,
            'n_operaciones': len(operaciones),
            'capital_final': capital,
            'contadores': self.contadores,
            'rechazos': self.rechazos_detallados,
            'operaciones': operaciones,
        }
    
    def _cargar_modulos(self) -> Dict:
        """Carga los módulos del bot."""
        resultado = {'disponible': False}
        
        try:
            from analysis.capas import AnalisisPorCapas
            from analysis.regimen import MarketRegimeFilter
            from trading.modos import ModoSelector
            from trading.timer import EntryTimer
            from trading.stops import GestorStops
            from trading.sniper.sniper_checklist import SniperChecklist
            
            analisis_capas = AnalisisPorCapas(modo_backtest=True)
            regimen_filter = MarketRegimeFilter(modo_backtest=True)
            modo_selector = ModoSelector(modo_backtest=True)
            entry_timer = EntryTimer(modo_backtest=True)
            gestor_stops = GestorStops(modo_backtest=True)
            
            sniper = SniperChecklist(
                pipeline=None,
                analisis_capas=analisis_capas,
                modo_selector=modo_selector,
                entry_timer=entry_timer,
                gestor_stops=gestor_stops,
                modo_backtest=True
            )
            
            resultado = {
                'disponible': True,
                'analisis_capas': analisis_capas,
                'regimen_filter': regimen_filter,
                'modo_selector': modo_selector,
                'entry_timer': entry_timer,
                'gestor_stops': gestor_stops,
                'sniper': sniper,
            }
            
        except ImportError as e:
            self.logger.warning(f"⚠️ Error importando módulos: {e}")
        except Exception as e:
            self.logger.warning(f"⚠️ Error cargando módulos: {e}")
        
        return resultado
    
    def _registrar_rechazo(self, etapa: str, razon: str):
        """Registra una razón de rechazo para diagnóstico."""
        if etapa not in self.rechazos_detallados:
            self.rechazos_detallados[etapa] = {}
        
        # Truncar razones largas
        if len(razon) > 50:
            razon = razon[:47] + "..."
        
        self.rechazos_detallados[etapa][razon] = self.rechazos_detallados[etapa].get(razon, 0) + 1
    
    def _determinar_direccion(self, medio, pesado, regimen) -> str:
        """Determina dirección basada en análisis."""
        if medio is None:
            return 'NEUTRAL'
        
        bullish = 0
        bearish = 0
        
        if medio.rsi > 55:
            bullish += 1
        elif medio.rsi < 45:
            bearish += 1
        
        if medio.macd_histogram > 0:
            bullish += 1
        elif medio.macd_histogram < 0:
            bearish += 1
        
        if medio.adx > 25:
            if medio.sma20 > medio.sma50:
                bullish += 2
            else:
                bearish += 2
        
        if pesado:
            if pesado.divergencia_rsi == 'BULLISH':
                bullish += 2
            elif pesado.divergencia_rsi == 'BEARISH':
                bearish += 2
        
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL']:
            bullish += 2
        elif regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL']:
            bearish += 2
        
        if bullish > bearish + 1:
            return 'COMPRA'
        elif bearish > bullish + 1:
            return 'VENTA'
        return 'NEUTRAL'
    
    def _simular_operacion(self, df: pd.DataFrame, index: int,
                           precio_entrada: float, sl: float, tp: float,
                           direccion: str, lotes: float, simbolo: str) -> Dict:
        """Simula el resultado de una operación."""
        
        if direccion == 'COMPRA':
            if sl >= precio_entrada or tp <= precio_entrada:
                return {'pnl': 0, 'resultado': 'INVALIDO', 'bars_held': 0}
        else:
            if sl <= precio_entrada or tp >= precio_entrada:
                return {'pnl': 0, 'resultado': 'INVALIDO', 'bars_held': 0}
        
        max_bars = 100
        pip_val = self._obtener_pip_val(simbolo)
        
        for j in range(index + 1, min(len(df), index + max_bars + 1)):
            try:
                high = df['High'].iloc[j]
                low = df['Low'].iloc[j]
            except Exception:
                continue
            
            if direccion == 'COMPRA':
                if low <= sl:
                    pnl = (sl - precio_entrada) / pip_val * lotes * 100000
                    return {'pnl': pnl, 'resultado': 'SL', 'bars_held': j - index}
                if high >= tp:
                    pnl = (tp - precio_entrada) / pip_val * lotes * 100000
                    return {'pnl': pnl, 'resultado': 'TP', 'bars_held': j - index}
            else:
                if high >= sl:
                    pnl = (precio_entrada - sl) / pip_val * lotes * 100000
                    return {'pnl': pnl, 'resultado': 'SL', 'bars_held': j - index}
                if low <= tp:
                    pnl = (precio_entrada - tp) / pip_val * lotes * 100000
                    return {'pnl': pnl, 'resultado': 'TP', 'bars_held': j - index}
        
        precio_final = df['Close'].iloc[min(len(df) - 1, index + max_bars)]
        
        if direccion == 'COMPRA':
            pnl = (precio_final - precio_entrada) / pip_val * lotes * 100000
        else:
            pnl = (precio_entrada - precio_final) / pip_val * lotes * 100000
        
        return {'pnl': pnl, 'resultado': 'TIMEOUT', 'bars_held': max_bars}
    
    def _obtener_pip_val(self, simbolo: str) -> float:
        """Obtiene pip_val para el símbolo."""
        simbolo_upper = simbolo.upper()
        if 'JPY' in simbolo_upper:
            return 0.01
        if 'XAU' in simbolo_upper:
            return 0.10
        if 'XAG' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001


def validar_con_diagnostico(simbolo: str = 'EURUSD',
                           n_velas: int = 500,
                           mt5: Any = None,
                           almacen: Any = None) -> Dict:
    """Función principal con diagnóstico."""
    
    logger.info("=" * 70)
    logger.info(f"🔍 DIAGNÓSTICO DE ESTRATEGIA PARA {simbolo}")
    logger.info("=" * 70)
    
    # 1. Obtener datos
    logger.info("📥 1. Obteniendo datos históricos...")
    obtenedor = ObtenedorDatosDiagnostico(mt5=mt5, almacen=almacen)
    
    dataframes = {}
    timeframes = [60, 5, 240, 1440]
    
    for tf in timeframes:
        n = n_velas * 12 if tf == 5 else n_velas
        df = obtenedor.obtener_timeframe(simbolo, tf, n)
        if df is not None:
            dataframes[tf] = df
    
    if 60 not in dataframes:
        logger.error("❌ No se pudieron obtener datos H1")
        return {'valido': False, 'razon': 'Sin datos H1'}
    
    # 2. Ejecutar simulación con diagnóstico
    logger.info("📊 2. Ejecutando simulación con diagnóstico...")
    simulador = SimuladorDiagnostico(capital_inicial=1000.0, riesgo_pct=0.01)
    resultado = simulador.simular(dataframes, simbolo)
    
    return resultado


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Diagnóstico de estrategia')
    parser.add_argument('--simbolo', '-s', default='EURUSD', help='Símbolo a validar')
    parser.add_argument('--velas', '-n', type=int, default=500, help='Número de velas H1')
    
    args = parser.parse_args()
    
    # Intentar cargar módulos
    mt5 = None
    almacen = None
    
    try:
        from mt5.conector_mt5 import ConectorPepperstone
        from config.settings import Config
        
        config = Config()
        mt5 = ConectorPepperstone(
            login=config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
            demo=config.MT5_DEMO
        )
        mt5.conectar()
        logger.info("✅ Conectado a MT5")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo conectar a MT5: {e}")
    
    try:
        from data.almacenamiento_sqlite import AlmacenamientoSQLite
        from pathlib import Path
        almacen = AlmacenamientoSQLite(base_dir=Path("data"))
    except Exception as e:
        logger.warning(f"⚠️ No se pudo cargar almacenamiento: {e}")
    
    resultado = validar_con_diagnostico(args.simbolo, args.velas, mt5, almacen)
    
    # Guardar diagnóstico
    ruta_diagnostico = Path("data") / f"diagnostico_{args.simbolo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    ruta_diagnostico.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(ruta_diagnostico, 'w', encoding='utf-8') as f:
            json.dump(resultado, f, indent=2, default=str)
        logger.info(f"💾 Diagnóstico guardado en: {ruta_diagnostico}")
    except Exception as e:
        logger.warning(f"⚠️ Error guardando diagnóstico: {e}")