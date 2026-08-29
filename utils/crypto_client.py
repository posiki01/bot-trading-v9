from utils.crypto_client import FreeCryptoAPIClient

# Inicializar
client = FreeCryptoAPIClient()

# Verificar disponibilidad
if client.is_available():
    print("✅ CryptoAPI disponible")
    
    # Obtener sentimiento de BTC
    sentiment = client.get_sentiment('BTC')
    print(f"📊 Sentimiento BTC: {sentiment['sentiment']:.2f}")
    
    # Obtener estadísticas de reintentos
    stats = client.get_retry_stats()
    print(f"📊 Reintentos: {stats}")
else:
    print("❌ CryptoAPI no disponible")