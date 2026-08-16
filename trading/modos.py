#!/usr/bin/env python3
"""
trading/modos.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Sistema de selección de modo de entrada con validación de régimen.

RESPONSABILIDADES:
- Seleccionar el mejor modo de entrada según régimen
- Validar condiciones específicas por modo
- Integrar con EntryTimer para validación de momento
- Aplicar ponderaciones por régimen

MEJORAS V9.0:
- Integración con umbrales centralizados
- Logs detallados de selección
- Configuración flexible por régimen
- Eliminación de duplicación con sniper_modos
- Soporte para backtest
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from enum import Enum

# ============================================================
# IMPORTS
# ============================================================

from config.umbrales import Umbrales
from utils.helpers import safe_float

logger = logging.getLogger('BotTrading.Modos')


# ============================================================
# ENUMS
# ============================================================

class ModoEntrada(Enum):
    """Modos de entrada disponibles."""
    RETEST = "RETEST"
    BREAKOUT = "BREAKOUT"
    PULLBACK = "PULLBACK"
    NIVEL_FUERTE = "NIVEL_FUERTE"
    PATRON = "PATRON"
    RUPTURA_FALSA = "RUPTURA_FALSA"
    VELA_BORDE = "VELA_BORDE"
    RETEST_FALLBACK = "RETEST_FALLBACK"
    SNIPER_ELITE = "SNIPER_ELITE"


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class ModoSelector:
    """
    Sistema de selección de modo con validación de régimen.
    V9.0 - REFACTORIZADO COMPLETAMENTE.
    """
    
    # ============================================================
    # CONFIGURACIÓN POR RÉGIMEN
    # ============================================================
    
    PRIORIDAD_POR_REGIMEN = {
        'TREND_ALCISTA_FUERTE': [
            ModoEntrada.PULLBACK,
            ModoEntrada.BREAKOUT,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.RETEST,
            ModoEntrada.PATRON,
            ModoEntrada.RETEST_FALLBACK,
        ],
        'TREND_BAJISTA_FUERTE': [
            ModoEntrada.PULLBACK,
            ModoEntrada.BREAKOUT,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.RETEST,
            ModoEntrada.PATRON,
            ModoEntrada.RETEST_FALLBACK,
        ],
        'TREND_ALCISTA_DEBIL': [
            ModoEntrada.PULLBACK,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.PATRON,
            ModoEntrada.BREAKOUT,
            ModoEntrada.RETEST_FALLBACK,
        ],
        'TREND_BAJISTA_DEBIL': [
            ModoEntrada.PULLBACK,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.PATRON,
            ModoEntrada.BREAKOUT,
            ModoEntrada.RETEST_FALLBACK,
        ],
        'RANGO_AMPLIO': [
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.VELA_BORDE,
            ModoEntrada.RUPTURA_FALSA,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.PATRON,
            ModoEntrada.BREAKOUT,
            ModoEntrada.RETEST_FALLBACK,
        ],
        'RANGO_APRETADO': [
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.RETEST,
            ModoEntrada.VELA_BORDE,
            ModoEntrada.RUPTURA_FALSA,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.PATRON,
            ModoEntrada.RETEST_FALLBACK,
        ],
        'BREAKOUT_INMINENTE': [
            ModoEntrada.BREAKOUT,
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.RUPTURA_FALSA,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
            ModoEntrada.PATRON,
            ModoEntrada.RETEST_FALLBACK,
        ],
        'CHOP_VOLATIL': [
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.RETEST_FALLBACK,
            ModoEntrada.RETEST,
        ],
        'INCERTO': [
            ModoEntrada.SNIPER_ELITE,
            ModoEntrada.RETEST_FALLBACK,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,
        ],
    }
    
    # ============================================================
    # SCORE MÍNIMO POR MODO
    # ============================================================
    
    SCORE_MINIMO_POR_MODO = {
        ModoEntrada.RETEST: 45,
        ModoEntrada.BREAKOUT: 55,
        ModoEntrada.PULLBACK: 50,
        ModoEntrada.NIVEL_FUERTE: 45,
        ModoEntrada.PATRON: 45,
        ModoEntrada.RUPTURA_FALSA: 35,
        ModoEntrada.VELA_BORDE: 35,
        ModoEntrada.RETEST_FALLBACK: 40,
        ModoEntrada.SNIPER_ELITE: 60,
    }
    
    # ============================================================
    # PONDERACIONES POR RÉGIMEN
    # ============================================================
    
    PONDERACION_POR_REGIMEN = {
        'TREND_ALCISTA_FUERTE': {
            ModoEntrada.PULLBACK: 1.4,
            ModoEntrada.BREAKOUT: 1.3,
            ModoEntrada.RETEST: 0.9,
            ModoEntrada.NIVEL_FUERTE: 1.0,
            ModoEntrada.SNIPER_ELITE: 1.2,
        },
        'TREND_BAJISTA_FUERTE': {
            ModoEntrada.PULLBACK: 1.4,
            ModoEntrada.BREAKOUT: 1.3,
            ModoEntrada.RETEST: 0.9,
            ModoEntrada.NIVEL_FUERTE: 1.0,
            ModoEntrada.SNIPER_ELITE: 1.2,
        },
        'TREND_ALCISTA_DEBIL': {
            ModoEntrada.PULLBACK: 1.3,
            ModoEntrada.RETEST: 1.1,
            ModoEntrada.BREAKOUT: 1.0,
            ModoEntrada.NIVEL_FUERTE: 1.1,
        },
        'TREND_BAJISTA_DEBIL': {
            ModoEntrada.PULLBACK: 1.3,
            ModoEntrada.RETEST: 1.1,
            ModoEntrada.BREAKOUT: 1.0,
            ModoEntrada.NIVEL_FUERTE: 1.1,
        },
        'RANGO_AMPLIO': {
            ModoEntrada.RETEST: 1.5,
            ModoEntrada.NIVEL_FUERTE: 1.3,
            ModoEntrada.BREAKOUT: 0.4,
            ModoEntrada.PULLBACK: 0.3,
        },
        'RANGO_APRETADO': {
            ModoEntrada.NIVEL_FUERTE: 1.6,
            ModoEntrada.RETEST: 1.4,
            ModoEntrada.SNIPER_ELITE: 1.2,
        },
        'BREAKOUT_INMINENTE': {
            ModoEntrada.BREAKOUT: 1.4,
            ModoEntrada.RUPTURA_FALSA: 1.2,
            ModoEntrada.RETEST: 0.8,
            ModoEntrada.SNIPER_ELITE: 1.1,
        },
        'CHOP_VOLATIL': {
            ModoEntrada.RETEST: 0.5,
            ModoEntrada.SNIPER_ELITE: 1.0,
        },
        'INCERTO': {
            ModoEntrada.RETEST: 0.5,
            ModoEntrada.SNIPER_ELITE: 1.0,
        },
    }
    
    def __init__(self,
                 config: Optional[Any] = None,
                 entry_timer: Optional[Any] = None,
                 modo_backtest: bool = False,
                 modo_depuracion: bool = False):
        """
        Inicializa el selector de modos.
        
        Args:
            config: Configuración
            entry_timer: EntryTimer para validación de momento
            modo_backtest: Modo backtest
            modo_depuracion: Modo depuración
        """
        self.config = config
        self.entry_timer = entry_timer
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.Modos')
        
        # Cargar configuración desde umbrales
        self._cargar_configuracion()
        
        self.logger.info(f"🎯 ModoSelector V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Modos configurados: {len(self.PRIORIDAD_POR_REGIMEN)}")
    
    def _cargar_configuracion(self):
        """Carga configuración desde umbrales centralizados."""
        if Umbrales is not None:
            # Score mínimo por modo
            if hasattr(Umbrales, 'MODOS'):
                modos_config = Umbrales.MODOS
                for modo in self.SCORE_MINIMO_POR_MODO:
                    key = f'score_modo_{modo.value.lower()}'
                    if key in modos_config:
                        self.SCORE_MINIMO_POR_MODO[modo] = modos_config[key]
            
            # Prioridades por régimen
            if hasattr(Umbrales, 'MODOS'):
                modos_config = Umbrales.MODOS
                for regimen in self.PRIORIDAD_POR_REGIMEN:
                    key = f'modos_{regimen.lower()}'
                    if key in modos_config:
                        # Convertir strings a ModoEntrada
                        nuevos_modos = []
                        for m in modos_config[key]:
                            try:
                                nuevos_modos.append(ModoEntrada(m))
                            except ValueError:
                                pass
                        if nuevos_modos:
                            self.PRIORIDAD_POR_REGIMEN[regimen] = nuevos_modos
        
        # Ajustes para backtest
        if self.modo_backtest:
            for modo in self.SCORE_MINIMO_POR_MODO:
                self.SCORE_MINIMO_POR_MODO[modo] = max(20, self.SCORE_MINIMO_POR_MODO[modo] - 15)
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def seleccionar_modo(self,
                         simbolo: str,
                         regimen: str,
                         direccion: str,
                         score_h1: float,
                         nivel_usado: Optional[float] = None,
                         df_m5: Optional[Any] = None,
                         precio_actual: float = 0,
                         volumen_relativo: float = 1.0,
                         patron_calidad: float = 0,
                         es_reversal: bool = False,
                         en_nivel_clave: bool = False,
                         fecha_vela: Optional[datetime] = None) -> Tuple[Optional[ModoEntrada], str, Dict]:
        """
        Selecciona el mejor modo de entrada según régimen y condiciones.
        
        Args:
            simbolo: Símbolo
            regimen: Régimen de mercado
            direccion: Dirección
            score_h1: Score H1
            nivel_usado: Nivel usado (opcional)
            df_m5: DataFrame M5 (para EntryTimer)
            precio_actual: Precio actual
            volumen_relativo: Volumen relativo
            patron_calidad: Calidad del patrón
            es_reversal: Si es reversal
            en_nivel_clave: Si está en nivel clave
            fecha_vela: Fecha de la vela (para backtest)
        
        Returns:
            (modo, razon, detalles)
        """
        detalles = {
            'simbolo': simbolo,
            'regimen': regimen,
            'direccion': direccion,
            'score_h1': score_h1,
            'nivel_usado': nivel_usado,
            'volumen': volumen_relativo,
            'patron_calidad': patron_calidad,
            'es_reversal': es_reversal,
            'en_nivel_clave': en_nivel_clave,
        }
        
        # 1. Obtener prioridades según régimen
        modos_prioridad = self._obtener_prioridades(regimen)
        
        if self.modo_depuracion:
            self.logger.debug(f"🔍 {simbolo}: Prioridades para {regimen}: {[m.value for m in modos_prioridad]}")
        
        # 2. Evaluar cada modo en orden de prioridad
        for modo in modos_prioridad:
            # Verificar score mínimo
            score_min = self.SCORE_MINIMO_POR_MODO.get(modo, 40)
            if self.modo_backtest:
                score_min = max(15, score_min - 10)
            
            if score_h1 < score_min:
                if self.modo_depuracion:
                    self.logger.debug(f"   ⏭️ {modo.value}: score {score_h1:.0f} < {score_min}")
                continue
            
            # Verificar condiciones específicas del modo
            valido, razon = self._verificar_condiciones_modo(
                modo, simbolo, regimen, direccion, score_h1,
                nivel_usado, volumen_relativo, patron_calidad,
                es_reversal, en_nivel_clave
            )
            
            if not valido:
                if self.modo_depuracion:
                    self.logger.debug(f"   ⏭️ {modo.value}: {razon}")
                continue
            
            # Verificar momento exacto (EntryTimer)
            if self.entry_timer and df_m5 is not None and precio_actual > 0:
                valido_momento, razon_momento, _ = self.entry_timer.validar_momento_exacto(
                    simbolo=simbolo,
                    modo=modo.value,
                    df_m5=df_m5,
                    precio_actual=precio_actual,
                    nivel_usado=nivel_usado,
                    direccion=direccion,
                    regimen=regimen,
                    volumen_relativo=volumen_relativo,
                    fecha_vela=fecha_vela
                )
                
                if not valido_momento:
                    if self.modo_depuracion:
                        self.logger.debug(f"   ⏭️ {modo.value}: momento no exacto - {razon_momento}")
                    continue
            
            # Modo seleccionado
            detalles['modo_seleccionado'] = modo.value
            detalles['score_min_usado'] = score_min
            detalles['ponderacion'] = self._obtener_ponderacion(modo, regimen)
            
            self.logger.info(f"🎯 {simbolo}: Modo seleccionado: {modo.value} (score: {score_h1:.0f}, min: {score_min})")
            
            return modo, f"Seleccionado {modo.value}", detalles
        
        # No se encontró modo
        self.logger.debug(f"⏭️ {simbolo}: No se encontró modo válido para {regimen}")
        return None, "No se encontró modo válido", detalles
    
    # ============================================================
    # OBTENCIÓN DE PRIORIDADES
    # ============================================================
    
    def _obtener_prioridades(self, regimen: str) -> List[ModoEntrada]:
        """
        Obtiene la lista de modos priorizados para un régimen.
        
        Args:
            regimen: Régimen de mercado
        
        Returns:
            Lista de modos en orden de prioridad
        """
        return self.PRIORIDAD_POR_REGIMEN.get(regimen, self.PRIORIDAD_POR_REGIMEN['INCERTO']).copy()
    
    def _obtener_ponderacion(self, modo: ModoEntrada, regimen: str) -> float:
        """
        Obtiene la ponderación de un modo para un régimen.
        
        Args:
            modo: Modo de entrada
            regimen: Régimen de mercado
        
        Returns:
            Ponderación (0.5-1.5)
        """
        ponderaciones = self.PONDERACION_POR_REGIMEN.get(regimen, {})
        return ponderaciones.get(modo, 1.0)
    
    # ============================================================
    # VERIFICACIÓN DE CONDICIONES POR MODO
    # ============================================================
    
    def _verificar_condiciones_modo(self,
                                    modo: ModoEntrada,
                                    simbolo: str,
                                    regimen: str,
                                    direccion: str,
                                    score_h1: float,
                                    nivel_usado: Optional[float],
                                    volumen_relativo: float,
                                    patron_calidad: float,
                                    es_reversal: bool,
                                    en_nivel_clave: bool) -> Tuple[bool, str]:
        """
        Verifica condiciones específicas para cada modo.
        
        Args:
            modo: Modo a verificar
            simbolo: Símbolo
            regimen: Régimen
            direccion: Dirección
            score_h1: Score H1
            nivel_usado: Nivel usado
            volumen_relativo: Volumen relativo
            patron_calidad: Calidad del patrón
            es_reversal: Si es reversal
            en_nivel_clave: Si está en nivel clave
        
        Returns:
            (valido, razon)
        """
        # --- RETEST ---
        if modo == ModoEntrada.RETEST:
            if not en_nivel_clave and not nivel_usado:
                return False, "No hay nivel clave"
            
            if regimen in ['CHOP_VOLATIL', 'INCERTO'] and score_h1 < 60:
                return False, f"Score bajo para {regimen}"
            
            return True, "RETEST válido"
        
        # --- NIVEL_FUERTE ---
        elif modo == ModoEntrada.NIVEL_FUERTE:
            if not en_nivel_clave and not nivel_usado:
                return False, "No hay nivel clave"
            
            if score_h1 < 50:
                return False, f"Score bajo ({score_h1:.0f} < 50)"
            
            return True, "NIVEL_FUERTE válido"
        
        # --- BREAKOUT ---
        elif modo == ModoEntrada.BREAKOUT:
            if volumen_relativo < 0.6:
                return False, f"Volumen bajo ({volumen_relativo:.2f}x < 0.6x)"
            
            if regimen not in ['BREAKOUT_INMINENTE', 'TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE']:
                return False, f"Régimen no adecuado para BREAKOUT"
            
            return True, "BREAKOUT válido"
        
        # --- PULLBACK ---
        elif modo == ModoEntrada.PULLBACK:
            if regimen not in ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE', 
                              'TREND_ALCISTA_DEBIL', 'TREND_BAJISTA_DEBIL']:
                return False, f"Régimen no adecuado para PULLBACK"
            
            if score_h1 < 55:
                return False, f"Score bajo para PULLBACK ({score_h1:.0f} < 55)"
            
            return True, "PULLBACK válido"
        
        # --- PATRON ---
        elif modo == ModoEntrada.PATRON:
            if patron_calidad < 25:
                return False, f"Calidad de patrón baja ({patron_calidad:.0f} < 25)"
            
            return True, "PATRON válido"
        
        # --- RUPTURA_FALSA ---
        elif modo == ModoEntrada.RUPTURA_FALSA:
            if regimen not in ['RANGO_AMPLIO', 'RANGO_APRETADO', 'BREAKOUT_INMINENTE']:
                return False, f"Régimen no adecuado para RUPTURA_FALSA"
            
            return True, "RUPTURA_FALSA válido"
        
        # --- VELA_BORDE ---
        elif modo == ModoEntrada.VELA_BORDE:
            if not en_nivel_clave and not nivel_usado:
                return False, "No hay nivel clave"
            
            return True, "VELA_BORDE válido"
        
        # --- SNIPER_ELITE ---
        elif modo == ModoEntrada.SNIPER_ELITE:
            if score_h1 < 65:
                return False, f"Score bajo para SNIPER_ELITE ({score_h1:.0f} < 65)"
            
            if not en_nivel_clave and patron_calidad < 35:
                return False, "Falta nivel clave o patrón de calidad"
            
            return True, "SNIPER_ELITE válido"
        
        # --- RETEST_FALLBACK ---
        elif modo == ModoEntrada.RETEST_FALLBACK:
            if score_h1 < 55:
                return False, f"Score bajo para RETEST_FALLBACK ({score_h1:.0f} < 55)"
            
            return True, "RETEST_FALLBACK válido"
        
        return True, "Condiciones OK"
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def set_entry_timer(self, entry_timer: Any):
        """
        Inyecta el EntryTimer.
        
        Args:
            entry_timer: EntryTimer
        """
        self.entry_timer = entry_timer
        self.logger.info("⏱️ EntryTimer inyectado en ModoSelector")
    
    def obtener_score_minimo(self, modo: ModoEntrada) -> int:
        """
        Obtiene el score mínimo para un modo.
        
        Args:
            modo: Modo de entrada
        
        Returns:
            Score mínimo
        """
        score = self.SCORE_MINIMO_POR_MODO.get(modo, 40)
        if self.modo_backtest:
            score = max(15, score - 10)
        return score
    
    def obtener_modos_prioritarios(self, regimen: str) -> List[str]:
        """
        Obtiene los modos prioritarios para un régimen como strings.
        
        Args:
            regimen: Régimen de mercado
        
        Returns:
            Lista de nombres de modos
        """
        modos = self.PRIORIDAD_POR_REGIMEN.get(regimen, self.PRIORIDAD_POR_REGIMEN['INCERTO'])
        return [m.value for m in modos]
    
    def es_modo_valido_para_regimen(self, modo: ModoEntrada, regimen: str) -> bool:
        """
        Verifica si un modo es válido para un régimen.
        
        Args:
            modo: Modo de entrada
            regimen: Régimen de mercado
        
        Returns:
            True si es válido
        """
        modos = self.PRIORIDAD_POR_REGIMEN.get(regimen, self.PRIORIDAD_POR_REGIMEN['INCERTO'])
        return modo in modos
    
    # ============================================================
    # MÉTODOS DE COMPATIBILIDAD (LEGACY)
    # ============================================================
    
    def seleccionar_modo_legacy(self,
                                simbolo: str,
                                regimen: str,
                                direccion: str,
                                score_h1: float,
                                nivel_usado: Optional[float] = None,
                                df_m5: Optional[Any] = None,
                                precio_actual: float = 0,
                                volumen_relativo: float = 1.0,
                                patron_calidad: float = 0,
                                es_reversal: bool = False,
                                en_nivel_clave: bool = False,
                                fecha_vela: Optional[datetime] = None) -> Tuple[Optional[str], str, Dict]:
        """
        Versión legacy de seleccionar_modo (retorna string en lugar de ModoEntrada).
        DEPRECADO - Usar seleccionar_modo() en su lugar.
        """
        modo, razon, detalles = self.seleccionar_modo(
            simbolo=simbolo,
            regimen=regimen,
            direccion=direccion,
            score_h1=score_h1,
            nivel_usado=nivel_usado,
            df_m5=df_m5,
            precio_actual=precio_actual,
            volumen_relativo=volumen_relativo,
            patron_calidad=patron_calidad,
            es_reversal=es_reversal,
            en_nivel_clave=en_nivel_clave,
            fecha_vela=fecha_vela
        )
        
        if modo:
            return modo.value, razon, detalles
        return None, razon, detalles
    
    def get_prioridad_por_regimen(self, regimen: str) -> List[str]:
        """
        Obtiene prioridades como strings.
        DEPRECADO - Usar obtener_modos_prioritarios() en su lugar.
        """
        return self.obtener_modos_prioritarios(regimen)


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_modo_selector(config: Optional[Any] = None,
                         entry_timer: Optional[Any] = None,
                         modo_backtest: bool = False,
                         modo_depuracion: bool = False) -> ModoSelector:
    """
    Crea una instancia de ModoSelector.
    
    Args:
        config: Configuración
        entry_timer: EntryTimer
        modo_backtest: Modo backtest
        modo_depuracion: Modo depuración
    
    Returns:
        ModoSelector
    """
    return ModoSelector(
        config=config,
        entry_timer=entry_timer,
        modo_backtest=modo_backtest,
        modo_depuracion=modo_depuracion
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Prueba rápida
    selector = ModoSelector(modo_backtest=True, modo_depuracion=True)
    
    # Simular selección
    modo, razon, detalles = selector.seleccionar_modo(
        simbolo='EURUSD',
        regimen='TREND_ALCISTA_FUERTE',
        direccion='COMPRA',
        score_h1=75,
        nivel_usado=1.1000,
        en_nivel_clave=True,
        volumen_relativo=1.5,
        patron_calidad=40
    )
    
    print(f"Modo seleccionado: {modo.value if modo else 'N/A'}")
    print(f"Razón: {razon}")
    print(f"Detalles: {detalles}")
    
    # Mostrar prioridades
    print("\nPrioridades por régimen:")
    for regimen in ['TREND_ALCISTA_FUERTE', 'RANGO_AMPLIO', 'CHOP_VOLATIL']:
        modos = selector.obtener_modos_prioritarios(regimen)
        print(f"  {regimen}: {modos}")
    
    print("\n✅ Prueba completada")