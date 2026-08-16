#!/usr/bin/env python3
"""
trading/timer.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Sistema de validación de momento exacto para cada modo de entrada.

RESPONSABILIDADES:
- Validar el momento exacto para entrada
- Configuración por modo de entrada
- Validación de toque de nivel
- Validación de fin de pullback
- Validación de breakout con volumen
- Validación de confluencias
- Validación de vela de confirmación
- Control de tiempo de espera

MEJORAS V9.0:
- Configuración centralizada
- Logs detallados de validación
- Integración con umbrales
- Métodos de compatibilidad
- Soporte para backtest
"""

import logging
import pandas as pd 
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone, timedelta


# ============================================================
# IMPORTS
# ============================================================

from config.umbrales import Umbrales
from utils.helpers import safe_float

logger = logging.getLogger('BotTrading.Timer')


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class EntryTimer:
    """
    Sistema de validación de momento exacto para entrada.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    # ============================================================
    # CONFIGURACIÓN POR MODO
    # ============================================================
    
    CONFIG_POR_MODO = {
        'RETEST': {
            'confirmacion_velas': 1,
            'toque_nivel_porcentaje': 0.3,
            'min_pips_para_mover': 5,
            'esperar_cierre_vela': True,
            'max_wait_minutos': 30,
            'volumen_minimo': 0.3,
        },
        'RETEST_FALLBACK': {
            'confirmacion_velas': 1,
            'toque_nivel_porcentaje': 0.5,
            'min_pips_para_mover': 5,
            'esperar_cierre_vela': True,
            'max_wait_minutos': 30,
            'volumen_minimo': 0.2,
        },
        'NIVEL_FUERTE': {
            'confirmacion_velas': 1,
            'toque_nivel_porcentaje': 0.2,
            'min_pips_para_mover': 3,
            'esperar_cierre_vela': True,
            'max_wait_minutos': 20,
            'volumen_minimo': 0.3,
        },
        'BREAKOUT': {
            'confirmacion_velas': 1,
            'toque_nivel_porcentaje': 0.1,
            'min_pips_para_mover': 3,
            'esperar_cierre_vela': True,
            'max_wait_minutos': 15,
            'volumen_minimo': 0.6,
        },
        'PULLBACK': {
            'confirmacion_velas': 2,
            'toque_nivel_porcentaje': 0.5,
            'min_pips_para_mover': 5,
            'esperar_cierre_vela': True,
            'max_wait_minutos': 45,
            'volumen_minimo': 0.3,
        },
        'PATRON': {
            'confirmacion_velas': 1,
            'toque_nivel_porcentaje': 0.3,
            'min_pips_para_mover': 5,
            'esperar_cierre_vela': True,
            'max_wait_minutos': 20,
            'volumen_minimo': 0.3,
        },
        'RUPTURA_FALSA': {
            'confirmacion_velas': 2,
            'toque_nivel_porcentaje': 0.1,
            'min_pips_para_mover': 3,
            'esperar_cierre_vela': True,
            'max_wait_minutos': 15,
            'volumen_minimo': 0.3,
        },
        'VELA_BORDE': {
            'confirmacion_velas': 1,
            'toque_nivel_porcentaje': 0.2,
            'min_pips_para_mover': 3,
            'esperar_cierre_vela': True,
            'max_wait_minutos': 10,
            'volumen_minimo': 0.2,
        },
        'SNIPER_ELITE': {
            'confirmacion_velas': 1,
            'toque_nivel_porcentaje': 0.2,
            'min_pips_para_mover': 3,
            'esperar_cierre_vela': True,
            'max_wait_minutos': 15,
            'volumen_minimo': 0.4,
            'confluencias_minimas': 2,
        },
    }
    
    def __init__(self,
                 config: Optional[Any] = None,
                 modo_backtest: bool = False,
                 modo_depuracion: bool = False):
        """
        Inicializa el EntryTimer.
        
        Args:
            config: Configuración
            modo_backtest: Modo backtest
            modo_depuracion: Modo depuración
        """
        self.config = config
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.Timer')
        
        # Cargar configuración desde umbrales
        self._cargar_configuracion()
        
        # Estado de espera por símbolo
        self._estado_espera: Dict[str, Dict] = {}
        
        self.logger.info(f"⏱️ EntryTimer V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Modos configurados: {len(self.CONFIG_POR_MODO)}")
    
    def _cargar_configuracion(self):
        """Carga configuración desde umbrales centralizados."""
        if Umbrales is not None:
            # Tiempos de espera
            if hasattr(Umbrales, 'TIEMPO'):
                tiempo_config = Umbrales.TIEMPO
                for modo in self.CONFIG_POR_MODO:
                    key = f'timeout_{modo.lower()}'
                    if key in tiempo_config:
                        self.CONFIG_POR_MODO[modo]['max_wait_minutos'] = tiempo_config[key]
        
        # Ajustes para backtest
        if self.modo_backtest:
            for modo in self.CONFIG_POR_MODO:
                config = self.CONFIG_POR_MODO[modo]
                config['max_wait_minutos'] = max(5, int(config['max_wait_minutos'] * 0.5))
                config['volumen_minimo'] = max(0.05, config['volumen_minimo'] * 0.3)
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def validar_momento_exacto(self,
                               simbolo: str,
                               modo: str,
                               df_m5: pd.DataFrame,
                               precio_actual: float,
                               nivel_usado: Optional[float] = None,
                               direccion: str = 'COMPRA',
                               regimen: str = 'INCERTO',
                               volumen_relativo: float = 1.0,
                               fecha_vela: Optional[datetime] = None) -> Tuple[bool, str, Dict]:
        """
        Valida si el momento actual es exacto para la entrada.
        
        Args:
            simbolo: Símbolo
            modo: Modo de entrada
            df_m5: DataFrame M5
            precio_actual: Precio actual
            nivel_usado: Nivel usado (opcional)
            direccion: Dirección
            regimen: Régimen de mercado
            volumen_relativo: Volumen relativo
            fecha_vela: Fecha de la vela (para backtest)
        
        Returns:
            (valido, razon, detalles)
        """
        if fecha_vela is None:
            fecha_vela = datetime.now(timezone.utc)
        if fecha_vela.tzinfo is None:
            fecha_vela = fecha_vela.replace(tzinfo=timezone.utc)
        
        # Obtener configuración del modo
        cfg = self.CONFIG_POR_MODO.get(modo, self.CONFIG_POR_MODO['RETEST']).copy()
        detalles = {
            'modo': modo,
            'nivel_usado': nivel_usado,
            'precio_actual': precio_actual,
            'direccion': direccion,
            'regimen': regimen,
            'volumen': volumen_relativo,
        }
        
        # 1. Validar datos básicos
        if df_m5 is None or len(df_m5) < 3:
            return False, "Datos insuficientes", detalles
        
        # 2. Validar toque de nivel (para modos que lo requieren)
        if modo in ['RETEST', 'RETEST_FALLBACK', 'NIVEL_FUERTE', 'VELA_BORDE']:
            if nivel_usado is None:
                return False, "No hay nivel definido", detalles
            
            valido, razon = self._validar_toque_nivel(
                df_m5, nivel_usado, precio_actual, direccion, cfg, simbolo
            )
            if not valido:
                return False, razon, detalles
            detalles['toque_nivel'] = True
        
        # 3. Validar fin de pullback (para PULLBACK)
        if modo == 'PULLBACK':
            valido, razon = self._validar_fin_pullback(
                df_m5, precio_actual, direccion, cfg, simbolo
            )
            if not valido:
                return False, razon, detalles
            detalles['fin_pullback'] = True
        
        # 4. Validar breakout con volumen (para BREAKOUT)
        if modo == 'BREAKOUT':
            if nivel_usado is None:
                return False, "No hay nivel definido para BREAKOUT", detalles
            
            valido, razon = self._validar_breakout(
                df_m5, nivel_usado, precio_actual, direccion, volumen_relativo, cfg, simbolo
            )
            if not valido:
                return False, razon, detalles
            detalles['breakout_confirmado'] = True
        
        # 5. Validar confluencias (para SNIPER_ELITE)
        if modo == 'SNIPER_ELITE':
            valido, razon = self._validar_confluencias(
                df_m5, precio_actual, direccion, cfg, simbolo
            )
            if not valido:
                return False, razon, detalles
            detalles['confluencias_confirmadas'] = True
        
        # 6. Validar vela de confirmación
        if cfg.get('esperar_cierre_vela', True):
            valido, razon = self._validar_vela_confirmacion(
                df_m5, direccion, cfg, simbolo
            )
            if not valido:
                return False, razon, detalles
            detalles['vela_confirmacion'] = True
        
        # 7. Validar tiempo de espera máximo
        valido, razon = self._validar_tiempo_espera(
            simbolo, modo, cfg, fecha_vela
        )
        if not valido:
            return False, razon, detalles
        
        # 8. Log de validación exitosa
        if self.modo_depuracion:
            self.logger.debug(f"✅ {simbolo}: Momento exacto validado para {modo}")
        
        return True, "Momento exacto validado", detalles
    
    # ============================================================
    # VALIDACIÓN DE TOQUE DE NIVEL
    # ============================================================
    
    def _validar_toque_nivel(self,
                             df: pd.DataFrame,
                             nivel: float,
                             precio_actual: float,
                             direccion: str,
                             cfg: Dict,
                             simbolo: str) -> Tuple[bool, str]:
        """
        Valida que el precio haya tocado el nivel.
        
        Returns:
            (valido, razon)
        """
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
    
    # ============================================================
    # VALIDACIÓN DE FIN DE PULLBACK
    # ============================================================
    
    def _validar_fin_pullback(self,
                              df: pd.DataFrame,
                              precio_actual: float,
                              direccion: str,
                              cfg: Dict,
                              simbolo: str) -> Tuple[bool, str]:
        """
        Valida que el pullback haya terminado.
        
        Returns:
            (valido, razon)
        """
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
    
    # ============================================================
    # VALIDACIÓN DE BREAKOUT
    # ============================================================
    
    def _validar_breakout(self,
                          df: pd.DataFrame,
                          nivel: float,
                          precio_actual: float,
                          direccion: str,
                          volumen_relativo: float,
                          cfg: Dict,
                          simbolo: str) -> Tuple[bool, str]:
        """
        Valida breakout con volumen.
        
        Returns:
            (valido, razon)
        """
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
            return False, f"Precio no superó nivel"
        else:
            if precio_actual < nivel:
                vela = df.iloc[-1]
                if vela['Close'] < vela['Open']:
                    return True, "Breakout confirmado"
                return False, "Vela de ruptura no es bajista"
            return False, f"Precio no superó nivel"
    
    # ============================================================
    # VALIDACIÓN DE CONFLUENCIAS
    # ============================================================
    
    def _validar_confluencias(self,
                              df: pd.DataFrame,
                              precio_actual: float,
                              direccion: str,
                              cfg: Dict,
                              simbolo: str) -> Tuple[bool, str]:
        """
        Valida confluencias para SNIPER_ELITE.
        
        Returns:
            (valido, razon)
        """
        confluencias = 1
        razones = ["Nivel clave"]
        
        # 1. Tendencia (EMAs)
        if len(df) > 20:
            ema20 = df['Close'].ewm(span=20, adjust=False).mean()
            ema50 = df['Close'].ewm(span=50, adjust=False).mean()
            if direccion == 'COMPRA' and ema20.iloc[-1] > ema50.iloc[-1]:
                confluencias += 1
                razones.append("Tendencia alcista")
            elif direccion == 'VENTA' and ema20.iloc[-1] < ema50.iloc[-1]:
                confluencias += 1
                razones.append("Tendencia bajista")
        
        # 2. Volumen
        if len(df) > 20:
            vol_prom = df['Volume'].iloc[-20:].mean()
            vol_actual = df['Volume'].iloc[-1]
            if vol_actual > vol_prom * 1.5:
                confluencias += 1
                razones.append("Volumen alto")
        
        # 3. RSI
        if len(df) > 14:
            rsi = self._calcular_rsi(df['Close'])
            if direccion == 'COMPRA' and rsi < 30:
                confluencias += 1
                razones.append("RSI sobreventa")
            elif direccion == 'VENTA' and rsi > 70:
                confluencias += 1
                razones.append("RSI sobrecompra")
        
        # 4. Patrón de vela
        if self._detectar_vela_reversion(df, direccion):
            confluencias += 1
            razones.append("Vela de reversión")
        
        # 5. Sombra larga
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
        
        min_confluencias = cfg.get('confluencias_minimas', 2)
        if self.modo_backtest:
            min_confluencias = max(1, min_confluencias - 1)
        
        if confluencias >= min_confluencias:
            return True, f"{confluencias} confluencias: {', '.join(razones)}"
        
        return False, f"Solo {confluencias} confluencia(s) (mínimo {min_confluencias})"
    
    # ============================================================
    # VALIDACIÓN DE VELA DE CONFIRMACIÓN
    # ============================================================
    
    def _validar_vela_confirmacion(self,
                                   df: pd.DataFrame,
                                   direccion: str,
                                   cfg: Dict,
                                   simbolo: str) -> Tuple[bool, str]:
        """
        Valida vela de confirmación.
        
        Returns:
            (valido, razon)
        """
        if df is None or len(df) < 2:
            return True, "Sin datos para validar vela"
        
        vela = df.iloc[-1]
        vela_anterior = df.iloc[-2] if len(df) > 1 else vela
        
        rango = vela['High'] - vela['Low']
        rango_promedio = (df['High'] - df['Low']).rolling(10).mean().iloc[-1] if len(df) >= 10 else rango
        
        if rango < rango_promedio * 0.3:
            return False, "Vela demasiado pequeña"
        
        if direccion == 'COMPRA':
            if vela['Close'] > vela['Open'] and vela['Close'] > vela_anterior['Close']:
                return True, "Vela de confirmación alcista"
            return False, "Vela no confirma tendencia alcista"
        else:
            if vela['Close'] < vela['Open'] and vela['Close'] < vela_anterior['Close']:
                return True, "Vela de confirmación bajista"
            return False, "Vela no confirma tendencia bajista"
    
    # ============================================================
    # VALIDACIÓN DE TIEMPO DE ESPERA
    # ============================================================
    
    def _validar_tiempo_espera(self,
                               simbolo: str,
                               modo: str,
                               cfg: Dict,
                               fecha_actual: Optional[datetime]) -> Tuple[bool, str]:
        """
        Valida tiempo máximo de espera.
        
        Returns:
            (valido, razon)
        """
        if fecha_actual is None:
            return True, "Sin fecha para validar tiempo"
        
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
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def _detectar_vela_reversion(self, df: pd.DataFrame, direccion: str) -> bool:
        """
        Detecta vela de reversión.
        
        Args:
            df: DataFrame
            direccion: Dirección
        
        Returns:
            True si detecta reversión
        """
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
    
    def _calcular_rsi(self, precios: pd.Series, periodo: int = 14) -> float:
        """
        Calcula RSI.
        
        Args:
            precios: Serie de precios
            periodo: Período
        
        Returns:
            Valor RSI
        """
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
    
    def _obtener_pip_val(self, simbolo: str, precio: float) -> float:
        """
        Obtiene el valor de un pip para el símbolo.
        
        Args:
            simbolo: Símbolo
            precio: Precio de referencia
        
        Returns:
            Valor del pip
        """
        simbolo_upper = simbolo.upper()
        
        if 'JPY' in simbolo_upper:
            return 0.01
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 0.10
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 1.0
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 1.0
        return 0.0001
    
    # ============================================================
    # MÉTODOS DE GESTIÓN DE ESTADO
    # ============================================================
    
    def reset_estado_espera(self, simbolo: str):
        """
        Resetea el estado de espera para un símbolo.
        
        Args:
            simbolo: Símbolo
        """
        if simbolo in self._estado_espera:
            del self._estado_espera[simbolo]
            if self.modo_depuracion:
                self.logger.debug(f"🔄 Estado de espera resetado para {simbolo}")
    
    def limpiar_estados_antiguos(self, max_edad_minutos: int = 60):
        """
        Limpia estados de espera antiguos.
        
        Args:
            max_edad_minutos: Edad máxima en minutos
        """
        ahora = datetime.now(timezone.utc)
        to_remove = []
        
        for simbolo, estado in self._estado_espera.items():
            edad = (ahora - estado['inicio']).total_seconds() / 60
            if edad > max_edad_minutos:
                to_remove.append(simbolo)
        
        for simbolo in to_remove:
            del self._estado_espera[simbolo]
            if self.modo_depuracion:
                self.logger.debug(f"🧹 Estado de espera antiguo eliminado: {simbolo}")
    
    def get_estado_espera(self, simbolo: str) -> Optional[Dict]:
        """
        Obtiene el estado de espera de un símbolo.
        
        Args:
            simbolo: Símbolo
        
        Returns:
            Estado de espera o None
        """
        return self._estado_espera.get(simbolo)
    
    # ============================================================
    # MÉTODOS DE COMPATIBILIDAD (LEGACY)
    # ============================================================
    
    def validar_momento_exacto_legacy(self,
                                      simbolo: str,
                                      modo: str,
                                      df_m5: pd.DataFrame,
                                      precio_actual: float,
                                      nivel_usado: Optional[float] = None,
                                      direccion: str = 'COMPRA',
                                      regimen: str = 'INCERTO',
                                      volumen_relativo: float = 1.0,
                                      fecha_vela: Optional[datetime] = None) -> Tuple[bool, str, Dict]:
        """
        Versión legacy de validar_momento_exacto.
        DEPRECADO - Usar validar_momento_exacto() en su lugar.
        """
        return self.validar_momento_exacto(
            simbolo=simbolo,
            modo=modo,
            df_m5=df_m5,
            precio_actual=precio_actual,
            nivel_usado=nivel_usado,
            direccion=direccion,
            regimen=regimen,
            volumen_relativo=volumen_relativo,
            fecha_vela=fecha_vela
        )


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_entry_timer(config: Optional[Any] = None,
                       modo_backtest: bool = False,
                       modo_depuracion: bool = False) -> EntryTimer:
    """
    Crea una instancia de EntryTimer.
    
    Args:
        config: Configuración
        modo_backtest: Modo backtest
        modo_depuracion: Modo depuración
    
    Returns:
        EntryTimer
    """
    return EntryTimer(
        config=config,
        modo_backtest=modo_backtest,
        modo_depuracion=modo_depuracion
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Prueba rápida
    import pandas as pd
    import numpy as np
    
    # Crear datos mock
    np.random.seed(42)
    n = 50
    dates = pd.date_range('2024-01-01', periods=n, freq='5min')
    df = pd.DataFrame({
        'Open': np.random.randn(n) * 10 + 100,
        'High': np.random.randn(n) * 10 + 102,
        'Low': np.random.randn(n) * 10 + 98,
        'Close': np.random.randn(n) * 10 + 100,
        'Volume': np.random.randint(100, 1000, n)
    }, index=dates)
    df['Close'] = df['Close'].cumsum() / 10 + 100
    df['High'] = df['Close'] + np.abs(np.random.randn(n) * 2)
    df['Low'] = df['Close'] - np.abs(np.random.randn(n) * 2)
    
    timer = EntryTimer(modo_backtest=True, modo_depuracion=True)
    
    # Probar validación
    valido, razon, detalles = timer.validar_momento_exacto(
        simbolo='EURUSD',
        modo='RETEST',
        df_m5=df,
        precio_actual=df['Close'].iloc[-1],
        nivel_usado=98.5,
        direccion='COMPRA',
        regimen='TREND_ALCISTA_FUERTE',
        volumen_relativo=1.5
    )
    
    print(f"Validación: {'✅' if valido else '❌'}")
    print(f"Razón: {razon}")
    print(f"Detalles: {detalles}")
    
    print("\n✅ Prueba completada")