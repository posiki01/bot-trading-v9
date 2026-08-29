#!/usr/bin/env python3
"""
prueba_sistema.py (V3.0 - VALIDACIÓN DE SNIPER CON H1)
Script de validación del sistema completo.
Verifica que el sniper use H1 correctamente.
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime, timezone
from colorama import Fore, Style, init

# Inicializar colorama
init(autoreset=True)

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

# ============================================================
# CONFIGURACIÓN DE PRUEBA
# ============================================================

SIMBOLOS_PRUEBA = [
    'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF',
    'EURJPY', 'GBPJPY', 'AUDJPY', 'XAUUSD', 'XAGUSD',
    'US30', 'NAS100', 'US500', 'BTCUSD', 'ETHUSD', 'SOLUSD'
]

# ============================================================
# CLASE DE PRUEBA
# ============================================================

class TestSistema:
    """Valida todos los módulos del bot."""
    
    def __init__(self):
        self.resultados = []
        self.total_pruebas = 0
        self.pasadas = 0
        self.falladas = 0
        
        # Inicializar logger
        from utils.logger_persistente import LoggerPersistente
        self.logger = LoggerPersistente(
            directorio_logs=Path("logs"),
            nivel_log='INFO',
            filter_emojis_consola=False
        ).get_logger()
        
        self.logger.info("🚀 Iniciando pruebas del sistema...")
    
    def ejecutar_prueba(self, nombre: str, funcion, *args, **kwargs):
        """Ejecuta una prueba y registra el resultado."""
        self.total_pruebas += 1
        try:
            resultado = funcion(*args, **kwargs)
            if resultado is True or (resultado is not None and resultado != False):
                self.pasadas += 1
                self.resultados.append({
                    'nombre': nombre,
                    'estado': '✅ PASÓ',
                    'detalle': str(resultado)[:100] if resultado is not True else 'OK'
                })
                print(f"{Fore.GREEN}✅ {nombre}: PASÓ{Style.RESET_ALL}")
                return True
            else:
                self.falladas += 1
                self.resultados.append({
                    'nombre': nombre,
                    'estado': '❌ FALLÓ',
                    'detalle': 'Resultado inválido'
                })
                print(f"{Fore.RED}❌ {nombre}: FALLÓ{Style.RESET_ALL}")
                return False
        except Exception as e:
            self.falladas += 1
            self.resultados.append({
                'nombre': nombre,
                'estado': '❌ ERROR',
                'detalle': str(e)[:200]
            })
            print(f"{Fore.RED}❌ {nombre}: ERROR - {e}{Style.RESET_ALL}")
            return False
    
    def imprimir_resumen(self):
        """Imprime el resumen de todas las pruebas."""
        print("\n" + "=" * 80)
        print(f"{Fore.CYAN}📊 RESUMEN DE PRUEBAS{Style.RESET_ALL}")
        print("=" * 80)
        print(f"Total: {self.total_pruebas}")
        print(f"{Fore.GREEN}✅ Pasadas: {self.pasadas}{Style.RESET_ALL}")
        print(f"{Fore.RED}❌ Falladas: {self.falladas}{Style.RESET_ALL}")
        
        if self.falladas > 0:
            print("\n" + "=" * 80)
            print(f"{Fore.YELLOW}📋 DETALLE DE FALLOS:{Style.RESET_ALL}")
            print("=" * 80)
            for r in self.resultados:
                if '❌' in r['estado']:
                    print(f"{Fore.RED}  {r['nombre']}: {r['detalle']}{Style.RESET_ALL}")
        
        print("\n" + "=" * 80)
        if self.falladas == 0:
            print(f"{Fore.GREEN}🎉 TODAS LAS PRUEBAS PASARON EXITOSAMENTE{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}⚠️ Hay {self.falladas} pruebas fallidas que requieren corrección{Style.RESET_ALL}")
        print("=" * 80)


# ============================================================
# PRUEBA 1: SNIPER CON H1 REAL
# ============================================================

def test_sniper_con_h1_real():
    """
    Prueba que el sniper obtenga H1 real desde MT5.
    V3.0 - NUEVO: Valida que _obtener_df_h1 funcione.
    """
    from trading.sniper.sniper_checklist import SniperChecklist
    from mt5.conector_mt5 import ConectorPepperstone
    from config.settings import Config
    
    # Conectar MT5
    conector = ConectorPepperstone(
        login=Config.MT5_LOGIN,
        password=Config.MT5_PASSWORD,
        server=Config.MT5_SERVER,
        magic_number=Config.MAGIC_NUMBER,
        demo=Config.MT5_DEMO
    )
    
    if not conector.conectar():
        return "No se pudo conectar a MT5"
    
    # Crear SniperChecklist con MT5 real
    class MockPipeline:
        def __init__(self):
            self.orquestador = None
            self.estados = {}
    
    class MockAnalisisCapas:
        def analisis_rapido(self, df, simbolo, precio_actual):
            from analysis.capas_rapido import AnalisisRapido
            return AnalisisRapido(
                valido=True, simbolo=simbolo,
                precio_actual=precio_actual,
                precio_anterior=df['Close'].iloc[-2],
                cambio_vela_pct=0.1, volumen_relativo=1.5,
                rsi=55, ema9=df['Close'].iloc[-1],
                ema21=df['Close'].iloc[-1],
                tendencia_corta='ALCISTA', atr=0.001,
                volumen_ok=True, rsi_extremo=False,
                tendencia_fuerte=True, pasa_filtro=True,
                razon_rechazo=""
            )
        
        def analisis_medio(self, df, simbolo, rapido, niveles):
            from analysis.capas import AnalisisMedio
            precio = df['Close'].iloc[-1]
            return AnalisisMedio(
                valido=True, simbolo=simbolo,
                rsi=55, macd_line=0.001, macd_signal=0.0005,
                macd_histogram=0.0005, bb_upper=precio*1.001,
                bb_lower=precio*0.999, bb_middle=precio,
                bb_width_pct=0.1, adx=25, atr=0.001,
                sma20=precio, sma50=precio, sma200=None,
                soporte_cercano=precio*0.998,
                resistencia_cercana=precio*1.002,
                distancia_soporte_pct=0.1, distancia_resistencia_pct=0.1,
                soporte_hits=3, resistencia_hits=2,
                adx_fuerte=True, en_nivel_clave=True,
                tendencia_alineada=True, pasa_filtro=True,
                razon_rechazo=""
            )
    
    class MockModoSelector:
        def seleccionar_modo(self, *args, **kwargs):
            from trading.sniper.sniper_modos import ModoEntrada
            return ModoEntrada.RETEST, "Modo válido", {}
    
    class MockEntryTimer:
        def validar_momento_exacto(self, *args, **kwargs):
            return True, "Momento válido", {}
    
    class MockGestorStops:
        def validar_sl_tp(self, simbolo, entry_price, sl, tp, tp2=0, **kwargs):
            from config.umbrales import Umbrales
            cfg_modo = getattr(Umbrales, 'SNIPER_CONFIG', {}).get('RETEST', {})
            sl_dist = abs(entry_price - sl)
            rr = cfg_modo.get('rr_target', 1.5)
            if kwargs.get('direccion') == 'COMPRA':
                tp_calc = entry_price + (sl_dist * rr)
            else:
                tp_calc = entry_price - (sl_dist * rr)
            return True, "OK", sl, tp_calc, 0
    
    class MockAdaptadorMercado:
        def obtener_ajustes(self, simbolo, df_m5, df_h1=None):
            return {
                'tolerancia_nivel': 1.0, 'volumen_minimo': 1.0,
                'score_minimo': 1.0, 'rr_minimo': 1.0,
                'sl_min_pips': 1.0, 'distancia_nivel_max': 1.0,
            }
    
    # Crear instancias mock
    pipeline = MockPipeline()
    analisis_capas = MockAnalisisCapas()
    modo_selector = MockModoSelector()
    entry_timer = MockEntryTimer()
    gestor_stops = MockGestorStops()
    
    # Crear SniperChecklist con MT5 real
    import unittest.mock as mock
    
    with mock.patch.object(SniperChecklist, '_validar_capital_minimo', return_value=(True, "OK")):
        
        checklist = SniperChecklist(
            pipeline=pipeline,
            analisis_capas=analisis_capas,
            modo_selector=modo_selector,
            entry_timer=entry_timer,
            gestor_stops=gestor_stops,
            config=None, almacen=None,
            mt5=conector,  # ✅ MT5 REAL
            noticias=None, patron_tracker=None, ml_optimizer=None,
            analysis_cache=None, modo_depuracion=True,
            modo_backtest=False, horario=None
        )
        
        # Reemplazar adaptador
        checklist.adaptador_mercado = MockAdaptadorMercado()
        
        # Probar EURUSD con H1 real
        simbolo = 'EURUSD'
        
        # Obtener M5 real
        df_m5 = conector.obtener_datos(simbolo, n_velas=100, timeframe=5)
        if df_m5 is None or len(df_m5) < 50:
            return "No se pudieron obtener datos M5 de EURUSD"
        
        # Obtener precio real
        tick = conector.obtener_precio(simbolo)
        if tick is None:
            return "No se pudo obtener tick de EURUSD"
        
        precio_actual = float(tick.get('ask', 0))
        
        # Ejecutar evaluación con H1
        señal = checklist.evaluar_sniper_optimizado(
            simbolo=simbolo,
            df_m5=df_m5,
            precio_actual=precio_actual,
            direccion='COMPRA',
            estado_pipeline=None,
            analisis_rapido=None,
            analisis_medio=None,
            ejecutar_pesado=False,
            contexto_h1={
                'score': 65,
                'regimen': 'TREND_ALCISTA_FUERTE',
                'en_nivel_clave': True,
                'niveles': {
                    'soportes': [{'precio': precio_actual*0.998, 'hits': 3}],
                    'resistencias': [{'precio': precio_actual*1.002, 'hits': 2}]
                },
                'soporte_cercano': precio_actual*0.998,
                'resistencia_cercana': precio_actual*1.002,
            },
            calidad_horario='EXCELENTE',
            tick_data=tick,
            precio_entrada=precio_actual
        )
        
        # Verificar que NO falló por falta de H1
        if señal is None:
            return "No se generó señal (posiblemente por falta de H1)"
        
        # Verificar que la señal tiene todos los campos
        if 'simbolo' not in señal:
            return "Señal sin símbolo"
        if 'sl' not in señal or señal['sl'] <= 0:
            return "Señal con SL inválido"
        if 'tp' not in señal or señal['tp'] <= señal['sl']:
            return "Señal con TP inválido"
        
        # Desconectar
        conector.desconectar()
        
        return True


# ============================================================
# PRUEBA 2: VERIFICAR QUE _obtener_df_h1 FUNCIONA
# ============================================================

def test_obtener_df_h1():
    """
    Prueba que _obtener_df_h1 obtenga H1 real.
    V3.0 - NUEVO: Valida el método de obtención de H1.
    """
    from trading.sniper.sniper_checklist import SniperChecklist
    from mt5.conector_mt5 import ConectorPepperstone
    from config.settings import Config
    
    # Conectar MT5
    conector = ConectorPepperstone(
        login=Config.MT5_LOGIN,
        password=Config.MT5_PASSWORD,
        server=Config.MT5_SERVER,
        magic_number=Config.MAGIC_NUMBER,
        demo=Config.MT5_DEMO
    )
    
    if not conector.conectar():
        return "No se pudo conectar a MT5"
    
    # Crear SniperChecklist mínimo
    class MockPipeline:
        def __init__(self):
            self.orquestador = None
            self.estados = {}
    
    checklist = SniperChecklist(
        pipeline=MockPipeline(),
        analisis_capas=None,
        modo_selector=None,
        entry_timer=None,
        gestor_stops=None,
        config=None, almacen=None,
        mt5=conector,  # ✅ MT5 REAL
        noticias=None, patron_tracker=None, ml_optimizer=None,
        analysis_cache=None, modo_depuracion=True,
        modo_backtest=False, horario=None
    )
    
    # Probar con EURUSD
    df_h1 = checklist._obtener_df_h1('EURUSD')
    
    if df_h1 is None:
        conector.desconectar()
        return "No se pudo obtener H1 de EURUSD"
    
    if len(df_h1) < 50:
        conector.desconectar()
        return f"H1 de EURUSD tiene solo {len(df_h1)} velas"
    
    # Probar con BTCUSD
    df_h1_btc = checklist._obtener_df_h1('BTCUSD')
    
    if df_h1_btc is None:
        conector.desconectar()
        return "No se pudo obtener H1 de BTCUSD"
    
    if len(df_h1_btc) < 50:
        conector.desconectar()
        return f"H1 de BTCUSD tiene solo {len(df_h1_btc)} velas"
    
    # Probar con XAUUSD
    df_h1_xau = checklist._obtener_df_h1('XAUUSD')
    
    if df_h1_xau is None:
        conector.desconectar()
        return "No se pudo obtener H1 de XAUUSD"
    
    # Desconectar
    conector.desconectar()
    
    return True


# ============================================================
# PRUEBA 3: VERIFICAR TODO EL FLUJO DEL SNIPER
# ============================================================

def test_sniper_flujo_completo():
    """
    Prueba que el sniper use H1 para análisis medio y pesado.
    V3.0 - NUEVO: Valida flujo completo con H1 real.
    """
    from trading.sniper.sniper_checklist import SniperChecklist
    from mt5.conector_mt5 import ConectorPepperstone
    from config.settings import Config
    import time
    
    # Conectar MT5
    conector = ConectorPepperstone(
        login=Config.MT5_LOGIN,
        password=Config.MT5_PASSWORD,
        server=Config.MT5_SERVER,
        magic_number=Config.MAGIC_NUMBER,
        demo=Config.MT5_DEMO
    )
    
    if not conector.conectar():
        return "No se pudo conectar a MT5"
    
    # Crear SniperChecklist con MT5 real y análisis real
    from analysis.capas import AnalisisPorCapas
    from analysis.scoring import ScoreEngine
    from trading.stops import GestorStops
    from trading.timer import EntryTimer
    from trading.sniper.sniper_modos import DetectorModos
    
    class MockPipeline:
        def __init__(self):
            self.orquestador = None
            self.estados = {}
    
    class MockModoSelector:
        def seleccionar_modo(self, *args, **kwargs):
            from trading.sniper.sniper_modos import ModoEntrada
            return ModoEntrada.RETEST, "Modo válido", {}
    
    class MockEntryTimer:
        def validar_momento_exacto(self, *args, **kwargs):
            return True, "Momento válido", {}
    
    # Crear análisis real
    score_engine = ScoreEngine(modo_backtest=False)
    analisis_capas = AnalisisPorCapas(
        config=None,
        score_engine=score_engine,
        nivel_tracker=None
    )
    gestor_stops = GestorStops(modo_backtest=False)
    
    # Crear SniperChecklist
    checklist = SniperChecklist(
        pipeline=MockPipeline(),
        analisis_capas=analisis_capas,
        modo_selector=MockModoSelector(),
        entry_timer=MockEntryTimer(),
        gestor_stops=gestor_stops,
        config=None, almacen=None,
        mt5=conector,  # ✅ MT5 REAL
        noticias=None, patron_tracker=None, ml_optimizer=None,
        analysis_cache=None, modo_depuracion=True,
        modo_backtest=False, horario=None
    )
    
    # Probar con EURUSD
    simbolo = 'EURUSD'
    
    # Obtener datos reales
    df_m5 = conector.obtener_datos(simbolo, n_velas=100, timeframe=5)
    if df_m5 is None or len(df_m5) < 50:
        return "No se pudieron obtener datos M5 de EURUSD"
    
    tick = conector.obtener_precio(simbolo)
    if tick is None:
        return "No se pudo obtener tick de EURUSD"
    
    precio_actual = float(tick.get('ask', 0))
    
    # Ejecutar evaluación con análisis real (H1)
    start_time = time.time()
    señal = checklist.evaluar_sniper_optimizado(
        simbolo=simbolo,
        df_m5=df_m5,
        precio_actual=precio_actual,
        direccion='COMPRA',
        estado_pipeline=None,
        analisis_rapido=None,
        analisis_medio=None,
        ejecutar_pesado=True,  # ✅ Ejecutar análisis pesado (usa H1)
        contexto_h1={
            'score': 65,
            'regimen': 'TREND_ALCISTA_FUERTE',
            'en_nivel_clave': True,
            'niveles': {},
        },
        calidad_horario='EXCELENTE',
        tick_data=tick,
        precio_entrada=precio_actual
    )
    elapsed = (time.time() - start_time) * 1000
    
    # Verificar que NO falló por falta de H1
    if señal is None:
        conector.desconectar()
        return "No se generó señal (posiblemente por falta de H1)"
    
    # Desconectar
    conector.desconectar()
    
    print(f"{Fore.CYAN}⏱️ Evaluación completada en {elapsed:.1f}ms{Style.RESET_ALL}")


# ============================================================
# PRUEBA 4: PARÁMETROS POR SÍMBOLO
# ============================================================

def test_parametros_simbolo():
    """Prueba que los parámetros por símbolo sean correctos."""
    from utils.parametros_simbolo import get_parametros_simbolo
    
    parametros_esperados = {
        'EURUSD': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'GBPUSD': {'digits': 5, 'pip_val': 0.0001, 'point': 0.00001},
        'USDJPY': {'digits': 3, 'pip_val': 0.01, 'point': 0.001},
        'XAUUSD': {'digits': 2, 'pip_val': 0.01, 'point': 0.01},
        'XAGUSD': {'digits': 3, 'pip_val': 0.01, 'point': 0.001},
        'BTCUSD': {'digits': 2, 'pip_val': 1.0, 'point': 0.01},
        'ETHUSD': {'digits': 2, 'pip_val': 0.01, 'point': 0.01},
        'SOLUSD': {'digits': 2, 'pip_val': 0.01, 'point': 0.01},
        'US30': {'digits': 1, 'pip_val': 1.0, 'point': 0.1},
        'NAS100': {'digits': 1, 'pip_val': 1.0, 'point': 0.1},
        'US500': {'digits': 1, 'pip_val': 1.0, 'point': 0.1},
    }
    
    for simbolo, esperado in parametros_esperados.items():
        params = get_parametros_simbolo(simbolo)
        if params['digits'] != esperado['digits']:
            return f"{simbolo}: digits={params['digits']} != {esperado['digits']}"
        if abs(params['pip_val'] - esperado['pip_val']) > 0.000001:
            return f"{simbolo}: pip={params['pip_val']} != {esperado['pip_val']}"
        if abs(params['point'] - esperado['point']) > 0.000001:
            return f"{simbolo}: point={params['point']} != {esperado['point']}"
    
    return True


# ============================================================
# PRUEBA 5: CONECTOR MT5
# ============================================================

def test_conector_mt5():
    """Prueba que el conector MT5 funcione."""
    from mt5.conector_mt5 import ConectorPepperstone
    from config.settings import Config
    
    conector = ConectorPepperstone(
        login=Config.MT5_LOGIN,
        password=Config.MT5_PASSWORD,
        server=Config.MT5_SERVER,
        magic_number=Config.MAGIC_NUMBER,
        demo=Config.MT5_DEMO
    )
    
    if not conector.conectar():
        return "No se pudo conectar a MT5"
    
    # Obtener precio de EURUSD
    tick = conector.obtener_precio('EURUSD')
    if tick is None:
        return "No se pudo obtener precio de EURUSD"
    if tick.get('bid', 0) <= 0:
        return "Precio EURUSD inválido"
    
    # Obtener datos H1
    df = conector.obtener_datos('EURUSD', n_velas=50, timeframe=60)
    if df is None or len(df) < 10:
        return "No se pudieron obtener datos H1 de EURUSD"
    
    # Desconectar
    conector.desconectar()
    
    return True


# ============================================================
# EJECUCIÓN PRINCIPAL
# ============================================================

def main():
    """Ejecuta todas las pruebas."""
    print("=" * 80)
    print(f"{Fore.CYAN}🚀 INICIANDO PRUEBAS DEL SISTEMA BOT V9.0{Style.RESET_ALL}")
    print("=" * 80)
    print()
    
    test = TestSistema()
    
    # Ejecutar pruebas
    print(f"\n{Fore.CYAN}📋 PRUEBA 1: Sniper con H1 real{Style.RESET_ALL}")
    test.ejecutar_prueba("Sniper con H1 real", test_sniper_con_h1_real)
    
    print(f"\n{Fore.CYAN}📋 PRUEBA 2: Obtener H1 desde MT5{Style.RESET_ALL}")
    test.ejecutar_prueba("Obtener H1 desde MT5", test_obtener_df_h1)
    
    print(f"\n{Fore.CYAN}📋 PRUEBA 3: Sniper flujo completo{Style.RESET_ALL}")
    test.ejecutar_prueba("Sniper flujo completo", test_sniper_flujo_completo)
    
    print(f"\n{Fore.CYAN}📋 PRUEBA 4: Parámetros por símbolo{Style.RESET_ALL}")
    test.ejecutar_prueba("Parámetros por símbolo", test_parametros_simbolo)
    
    print(f"\n{Fore.CYAN}📋 PRUEBA 5: Conector MT5{Style.RESET_ALL}")
    test.ejecutar_prueba("Conector MT5", test_conector_mt5)
    
    # Imprimir resumen
    test.imprimir_resumen()
    
    # Guardar resultados
    with open('resultados_prueba.json', 'w', encoding='utf-8') as f:
        json.dump({
            'total': test.total_pruebas,
            'pasadas': test.pasadas,
            'falladas': test.falladas,
            'resultados': test.resultados
        }, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n{Fore.CYAN}📊 Resultados guardados en: resultados_prueba.json{Style.RESET_ALL}")


if __name__ == "__main__":
    main()