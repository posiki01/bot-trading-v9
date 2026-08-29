#!/usr/bin/env python3
"""
prueba_ejecucion.py - Prueba de ejecución con Cripto (24/7)
CORREGIDO: Contexto H1 completo para que el sniper dispare.
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from core.orquestador import Orquestador
from analysis.pipeline import FaseOportunidad


def crear_oportunidad_artificial(bot, simbolo='BTCUSD', direccion='COMPRA', score=85.0):
    """
    Crea una oportunidad artificial en Fase 3 con contexto H1 completo.
    """
    print(f"\n🔧 Creando oportunidad artificial para {simbolo}...")
    
    # Contexto H1 completo
    contexto_h1 = {
        'score': score,
        'direccion': direccion,
        'regimen': 'TREND_ALCISTA_FUERTE',
        'en_nivel_clave': True,
        'soporte_cercano': 74500.0,
        'resistencia_cercana': 75000.0,
        'nivel_usado': 74500.0,
        'medio': {
            'adx': 35.0,
            'rsi': 65.0,
            'macd_histogram': 0.0005,
            'sma20': 74500.0,
            'sma50': 74000.0,
        },
        'pesado': {
            'score_estructura': 25.0,
            'score_momentum': 30.0,
            'score_confluencia': 25.0,
            'score_institucional': 20.0,
            'patron_principal': 'PIN_BAR_ALCISTA',
            'divergencia_rsi': None,
        }
    }
    
    # Crear o actualizar estado
    estado = bot.pipeline.obtener_estado(simbolo)
    if estado is None:
        bot.pipeline.actualizar_fase_1(
            simbolo=simbolo,
            analisis={},
            score=score,
            direccion=direccion,
            regimen='TREND_ALCISTA_FUERTE',
            direccion_regimen='ALCISTA',
            confianza_regimen=80,
            tendencia_h4='ALCISTA',
            contexto_h1=contexto_h1
        )
        estado = bot.pipeline.obtener_estado(simbolo)
    
    # Forzar promoción a Fase 3
    if estado:
        estado.fase_actual = FaseOportunidad.FASE_3
        estado.score_acumulado = score
        estado.contexto_h1 = contexto_h1
    
    print(f"✅ Oportunidad artificial creada en Fase 3 (score: {score})")
    return estado


def ejecutar_prueba(simbolo='BTCUSD', direccion='COMPRA'):
    print(f"\n🚀 INICIANDO PRUEBA DE EJECUCIÓN CON CRIPTO")
    print("=" * 60)
    print(f"📊 Símbolo: {simbolo}")
    print(f"📈 Dirección: {direccion}")
    print("=" * 60)
    
    # 1. Inicializar orquestador
    print("\n🔌 Inicializando orquestador...")
    bot = Orquestador(modo_depuracion=True)
    
    if not bot.mt5.conectar():
        print("❌ No se pudo conectar a MT5")
        return False
    
    print("✅ Orquestador listo")
    
    # 2. Crear oportunidad artificial con contexto H1 completo
    estado = crear_oportunidad_artificial(bot, simbolo, direccion, 85.0)
    
    # 3. Obtener datos M5 con vela virtual
    print(f"\n📥 Obteniendo datos M5 para {simbolo}...")
    df_m5 = bot._obtener_df_m5_con_precio_real(simbolo)
    if df_m5 is None:
        print("❌ No se pudo obtener vela virtual")
        bot.mt5.desconectar()
        return False
    
    precio_actual = df_m5['Close'].iloc[-1]
    print(f"✅ Vela virtual obtenida (precio: {precio_actual:.5f})")
    
    # 4. Ejecutar sniper con contexto H1 completo
    print(f"\n🎯 Ejecutando sniper para {simbolo}...")
    resultado = bot.sniper_checklist.evaluar_sniper_optimizado(
        simbolo=simbolo,
        df_m5=df_m5,
        precio_actual=precio_actual,
        direccion=direccion,
        estado_pipeline=estado,
        contexto_h1=estado.contexto_h1 if estado else None,
        calidad_horario='EXCELENTE'
    )
    
    if resultado:
        print("\n🎯 ✅ ¡SNIPER DISPARA!")
        print(f"   Modo: {resultado['modo']}")
        print(f"   Score: {resultado['score']:.1f}")
        print(f"   R:R: {resultado['rr']:.2f}")
        print(f"   Entry: {resultado['entry_price']:.5f}")
        print(f"   SL: {resultado['sl']:.5f}")
        print(f"   TP: {resultado['tp']:.5f}")
        
        # 5. Ejecutar operación
        print(f"\n💹 Ejecutando operación en MT5...")
        exito = bot.ejecutor.ejecutar(resultado)
        
        if exito:
            print("✅ ¡OPERACIÓN EJECUTADA CON ÉXITO!")
            print(f"   Ticket: {list(bot.estado.posiciones_abiertas.keys())}")
            
            # 6. Verificar posición abierta
            posiciones = bot.mt5.obtener_posiciones()
            for pos in posiciones:
                if pos['magic'] == bot.config.MAGIC_NUMBER:
                    print(f"\n📊 Posición abierta:")
                    print(f"   Símbolo: {pos['simbolo']}")
                    print(f"   Tipo: {pos['tipo']}")
                    print(f"   Entrada: {pos['precio_apertura']:.5f}")
                    print(f"   SL: {pos['sl']:.5f}")
                    print(f"   TP: {pos['tp']:.5f}")
                    print(f"   Volumen: {pos['volumen']:.3f}")
                    print(f"   Ganancia flotante: {pos['ganancia']:.2f}")
            
            # 7. Cerrar la posición automáticamente (opcional)
            cerrar = input("\n¿Deseas cerrar la posición ahora? (s/n): ").lower()
            if cerrar == 's':
                for pos in posiciones:
                    if pos['magic'] == bot.config.MAGIC_NUMBER:
                        bot.mt5.cerrar_posicion(pos['ticket'])
                        print(f"✅ Posición {pos['ticket']} cerrada")
        else:
            print("❌ La operación no se pudo ejecutar.")
    else:
        print("\n⏭️ Sniper no disparó.")
        print("   Razones posibles:")
        print("   1. El contexto H1 no tiene suficientes datos.")
        print("   2. El spread es demasiado alto.")
        print("   3. Las condiciones no cumplen los umbrales.")
    
    # 8. Desconectar
    print("\n🔌 Desconectando de MT5...")
    bot.mt5.desconectar()
    
    return resultado is not None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--simbolo", type=str, default="BTCUSD")
    parser.add_argument("--direccion", type=str, default="COMPRA")
    args = parser.parse_args()
    
    ejecutar_prueba(args.simbolo, args.direccion)