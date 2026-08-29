#!/usr/bin/env python3
"""
prueba_universal.py - Prueba de ejecución universal para CUALQUIER símbolo
Valida que el bot funcione con pares que cambian en decimales o símbolos.
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timezone

root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from core.orquestador import Orquestador
from analysis.pipeline import FaseOportunidad


def obtener_pip_val_real(simbolo: str, mt5) -> float:
    try:
        info = mt5.obtener_info_simbolo(simbolo)
        if info is not None:
            point = float(getattr(info, 'point', 0.0) or 0.0)
            digits = int(getattr(info, 'digits', 0) or 0)
            
            # ✅ CORRECCIÓN: Detectar por nombre del símbolo primero
            simbolo_upper = simbolo.upper()
            if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
                return 0.10  # Metales
            if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                return 1.0  # Cripto
            if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
                return 1.0  # Índices
            if 'JPY' in simbolo_upper:
                return 0.01  # JPY
            if digits == 5:
                return 0.0001  # Forex estándar
            return point
    except Exception as e:
        print(f"⚠️ Error obteniendo pip_val: {e}")
    
    # Fallback
    simbolo_upper = simbolo.upper()
    if 'JPY' in simbolo_upper:
        return 0.01
    if 'XAU' in simbolo_upper or 'XAG' in simbolo_upper:
        return 0.10
    if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
        return 1.0
    if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
        return 1.0
    return 0.0001


def obtener_lote_minimo(simbolo: str) -> float:
    """Obtiene el lote mínimo según el tipo de activo."""
    simbolo_upper = simbolo.upper()
    if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500', 'SP500']):
        return 0.1
    if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
        return 0.01
    if any(x in simbolo_upper for x in ['XAU', 'XAG']):
        return 0.01
    return 0.01


def crear_oportunidad_artificial(bot, simbolo: str, direccion: str, score: float = 85.0):
    """Crea una oportunidad artificial en Fase 3."""
    # Obtener datos H1 para contexto
    df_h1 = bot.cache.get_datos(simbolo, 60, 250, bot.mt5.obtener_datos)
    if df_h1 is not None and not df_h1.empty:
        precio_actual = df_h1['Close'].iloc[-1]
        soporte_cercano = df_h1['Low'].iloc[-20:].min()
        resistencia_cercana = df_h1['High'].iloc[-20:].max()
    else:
        precio_actual = 0
        soporte_cercano = 0
        resistencia_cercana = 0
    
    contexto_h1 = {
        'score': score,
        'direccion': direccion,
        'regimen': 'TREND_ALCISTA_FUERTE' if direccion == 'COMPRA' else 'TREND_BAJISTA_FUERTE',
        'en_nivel_clave': True,
        'soporte_cercano': soporte_cercano,
        'resistencia_cercana': resistencia_cercana,
        'nivel_usado': soporte_cercano if direccion == 'COMPRA' else resistencia_cercana,
        'medio': {
            'adx': 35.0,
            'rsi': 65.0,
            'macd_histogram': 0.0005,
            'sma20': precio_actual,
            'sma50': precio_actual,
        },
        'pesado': {
            'score_estructura': 25.0,
            'score_momentum': 30.0,
            'score_confluencia': 25.0,
            'score_institucional': 20.0,
            'patron_principal': 'PIN_BAR_ALCISTA' if direccion == 'COMPRA' else 'PIN_BAR_BAJISTA',
            'divergencia_rsi': None,
        }
    }
    
    estado = bot.pipeline.obtener_estado(simbolo)
    if estado is None:
        bot.pipeline.actualizar_fase_1(
            simbolo=simbolo,
            analisis={},
            score=score,
            direccion=direccion,
            regimen=contexto_h1['regimen'],
            direccion_regimen='ALCISTA' if direccion == 'COMPRA' else 'BAJISTA',
            confianza_regimen=80,
            tendencia_h4='ALCISTA' if direccion == 'COMPRA' else 'BAJISTA',
            contexto_h1=contexto_h1
        )
        estado = bot.pipeline.obtener_estado(simbolo)
    
    if estado:
        estado.fase_actual = FaseOportunidad.FASE_3
        estado.score_acumulado = score
        estado.contexto_h1 = contexto_h1
    
    return estado


def probar_simbolo(bot, simbolo: str, direccion: str):
    """Prueba un símbolo en una dirección específica."""
    print(f"\n{'='*60}")
    print(f"🔍 PROBANDO {simbolo} - DIRECCIÓN: {direccion}")
    print('='*60)
    
    # 1. Obtener pip_val real
    pip_val = obtener_pip_val_real(simbolo, bot.mt5)
    print(f"📊 pip_val para {simbolo}: {pip_val:.6f}")
    
    # 2. Crear oportunidad artificial
    estado = crear_oportunidad_artificial(bot, simbolo, direccion, 85.0)
    if not estado:
        print(f"❌ No se pudo crear oportunidad para {simbolo}")
        return False
    
    # 3. Obtener datos M5 con vela virtual
    df_m5 = bot._obtener_df_m5_con_precio_real(simbolo)
    if df_m5 is None:
        print(f"❌ No se pudo obtener vela virtual para {simbolo}")
        return False
    
    precio_actual = df_m5['Close'].iloc[-1]
    print(f"✅ Vela virtual obtenida (precio: {precio_actual:.5f})")
    
    # 4. Ejecutar sniper
    print(f"🎯 Ejecutando sniper para {simbolo}...")
    resultado = bot.sniper_checklist.evaluar_sniper_optimizado(
        simbolo=simbolo,
        df_m5=df_m5,
        precio_actual=precio_actual,
        direccion=direccion,
        estado_pipeline=estado,
        contexto_h1=estado.contexto_h1,
        calidad_horario='EXCELENTE'
    )
    
    if not resultado:
        print(f"⏭️ Sniper no disparó para {simbolo} ({direccion})")
        # Mostrar razones del rechazo
        print("   Posibles razones:")
        print("   1. El score es insuficiente")
        print("   2. Las confluencias no cumplen los umbrales")
        print("   3. El spread es demasiado alto")
        return False
    
    print(f"🎯 ✅ ¡SNIPER DISPARA! Modo: {resultado['modo']}, Score: {resultado['score']:.1f}, R:R: {resultado['rr']:.2f}")
    
    # 5. Ejecutar operación
    print(f"💹 Ejecutando operación en MT5...")
    exito = bot.ejecutor.ejecutar(resultado)
    
    if exito:
        print(f"✅ ¡OPERACIÓN EJECUTADA CON ÉXITO!")
        print(f"   Ticket: {list(bot.estado.posiciones_abiertas.keys())}")
        
        # 6. Verificar posición abierta
        posiciones = bot.mt5.obtener_posiciones()
        for pos in posiciones:
            if pos['magic'] == bot.config.MAGIC_NUMBER and pos['simbolo'] == simbolo:
                print(f"📊 Posición abierta:")
                print(f"   Símbolo: {pos['simbolo']}")
                print(f"   Tipo: {pos['tipo']}")
                print(f"   Entrada: {pos['precio_apertura']:.5f}")
                print(f"   SL: {pos['sl']:.5f}")
                print(f"   TP: {pos['tp']:.5f}")
                print(f"   Volumen: {pos['volumen']:.3f}")
                
                # 7. Cerrar posición automáticamente
                print(f"🔒 Cerrando posición {pos['ticket']}...")
                bot.mt5.cerrar_posicion(pos['ticket'])
                print(f"✅ Posición cerrada")
                break
        
        return True
    else:
        print(f"❌ La operación no se pudo ejecutar.")
        return False


def ejecutar_prueba_universal():
    print(f"\n🚀 INICIANDO PRUEBA UNIVERSAL DE EJECUCIÓN")
    print("=" * 60)
    
    # 1. Inicializar orquestador
    print("🔌 Inicializando orquestador...")
    bot = Orquestador(modo_depuracion=True)
    
    if not bot.mt5.conectar():
        print("❌ No se pudo conectar a MT5")
        return
    
    print("✅ Orquestador listo")
    
    # 2. Lista de símbolos a probar (representativos de cada tipo)
    simbolos_a_probar = [
        # Forex
        ('EURUSD', 'COMPRA'),
        ('GBPUSD', 'VENTA'),
        ('USDJPY', 'COMPRA'),
        # Metales
        ('XAUUSD', 'COMPRA'),
        # Índices
        ('US30', 'COMPRA'),
        ('NAS100', 'VENTA'),
        # Cripto
        ('BTCUSD', 'COMPRA'),
        ('ETHUSD', 'VENTA'),
        ('SOLUSD', 'COMPRA'),
    ]
    
    resultados = []
    
    for simbolo, direccion in simbolos_a_probar:
        try:
            exito = probar_simbolo(bot, simbolo, direccion)
            resultados.append({
                'simbolo': simbolo,
                'direccion': direccion,
                'exito': exito
            })
            
            # Esperar un poco entre pruebas
            time.sleep(1)
            
        except Exception as e:
            print(f"❌ Error probando {simbolo}: {e}")
            resultados.append({
                'simbolo': simbolo,
                'direccion': direccion,
                'exito': False,
                'error': str(e)
            })
    
    # 3. Resumen final
    print(f"\n{'='*60}")
    print("📊 RESUMEN DE PRUEBAS")
    print('='*60)
    
    exitos = sum(1 for r in resultados if r['exito'])
    fallos = len(resultados) - exitos
    
    for r in resultados:
        estado = "✅" if r['exito'] else "❌"
        print(f"  {estado} {r['simbolo']} ({r['direccion']})")
    
    print(f"\n📈 Total exitosos: {exitos}/{len(resultados)}")
    print(f"📉 Total fallidos: {fallos}/{len(resultados)}")
    
    # 4. Desconectar
    print("\n🔌 Desconectando de MT5...")
    bot.mt5.desconectar()
    
    print(f"\n{'='*60}")
    if exitos == len(resultados):
        print("✅ TODAS LAS PRUEBAS PASARON CON ÉXITO")
    else:
        print("⚠️ ALGUNAS PRUEBAS FALLARON - Revisa los logs")
    print('='*60)


if __name__ == "__main__":
    ejecutar_prueba_universal()