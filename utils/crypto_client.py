"""
utils/crypto_client.py (V7)
Cliente para FreeCryptoAPI - Reemplazo de CryptoPanic para noticias y datos de criptomonedas.
Mejoras: logging, timeouts, validación de respuestas, integración con retry_http.
V7+: Retry solo en _get, validación de symbol, advertencia de API key.
"""

import requests
import os
import logging
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from utils.retry import retry_http

load_dotenv()

logger = logging.getLogger('BotTrading.CryptoClient')


class FreeCryptoAPIClient:
    """
    Cliente para FreeCryptoAPI - reemplazo de CryptoPanic.
    Proporciona datos de criptomonedas, análisis técnico y sentimiento.
    NOTA: Esta API es de terceros y puede tener límites de uso.
    """

    BASE_URL = "https://api.freecryptoapi.com/v1"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('CRYPTO_API_KEY')
        if not self.api_key:
            logger.warning("⚠️ CRYPTO_API_KEY no configurada. El cliente de criptomonedas funcionará en modo limitado (todas las llamadas retornarán datos vacíos).")

        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json'
        })
        if self.api_key:
            self.session.headers.update({
                'Authorization': f'Bearer {self.api_key}'
            })

        self.timeout = 10.0

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Método interno para realizar peticiones GET con retry_http."""
        if not self.api_key:
            logger.error("❌ CryptoClient sin API Key. No se pueden hacer peticiones.")
            return None
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"⏳ Timeout al consultar {endpoint} con params {params}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error HTTP en {endpoint}: {e}")
            return None
        except ValueError as e:
            logger.error(f"❌ Error parseando JSON en {endpoint}: {e}")
            return None

    # Los métodos públicos ya no tienen @retry_http; el retry está en _get
    def get_crypto_list(self) -> List[Dict[str, Any]]:
        data = self._get("getCryptoList")
        return data if isinstance(data, list) else []

    def get_data(self, symbol: str) -> Dict[str, Any]:
        data = self._get("getData", params={"symbol": symbol})
        return data if isinstance(data, dict) else {}

    def get_multiple_data(self, symbols: List[str]) -> List[Dict[str, Any]]:
        data = self._get("getData", params={"symbol": ",".join(symbols)})
        return data if isinstance(data, list) else []

    def get_technical_analysis(self, symbol: str) -> Dict[str, Any]:
        data = self._get("getTechnicalAnalysis", params={"symbol": symbol})
        return data if isinstance(data, dict) else {}

    def get_support_resistance(self, symbol: str) -> Dict[str, Any]:
        data = self._get("getSupportResistance", params={"symbol": symbol})
        return data if isinstance(data, dict) else {}

    def get_volatility(self, symbol: str) -> Dict[str, Any]:
        data = self._get("getVolatility", params={"symbol": symbol})
        return data if isinstance(data, dict) else {}

    def get_correlation(self, symbol1: str, symbol2: str) -> Dict[str, Any]:
        data = self._get("getCorrelation", params={"symbol1": symbol1, "symbol2": symbol2})
        return data if isinstance(data, dict) else {}

    def get_ohlc(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> List[Dict[str, Any]]:
        data = self._get("getOHLC", params={
            "symbol": symbol,
            "timeframe": timeframe,
            "limit": limit
        })
        return data if isinstance(data, list) else []

    def get_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Obtiene sentimiento de mercado para una criptomoneda."""
        if not symbol:
            return {'symbol': symbol, 'sentiment': 0.0, 'error': 'Símbolo vacío'}
        try:
            data = self.get_data(symbol)
            tech = self.get_technical_analysis(symbol)
            if not data or not tech:
                logger.warning(f"⚠️ Datos incompletos para sentimiento de {symbol}")
                return {'symbol': symbol, 'sentiment': 0.0, 'error': 'Datos incompletos'}
            rsi = tech.get('rsi', 50)
            signal = tech.get('signal', 'NEUTRAL')
            if signal == 'BUY' and rsi < 70:
                sentiment = 0.7
            elif signal == 'SELL' and rsi > 30:
                sentiment = -0.7
            else:
                sentiment = (rsi - 50) / 50
                sentiment = max(-1.0, min(1.0, sentiment))
            change_24h = data.get('change_24h', 0)
            if change_24h > 5:
                sentiment = min(1.0, sentiment + 0.2)
            elif change_24h < -5:
                sentiment = max(-1.0, sentiment - 0.2)
            return {
                'symbol': symbol,
                'sentiment': sentiment,
                'rsi': rsi,
                'signal': signal,
                'price': data.get('price', 0),
                'change_24h': change_24h
            }
        except Exception as e:
            logger.error(f"❌ Error obteniendo sentimiento de {symbol}: {e}")
            return {'symbol': symbol, 'sentiment': 0.0, 'error': str(e)}

    def is_available(self) -> bool:
        """Verifica si la API está disponible (tiene API key y responde)."""
        if not self.api_key:
            return False
        try:
            result = self.get_crypto_list()
            return isinstance(result, list)
        except Exception:
            return False
