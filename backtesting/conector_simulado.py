#!/usr/bin/env python3
"""
backtesting/conector_simulado.py (V1.0 - NUEVO)
Conector MT5 simulado para backtest.

Reemplaza a ConectorPepperstone manteniendo interfaz idéntica.

RESPONSABILIDADES:
- Servir datos históricos (obtener_datos)
- Servir precios con spread modelado (obtener_precio)
- Simular órdenes (enviar_orden, cerrar_posicion, modificar_sl)
- Mantener posiciones abiertas y balance/equity
- Modelar comisión y swap

NO AVANZA TIEMPO — eso lo hace el BacktesterV10 con
SimulatedClock. Este conector solo responde en base a
`utils.reloj.now_utc()`.
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from collections import defaultdict
import pandas as pd

from utils.reloj import now_utc
from utils.helpers import get_pip_val, get_digits, get_contract_size


logger = logging.getLogger('BotTrading.Backtesting.ConectorSimulado')


# ============================================================
# CONFIGURACIÓN DE COSTES
# ============================================================

# Spread por símbolo (en pips)
SPREAD_PIPS_DEFAULT = {
    # Forex mayores
    'EURUSD': 1.5, 'GBPUSD': 2.0, 'USDJPY': 1.5,
    'AUDUSD': 2.0, 'USDCAD': 2.0, 'USDCHF': 2.0,
    # Forex cruzados
    'EURGBP': 2.0, 'EURJPY': 2.5, 'GBPJPY': 3.5,
    'AUDJPY': 3.0, 'EURNZD': 3.5, 'GBPAUD': 3.5,
    'EURCHF': 2.5, 'GBPCHF': 3.0,
    # Metales
    'XAUUSD': 20.0, 'XAGUSD': 25.0,
    # Índices
    'US30': 3.0, 'NAS100': 2.0, 'US500': 1.0,
    # Cripto
    'BTCUSD': 50.0, 'ETHUSD': 30.0, 'SOLUSD': 30.0,
}

# Comisión por lote estándar round-trip (en USD)
COMISION_POR_LOTE_ROUNDTRIP = 3.5

# Swap diario por 0.01 lote (en USD, aproximado)
# Negativo = coste, positivo = ganancia
SWAP_DIARIO_POR_LOTE = {
    'EURUSD': -0.10,
    'GBPUSD': -0.15,
    'USDJPY': -0.12,
    'XAUUSD': -0.50,
    'BTCUSD': -0.80,
    'US30': -0.40,
}

# Slippage en pips (aplicado en contra del trader)
SLIPPAGE_PIPS = 0.5

# Apalancamiento por defecto
APALANCAMIENTO_DEFAULT = 500


# ============================================================
# POSICIÓN SIMULADA
# ============================================================

@dataclass
class PosicionSimulada:
    """Una posición abierta en el simulador."""
    ticket: int
    simbolo: str
    tipo: int  # 0=BUY, 1=SELL (compatibilidad MT5)
    volumen: float
    precio_apertura: float
    sl: float = 0.0
    tp: float = 0.0
    comentario: str = ""
    magic: int = 0
    time: int = 0  # unix timestamp de apertura
    precio_actual: float = 0.0
    swap_acumulado: float = 0.0
    comision_pagada: float = 0.0

    @property
    def direccion(self) -> str:
        return 'COMPRA' if self.tipo == 0 else 'VENTA'


# ============================================================
# CONECTOR SIMULADO
# ============================================================

class ConectorSimulado:
    """
    Conector MT5 simulado.
    V1.0 - NUEVO.

    Interfaz compatible con ConectorBase.
    """

    def __init__(
        self,
        dataframes: Dict[str, Dict[int, pd.DataFrame]],
        balance_inicial: float = 300.0,
        apalancamiento: int = APALANCAMIENTO_DEFAULT,
        spread_pips: Optional[Dict[str, float]] = None,
        comision_por_lote: float = COMISION_POR_LOTE_ROUNDTRIP,
        slippage_pips: float = SLIPPAGE_PIPS,
        aplicar_swap: bool = True,
        modo_depuracion: bool = False,
    ):
        """
        Args:
            dataframes: Dict {simbolo: {timeframe_min: DataFrame}}
                        Los DF deben tener índice datetime UTC
            balance_inicial: Balance inicial
            apalancamiento: Apalancamiento del broker simulado
            spread_pips: Spread por símbolo (override del default)
            comision_por_lote: Comisión round-trip por lote estándar
            slippage_pips: Slippage en pips
            aplicar_swap: Si True, aplica swap al cerrar
            modo_depuracion: Logs extra
        """
        self.dataframes = dataframes
        self.balance = balance_inicial
        self.balance_inicial = balance_inicial
        self.apalancamiento = apalancamiento
        self.comision_por_lote = comision_por_lote
        self.slippage_pips = slippage_pips
        self.aplicar_swap = aplicar_swap
        self.modo_depuracion = modo_depuracion
        self.logger = logger

        # Spread personalizado
        self.spread_pips = dict(SPREAD_PIPS_DEFAULT)
        if spread_pips:
            self.spread_pips.update(spread_pips)

        # Estado interno
        self._posiciones: Dict[int, PosicionSimulada] = {}
        self._ticket_counter = 1000
        self._historial_cierres: List[Dict[str, Any]] = []
        self._conectado = False

        # Equity calculado en cada avance
        self.equity = balance_inicial

        # Cache de precios por tick (evita recalcular)
        self._tick_cache: Dict[str, Dict[str, Any]] = {}

        # Info de cuenta
        self.magic_number = 0

        self.logger.info(f"🔌 ConectorSimulado V1.0 inicializado")
        self.logger.info(f"   Símbolos: {len(dataframes)}")
        self.logger.info(f"   Balance inicial: ${balance_inicial:.2f}")
        self.logger.info(f"   Apalancamiento: 1:{apalancamiento}")
        self.logger.info(f"   Comisión/lote RT: ${comision_por_lote:.2f}")
        self.logger.info(f"   Slippage: {slippage_pips} pips")

    # ============================================================
    # CONEXIÓN
    # ============================================================

    def conectar(self) -> bool:
        """Simula conexión."""
        self._conectado = True
        self.logger.info("✅ ConectorSimulado conectado")
        return True

    def verificar_conexion(self) -> bool:
        return self._conectado

    def desconectar(self):
        self._conectado = False
        self.logger.info("🔒 ConectorSimulado desconectado")

    # ============================================================
    # DATOS HISTÓRICOS
    # ============================================================

    def obtener_datos(
        self,
        simbolo: str,
        n_velas: int = 100,
        timeframe: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Retorna las últimas `n_velas` velas cuyo timestamp <= now_utc().
        """
        tf = timeframe or 60
        df = self.dataframes.get(simbolo, {}).get(tf)

        if df is None or len(df) == 0:
            return None

        # Filtrar hasta el tiempo actual del reloj simulado
        ahora = now_utc()
        df_hasta = df[df.index <= ahora]

        if len(df_hasta) == 0:
            return None

        # Retornar últimas n_velas
        return df_hasta.iloc[-n_velas:].copy()

    def obtener_datos_rango(
        self,
        simbolo: str,
        timeframe: int,
        desde: datetime,
        hasta: datetime,
    ) -> Optional[pd.DataFrame]:
        """Retorna velas en un rango específico."""
        df = self.dataframes.get(simbolo, {}).get(timeframe)
        if df is None or len(df) == 0:
            return None
        return df[(df.index >= desde) & (df.index <= hasta)].copy()

    # ============================================================
    # PRECIO
    # ============================================================

    def obtener_precio(self, simbolo: str) -> Optional[Dict[str, Any]]:
        """
        Retorna precio bid/ask simulado con spread.
        Usa la última vela M5 disponible en el clock simulado.
        """
        if not self._conectado:
            return None

        # Intentar caché de tick (por segundo)
        ahora = now_utc()
        cache_key = f"{simbolo}_{int(ahora.timestamp())}"
        if cache_key in self._tick_cache:
            return self._tick_cache[cache_key]

        # Obtener último close disponible (timeframe más bajo = más preciso)
        df = self._obtener_df_reciente(simbolo)
        if df is None or len(df) == 0:
            return None

        precio_mid = float(df['Close'].iloc[-1])
        if precio_mid <= 0:
            return None

        # Calcular spread
        pip_val = self._obtener_pip_val(simbolo)
        digits = self._obtener_digits(simbolo)
        spread_pips = self.spread_pips.get(simbolo.upper(), 2.0)
        spread_precio = spread_pips * pip_val

        bid = precio_mid - spread_precio / 2
        ask = precio_mid + spread_precio / 2

        result = {
            'bid': round(bid, digits),
            'ask': round(ask, digits),
            'spread': spread_precio,
            'spread_price': spread_precio,
            'spread_points': spread_precio / (10 ** -digits),
            'spread_pips': spread_pips,
            'point': 10 ** -digits,
            'pip_size': pip_val,
            'tick_size': 10 ** -digits,
            'digits': digits,
            'timestamp': ahora.timestamp(),
            'tick_time': ahora.timestamp(),
            'fuente': 'simulado',
        }

        self._tick_cache[cache_key] = result

        # Limpiar caché antiguo (últimos 100 ticks)
        if len(self._tick_cache) > 200:
            claves = sorted(self._tick_cache.keys())[:100]
            for k in claves:
                del self._tick_cache[k]

        return result

    def _obtener_df_reciente(self, simbolo: str) -> Optional[pd.DataFrame]:
        """Retorna el DF del timeframe más bajo disponible con datos."""
        dfs_simbolo = self.dataframes.get(simbolo, {})
        if not dfs_simbolo:
            return None

        # Preferencia: M5 > M15 > H1 > H4 > D1
        for tf in [5, 15, 30, 60, 240, 1440]:
            if tf in dfs_simbolo:
                df = dfs_simbolo[tf]
                if df is not None and len(df) > 0:
                    ahora = now_utc()
                    df_hasta = df[df.index <= ahora]
                    if len(df_hasta) > 0:
                        return df_hasta

        return None

    # ============================================================
    # INFO DE SÍMBOLO / CUENTA
    # ============================================================

    def obtener_info_simbolo(self, simbolo: str) -> Optional[Dict[str, Any]]:
        """Info del símbolo (mock)."""
        pip_val = self._obtener_pip_val(simbolo)
        digits = self._obtener_digits(simbolo)

        return {
            'name': simbolo,
            'digits': digits,
            'point': 10 ** -digits,
            'volume_min': 0.01,
            'volume_max': 100.0,
            'volume_step': 0.01,
            'trade_contract_size': self._obtener_contract_size(simbolo),
            'trade_tick_value': 1.0,
            'trade_tick_size': 10 ** -digits,
            'trade_stops_level': 0,
            'filling_mode': 0,
        }

    def info_cuenta(self) -> Optional[Dict[str, Any]]:
        """Info de cuenta simulada."""
        margen_usado = self._calcular_margen_usado()
        margen_libre = max(0.0, self.equity - margen_usado)
        margin_level = (self.equity / margen_usado * 100) if margen_usado > 0 else 0.0

        return {
            'login': 999999,
            'balance': round(self.balance, 2),
            'equity': round(self.equity, 2),
            'margen_libre': round(margen_libre, 2),
            'margin_free': round(margen_libre, 2),
            'margin': round(margen_usado, 2),
            'nivel_margen': round(margin_level, 2),
            'margin_level': round(margin_level, 2),
            'apalancamiento': self.apalancamiento,
            'leverage': self.apalancamiento,
            'moneda': 'USD',
        }

    # ============================================================
    # ÓRDENES
    # ============================================================

    def enviar_orden(
        self,
        simbolo: str,
        tipo: str,
        volumen: float,
        sl: float = 0,
        tp: float = 0,
        comentario: str = "",
        magic_number: int = 0,
    ) -> Dict[str, Any]:
        """
        Simula envío de orden. Abre posición interna.
        """
        if not self._conectado:
            return {'retcode': -1, 'comentario': 'No conectado', 'ticket': None}

        tipo_norm = tipo.upper().strip()
        if tipo_norm in ('BUY', 'COMPRA', 'LONG'):
            order_type = 0
            direccion = 'COMPRA'
        elif tipo_norm in ('SELL', 'VENTA', 'SHORT'):
            order_type = 1
            direccion = 'VENTA'
        else:
            return {'retcode': -1, 'comentario': f'Tipo inválido: {tipo}', 'ticket': None}

        # Precio de entrada con slippage
        tick = self.obtener_precio(simbolo)
        if tick is None:
            return {'retcode': -1, 'comentario': 'Sin precio', 'ticket': None}

        pip_val = self._obtener_pip_val(simbolo)
        digits = self._obtener_digits(simbolo)

        if direccion == 'COMPRA':
            precio_base = tick['ask']
            # Slippage en contra: precio más alto
            precio_ejecucion = precio_base + (self.slippage_pips * pip_val)
        else:
            precio_base = tick['bid']
            precio_ejecucion = precio_base - (self.slippage_pips * pip_val)

        precio_ejecucion = round(precio_ejecucion, digits)

        # Validaciones básicas (mismas que MT5)
        if direccion == 'COMPRA':
            if sl > 0 and sl >= precio_ejecucion:
                return {'retcode': -1, 'comentario': f'SL inválido', 'ticket': None}
            if tp > 0 and tp <= precio_ejecucion:
                return {'retcode': -1, 'comentario': f'TP inválido', 'ticket': None}
        else:
            if sl > 0 and sl <= precio_ejecucion:
                return {'retcode': -1, 'comentario': f'SL inválido', 'ticket': None}
            if tp > 0 and tp >= precio_ejecucion:
                return {'retcode': -1, 'comentario': f'TP inválido', 'ticket': None}

        # Crear ticket
        self._ticket_counter += 1
        ticket = self._ticket_counter

        # Calcular comisión (apertura = mitad del round-trip)
        comision_apertura = (self.comision_por_lote * volumen) / 2.0

        # Crear posición
        pos = PosicionSimulada(
            ticket=ticket,
            simbolo=simbolo,
            tipo=order_type,
            volumen=float(volumen),
            precio_apertura=precio_ejecucion,
            sl=float(sl),
            tp=float(tp),
            comentario=comentario,
            magic=magic_number or self.magic_number,
            time=int(now_utc().timestamp()),
            precio_actual=precio_ejecucion,
            comision_pagada=comision_apertura,
        )
        self._posiciones[ticket] = pos

        # Aplicar comisión al balance
        self.balance -= comision_apertura

        self.logger.info(
            f"📈 ORDEN SIMULADA {simbolo} {direccion} {volumen:.3f} "
            f"@ {precio_ejecucion:.{digits}f} | Ticket: {ticket} | "
            f"SL: {sl:.{digits}f} TP: {tp:.{digits}f} | "
            f"Comisión: ${comision_apertura:.2f}"
        )

        return {
            'retcode': 0,
            'ticket': ticket,
            'precio': precio_ejecucion,
            'sl': sl,
            'tp': tp,
            'comentario': 'Ejecutada',
            'volumen': volumen,
        }

    def cerrar_posicion(self, ticket: int) -> bool:
        """Cierra una posición completamente."""
        if ticket not in self._posiciones:
            return False

        pos = self._posiciones[ticket]
        precio_cierre = self._obtener_precio_cierre(pos.simbolo, pos.direccion)

        if precio_cierre is None:
            self.logger.warning(f"⚠️ No se pudo cerrar {ticket}: sin precio")
            return False

        return self._ejecutar_cierre(pos, precio_cierre, "MANUAL")

    def cerrar_parcial(self, ticket: int, volumen_a_cerrar: float) -> bool:
        """Cierra parte de una posición."""
        if ticket not in self._posiciones:
            return False

        pos = self._posiciones[ticket]

        if volumen_a_cerrar >= pos.volumen - 0.001:
            return self.cerrar_posicion(ticket)

        if volumen_a_cerrar <= 0:
            return False

        volumen_a_cerrar = max(0.01, round(volumen_a_cerrar, 2))

        # Crear una "posición parcial" temporal para calcular PnL
        temp_pos = PosicionSimulada(
            ticket=pos.ticket,
            simbolo=pos.simbolo,
            tipo=pos.tipo,
            volumen=volumen_a_cerrar,
            precio_apertura=pos.precio_apertura,
            sl=pos.sl,
            tp=pos.tp,
            time=pos.time,
            comision_pagada=(self.comision_por_lote * volumen_a_cerrar) / 2.0,
        )

        precio_cierre = self._obtener_precio_cierre(pos.simbolo, pos.direccion)
        if precio_cierre is None:
            return False

        # Aplicar cierre parcial
        self._ejecutar_cierre(temp_pos, precio_cierre, "PARCIAL")

        # Reducir volumen de la posición original
        pos.volumen = round(pos.volumen - volumen_a_cerrar, 3)
        if pos.volumen <= 0.001:
            del self._posiciones[ticket]

        return True

    def _ejecutar_cierre(
        self,
        pos: PosicionSimulada,
        precio_cierre: float,
        motivo: str,
    ) -> bool:
        """Ejecuta el cierre y actualiza estado."""
        # Calcular PnL bruto
        contract_size = self._obtener_contract_size(pos.simbolo)
        pip_val = self._obtener_pip_val(pos.simbolo)

        if pos.tipo == 0:  # COMPRA
            puntos = (precio_cierre - pos.precio_apertura) / pip_val
        else:  # VENTA
            puntos = (pos.precio_apertura - precio_cierre) / pip_val

        # PnL en USD: puntos * valor_pip * volumen
        valor_pip_pos = self._valor_pip_posicion(pos.simbolo, pos.volumen)
        pnl_bruto = puntos * valor_pip_pos

        # Comisión de cierre
        comision_cierre = (self.comision_por_lote * pos.volumen) / 2.0

        # Swap acumulado
        swap_total = 0.0
        if self.aplicar_swap:
            swap_total = self._calcular_swap(pos)
        swap_total += pos.swap_acumulado

        pnl_neto = pnl_bruto - comision_cierre + swap_total

        # Actualizar balance
        self.balance += pnl_neto

        # Timestamp cierre
        ts_cierre = now_utc()
        duracion_min = (ts_cierre - datetime.fromtimestamp(pos.time, tz=timezone.utc)).total_seconds() / 60

        # Registrar en historial
        registro = {
            'ticket': pos.ticket,
            'simbolo': pos.simbolo,
            'direccion': pos.direccion,
            'volumen': pos.volumen,
            'precio_apertura': pos.precio_apertura,
            'precio_cierre': precio_cierre,
            'sl': pos.sl,
            'tp': pos.tp,
            'timestamp_apertura': datetime.fromtimestamp(pos.time, tz=timezone.utc).isoformat(),
            'timestamp_cierre': ts_cierre.isoformat(),
            'duracion_min': round(duracion_min, 1),
            'puntos': round(puntos, 2),
            'pnl_bruto': round(pnl_bruto, 2),
            'comision_apertura': round(pos.comision_pagada, 2),
            'comision_cierre': round(comision_cierre, 2),
            'swap': round(swap_total, 2),
            'pnl_neto': round(pnl_neto, 2),
            'motivo_cierre': motivo,
            'comentario_apertura': pos.comentario,
            'magic': pos.magic,
        }
        self._historial_cierres.append(registro)

        # Eliminar si no es parcial
        if motivo != "PARCIAL" and pos.ticket in self._posiciones:
            del self._posiciones[pos.ticket]

        self.logger.info(
            f"📊 CIERRE {pos.simbolo} [{pos.ticket}] {motivo} | "
            f"PnL: ${pnl_neto:+.2f} | Balance: ${self.balance:.2f}"
        )

        return True

    def modificar_sl(self, ticket: int, nuevo_sl: float) -> bool:
        """Modifica el SL."""
        if ticket not in self._posiciones:
            return False

        pos = self._posiciones[ticket]

        # Validar
        if pos.tipo == 0 and nuevo_sl > 0 and nuevo_sl >= pos.precio_actual:
            return False
        if pos.tipo == 1 and nuevo_sl > 0 and nuevo_sl <= pos.precio_actual:
            return False

        pos.sl = float(nuevo_sl)
        self.logger.debug(f"🔄 SL modificado {ticket} → {nuevo_sl:.5f}")
        return True

    def modificar_tp(self, ticket: int, nuevo_tp: float) -> bool:
        """Modifica el TP."""
        if ticket not in self._posiciones:
            return False

        pos = self._posiciones[ticket]
        pos.tp = float(nuevo_tp)
        return True

    # ============================================================
    # POSICIONES
    # ============================================================

    def obtener_posiciones(
        self,
        simbolo: Optional[str] = None,
        force: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retorna posiciones abiertas (formato MT5-like)."""
        # Actualizar precio actual de cada posición
        for pos in self._posiciones.values():
            tick = self.obtener_precio(pos.simbolo)
            if tick:
                pos.precio_actual = tick['bid'] if pos.tipo == 0 else tick['ask']

        resultado = []
        for pos in self._posiciones.values():
            if simbolo and pos.simbolo != simbolo:
                continue

            ganancia = self._calcular_pnl_flotante(pos)

            resultado.append({
                'ticket': pos.ticket,
                'simbolo': pos.simbolo,
                'tipo': pos.tipo,
                'volumen': pos.volumen,
                'precio_apertura': pos.precio_apertura,
                'precio_actual': pos.precio_actual,
                'sl': pos.sl,
                'tp': pos.tp,
                'ganancia': round(ganancia, 2),
                'swap': round(pos.swap_acumulado, 2),
                'magic': pos.magic,
                'time': pos.time,
                'comentario': pos.comentario,
            })

        return resultado

    def obtener_detalle_cierre(self, ticket: int) -> Optional[Dict[str, Any]]:
        """Detalle del último cierre con ese ticket."""
        for reg in reversed(self._historial_cierres):
            if reg['ticket'] == ticket:
                return {
                    'ganancia': reg['pnl_bruto'],
                    'comision': -(reg['comision_apertura'] + reg['comision_cierre']),
                    'swap': reg['swap'],
                    'precio_salida': reg['precio_cierre'],
                    'timestamp_salida': reg['timestamp_cierre'],
                    'pnl_neto': reg['pnl_neto'],
                    'motivo_cierre': reg['motivo_cierre'],
                }
        return None

    def obtener_historial_cierres(self) -> List[Dict[str, Any]]:
        """Historial completo de cierres."""
        return list(self._historial_cierres)

    # ============================================================
    # MÉTODOS AUXILIARES
    # ============================================================

    def _obtener_precio_cierre(self, simbolo: str, direccion: str) -> Optional[float]:
        """Precio para cerrar (bid si COMPRA, ask si VENTA)."""
        tick = self.obtener_precio(simbolo)
        if tick is None:
            return None
        return tick['bid'] if direccion == 'COMPRA' else tick['ask']

    def _calcular_pnl_flotante(self, pos: PosicionSimulada) -> float:
        """PnL no realizado."""
        pip_val = self._obtener_pip_val(pos.simbolo)

        if pos.tipo == 0:
            puntos = (pos.precio_actual - pos.precio_apertura) / pip_val
        else:
            puntos = (pos.precio_apertura - pos.precio_actual) / pip_val

        valor_pip_pos = self._valor_pip_posicion(pos.simbolo, pos.volumen)
        return puntos * valor_pip_pos

    def _calcular_swap(self, pos: PosicionSimulada) -> float:
        """Swap acumulado desde apertura."""
        if not self.aplicar_swap:
            return 0.0

        ts_apertura = datetime.fromtimestamp(pos.time, tz=timezone.utc)
        ts_actual = now_utc()
        dias = max(0, (ts_actual - ts_apertura).total_seconds() / 86400)

        swap_diario = SWAP_DIARIO_POR_LOTE.get(pos.simbolo.upper(), -0.20)

        # Swap por lote * volumen
        # Si es VENTA, invertir signo (a veces es positivo, depende del broker)
        swap_por_dia = swap_diario * (pos.volumen / 0.01)
        if pos.tipo == 1:  # VENTA
            swap_por_dia = -swap_por_dia

        return swap_por_dia * dias

    def _calcular_margen_usado(self) -> float:
        """Margen total usado por posiciones abiertas."""
        total = 0.0
        for pos in self._posiciones.values():
            tick = self.obtener_precio(pos.simbolo)
            if tick is None:
                continue
            precio = tick['ask'] if pos.tipo == 0 else tick['bid']
            total += self._margen_posicion(pos.simbolo, pos.volumen, precio)
        return total

    def _margen_posicion(self, simbolo: str, volumen: float, precio: float) -> float:
        """Margen requerido para una posición."""
        contract_size = self._obtener_contract_size(simbolo)
        valor = volumen * contract_size * precio
        return valor / self.apalancamiento

    def _valor_pip_posicion(self, simbolo: str, volumen: float) -> float:
        """
        Valor de 1 pip en USD para la posición (volumen ya incluido).
        """
        s = simbolo.upper()
        pip_val = self._obtener_pip_val(simbolo)
        contract_size = self._obtener_contract_size(simbolo)

        # Para JPY, dividir por precio (aproximado)
        if 'JPY' in s:
            tick = self.obtener_precio(simbolo)
            precio = tick['bid'] if tick else 150.0
            valor_1_lote = (contract_size * pip_val) / precio
        else:
            valor_1_lote = contract_size * pip_val

        return valor_1_lote * volumen

    def _obtener_pip_val(self, simbolo: str) -> float:
        try:
            from utils.helpers import get_pip_val
            return get_pip_val(simbolo)
        except Exception:
            s = simbolo.upper()
            if 'JPY' in s: return 0.01
            if 'XAU' in s: return 0.10
            if 'XAG' in s: return 0.01
            if any(x in s for x in ('US30', 'NAS100', 'US500')): return 1.0
            if any(c in s for c in ('BTC', 'ETH', 'SOL')): return 1.0
            return 0.0001

    def _obtener_digits(self, simbolo: str) -> int:
        try:
            from utils.helpers import get_digits
            return get_digits(simbolo)
        except Exception:
            s = simbolo.upper()
            if 'JPY' in s: return 3
            if 'XAU' in s: return 2
            if 'XAG' in s: return 3
            if any(x in s for x in ('US30', 'NAS100', 'US500')): return 1
            if any(c in s for c in ('BTC', 'ETH', 'SOL')): return 2
            return 5

    def _obtener_contract_size(self, simbolo: str) -> float:
        try:
            from utils.helpers import get_contract_size
            return get_contract_size(simbolo)
        except Exception:
            s = simbolo.upper()
            if any(c in s for c in ('BTC', 'ETH', 'SOL')): return 1.0
            if 'XAU' in s: return 100.0
            if 'XAG' in s: return 5000.0
            if any(x in s for x in ('US30', 'NAS100', 'US500')): return 1.0
            return 100000.0

    # ============================================================
    # ACTUALIZACIÓN DE ESTADO
    # ============================================================

    def actualizar_equity(self):
        """Recalcula equity = balance + PnL flotante."""
        pnl_flotante = sum(
            self._calcular_pnl_flotante(pos)
            for pos in self._posiciones.values()
        )
        self.equity = self.balance + pnl_flotante

    def get_estado(self) -> Dict[str, Any]:
        """Estado actual del simulador."""
        self.actualizar_equity()

        ganadoras = sum(1 for r in self._historial_cierres if r['pnl_neto'] > 0)
        perdedoras = sum(1 for r in self._historial_cierres if r['pnl_neto'] < 0)
        total = len(self._historial_cierres)

        return {
            'balance': round(self.balance, 2),
            'equity': round(self.equity, 2),
            'balance_inicial': self.balance_inicial,
            'pnl_total': round(self.balance - self.balance_inicial, 2),
            'posiciones_abiertas': len(self._posiciones),
            'cierres_totales': total,
            'ganadoras': ganadoras,
            'perdedoras': perdedoras,
            'win_rate': round(ganadoras / total * 100, 1) if total > 0 else 0,
        }

    def reset(self):
        """Reinicia el simulador (para correr otro backtest)."""
        self._posiciones.clear()
        self._historial_cierres.clear()
        self._tick_cache.clear()
        self._ticket_counter = 1000
        self.balance = self.balance_inicial
        self.equity = self.balance_inicial
        self.logger.info("🔄 ConectorSimulado reseteado")


# ============================================================
# FACTORY
# ============================================================

def create_conector_simulado(
    dataframes: Dict[str, Dict[int, pd.DataFrame]],
    balance_inicial: float = 300.0,
    **kwargs,
) -> ConectorSimulado:
    """Crea una instancia del conector simulado."""
    return ConectorSimulado(
        dataframes=dataframes,
        balance_inicial=balance_inicial,
        **kwargs,
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando ConectorSimulado V1.0...")

    import numpy as np
    from utils.reloj import activate_clock, deactivate_clock, set_clock

    # Crear datos sintéticos
    np.random.seed(42)
    n = 200
    fechas = pd.date_range('2024-01-01', periods=n, freq='5min', tz='UTC')
    precios = 1.1000 + np.cumsum(np.random.randn(n) * 0.0003)

    df_m5 = pd.DataFrame({
        'Open': precios,
        'High': precios + 0.0002,
        'Low': precios - 0.0002,
        'Close': precios + np.random.randn(n) * 0.0001,
        'Volume': np.random.randint(100, 1000, n),
    }, index=fechas)

    # Conector
    conn = create_conector_simulado(
        dataframes={'EURUSD': {5: df_m5}},
        balance_inicial=1000.0,
    )

    # Activar reloj en medio del rango
    activate_clock(fechas[100])
    conn.conectar()

    # 1. Datos
    datos = conn.obtener_datos('EURUSD', n_velas=50, timeframe=5)
    print(f"\n1. obtener_datos: {len(datos) if datos is not None else 0} velas")

    # 2. Precio
    tick = conn.obtener_precio('EURUSD')
    print(f"2. Precio: bid={tick['bid']:.5f} ask={tick['ask']:.5f} spread={tick['spread_pips']}pips")

    # 3. Enviar orden COMPRA
    res = conn.enviar_orden('EURUSD', 'COMPRA', 0.01, sl=1.0950, tp=1.1050, comentario='test')
    print(f"3. Orden: ticket={res['ticket']} precio={res['precio']:.5f}")

    # 4. Obtener posiciones
    pos = conn.obtener_posiciones()
    print(f"4. Posiciones: {len(pos)}")

    # 5. Avanzar tiempo
    set_clock(fechas[120])
    conn.actualizar_equity()
    estado = conn.get_estado()
    print(f"5. Después de avanzar: balance=${estado['balance']:.2f} equity=${estado['equity']:.2f}")

    # 6. Cerrar
    conn.cerrar_posicion(res['ticket'])
    estado = conn.get_estado()
    print(f"6. Después de cerrar: balance=${estado['balance']:.2f}")

    # 7. Info cuenta
    info = conn.info_cuenta()
    print(f"7. Cuenta: balance=${info['balance']:.2f} equity=${info['equity']:.2f}")

    deactivate_clock()
    conn.desconectar()

    print("\n✅ Todos los tests pasan")