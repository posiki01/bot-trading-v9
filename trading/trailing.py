#!/usr/bin/env python3
"""
trading/trailing.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Motor de Trailing Stop con reanálisis de mercado y estrategia por fases.

RESPONSABILIDADES:
- Gestionar el movimiento del Stop Loss
- Reanalizar el mercado para decisiones informadas
- Aplicar trailing por fases (breakeven, trailing suave, trailing agresivo)
- Gestionar timeout de operaciones
- Gestionar cierres parciales

MEJORAS V9.0:
- Configuración centralizada desde umbrales
- Reanálisis de mercado más robusto
- Logs detallados de decisiones
- Timeout dinámico por tipo de activo
- Soporte para backtest
- Métodos de compatibilidad
"""

import logging
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

# Importar umbrales centralizados
try:
    from config.umbrales import Umbrales
except ImportError:
    Umbrales = None

logger = logging.getLogger('BotTrading.Trailing')


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class DecisionTrailing:
    """Decisión de trailing."""
    mover_sl: bool = False
    nuevo_sl: Optional[float] = None
    cerrar: bool = False
    motivo_cierre: Optional[str] = None
    razon: str = ""
    fase: str = "NINGUNA"
    analisis: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalisisMercado:
    """Resultado del reanálisis de mercado."""
    soporte_intacto: bool = False
    soporte_cercano: bool = False
    dist_soporte: float = 999.0
    resistencia_cercana: bool = False
    dist_resistencia: float = 999.0
    pullback_valido: bool = False
    regimen_cambio: bool = False
    cerrar: bool = False
    razon: str = ""
    estructura_rota: bool = False


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class TrailingEngine:
    """
    Motor de Trailing Stop con reanálisis de mercado.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    # ============================================================
    # CONFIGURACIÓN POR MODO
    # ============================================================
    
    CONFIG_POR_MODO = {
        'RETEST': {
            'breakeven_umbral': 20,
            'breakeven_margen': 0,
            'trailing_umbral': 40,
            'trailing_distancia': 15,
            'trailing_agresivo_umbral': 70,
            'trailing_agresivo_distancia': 10,
            'timeout_minutos': 480,
            'min_pips_para_mover': 15,
            'cierre_parcial_umbral': 25,
            'cierre_parcial_porcentaje': 0.5,
        },
        'BREAKOUT': {
            'breakeven_umbral': 25,
            'breakeven_margen': 0,
            'trailing_umbral': 50,
            'trailing_distancia': 20,
            'trailing_agresivo_umbral': 80,
            'trailing_agresivo_distancia': 15,
            'timeout_minutos': 360,
            'min_pips_para_mover': 20,
            'cierre_parcial_umbral': 30,
            'cierre_parcial_porcentaje': 0.5,
        },
        'PULLBACK': {
            'breakeven_umbral': 25,
            'breakeven_margen': 0,
            'trailing_umbral': 45,
            'trailing_distancia': 18,
            'trailing_agresivo_umbral': 80,
            'trailing_agresivo_distancia': 12,
            'timeout_minutos': 480,
            'min_pips_para_mover': 18,
            'cierre_parcial_umbral': 30,
            'cierre_parcial_porcentaje': 0.5,
        },
        'NIVEL_FUERTE': {
            'breakeven_umbral': 15,
            'breakeven_margen': 0,
            'trailing_umbral': 35,
            'trailing_distancia': 12,
            'trailing_agresivo_umbral': 60,
            'trailing_agresivo_distancia': 8,
            'timeout_minutos': 360,
            'min_pips_para_mover': 12,
            'cierre_parcial_umbral': 20,
            'cierre_parcial_porcentaje': 0.5,
        },
        'SNIPER_ELITE': {
            'breakeven_umbral': 15,
            'breakeven_margen': 0,
            'trailing_umbral': 35,
            'trailing_distancia': 12,
            'trailing_agresivo_umbral': 60,
            'trailing_agresivo_distancia': 8,
            'timeout_minutos': 480,
            'min_pips_para_mover': 12,
            'cierre_parcial_umbral': 25,
            'cierre_parcial_porcentaje': 0.5,
        },
        'PATRON': {
            'breakeven_umbral': 20,
            'breakeven_margen': 0,
            'trailing_umbral': 40,
            'trailing_distancia': 15,
            'trailing_agresivo_umbral': 70,
            'trailing_agresivo_distancia': 10,
            'timeout_minutos': 360,
            'min_pips_para_mover': 15,
            'cierre_parcial_umbral': 25,
            'cierre_parcial_porcentaje': 0.5,
        },
        'RETEST_FALLBACK': {
            'breakeven_umbral': 20,
            'breakeven_margen': 0,
            'trailing_umbral': 40,
            'trailing_distancia': 15,
            'trailing_agresivo_umbral': 70,
            'trailing_agresivo_distancia': 10,
            'timeout_minutos': 360,
            'min_pips_para_mover': 15,
            'cierre_parcial_umbral': 25,
            'cierre_parcial_porcentaje': 0.5,
        },
        'RUPTURA_FALSA': {
            'breakeven_umbral': 15,
            'breakeven_margen': 0,
            'trailing_umbral': 30,
            'trailing_distancia': 12,
            'trailing_agresivo_umbral': 50,
            'trailing_agresivo_distancia': 8,
            'timeout_minutos': 240,
            'min_pips_para_mover': 12,
            'cierre_parcial_umbral': 20,
            'cierre_parcial_porcentaje': 0.5,
        },
        'VELA_BORDE': {
            'breakeven_umbral': 15,
            'breakeven_margen': 0,
            'trailing_umbral': 30,
            'trailing_distancia': 12,
            'trailing_agresivo_umbral': 50,
            'trailing_agresivo_distancia': 8,
            'timeout_minutos': 240,
            'min_pips_para_mover': 12,
            'cierre_parcial_umbral': 20,
            'cierre_parcial_porcentaje': 0.5,
        },
    }
    
    # ============================================================
    # MULTIPLICADORES POR RÉGIMEN
    # ============================================================
    
    REGIMEN_MULTIPLICADORES = {
        'TREND_ALCISTA_FUERTE': 1.3,
        'TREND_BAJISTA_FUERTE': 1.3,
        'TREND_ALCISTA_DEBIL': 1.1,
        'TREND_BAJISTA_DEBIL': 1.1,
        'RANGO_AMPLIO': 0.9,
        'RANGO_APRETADO': 0.7,
        'CHOP_VOLATIL': 0.5,
        'BREAKOUT_INMINENTE': 1.1,
        'INCERTO': 0.8,
    }
    
    def __init__(self,
                 config: Optional[Any] = None,
                 modo_backtest: bool = False,
                 modo_depuracion: bool = False):
        """
        Inicializa el motor de trailing.
        
        Args:
            config: Configuración
            modo_backtest: Modo backtest
            modo_depuracion: Modo depuración
        """
        self.config = config
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.Trailing')
        
        # Cargar configuración desde umbrales
        self._cargar_configuracion()
        
        # Caché de reanálisis
        self._cache_analisis: Dict[str, Dict] = {}
        self._cache_ttl = 60  # segundos
        
        self.logger.info(f"🚀 TrailingEngine V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Modos configurados: {len(self.CONFIG_POR_MODO)}")
    
    def _cargar_configuracion(self):
        """Carga configuración desde umbrales centralizados."""
        if Umbrales is not None:
            # Trailing desde umbrales
            if hasattr(Umbrales, 'TRAILING'):
                trailing_config = Umbrales.TRAILING
                for modo in self.CONFIG_POR_MODO:
                    # Breakeven
                    key = f'trailing_breakeven_{modo.lower()}'
                    if key in trailing_config:
                        self.CONFIG_POR_MODO[modo]['breakeven_umbral'] = trailing_config[key]
                    
                    # Distancia
                    key = f'trailing_distancia_{modo.lower()}'
                    if key in trailing_config:
                        self.CONFIG_POR_MODO[modo]['trailing_distancia'] = trailing_config[key]
                    
                    # Agresivo
                    key = f'trailing_agresivo_umbral_{modo.lower()}'
                    if key in trailing_config:
                        self.CONFIG_POR_MODO[modo]['trailing_agresivo_umbral'] = trailing_config[key]
        
        # Ajustes para backtest
        if self.modo_backtest:
            for modo in self.CONFIG_POR_MODO:
                config = self.CONFIG_POR_MODO[modo]
                config['breakeven_umbral'] = int(config['breakeven_umbral'] * 0.8)
                config['trailing_umbral'] = int(config['trailing_umbral'] * 0.8)
                config['timeout_minutos'] = int(config['timeout_minutos'] * 0.5)
                config['min_pips_para_mover'] = int(config['min_pips_para_mover'] * 0.8)
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def calcular_movimiento_sl(self,
                               pos: Dict[str, Any],
                               df_h1: Optional[Any],
                               precio_actual: float,
                               fecha: datetime,
                               regimen: str = 'INCERTO',
                               modo: str = 'RETEST') -> DecisionTrailing:
        """
        Calcula si se debe mover el SL y a dónde.
        
        Args:
            pos: Datos de la posición
            df_h1: DataFrame H1 para reanálisis
            precio_actual: Precio actual
            fecha: Fecha actual
            regimen: Régimen de mercado
            modo: Modo de entrada
        
        Returns:
            DecisionTrailing
        """
        simbolo = pos.get('simbolo', '')
        direccion = pos.get('direccion', 'COMPRA')
        entry_price = pos.get('entrada', 0)
        sl_actual = pos.get('sl', 0)
        
        # Validar datos
        if entry_price <= 0 or sl_actual <= 0:
            return DecisionTrailing(razon="Datos de posición inválidos")
        
        # Obtener parámetros
        pip_val = self._obtener_pip_val(simbolo, precio_actual)
        if pip_val <= 0:
            pip_val = 0.0001
        
        digits = self._obtener_digits(simbolo)
        
        # Calcular ganancia en pips
        if direccion == 'COMPRA':
            ganancia_pips = (precio_actual - entry_price) / pip_val
        else:
            ganancia_pips = (entry_price - precio_actual) / pip_val
        
        # ============================================================
        # 1. REANÁLISIS DE MERCADO
        # ============================================================
        
        analisis = self._reanalizar_mercado(
            simbolo=simbolo,
            df_h1=df_h1,
            precio_actual=precio_actual,
            entry_price=entry_price,
            direccion=direccion,
            soporte_original=pos.get('nivel_usado', 0),
            regimen=regimen,
            modo=modo,
            ganancia_pips=ganancia_pips
        )
        
        # Cerrar si el análisis lo recomienda
        if analisis.cerrar:
            return DecisionTrailing(
                cerrar=True,
                motivo_cierre=analisis.razon,
                razon=f"Cierre por reanálisis: {analisis.razon}",
                analisis=analisis.__dict__
            )
        
        # ============================================================
        # 2. OBTENER CONFIGURACIÓN
        # ============================================================
        
        cfg = self.CONFIG_POR_MODO.get(modo, self.CONFIG_POR_MODO['RETEST']).copy()
        
        # Aplicar multiplicador por régimen
        multiplicador = self.REGIMEN_MULTIPLICADORES.get(regimen, 1.0)
        cfg['breakeven_umbral'] = int(cfg['breakeven_umbral'] * multiplicador)
        cfg['trailing_umbral'] = int(cfg['trailing_umbral'] * multiplicador)
        cfg['trailing_agresivo_umbral'] = int(cfg['trailing_agresivo_umbral'] * multiplicador)
        
        # Ajuste por backtest
        if self.modo_backtest:
            cfg['breakeven_umbral'] = max(5, cfg['breakeven_umbral'] - 5)
            cfg['trailing_umbral'] = max(10, cfg['trailing_umbral'] - 10)
        
        # ============================================================
        # 3. DECISIÓN DE TRAILING
        # ============================================================
        
        decision = self._decidir_trailing(
            ganancia_pips=ganancia_pips,
            precio_actual=precio_actual,
            entry_price=entry_price,
            sl_actual=sl_actual,
            direccion=direccion,
            cfg=cfg,
            pip_val=pip_val,
            digits=digits,
            analisis=analisis
        )
        
        # Añadir análisis a la decisión
        decision.analisis = analisis.__dict__
        
        # Log de la decisión
        self._log_decision(simbolo, ganancia_pips, decision)
        
        return decision
    
    # ============================================================
    # DECISIÓN DE TRAILING
    # ============================================================
    
    def _decidir_trailing(self,
                          ganancia_pips: float,
                          precio_actual: float,
                          entry_price: float,
                          sl_actual: float,
                          direccion: str,
                          cfg: Dict[str, Any],
                          pip_val: float,
                          digits: int,
                          analisis: AnalisisMercado) -> DecisionTrailing:
        """
        Decide si mover el SL y a dónde.
        
        Args:
            ganancia_pips: Ganancia en pips
            precio_actual: Precio actual
            entry_price: Precio de entrada
            sl_actual: SL actual
            direccion: Dirección
            cfg: Configuración del modo
            pip_val: Valor del pip
            digits: Dígitos del símbolo
            analisis: Resultado del reanálisis
        
        Returns:
            DecisionTrailing
        """
        # FASE 0: GANANCIA INSUFICIENTE
        if ganancia_pips < cfg.get('min_pips_para_mover', 15):
            return DecisionTrailing(
                razon=f"Ganancia insuficiente ({ganancia_pips:.1f}pips)",
                fase="ESPERA"
            )
        
        # FASE 1: BREAKEVEN
        if ganancia_pips >= cfg['breakeven_umbral']:
            # Calcular breakeven
            if direccion == 'COMPRA':
                nuevo_sl = entry_price + (cfg['breakeven_margen'] * pip_val)
            else:
                nuevo_sl = entry_price - (cfg['breakeven_margen'] * pip_val)
            
            razon = f"BREAKEVEN (umbral {cfg['breakeven_umbral']}pips)"
            fase = "BREAKEVEN"
            
            # Si hay resistencia cercana, breakeven urgente
            if analisis.resistencia_cercana and direccion == 'COMPRA':
                nuevo_sl = entry_price + (2 * pip_val)
                razon = f"BREAKEVEN_URGENTE (resistencia a {analisis.dist_resistencia:.2f}%)"
            elif analisis.soporte_cercano and direccion == 'VENTA':
                nuevo_sl = entry_price - (2 * pip_val)
                razon = f"BREAKEVEN_URGENTE (soporte a {analisis.dist_soporte:.2f}%)"
            
            return self._crear_decision_sl(nuevo_sl, sl_actual, direccion, razon, fase)
        
        # FASE 2: TRAILING SUAVE
        if ganancia_pips >= cfg['trailing_umbral']:
            if direccion == 'COMPRA':
                nuevo_sl = precio_actual - (cfg['trailing_distancia'] * pip_val)
            else:
                nuevo_sl = precio_actual + (cfg['trailing_distancia'] * pip_val)
            
            razon = f"TRAILING_SUAVE (distancia {cfg['trailing_distancia']}pips)"
            fase = "TRAILING_SUAVE"
            
            return self._crear_decision_sl(nuevo_sl, sl_actual, direccion, razon, fase)
        
        # FASE 3: TRAILING AGRESIVO
        if ganancia_pips >= cfg['trailing_agresivo_umbral']:
            if direccion == 'COMPRA':
                nuevo_sl = precio_actual - (cfg['trailing_agresivo_distancia'] * pip_val)
            else:
                nuevo_sl = precio_actual + (cfg['trailing_agresivo_distancia'] * pip_val)
            
            razon = f"TRAILING_AGRESSIVO (distancia {cfg['trailing_agresivo_distancia']}pips)"
            fase = "TRAILING_AGRESSIVO"
            
            return self._crear_decision_sl(nuevo_sl, sl_actual, direccion, razon, fase)
        
        return DecisionTrailing(razon="Sin cambio de SL", fase="NINGUNA")
    
    def _crear_decision_sl(self,
                           nuevo_sl: float,
                           sl_actual: float,
                           direccion: str,
                           razon: str,
                           fase: str) -> DecisionTrailing:
        """
        Crea una decisión de SL.
        
        Args:
            nuevo_sl: Nuevo SL propuesto
            sl_actual: SL actual
            direccion: Dirección
            razon: Razón del movimiento
            fase: Fase del trailing
        
        Returns:
            DecisionTrailing
        """
        # Validar que mejora el SL actual
        if direccion == 'COMPRA' and nuevo_sl <= sl_actual:
            return DecisionTrailing(
                razon=f"SL no mejora (nuevo: {nuevo_sl:.5f}, actual: {sl_actual:.5f})",
                fase=fase
            )
        if direccion == 'VENTA' and nuevo_sl >= sl_actual:
            return DecisionTrailing(
                razon=f"SL no mejora (nuevo: {nuevo_sl:.5f}, actual: {sl_actual:.5f})",
                fase=fase
            )
        
        return DecisionTrailing(
            mover_sl=True,
            nuevo_sl=nuevo_sl,
            razon=razon,
            fase=fase
        )
    
    # ============================================================
    # REANÁLISIS DE MERCADO
    # ============================================================
    
    def _reanalizar_mercado(self,
                            simbolo: str,
                            df_h1: Optional[Any],
                            precio_actual: float,
                            entry_price: float,
                            direccion: str,
                            soporte_original: float,
                            regimen: str,
                            modo: str,
                            ganancia_pips: float) -> AnalisisMercado:
        """
        Reanaliza el mercado para decidir si mover SL.
        
        Args:
            simbolo: Símbolo
            df_h1: DataFrame H1
            precio_actual: Precio actual
            entry_price: Precio de entrada
            direccion: Dirección
            soporte_original: Soporte original
            regimen: Régimen de mercado
            modo: Modo de entrada
            ganancia_pips: Ganancia en pips
        
        Returns:
            AnalisisMercado
        """
        resultado = AnalisisMercado()
        
        # Verificar caché
        cache_key = f"{simbolo}_{id(df_h1)}"
        if cache_key in self._cache_analisis:
            return AnalisisMercado(**self._cache_analisis[cache_key])
        
        if df_h1 is None or len(df_h1) < 20:
            resultado.razon = "Sin datos suficientes"
            return resultado
        
        try:
            high = df_h1['High']
            low = df_h1['Low']
            close = df_h1['Close']
            lookback = min(50, len(df_h1))
            
            # 1. Encontrar soportes y resistencias locales
            soportes = []
            resistencias = []
            
            for i in range(5, len(df_h1) - 5):
                if low.iloc[i] == low.iloc[i-5:i+5].min():
                    soportes.append((df_h1.index[i], low.iloc[i]))
                if high.iloc[i] == high.iloc[i-5:i+5].max():
                    resistencias.append((df_h1.index[i], high.iloc[i]))
            
            # 2. Verificar soporte original
            if soporte_original > 0:
                min_reciente = low.iloc[-20:].min()
                if min_reciente >= soporte_original * 0.999:
                    resultado.soporte_intacto = True
                    resultado.dist_soporte = (precio_actual - soporte_original) / soporte_original * 100
                else:
                    resultado.cerrar = True
                    resultado.razon = f"Soporte roto (original: {soporte_original:.5f})"
                    return resultado
            
            # 3. Encontrar soporte cercano
            for idx, precio in soportes:
                dist = (precio_actual - precio) / precio_actual * 100
                if 0 < dist < 1.0:
                    resultado.soporte_cercano = True
                    if dist < resultado.dist_soporte:
                        resultado.dist_soporte = dist
            
            # 4. Encontrar resistencia cercana
            for idx, precio in resistencias:
                dist = (precio - precio_actual) / precio_actual * 100
                if 0 < dist < 1.0:
                    resultado.resistencia_cercana = True
                    if dist < resultado.dist_resistencia:
                        resultado.dist_resistencia = dist
            
            # 5. Detectar pullback válido
            if resultado.soporte_cercano and ganancia_pips > 10:
                if resultado.dist_soporte < 0.5:
                    resultado.pullback_valido = True
            
            # 6. Ruptura de estructura
            max_reciente = high.iloc[-lookback:].max()
            min_reciente = low.iloc[-lookback:].min()
            
            if direccion == 'COMPRA' and precio_actual < min_reciente:
                resultado.estructura_rota = True
                resultado.cerrar = True
                resultado.razon = "Ruptura de mínimo reciente"
                return resultado
            elif direccion == 'VENTA' and precio_actual > max_reciente:
                resultado.estructura_rota = True
                resultado.cerrar = True
                resultado.razon = "Ruptura de máximo reciente"
                return resultado
            
            # 7. Cambio de régimen
            if regimen in ['CHOP_VOLATIL', 'INCERTO'] and ganancia_pips < 5:
                resultado.regimen_cambio = True
                resultado.cerrar = True
                resultado.razon = f"Régimen {regimen} sin avance"
                return resultado
            
            resultado.razon = "Análisis completado"
            
        except Exception as e:
            self.logger.error(f"Error en reanálisis para {simbolo}: {e}")
            resultado.razon = f'Error en análisis: {e}'
        
        # Guardar en caché
        self._cache_analisis[cache_key] = resultado.__dict__
        
        return resultado
    
    # ============================================================
    # TIMEOUT
    # ============================================================
    
    def verificar_timeout(self,
                          pos: Dict[str, Any],
                          fecha: datetime,
                          ganancia_pips: float,
                          modo: str = 'RETEST') -> Tuple[bool, str]:
        """
        Verifica si la operación debe cerrarse por TIMEOUT.
        
        Args:
            pos: Datos de la posición
            fecha: Fecha actual
            ganancia_pips: Ganancia en pips
            modo: Modo de entrada
        
        Returns:
            (debe_cerrar, razon)
        """
        tiempo_abierto = (fecha - pos.get('fecha_entrada', fecha)).total_seconds() / 60
        
        cfg = self.CONFIG_POR_MODO.get(modo, self.CONFIG_POR_MODO['RETEST'])
        timeout_minutos = cfg.get('timeout_minutos', 480)
        
        if self.modo_backtest:
            timeout_minutos = int(timeout_minutos * 0.5)
        
        if tiempo_abierto > timeout_minutos:
            if ganancia_pips > 15:
                return False, "Timeout en ganancia significativa"
            if 5 < ganancia_pips <= 15:
                return False, "Timeout ganancia moderada"
            if ganancia_pips < 0:
                return True, "TIMEOUT_PERDIDA"
            if abs(ganancia_pips) < 5:
                return True, "TIMEOUT_BREAKEVEN"
        
        return False, "OK"
    
    # ============================================================
    # CIERRE PARCIAL
    # ============================================================
    
    def verificar_cierre_parcial(self,
                                 pos: Dict[str, Any],
                                 ganancia_pips: float,
                                 modo: str = 'RETEST') -> Tuple[bool, float]:
        """
        Verifica si se debe realizar cierre parcial.
        
        Args:
            pos: Datos de la posición
            ganancia_pips: Ganancia en pips
            modo: Modo de entrada
        
        Returns:
            (debe_cerrar, volumen_a_cerrar)
        """
        tp1_realizado = pos.get('tp1_realizado', False)
        
        if not tp1_realizado:
            cfg = self.CONFIG_POR_MODO.get(modo, self.CONFIG_POR_MODO['RETEST'])
            umbral = cfg.get('cierre_parcial_umbral', 25)
            porcentaje = cfg.get('cierre_parcial_porcentaje', 0.5)
            
            if ganancia_pips > umbral:
                volumen = pos.get('lotes', 0)
                volumen_a_cerrar = volumen * porcentaje
                
                if volumen_a_cerrar >= 0.01:
                    return True, round(volumen_a_cerrar, 3)
        
        return False, 0.0
    
    # ============================================================
    # UTILIDADES
    # ============================================================
    
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
    
    def _obtener_digits(self, simbolo: str) -> int:
        """
        Obtiene el número de dígitos del símbolo.
        
        Args:
            simbolo: Símbolo
        
        Returns:
            Número de dígitos
        """
        simbolo_upper = simbolo.upper()
        
        if 'JPY' in simbolo_upper:
            return 3
        if any(x in simbolo_upper for x in ['XAU', 'XAG']):
            return 2
        if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']):
            return 2
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return 2
        return 5
    
    # ============================================================
    # LOGGING
    # ============================================================
    
    def _log_decision(self, simbolo: str, ganancia_pips: float, decision: DecisionTrailing):
        """
        Log de la decisión de trailing.
        
        Args:
            simbolo: Símbolo
            ganancia_pips: Ganancia en pips
            decision: Decisión de trailing
        """
        if self.modo_depuracion:
            nivel = logging.DEBUG
        else:
            nivel = logging.INFO
        
        if decision.mover_sl:
            self.logger.log(
                nivel,
                f"🔄 {simbolo}: {decision.razon} | "
                f"Nuevo SL: {decision.nuevo_sl:.5f} | "
                f"Ganancia: {ganancia_pips:.1f}pips | "
                f"Fase: {decision.fase}"
            )
        elif decision.cerrar:
            self.logger.log(
                nivel,
                f"🔒 {simbolo}: {decision.razon} | "
                f"Ganancia: {ganancia_pips:.1f}pips | "
                f"Motivo: {decision.motivo_cierre}"
            )
        elif self.modo_depuracion:
            self.logger.debug(
                f"⏭️ {simbolo}: {decision.razon} | "
                f"Ganancia: {ganancia_pips:.1f}pips"
            )
    
    # ============================================================
    # MANTENIMIENTO
    # ============================================================
    
    def limpiar_cache(self):
        """Limpia la caché de reanálisis."""
        self._cache_analisis.clear()
        self.logger.debug("🧹 Caché de trailing limpiada")
    
    # ============================================================
    # MÉTODOS DE COMPATIBILIDAD (LEGACY)
    # ============================================================
    
    def calcular_movimiento_sl_legacy(self,
                                      pos: Dict[str, Any],
                                      df_h1: Optional[Any],
                                      precio_actual: float,
                                      fecha: datetime,
                                      regimen: str = 'INCERTO',
                                      modo: str = 'RETEST') -> Dict[str, Any]:
        """
        Versión legacy de calcular_movimiento_sl.
        DEPRECADO - Usar calcular_movimiento_sl() en su lugar.
        """
        decision = self.calcular_movimiento_sl(
            pos=pos,
            df_h1=df_h1,
            precio_actual=precio_actual,
            fecha=fecha,
            regimen=regimen,
            modo=modo
        )
        
        # Convertir a diccionario para compatibilidad
        return {
            'mover_sl': decision.mover_sl,
            'nuevo_sl': decision.nuevo_sl,
            'razon': decision.razon,
            'cerrar': decision.cerrar,
            'motivo_cierre': decision.motivo_cierre,
            'analisis': decision.analisis,
        }


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_trailing_engine(config: Optional[Any] = None,
                           modo_backtest: bool = False,
                           modo_depuracion: bool = False) -> TrailingEngine:
    """
    Crea una instancia de TrailingEngine.
    
    Args:
        config: Configuración
        modo_backtest: Modo backtest
        modo_depuracion: Modo depuración
    
    Returns:
        TrailingEngine
    """
    return TrailingEngine(
        config=config,
        modo_backtest=modo_backtest,
        modo_depuracion=modo_depuracion
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Prueba rápida
    engine = TrailingEngine(modo_backtest=True, modo_depuracion=True)
    
    # Simular posición
    pos = {
        'simbolo': 'EURUSD',
        'direccion': 'COMPRA',
        'entrada': 1.10000,
        'sl': 1.09800,
        'lotes': 0.01,
        'nivel_usado': 1.09850,
        'fecha_entrada': datetime.now(timezone.utc) - timedelta(hours=1),
    }
    
    # Simular precio actual
    precio_actual = 1.10200
    fecha = datetime.now(timezone.utc)
    
    # Calcular decisión
    decision = engine.calcular_movimiento_sl(
        pos=pos,
        df_h1=None,
        precio_actual=precio_actual,
        fecha=fecha,
        regimen='TREND_ALCISTA_FUERTE',
        modo='RETEST'
    )
    
    print(f"Decisión: {decision.razon}")
    print(f"  Mover SL: {decision.mover_sl}")
    if decision.mover_sl:
        print(f"  Nuevo SL: {decision.nuevo_sl:.5f}")
    print(f"  Fase: {decision.fase}")
    
    # Verificar timeout
    debe_cerrar, razon = engine.verificar_timeout(
        pos=pos,
        fecha=fecha,
        ganancia_pips=20,
        modo='RETEST'
    )
    print(f"\nTimeout: {debe_cerrar} - {razon}")
    
    # Verificar cierre parcial
    debe_cerrar_parcial, volumen = engine.verificar_cierre_parcial(
        pos=pos,
        ganancia_pips=30,
        modo='RETEST'
    )
    print(f"Cierre parcial: {debe_cerrar_parcial} - Volumen: {volumen:.3f}")
    
    print("\n✅ Prueba completada")