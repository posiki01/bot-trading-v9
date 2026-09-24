#!/usr/bin/env python3
"""
trading/timer.py (V10.1 - FASE 1)
Sistema de validación de momento exacto + confirmación de rechazo.

CAMBIOS V10.1 (FASE 1):
- ✅ validar_confirmacion_rechazo() — 2 velas M5 consecutivas
- ✅ detectar_stop_hunt() — mecha larga + retorno al nivel
- ✅ Mantiene toda la funcionalidad de V10.0
"""

import logging
import pandas as pd
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone, timedelta

from config.umbrales import Umbrales
from utils.helpers import safe_float

logger = logging.getLogger('BotTrading.Timer')


class EntryTimer:
    """
    Sistema de validación de momento exacto + confirmación de rechazo.
    V10.1 - FASE 1.
    """

    CONFIG_POR_MODO = {
        'RETEST': {
            'confirmacion_velas': 1, 'toque_nivel_porcentaje': 0.3,
            'min_pips_para_mover': 5, 'esperar_cierre_vela': True,
            'max_wait_minutos': 30, 'volumen_minimo': 0.3,
        },
        'RETEST_FALLBACK': {
            'confirmacion_velas': 1, 'toque_nivel_porcentaje': 0.5,
            'min_pips_para_mover': 5, 'esperar_cierre_vela': True,
            'max_wait_minutos': 30, 'volumen_minimo': 0.2,
        },
        'NIVEL_FUERTE': {
            'confirmacion_velas': 1, 'toque_nivel_porcentaje': 0.2,
            'min_pips_para_mover': 3, 'esperar_cierre_vela': True,
            'max_wait_minutos': 20, 'volumen_minimo': 0.3,
        },
        'BREAKOUT': {
            'confirmacion_velas': 1, 'toque_nivel_porcentaje': 0.1,
            'min_pips_para_mover': 3, 'esperar_cierre_vela': True,
            'max_wait_minutos': 15, 'volumen_minimo': 0.6,
        },
        'PULLBACK': {
            'confirmacion_velas': 2, 'toque_nivel_porcentaje': 0.5,
            'min_pips_para_mover': 5, 'esperar_cierre_vela': True,
            'max_wait_minutos': 45, 'volumen_minimo': 0.3,
        },
        'PATRON': {
            'confirmacion_velas': 1, 'toque_nivel_porcentaje': 0.3,
            'min_pips_para_mover': 5, 'esperar_cierre_vela': True,
            'max_wait_minutos': 20, 'volumen_minimo': 0.3,
        },
        'RUPTURA_FALSA': {
            'confirmacion_velas': 2, 'toque_nivel_porcentaje': 0.1,
            'min_pips_para_mover': 3, 'esperar_cierre_vela': True,
            'max_wait_minutos': 15, 'volumen_minimo': 0.3,
        },
        'VELA_BORDE': {
            'confirmacion_velas': 1, 'toque_nivel_porcentaje': 0.2,
            'min_pips_para_mover': 3, 'esperar_cierre_vela': True,
            'max_wait_minutos': 10, 'volumen_minimo': 0.2,
        },
        'SNIPER_ELITE': {
            'confirmacion_velas': 1, 'toque_nivel_porcentaje': 0.2,
            'min_pips_para_mover': 3, 'esperar_cierre_vela': True,
            'max_wait_minutos': 15, 'volumen_minimo': 0.4,
            'confluencias_minimas': 2,
        },
    }

    def __init__(self, config=None, modo_backtest: bool = False, modo_depuracion: bool = False):
        self.config = config
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.Timer')
        self._cargar_configuracion()
        self._estado_espera: Dict[str, Dict] = {}
        self.logger.info(f"⏱️ EntryTimer V10.1 FASE-1 inicializado")

    def _cargar_configuracion(self):
        if Umbrales is not None:
            if hasattr(Umbrales, 'TIEMPO'):
                tiempo_config = Umbrales.TIEMPO
                for modo in self.CONFIG_POR_MODO:
                    key = f'timeout_{modo.lower()}'
                    if key in tiempo_config:
                        self.CONFIG_POR_MODO[modo]['max_wait_minutos'] = tiempo_config[key]
        if self.modo_backtest:
            for modo in self.CONFIG_POR_MODO:
                config = self.CONFIG_POR_MODO[modo]
                config['max_wait_minutos'] = max(5, int(config['max_wait_minutos'] * 0.5))
                config['volumen_minimo'] = max(0.05, config['volumen_minimo'] * 0.3)

    # ============================================================
    # ✅ NUEVO V10.1: CONFIRMACIÓN DE RECHAZO
    # ============================================================

    def validar_confirmacion_rechazo(
        self,
        df_m5: pd.DataFrame,
        direccion: str,
        nivel_usado: Optional[float],
        simbolo: str = '',
    ) -> Tuple[bool, str]:
        """
        ✅ FASE 1: Confirma rechazo real en 2 velas consecutivas.

        Reglas:
        - Vela actual debe cerrar del lado correcto del nivel
        - Vela anterior también (ideal)
        - Para COMPRA: cierre > open y cierre >= nivel
        - Para VENTA:  cierre < open y cierre <= nivel
        """
        if df_m5 is None or len(df_m5) < 3:
            return False, "Datos insuficientes"

        vela = df_m5.iloc[-1]
        vela_ant = df_m5.iloc[-2]

        rango = vela['High'] - vela['Low']
        if rango <= 0:
            return False, "Rango cero"

        if direccion == 'COMPRA':
            if vela['Close'] <= vela['Open']:
                return False, "Vela actual no alcista"
            if nivel_usado and nivel_usado > 0:
                if vela['Close'] < nivel_usado * 0.9999:
                    return False, f"Cierre bajo nivel"
                # Confirmación 2 velas
                if vela_ant['Close'] > vela_ant['Open'] and vela_ant['Close'] > nivel_usado * 0.9999:
                    return True, "Rechazo confirmado (2 velas)"
                return True, "Rechazo confirmado (1 vela fuerte)"

        elif direccion == 'VENTA':
            if vela['Close'] >= vela['Open']:
                return False, "Vela actual no bajista"
            if nivel_usado and nivel_usado > 0:
                if vela['Close'] > nivel_usado * 1.0001:
                    return False, f"Cierre sobre nivel"
                if vela_ant['Close'] < vela_ant['Open'] and vela_ant['Close'] < nivel_usado * 1.0001:
                    return True, "Rechazo confirmado (2 velas)"
                return True, "Rechazo confirmado (1 vela fuerte)"

        return False, "Dirección inválida"

    # ============================================================
    # ✅ NUEVO V10.1: DETECCIÓN DE STOP HUNT
    # ============================================================

    def detectar_stop_hunt(
        self,
        df_m5: pd.DataFrame,
        nivel_usado: Optional[float],
        direccion: str,
        simbolo: str = '',
        pip_val: float = 0.0,
    ) -> Tuple[bool, str]:
        """
        ✅ FASE 1: Detecta manipulación (barrido de stops).

        Reglas:
        - Mecha larga (> 50% del rango)
        - Que rompió el nivel (por al menos 0.5 pips)
        - Y cerró del lado correcto
        - En las últimas 3 velas M5
        """
        if df_m5 is None or len(df_m5) < 3:
            return False, ""
        if not nivel_usado or nivel_usado <= 0:
            return False, ""
        if pip_val <= 0:
            return False, ""

        ultimas = df_m5.tail(3)

        for i in range(len(ultimas) - 1, -1, -1):
            vela = ultimas.iloc[i]
            rango = vela['High'] - vela['Low']
            if rango <= 0:
                continue

            if direccion == 'COMPRA':
                mecha_inf = min(vela['Open'], vela['Close']) - vela['Low']
                mecha_ratio = mecha_inf / rango
                rompio = vela['Low'] < (nivel_usado - pip_val * 0.5)
                cerro_arriba = vela['Close'] > nivel_usado

                if mecha_ratio > 0.5 and rompio and cerro_arriba:
                    return True, f"STOP_HUNT_ALCISTA (mecha={mecha_ratio:.2f})"
            else:
                mecha_sup = vela['High'] - max(vela['Open'], vela['Close'])
                mecha_ratio = mecha_sup / rango
                rompio = vela['High'] > (nivel_usado + pip_val * 0.5)
                cerro_abajo = vela['Close'] < nivel_usado

                if mecha_ratio > 0.5 and rompio and cerro_abajo:
                    return True, f"STOP_HUNT_BAJISTA (mecha={mecha_ratio:.2f})"

        return False, ""

    # ============================================================
    # VALIDACIÓN DE MOMENTO EXACTO (V10.0 - mantener)
    # ============================================================

    def validar_momento_exacto(
        self,
        simbolo: str,
        modo: str,
        df_m5: pd.DataFrame,
        precio_actual: float,
        nivel_usado: Optional[float] = None,
        direccion: str = 'COMPRA',
        regimen: str = 'INCERTO',
        volumen_relativo: float = 1.0,
        fecha_vela: Optional[datetime] = None,
    ) -> Tuple[bool, str, Dict]:
        """Valida si el momento actual es exacto."""
        if fecha_vela is None:
            fecha_vela = datetime.now(timezone.utc)
        if fecha_vela.tzinfo is None:
            fecha_vela = fecha_vela.replace(tzinfo=timezone.utc)

        cfg = self.CONFIG_POR_MODO.get(modo, self.CONFIG_POR_MODO['RETEST']).copy()
        detalles = {
            'modo': modo, 'nivel_usado': nivel_usado,
            'precio_actual': precio_actual, 'direccion': direccion,
            'regimen': regimen, 'volumen': volumen_relativo,
        }

        if df_m5 is None or len(df_m5) < 3:
            return False, "Datos insuficientes", detalles

        # Dirección M5
        direccion_m5 = self._determinar_direccion_m5(df_m5)
        detalles['direccion_m5'] = direccion_m5

        if direccion == 'VENTA' and direccion_m5 == 'ALCISTA':
            return False, "M5 en tendencia ALCISTA - no permitir VENTA", detalles
        if direccion == 'COMPRA' and direccion_m5 == 'BAJISTA':
            return False, "M5 en tendencia BAJISTA - no permitir COMPRA", detalles

        if direccion == 'COMPRA' and direccion_m5 != 'ALCISTA':
            if direccion_m5 == 'LATERAL' and nivel_usado is None:
                return False, "M5 lateral sin nivel clave", detalles
        if direccion == 'VENTA' and direccion_m5 != 'BAJISTA':
            if direccion_m5 == 'LATERAL' and nivel_usado is None:
                return False, "M5 lateral sin nivel clave", detalles

        # Validar toque
        if modo in ['RETEST', 'RETEST_FALLBACK', 'NIVEL_FUERTE', 'VELA_BORDE']:
            if nivel_usado is None:
                return False, "No hay nivel definido", detalles
            valido, razon = self._validar_toque_nivel(
                df_m5, nivel_usado, precio_actual, direccion, cfg, simbolo
            )
            if not valido:
                distancia = abs(precio_actual - nivel_usado) / precio_actual * 100
                if distancia < 0.2:
                    valido = True
            if not valido:
                return False, razon, detalles
            detalles['toque_nivel'] = True

        # PULLBACK
        if modo == 'PULLBACK':
            valido, razon = self._validar_fin_pullback(
                df_m5, precio_actual, direccion, cfg, simbolo
            )
            if not valido:
                return False, razon, detalles
            detalles['fin_pullback'] = True

        # BREAKOUT
        if modo == 'BREAKOUT':
            if nivel_usado is None:
                return False, "No hay nivel para BREAKOUT", detalles
            valido, razon = self._validar_breakout(
                df_m5, nivel_usado, precio_actual, direccion, volumen_relativo, cfg, simbolo
            )
            if not valido:
                return False, razon, detalles
            detalles['breakout_confirmado'] = True

        # SNIPER_ELITE
        if modo == 'SNIPER_ELITE':
            valido, razon = self._validar_confluencias(
                df_m5, precio_actual, direccion, cfg, simbolo
            )
            if not valido:
                return False, razon, detalles
            detalles['confluencias_confirmadas'] = True

        # Vela de confirmación
        if cfg.get('esperar_cierre_vela', True):
            valido, razon = self._validar_vela_confirmacion(df_m5, direccion, cfg, simbolo)
            if not valido:
                return False, razon, detalles
            detalles['vela_confirmacion'] = True

        # Tiempo de espera
        valido, razon = self._validar_tiempo_espera(simbolo, modo, cfg, fecha_vela)
        if not valido:
            return False, razon, detalles

        return True, "Momento exacto validado", detalles

    def _determinar_direccion_m5(self, df_m5: pd.DataFrame) -> str:
        if df_m5 is None or len(df_m5) < 20:
            return 'LATERAL'
        try:
            ema9 = df_m5['Close'].ewm(span=9, adjust=False).mean()
            ema21 = df_m5['Close'].ewm(span=21, adjust=False).mean()
            ema50 = df_m5['Close'].ewm(span=50, adjust=False).mean()
            precio_actual = df_m5['Close'].iloc[-1]

            if ema9.iloc[-1] > ema21.iloc[-1] and ema21.iloc[-1] > ema50.iloc[-1]:
                if precio_actual > ema9.iloc[-1]:
                    return 'ALCISTA'
            if ema9.iloc[-1] < ema21.iloc[-1] and ema21.iloc[-1] < ema50.iloc[-1]:
                if precio_actual < ema9.iloc[-1]:
                    return 'BAJISTA'

            if len(df_m5) >= 14:
                rsi = self._calcular_rsi(df_m5['Close'])
                if rsi > 60:
                    return 'ALCISTA'
                elif rsi < 40:
                    return 'BAJISTA'
            return 'LATERAL'
        except Exception:
            return 'LATERAL'

    def _validar_toque_nivel(self, df, nivel, precio_actual, direccion, cfg, simbolo):
        if df is None or len(df) < 3:
            return False, "Datos insuficientes"
        ventana = min(5, len(df))
        df_ventana = df.iloc[-ventana:]
        tolerancia = cfg.get('toque_nivel_porcentaje', 0.3) / 100 * nivel
        if self.modo_backtest:
            tolerancia = tolerancia * 2

        if direccion == 'COMPRA':
            min_precio = df_ventana['Low'].min()
            if min_precio <= nivel + tolerancia:
                return True, "Nivel tocado"
            return False, f"Precio no tocó nivel (min: {min_precio:.5f})"
        else:
            max_precio = df_ventana['High'].max()
            if max_precio >= nivel - tolerancia:
                return True, "Nivel tocado"
            return False, f"Precio no tocó nivel (max: {max_precio:.5f})"

    def _validar_fin_pullback(self, df, precio_actual, direccion, cfg, simbolo):
        if df is None or len(df) < 10:
            return False, "Datos insuficientes"
        ema9 = df['Close'].ewm(span=9, adjust=False).mean()
        precio_anterior = df['Close'].iloc[-2] if len(df) > 1 else precio_actual

        if direccion == 'COMPRA':
            if precio_actual > precio_anterior and precio_actual > ema9.iloc[-1]:
                return True, "Pullback terminado"
            if self._detectar_vela_reversion(df, 'COMPRA'):
                return True, "Vela de reversión detectada"
            return False, "Pullback no ha terminado"
        else:
            if precio_actual < precio_anterior and precio_actual < ema9.iloc[-1]:
                return True, "Pullback terminado"
            if self._detectar_vela_reversion(df, 'VENTA'):
                return True, "Vela de reversión detectada"
            return False, "Pullback no ha terminado"

    def _validar_breakout(self, df, nivel, precio_actual, direccion, volumen_relativo, cfg, simbolo):
        if df is None or len(df) < 5:
            return False, "Datos insuficientes"
        vol_min = cfg.get('volumen_minimo', 0.6)
        if self.modo_backtest:
            vol_min = max(0.2, vol_min * 0.3)
        if volumen_relativo < vol_min:
            return False, f"Volumen insuficiente ({volumen_relativo:.2f}x < {vol_min:.2f}x)"

        if direccion == 'COMPRA':
            if precio_actual > nivel:
                vela = df.iloc[-1]
                if vela['Close'] > vela['Open']:
                    return True, "Breakout confirmado"
                return False, "Vela de ruptura no es alcista"
            return False, "Precio no superó nivel"
        else:
            if precio_actual < nivel:
                vela = df.iloc[-1]
                if vela['Close'] < vela['Open']:
                    return True, "Breakout confirmado"
                return False, "Vela de ruptura no es bajista"
            return False, "Precio no superó nivel"

    def _validar_confluencias(self, df, precio_actual, direccion, cfg, simbolo):
        confluencias = 1
        razones = ["Nivel clave"]

        if len(df) > 20:
            ema20 = df['Close'].ewm(span=20, adjust=False).mean()
            ema50 = df['Close'].ewm(span=50, adjust=False).mean()
            if direccion == 'COMPRA' and ema20.iloc[-1] > ema50.iloc[-1]:
                confluencias += 1
                razones.append("Tendencia alcista")
            elif direccion == 'VENTA' and ema20.iloc[-1] < ema50.iloc[-1]:
                confluencias += 1
                razones.append("Tendencia bajista")

        if len(df) > 20:
            vol_prom = df['Volume'].iloc[-20:].mean()
            vol_actual = df['Volume'].iloc[-1]
            if vol_actual > vol_prom * 1.5:
                confluencias += 1
                razones.append("Volumen alto")

        if len(df) > 14:
            rsi = self._calcular_rsi(df['Close'])
            if direccion == 'COMPRA' and rsi < 30:
                confluencias += 1
                razones.append("RSI sobreventa")
            elif direccion == 'VENTA' and rsi > 70:
                confluencias += 1
                razones.append("RSI sobrecompra")

        if self._detectar_vela_reversion(df, direccion):
            confluencias += 1
            razones.append("Vela de reversión")

        vela = df.iloc[-1]
        rango = vela['High'] - vela['Low']
        if rango > 0:
            if direccion == 'COMPRA':
                sombra_inf = min(vela['Open'], vela['Close']) - vela['Low']
                if sombra_inf / rango > 0.5:
                    confluencias += 1
                    razones.append("Sombra inferior larga")
            else:
                sombra_sup = vela['High'] - max(vela['Open'], vela['Close'])
                if sombra_sup / rango > 0.5:
                    confluencias += 1
                    razones.append("Sombra superior larga")

        min_conf = cfg.get('confluencias_minimas', 2)
        if self.modo_backtest:
            min_conf = max(1, min_conf - 1)
        if confluencias >= min_conf:
            return True, f"{confluencias} confluencias: {', '.join(razones)}"
        return False, f"Solo {confluencias} confluencia(s) (mínimo {min_conf})"

    def _validar_vela_confirmacion(self, df, direccion, cfg, simbolo):
        if df is None or len(df) < 2:
            return True, "Sin datos"
        vela = df.iloc[-1]
        vela_ant = df.iloc[-2] if len(df) > 1 else vela
        rango = vela['High'] - vela['Low']
        rango_promedio = (df['High'] - df['Low']).rolling(10).mean().iloc[-1] if len(df) >= 10 else rango
        if rango < rango_promedio * 0.3:
            return False, "Vela demasiado pequeña"

        if direccion == 'COMPRA':
            if vela['Close'] > vela['Open'] and vela['Close'] > vela_ant['Close']:
                return True, "Vela de confirmación alcista"
            return False, "Vela no confirma tendencia alcista"
        else:
            if vela['Close'] < vela['Open'] and vela['Close'] < vela_ant['Close']:
                return True, "Vela de confirmación bajista"
            return False, "Vela no confirma tendencia bajista"

    def _validar_tiempo_espera(self, simbolo, modo, cfg, fecha_actual):
        if fecha_actual is None:
            return True, "Sin fecha"
        if simbolo not in self._estado_espera:
            self._estado_espera[simbolo] = {'inicio': fecha_actual, 'modo': modo}
            return True, "Inicio de espera"
        estado = self._estado_espera[simbolo]
        if estado['modo'] != modo:
            self._estado_espera[simbolo] = {'inicio': fecha_actual, 'modo': modo}
            return True, "Reinicio de espera"
        tiempo_espera = (fecha_actual - estado['inicio']).total_seconds() / 60
        max_wait = cfg.get('max_wait_minutos', 30)
        if self.modo_backtest:
            max_wait = max(5, int(max_wait * 0.5))
        if tiempo_espera > max_wait:
            del self._estado_espera[simbolo]
            return False, f"Tiempo de espera excedido ({tiempo_espera:.0f}min > {max_wait}min)"
        return True, f"Tiempo de espera válido ({tiempo_espera:.0f}/{max_wait}min)"

    def _detectar_vela_reversion(self, df, direccion):
        if len(df) < 2:
            return False
        vela = df.iloc[-1]
        rango = vela['High'] - vela['Low']
        if rango == 0:
            return False
        if direccion == 'COMPRA':
            sombra_inf = min(vela['Open'], vela['Close']) - vela['Low']
            return sombra_inf / rango > 0.6
        else:
            sombra_sup = vela['High'] - max(vela['Open'], vela['Close'])
            return sombra_sup / rango > 0.6

    def _calcular_rsi(self, precios, periodo: int = 14):
        if len(precios) < periodo:
            return 50.0
        try:
            delta = precios.diff()
            ganancia = (delta.where(delta > 0, 0.0)).rolling(window=periodo).mean()
            perdida = (-delta.where(delta < 0, 0.0)).rolling(window=periodo).mean()
            if perdida == 0:
                return 100.0
            rs = ganancia / perdida
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0
        except Exception:
            return 50.0

    def reset_estado_espera(self, simbolo: str):
        if simbolo in self._estado_espera:
            del self._estado_espera[simbolo]

    def limpiar_estados_antiguos(self, max_edad_minutos: int = 60):
        ahora = datetime.now(timezone.utc)
        to_remove = []
        for simbolo, estado in self._estado_espera.items():
            edad = (ahora - estado['inicio']).total_seconds() / 60
            if edad > max_edad_minutos:
                to_remove.append(simbolo)
        for simbolo in to_remove:
            del self._estado_espera[simbolo]

    def get_estado_espera(self, simbolo: str):
        return self._estado_espera.get(simbolo)

    def validar_momento_exacto_legacy(self, simbolo, modo, df_m5, precio_actual,
                                       nivel_usado=None, direccion='COMPRA',
                                       regimen='INCERTO', volumen_relativo=1.0,
                                       fecha_vela=None):
        return self.validar_momento_exacto(
            simbolo=simbolo, modo=modo, df_m5=df_m5,
            precio_actual=precio_actual, nivel_usado=nivel_usado,
            direccion=direccion, regimen=regimen,
            volumen_relativo=volumen_relativo, fecha_vela=fecha_vela,
        )


def create_entry_timer(config=None, modo_backtest: bool = False, modo_depuracion: bool = False):
    return EntryTimer(config=config, modo_backtest=modo_backtest, modo_depuracion=modo_depuracion)


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("🧪 Probando EntryTimer V10.1 FASE-1...")

    import numpy as np

    # Simular M5 alcista
    n = 50
    fechas = pd.date_range('2024-01-01', periods=n, freq='5min')
    df = pd.DataFrame({
        'Open': np.random.randn(n) * 0.001 + 1.1000,
        'High': np.random.randn(n) * 0.001 + 1.1010,
        'Low': np.random.randn(n) * 0.001 + 1.0990,
        'Close': np.random.randn(n) * 0.001 + 1.1000,
        'Volume': np.random.randint(100, 1000, n),
    }, index=fechas)

    timer = EntryTimer(modo_backtest=True, modo_depuracion=True)

    # Test 1: Confirmación de rechazo
    valido, razon = timer.validar_confirmacion_rechazo(
        df, 'COMPRA', 1.1000, 'EURUSD'
    )
    print(f"1. Rechazo: {valido} - {razon}")

    # Test 2: Stop hunt
    valido, razon = timer.detectar_stop_hunt(
        df, 1.1000, 'COMPRA', 'EURUSD', pip_val=0.0001
    )
    print(f"2. Stop hunt: {valido} - {razon}")

    print("\n✅ Test completado")