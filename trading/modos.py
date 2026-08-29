#!/usr/bin/env python3
"""
trading/modos.py (V9.2 - DINÁMICO)
Sistema de selección de modo de entrada con validación de régimen y priorización dinámica.

MEJORAS V9.2:
- Priorización dinámica basada en winrate y factor de beneficio históricos
- Aprendizaje automático de los modos más rentables por régimen
- Integración con SQLite para consultar resultados históricos
- Umbrales configurables para el sistema de aprendizaje
"""

import logging
import time
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
    Sistema de selección de modo con priorización dinámica.
    V9.2 - DINÁMICO.
    """
    
    # ============================================================
    # CONFIGURACIÓN POR RÉGIMEN (BASE)
    # ============================================================
    
    PRIORIDAD_BASE_POR_REGIMEN = {
        # ============================================================
        # TENDENCIA ALCISTA → RETEST primero
        # ============================================================
        'TREND_ALCISTA_FUERTE': [
            ModoEntrada.RETEST,           # ✅ 1ª prioridad
            ModoEntrada.BREAKOUT,         # ✅ 2ª prioridad
            # ModoEntrada.NIVEL_FUERTE,   # ❌ Desactivado en tendencia alcista
        ],
        'TREND_ALCISTA_DEBIL': [
            ModoEntrada.RETEST,           # ✅ 1ª prioridad
            ModoEntrada.NIVEL_FUERTE,     # ⚠️ Solo si score > 65
            ModoEntrada.BREAKOUT,
        ],
        
        # ============================================================
        # TENDENCIA BAJISTA → RETEST primero, NIVEL_FUERTE solo en VENTA
        # ============================================================
        'TREND_BAJISTA_FUERTE': [
            ModoEntrada.RETEST,           # ✅ 1ª prioridad
            # ModoEntrada.NIVEL_FUERTE,   # ❌ Desactivado en tendencia bajista
            ModoEntrada.BREAKOUT,
        ],
        'TREND_BAJISTA_DEBIL': [
            ModoEntrada.RETEST,           # ✅ 1ª prioridad
            ModoEntrada.NIVEL_FUERTE,     # ⚠️ Solo si score > 65 y VENTA
            ModoEntrada.BREAKOUT,
        ],
        
        # ============================================================
        # RANGO → RETEST y NIVEL_FUERTE, pero con score > 60
        # ============================================================
        'RANGO_AMPLIO': [
            ModoEntrada.RETEST,           # ✅ 1ª prioridad
            ModoEntrada.NIVEL_FUERTE,     # ⚠️ Solo si score > 60
            ModoEntrada.VELA_BORDE,
            ModoEntrada.RUPTURA_FALSA,
        ],
        'RANGO_APRETADO': [
            ModoEntrada.NIVEL_FUERTE,     # ⚠️ Solo si score > 60
            ModoEntrada.RETEST,
            ModoEntrada.VELA_BORDE,
            ModoEntrada.RUPTURA_FALSA,
        ],
        
        # ============================================================
        # BREAKOUT_INMINENTE → BREAKOUT y RUPTURA_FALSA
        # ============================================================
        'BREAKOUT_INMINENTE': [
            ModoEntrada.BREAKOUT,
            ModoEntrada.RUPTURA_FALSA,
            ModoEntrada.RETEST,
            ModoEntrada.NIVEL_FUERTE,     # ⚠️ Solo si score > 60
        ],
        
        # ============================================================
        # CHOP_VOLATIL → Solo RETEST_FALLBACK
        # ============================================================
        'CHOP_VOLATIL': [
            ModoEntrada.RETEST_FALLBACK,
            ModoEntrada.RETEST,           # ⚠️ Solo si score > 70
        ],
        
        # ============================================================
        # INCERTO → RETEST_FALLBACK primero
        # ============================================================
        'INCERTO': [
            ModoEntrada.RETEST_FALLBACK,  # ✅ 1ª prioridad
            ModoEntrada.NIVEL_FUERTE,     # ⚠️ Solo si score > 70
        ],
    }
    # ============================================================
    # SCORE MÍNIMO POR MODO
    # ============================================================
    
    SCORE_MINIMO_POR_MODO = {
        ModoEntrada.RETEST: 55,
        ModoEntrada.BREAKOUT: 65,
        ModoEntrada.PULLBACK: 65,
        ModoEntrada.NIVEL_FUERTE: 60,
        ModoEntrada.PATRON: 55,
        ModoEntrada.RUPTURA_FALSA: 50,
        ModoEntrada.VELA_BORDE: 50,
        ModoEntrada.RETEST_FALLBACK: 50,
        ModoEntrada.SNIPER_ELITE: 70,
    }
    
    # ============================================================
    # CONFIGURACIÓN DEL SISTEMA DE APRENDIZAJE
    # ============================================================
    
    APRENDIZAJE_CONFIG = {
        # Mínimo de operaciones para considerar un modo como válido
        'min_operaciones_para_aprender': 5,
        
        # Peso del winrate vs factor de beneficio (0.5 = ambos al 50%)
        'peso_winrate': 0.5,
        'peso_factor_beneficio': 0.5,
        
        # Si un modo tiene menos de 'min_operaciones_para_aprender', se usa la prioridad base
        'usar_prioridad_base_si_datos_insuficientes': True,
        
        # Penalización por falta de datos (si un modo no tiene datos, se baja de prioridad)
        'penalizacion_falta_datos': 0.3,
    }
    
    def __init__(self,
                 config: Optional[Any] = None,
                 entry_timer: Optional[Any] = None,
                 almacen: Optional[Any] = None,
                 modo_backtest: bool = False,
                 modo_depuracion: bool = False):
        """
        Inicializa el selector de modos.
        
        Args:
            config: Configuración
            entry_timer: EntryTimer para validación de momento
            almacen: Almacenamiento SQLite para consultar métricas históricas
            modo_backtest: Modo backtest
            modo_depuracion: Modo depuración
        """
        self.config = config
        self.entry_timer = entry_timer
        self.almacen = almacen
        self.modo_backtest = modo_backtest
        self.modo_depuracion = modo_depuracion
        self.logger = logging.getLogger('BotTrading.Modos')
        
        # Cargar configuración desde umbrales
        self._cargar_configuracion()
        
        # Caché de prioridades dinámicas (se recalcula cada escaneo)
        self._cache_prioridades: Dict[str, List[ModoEntrada]] = {}
        self._cache_timestamp: Dict[str, float] = {}
        self._cache_ttl = 300  # 5 minutos
        
        # Estadísticas del sistema de aprendizaje
        self._stats_aprendizaje = {
            'total_consultas': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'modos_promovidos': 0,
            'modos_degradados': 0,
        }
        
        self.logger.info(f"🎯 ModoSelector V9.2 DINÁMICO inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Modos configurados: {len(self.SCORE_MINIMO_POR_MODO)}")
        self.logger.info(f"   Aprendizaje: ✅ ACTIVADO (min ops: {self.APRENDIZAJE_CONFIG['min_operaciones_para_aprender']})")
    
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
            
            # Configuración de aprendizaje
            if hasattr(Umbrales, 'APRENDIZAJE'):
                aprendizaje_config = Umbrales.APRENDIZAJE
                for key in self.APRENDIZAJE_CONFIG:
                    if key in aprendizaje_config:
                        self.APRENDIZAJE_CONFIG[key] = aprendizaje_config[key]
        
        # Ajustes para backtest
        if self.modo_backtest:
            for modo in self.SCORE_MINIMO_POR_MODO:
                self.SCORE_MINIMO_POR_MODO[modo] = max(20, self.SCORE_MINIMO_POR_MODO[modo] - 15)
            
            # En backtest, reducir el mínimo de operaciones para aprender
            self.APRENDIZAJE_CONFIG['min_operaciones_para_aprender'] = max(2, self.APRENDIZAJE_CONFIG['min_operaciones_para_aprender'] - 2)
    
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
        
        # ✅ VALIDACIÓN CRÍTICA: SI LA DIRECCIÓN ES NEUTRAL, NO CONTINUAR
        if direccion == 'NEUTRAL':
            return None, "Dirección NEUTRAL - no operar", detalles
        
        # 1. Obtener prioridades según régimen (con aprendizaje dinámico)
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
                modo=modo,
                simbolo=simbolo,
                regimen=regimen,
                direccion=direccion,
                score_h1=score_h1,
                nivel_usado=nivel_usado,
                volumen_relativo=volumen_relativo,
                patron_calidad=patron_calidad,
                es_reversal=es_reversal,
                en_nivel_clave=en_nivel_clave
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
    # OBTENCIÓN DE PRIORIDADES (CON APRENDIZAJE DINÁMICO)
    # ============================================================
    
    def _obtener_prioridades(self, regimen: str) -> List[ModoEntrada]:
        """
        Obtiene la lista de modos priorizados para un régimen.
        V9.2 - DINÁMICO: Usa aprendizaje histórico si está disponible.
        
        Args:
            regimen: Régimen de mercado
        
        Returns:
            Lista de modos en orden de prioridad
        """
        # Verificar caché
        cache_key = f"{regimen}"
        if cache_key in self._cache_prioridades:
            if time.time() - self._cache_timestamp.get(cache_key, 0) < self._cache_ttl:
                self._stats_aprendizaje['cache_hits'] += 1
                return self._cache_prioridades[cache_key].copy()
        
        self._stats_aprendizaje['cache_misses'] += 1
        self._stats_aprendizaje['total_consultas'] += 1
        
        # 1. Obtener prioridad base
        prioridad_base = self.PRIORIDAD_BASE_POR_REGIMEN.get(regimen, self.PRIORIDAD_BASE_POR_REGIMEN['INCERTO']).copy()
        
        # 2. Si no hay almacenamiento, devolver base
        if not self.almacen:
            self._cache_prioridades[cache_key] = prioridad_base
            self._cache_timestamp[cache_key] = time.time()
            return prioridad_base
        
        # 3. Consultar métricas históricas desde SQLite
        modos_metrics = self._consultar_metricas_modos(regimen)
        
        # 4. Si no hay suficientes datos, devolver base
        if not modos_metrics:
            self._cache_prioridades[cache_key] = prioridad_base
            self._cache_timestamp[cache_key] = time.time()
            return prioridad_base
        
        # 5. Calcular puntuación dinámica para cada modo
        puntuaciones = {}
        for modo in prioridad_base:
            modo_str = modo.value
            if modo_str in modos_metrics:
                metrics = modos_metrics[modo_str]
                winrate = metrics.get('winrate', 0)
                factor_beneficio = metrics.get('factor_beneficio', 0)
                total_ops = metrics.get('total', 0)
                
                # Si no hay suficientes operaciones, penalizar
                if total_ops < self.APRENDIZAJE_CONFIG['min_operaciones_para_aprender']:
                    if self.APRENDIZAJE_CONFIG['usar_prioridad_base_si_datos_insuficientes']:
                        # Usar prioridad base para este modo
                        puntuaciones[modo] = 1.0 - self.APRENDIZAJE_CONFIG['penalizacion_falta_datos']
                    else:
                        puntuaciones[modo] = 0.0
                else:
                    # Calcular puntuación: combinación de winrate y factor de beneficio
                    puntuacion = (
                        (winrate * self.APRENDIZAJE_CONFIG['peso_winrate']) +
                        (min(factor_beneficio, 3.0) * self.APRENDIZAJE_CONFIG['peso_factor_beneficio'])
                    )
                    puntuaciones[modo] = puntuacion
            else:
                # Modo sin datos históricos, penalizar
                puntuaciones[modo] = 0.0
        
        # 6. Ordenar modos por puntuación descendente
        modos_ordenados = sorted(puntuaciones.keys(), key=lambda m: puntuaciones[m], reverse=True)
        
        # 7. Registrar promociones/degradaciones
        if self.modo_depuracion:
            for i, modo in enumerate(modos_ordenados):
                pos_base = prioridad_base.index(modo) if modo in prioridad_base else len(prioridad_base)
                if i < pos_base:
                    self._stats_aprendizaje['modos_promovidos'] += 1
                elif i > pos_base:
                    self._stats_aprendizaje['modos_degradados'] += 1
        
        # 8. Guardar en caché
        self._cache_prioridades[cache_key] = modos_ordenados
        self._cache_timestamp[cache_key] = time.time()
        
        self.logger.debug(f"📊 Prioridades dinámicas para {regimen}: {[m.value for m in modos_ordenados]}")
        
        return modos_ordenados
    
    def _consultar_metricas_modos(self, regimen: str) -> Dict[str, Dict[str, float]]:
        """
        Consulta las métricas históricas de cada modo para un régimen desde SQLite.
        
        Args:
            regimen: Régimen de mercado
        
        Returns:
            Diccionario: {modo_str: {'total': int, 'winrate': float, 'factor_beneficio': float}}
        """
        if not self.almacen:
            return {}
        
        try:
            # Obtener operaciones cerradas con este régimen
            operaciones = self.almacen.obtener_operaciones({
                'estado': 'CERRADA',
                'modo': None,  # Todos los modos
                'regimen': regimen,
                'limit': 1000,  # Límite razonable
            })
            
            if not operaciones:
                return {}
            
            # Agrupar por modo
            modos_stats = {}
            for op in operaciones:
                modo = op.get('modo', 'DESCONOCIDO')
                if modo not in modos_stats:
                    modos_stats[modo] = {'total': 0, 'ganadoras': 0, 'pnl_total': 0.0}
                
                modos_stats[modo]['total'] += 1
                ganancia = op.get('ganancia', 0.0)
                modos_stats[modo]['pnl_total'] += ganancia
                if ganancia > 0:
                    modos_stats[modo]['ganadoras'] += 1
            
            # Calcular métricas
            resultados = {}
            for modo, stats in modos_stats.items():
                total = stats['total']
                if total > 0:
                    winrate = (stats['ganadoras'] / total) * 100
                    ganancia_bruta = sum(o.get('ganancia', 0) for o in operaciones if o.get('modo') == modo and o.get('ganancia', 0) > 0)
                    perdida_bruta = abs(sum(o.get('ganancia', 0) for o in operaciones if o.get('modo') == modo and o.get('ganancia', 0) < 0))
                    factor_beneficio = ganancia_bruta / perdida_bruta if perdida_bruta > 0 else 0
                    
                    resultados[modo] = {
                        'total': total,
                        'winrate': winrate,
                        'factor_beneficio': factor_beneficio,
                    }
            
            return resultados
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error consultando métricas de modos: {e}")
            return {}
    
    def _obtener_ponderacion(self, modo: ModoEntrada, regimen: str) -> float:
        """
        Obtiene la ponderación de un modo para un régimen.
        
        Args:
            modo: Modo de entrada
            regimen: Régimen de mercado
        
        Returns:
            Ponderación (0.5-1.5)
        """
        # Nota: La ponderación ya no se usa para priorización, pero se mantiene para compatibilidad
        return 1.0
    
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
        V9.10 - REFACTORIZADO COMPLETAMENTE.
        
        MEJORAS:
        - RETEST: Permite entrar sin nivel clave si score_h1 >= 75.
        - NIVEL_FUERTE: Score mínimo aumentado a 70.
        - Validación de dirección por régimen ANTES de evaluar modos.
        - Mensajes de rechazo más claros.
        """
        # ============================================================
        # 0. VALIDACIÓN DE DIRECCIÓN POR RÉGIMEN (PREVIA AL MODO)
        # ============================================================
        
        # ✅ TENDENCIA ALCISTA → SOLO COMPRA (excepción con score alto)
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL']:
            if direccion == 'VENTA':
                if score_h1 >= 80:
                    return True, f"Score alto ({score_h1:.0f}), permitiendo VENTA en {regimen}"
                return False, f"VENTA en contra de tendencia alcista ({regimen})"
        
        # ✅ TENDENCIA BAJISTA → SOLO VENTA (excepción con score alto)
        if regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL']:
            if direccion == 'COMPRA':
                if score_h1 >= 80:
                    return True, f"Score alto ({score_h1:.0f}), permitiendo COMPRA en {regimen}"
                return False, f"COMPRA en contra de tendencia bajista ({regimen})"
        
        # ✅ RANGO → AMBAS DIRECCIONES PERMITIDAS (con precaución)
        if regimen in ['RANGO_AMPLIO', 'RANGO_APRETADO']:
            if direccion == 'COMPRA' and score_h1 < 60:
                return False, f"COMPRA en rango requiere score > 60 ({score_h1:.0f})"
            if direccion == 'VENTA' and score_h1 < 60:
                return False, f"VENTA en rango requiere score > 60 ({score_h1:.0f})"
        
        # ✅ BREAKOUT_INMINENTE → AMBAS DIRECCIONES
        if regimen == 'BREAKOUT_INMINENTE':
            if direccion == 'COMPRA' and score_h1 < 60:
                return False, f"COMPRA en breakout requiere score > 60 ({score_h1:.0f})"
            if direccion == 'VENTA' and score_h1 < 60:
                return False, f"VENTA en breakout requiere score > 60 ({score_h1:.0f})"
        
        # ✅ INCERTO → PERMITIR CON PRECAUCIÓN
        if regimen == 'INCERTO':
            if score_h1 < 70:
                return False, f"INCERTO requiere score > 70 ({score_h1:.0f})"
        
        # ============================================================
        # 1. RETEST (MÁS PERMISIVO CON SCORE ALTO)
        # ============================================================
        if modo == ModoEntrada.RETEST:
            # ✅ Si no hay nivel clave, permitir solo con score muy alto
            if not en_nivel_clave and not nivel_usado:
                if score_h1 >= 75:
                    return True, f"RETEST permitido sin nivel clave (score alto: {score_h1:.0f})"
                return False, "No hay nivel clave (score insuficiente)"
            
            # RETEST solo funciona en la dirección correcta según régimen
            if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL'] and direccion == 'VENTA':
                return False, "RETEST en VENTA no permitido en tendencia alcista"
            if regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL'] and direccion == 'COMPRA':
                return False, "RETEST en COMPRA no permitido en tendencia bajista"
            
            # En regímenes difíciles, se requiere score más alto
            if regimen in ['CHOP_VOLATIL', 'INCERTO'] and score_h1 < 65:
                return False, f"Score bajo para {regimen} (mínimo 65)"
            
            return True, "RETEST válido"
        
        # ============================================================
        # 2. NIVEL_FUERTE (MÁS RESTRICTIVO)
        # ============================================================
        elif modo == ModoEntrada.NIVEL_FUERTE:
            if not en_nivel_clave and not nivel_usado:
                return False, "No hay nivel clave"
            
            # NIVEL_FUERTE solo funciona en la dirección correcta según régimen
            if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL'] and direccion == 'VENTA':
                return False, "NIVEL_FUERTE en VENTA no permitido en tendencia alcista"
            if regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL'] and direccion == 'COMPRA':
                return False, "NIVEL_FUERTE en COMPRA no permitido en tendencia bajista"
            
            # ⬆️ SCORE MÍNIMO AUMENTADO A 70
            if score_h1 < 70:
                return False, f"Score bajo para NIVEL_FUERTE ({score_h1:.0f} < 70)"
            
            return True, "NIVEL_FUERTE válido"
        
        # ============================================================
        # 3. BREAKOUT
        # ============================================================
        elif modo == ModoEntrada.BREAKOUT:
            if volumen_relativo < 0.6:
                return False, f"Volumen bajo ({volumen_relativo:.2f}x < 0.6x)"
            
            if regimen not in ['BREAKOUT_INMINENTE', 'TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE']:
                return False, f"Régimen no adecuado para BREAKOUT"
            
            # BREAKOUT solo funciona en la dirección de la tendencia
            if regimen in ['TREND_ALCISTA_FUERTE'] and direccion == 'VENTA':
                return False, "BREAKOUT en VENTA no permitido en tendencia alcista"
            if regimen in ['TREND_BAJISTA_FUERTE'] and direccion == 'COMPRA':
                return False, "BREAKOUT en COMPRA no permitido en tendencia bajista"
            
            return True, "BREAKOUT válido"
        
        # ============================================================
        # 4. PULLBACK
        # ============================================================
        elif modo == ModoEntrada.PULLBACK:
            if regimen not in ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE', 
                            'TREND_ALCISTA_DEBIL', 'TREND_BAJISTA_DEBIL']:
                return False, f"Régimen no adecuado para PULLBACK"
            
            if score_h1 < 60:
                return False, f"Score bajo para PULLBACK ({score_h1:.0f} < 60)"
            
            # PULLBACK solo funciona en la dirección de la tendencia
            if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL'] and direccion == 'VENTA':
                return False, "PULLBACK en VENTA no permitido en tendencia alcista"
            if regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL'] and direccion == 'COMPRA':
                return False, "PULLBACK en COMPRA no permitido en tendencia bajista"
            
            return True, "PULLBACK válido"
        
        # ============================================================
        # 5. PATRON
        # ============================================================
        elif modo == ModoEntrada.PATRON:
            if patron_calidad < 25:
                return False, f"Calidad de patrón baja ({patron_calidad:.0f} < 25)"
            return True, "PATRON válido"
        
        # ============================================================
        # 6. RUPTURA_FALSA
        # ============================================================
        elif modo == ModoEntrada.RUPTURA_FALSA:
            if regimen not in ['RANGO_AMPLIO', 'RANGO_APRETADO', 'BREAKOUT_INMINENTE']:
                return False, f"Régimen no adecuado para RUPTURA_FALSA"
            return True, "RUPTURA_FALSA válido"
        
        # ============================================================
        # 7. VELA_BORDE
        # ============================================================
        elif modo == ModoEntrada.VELA_BORDE:
            if not en_nivel_clave and not nivel_usado:
                return False, "No hay nivel clave"
            return True, "VELA_BORDE válido"
        
        # ============================================================
        # 8. SNIPER_ELITE (MÁS RESTRICTIVO)
        # ============================================================
        elif modo == ModoEntrada.SNIPER_ELITE:
            if score_h1 < 70:
                return False, f"Score bajo para SNIPER_ELITE ({score_h1:.0f} < 70)"
            
            if not en_nivel_clave and patron_calidad < 35:
                return False, "Falta nivel clave o patrón de calidad"
            
            # SNIPER_ELITE solo funciona en la dirección correcta según régimen
            if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL'] and direccion == 'VENTA':
                return False, "SNIPER_ELITE en VENTA no permitido en tendencia alcista"
            if regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL'] and direccion == 'COMPRA':
                return False, "SNIPER_ELITE en COMPRA no permitido en tendencia bajista"
            
            return True, "SNIPER_ELITE válido"
        
        # ============================================================
        # 9. RETEST_FALLBACK
        # ============================================================
        elif modo == ModoEntrada.RETEST_FALLBACK:
            if score_h1 < 55:
                return False, f"Score bajo para RETEST_FALLBACK ({score_h1:.0f} < 55)"
            
            # RETEST_FALLBACK solo funciona en la dirección correcta según régimen
            if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_ALCISTA_DEBIL'] and direccion == 'VENTA':
                return False, "RETEST_FALLBACK en VENTA no permitido en tendencia alcista"
            if regimen in ['TREND_BAJISTA_FUERTE', 'TREND_BAJISTA_DEBIL'] and direccion == 'COMPRA':
                return False, "RETEST_FALLBACK en COMPRA no permitido en tendencia bajista"
            
            return True, "RETEST_FALLBACK válido"
        
        return True, "Condiciones OK"
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def set_entry_timer(self, entry_timer: Any):
        """Inyecta el EntryTimer."""
        self.entry_timer = entry_timer
        self.logger.info("⏱️ EntryTimer inyectado en ModoSelector")
    
    def set_almacen(self, almacen: Any):
        """Inyecta el almacenamiento SQLite."""
        self.almacen = almacen
        self.logger.info("💾 Almacenamiento SQLite inyectado en ModoSelector")
    
    def obtener_score_minimo(self, modo: ModoEntrada) -> int:
        """Obtiene el score mínimo para un modo."""
        score = self.SCORE_MINIMO_POR_MODO.get(modo, 40)
        if self.modo_backtest:
            score = max(15, score - 10)
        return score
    
    def obtener_modos_prioritarios(self, regimen: str) -> List[str]:
        """Obtiene los modos prioritarios para un régimen como strings."""
        modos = self._obtener_prioridades(regimen)
        return [m.value for m in modos]
    
    def es_modo_valido_para_regimen(self, modo: ModoEntrada, regimen: str) -> bool:
        """Verifica si un modo es válido para un régimen."""
        modos = self._obtener_prioridades(regimen)
        return modo in modos
    
    def get_stats_aprendizaje(self) -> Dict[str, Any]:
        """Obtiene estadísticas del sistema de aprendizaje."""
        return self._stats_aprendizaje.copy()
    
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
        """Versión legacy de seleccionar_modo."""
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


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_modo_selector(config: Optional[Any] = None,
                         entry_timer: Optional[Any] = None,
                         almacen: Optional[Any] = None,
                         modo_backtest: bool = False,
                         modo_depuracion: bool = False) -> ModoSelector:
    """
    Crea una instancia de ModoSelector.
    
    Args:
        config: Configuración
        entry_timer: EntryTimer
        almacen: Almacenamiento SQLite
        modo_backtest: Modo backtest
        modo_depuracion: Modo depuración
    
    Returns:
        ModoSelector
    """
    return ModoSelector(
        config=config,
        entry_timer=entry_timer,
        almacen=almacen,
        modo_backtest=modo_backtest,
        modo_depuracion=modo_depuracion
    )