from core.orquestador import Orquestador

bot = Orquestador(modo_depuracion=True)
bot.mt5.conectar()

simbolo = 'EURUSD'

# 1. ADX en H1
df_h1 = bot.mt5.obtener_datos(simbolo, n_velas=150, timeframe=60)
adx_h1 = bot.analisis_capas.analisis_medio(df_h1, simbolo).adx
print(f"ADX H1: {adx_h1:.2f}")

# 2. ADX en M5
df_m5 = bot.mt5.obtener_datos(simbolo, n_velas=150, timeframe=5)
adx_m5 = bot.analisis_capas.analisis_medio(df_m5, simbolo).adx
print(f"ADX M5: {adx_m5:.2f}")

# 3. ADX en H4
df_h4 = bot.mt5.obtener_datos(simbolo, n_velas=100, timeframe=240)
adx_h4 = bot.analisis_capas.analisis_medio(df_h4, simbolo).adx
print(f"ADX H4: {adx_h4:.2f}")

bot.mt5.desconectar()