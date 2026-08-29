import sys
import os
from pathlib import Path

# Añadir directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orquestador import Orquestador
import logging
from datetime import datetime, timezone, timedelta

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Inicializar orquestador
bot = Orquestador(modo_depuracion=True)
bot.mt5.conectar()

# Probar con EURUSD
simbolo = 'EURUSD'
timeframe = 60  # H1

# Verificar datos actuales
df_actual = bot.mt5.obtener_datos(simbolo, n_velas=100, timeframe=timeframe)

if df_actual is not None and len(df_actual) > 0:
    print(f"\n✅ Datos obtenidos para {simbolo} TF{timeframe}:")
    print(f"   Última vela: {df_actual.index[-1]}")
    print(f"   Total velas: {len(df_actual)}")
    
    # Verificar frescura
    ultima_fecha = df_actual.index[-1]
    ahora = datetime.now(timezone.utc)
    diferencia = (ahora - ultima_fecha).total_seconds() / 60
    
    print(f"   Diferencia con ahora: {diferencia:.1f} minutos")
    
    if diferencia < 120:  # 2 horas para H1
        print(f"   ✅ Datos FRESCOS (actualizados)")
    else:
        print(f"   ❌ Datos DESACTUALIZADOS")
        print(f"   → El bot NO está actualizando correctamente")
else:
    print(f"❌ No se pudieron obtener datos para {simbolo}")

# Probar con M5 (más sensible a frescura)
timeframe_m5 = 5
df_m5 = bot.mt5.obtener_datos(simbolo, n_velas=100, timeframe=timeframe_m5)

if df_m5 is not None and len(df_m5) > 0:
    ultima_fecha_m5 = df_m5.index[-1]
    diferencia_m5 = (datetime.now(timezone.utc) - ultima_fecha_m5).total_seconds() / 60
    
    print(f"\n✅ Datos M5 para {simbolo}:")
    print(f"   Última vela: {ultima_fecha_m5}")
    print(f"   Diferencia con ahora: {diferencia_m5:.1f} minutos")
    
    if diferencia_m5 < 10:  # 10 minutos para M5
        print(f"   ✅ Datos M5 FRESCOS")
    else:
        print(f"   ❌ Datos M5 DESACTUALIZADOS")
else:
    print(f"❌ No se pudieron obtener datos M5 para {simbolo}")

# Desconectar
bot.mt5.desconectar()

print("\n📊 Verificación completada")