# services/order_service.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from mt5.conector_mt5 import ConectorBase
from trading.riesgo import GestionRiesgo
from analysis.scoring import ScoreEngine
from analysis.tecnico import AnalisisTecnico
from config.settings import Config
import logging

logger = logging.getLogger('BotTrading.OrderService')

@dataclass
class OrderRequest:
    symbol: str
    direction: str          # 'BUY' or 'SELL'
    volume: float
    sl: float
    tp: float
    comment: str = "Bot"

@dataclass
class OrderResult:
    ticket: Optional[int]
    price: float
    sl: float
    tp: float
    volume: float
    success: bool
    executed_price: Optional[float] = None
    slippage: Optional[float] = None
    error_msg: Optional[str] = None

class OrderService:
    def __init__(
        self,
        mt5: ConectorBase,
        risk: GestionRiesgo,
        score_engine: ScoreEngine,
        analyzer: AnalisisTecnico,
    ):
        self.mt5 = mt5
        self.risk = risk
        self.score_engine = score_engine
        self.analyzer = analyzer

    def _obtener_pip_val(self, symbol: str) -> float:
        """Calcula el valor de un pip para el símbolo."""
        try:
            info = self.mt5._get_symbol_info(symbol) if hasattr(self.mt5, '_get_symbol_info') else None
            if not info:
                # Fallback simple
                if 'JPY' in symbol:
                    return 0.01
                return 0.0001
            digits = getattr(info, 'digits', 5)
            if digits in [2, 3]:
                return 0.01
            elif digits == 5:
                return 0.0001
            return 10 ** (-digits)
        except Exception:
            return 0.0001

    def _obtener_parametros_simbolo(self, symbol: str) -> dict:
        """Obtiene tick_value, tick_size, point, stops_level del símbolo."""
        try:
            info = self.mt5._get_symbol_info(symbol) if hasattr(self.mt5, '_get_symbol_info') else None
            if not info:
                logger.warning(f"No se pudo obtener info de {symbol}, usando valores por defecto")
                return {'tick_value': 1.0, 'tick_size': 0.00001, 'point': 0.00001, 'stops_level': 0}
            return {
                'tick_value': float(getattr(info, 'trade_tick_value', 1.0)),
                'tick_size': float(getattr(info, 'trade_tick_size', 0.00001)),
                'point': float(getattr(info, 'point', 0.00001)),
                'stops_level': int(getattr(info, 'trade_stops_level', 0)),
                'digits': int(getattr(info, 'digits', 5))
            }
        except Exception as e:
            logger.warning(f"Error obteniendo parámetros de {symbol}: {e}")
            return {'tick_value': 1.0, 'tick_size': 0.00001, 'point': 0.00001, 'stops_level': 0, 'digits': 5}

    def crear_orden_desde_signal(
        self,
        signal: dict,      # viene del pipeline/sniper (symbol, direction, price, sl, tp, score, …)
    ) -> OrderResult:
        symbol = signal.get('symbol')
        direction = signal.get('direction', '').upper()
        precio = signal.get('price', 0.0)
        sl = signal.get('sl', 0.0)
        tp = signal.get('tp', 0.0)
        score = signal.get('score', 50)
        analisis = signal.get('analisis', {})

        # 0. Validar conexión
        if not self.mt5.verificar_conexion():
            return OrderResult(None, precio, sl, tp, 0, False, error_msg="Sin conexión MT5")

        # 1. Obtener precio de mercado y validar slippage
        tick = self.mt5.obtener_precio(symbol)
        if not tick:
            return OrderResult(None, precio, sl, tp, 0, False, error_msg="No se pudo obtener precio")
        bid = tick.get('bid', 0.0)
        ask = tick.get('ask', 0.0)
        spread = tick.get('spread', 0.0)
        precio_mercado = ask if direction == 'BUY' else bid
        if precio_mercado <= 0:
            return OrderResult(None, precio, sl, tp, 0, False, error_msg="Precio de mercado inválido")

        # Slippage
        slippage = abs(precio_mercado - precio) / precio_mercado
        if slippage > Config.MAX_SLIPPAGE_PCT:
            return OrderResult(None, precio_mercado, sl, tp, 0, False,
                               error_msg=f"Slippage excesivo {slippage*100:.2f}%",
                               slippage=slippage)

        # 2. Validar SL y TP
        if sl <= 0 or tp <= 0:
            return OrderResult(None, precio_mercado, sl, tp, 0, False,
                               error_msg="SL o TP inválidos (<=0)")

        # Obtener parámetros del símbolo
        params = self._obtener_parametros_simbolo(symbol)
        tick_value = params['tick_value']
        tick_size = params['tick_size']
        point = params['point']
        stops_level = params['stops_level']
        digits = params['digits']

        # Verificar distancia mínima de SL/TP (stops level)
        min_dist = stops_level * point
        if min_dist > 0:
            if abs(sl - precio_mercado) < min_dist:
                # Ajustar SL a la distancia mínima
                if direction == 'BUY':
                    sl = precio_mercado - min_dist
                else:
                    sl = precio_mercado + min_dist
                logger.info(f"SL ajustado a {sl} por stops_level")
            if abs(tp - precio_mercado) < min_dist:
                if direction == 'BUY':
                    tp = precio_mercado + min_dist
                else:
                    tp = precio_mercado - min_dist
                logger.info(f"TP ajustado a {tp} por stops_level")

        # 3. Cálculo de lotes
        pip_val = self._obtener_pip_val(symbol)
        volumen = self.risk.calcular_lotes(
            entrada=precio,
            stop_loss=sl,
            probabilidad=score,
            tick_value=tick_value,
            tick_size=tick_size,
            point=point,
            simbolo=symbol,
            wyckoff_fase=analisis.get('smart_money', {}).get('wyckoff', ''),
            spread=spread,
            atr=analisis.get('atr', 0),
            atr_medio=analisis.get('atr_medio', 0),
            distancia_tp1=analisis.get('distancia_tp1', 0),
            sl_mean_threshold=analisis.get('sl_mt', False),
            ob_contrario_cerca=analisis.get('ob_contrario_cerca', False),
            margin_level=None,
            equity_referencia=None,
            pip_value=pip_val
        )
        if volumen == 0.0:
            return OrderResult(None, precio_mercado, sl, tp, 0, False,
                               error_msg="Lote calculado = 0 (riesgo o margen insuficiente)")

        # 4. Enviar orden
        try:
            resultado = self.mt5.enviar_orden(
                symbol=symbol,
                tipo='BUY' if direction == 'BUY' else 'SELL',
                volumen=volumen,
                sl=sl,
                tp=tp,
                comentario=f"Bot_Score{int(score)}"
            )
        except Exception as e:
            logger.error(f"Excepción al enviar orden: {e}")
            return OrderResult(None, precio_mercado, sl, tp, volumen, False,
                               error_msg=f"Excepción: {e}")

        if not resultado or not resultado.get('ticket'):
            return OrderResult(None, precio_mercado, sl, tp, volumen, False,
                               error_msg=resultado.get('comment', 'Error desconocido en envío'))

        # Éxito
        return OrderResult(
            ticket=resultado['ticket'],
            price=precio,
            sl=sl,
            tp=tp,
            volume=volumen,
            success=True,
            executed_price=resultado.get('precio', precio_mercado),
            slippage=slippage
        )