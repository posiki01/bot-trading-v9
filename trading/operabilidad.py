#!/usr/bin/env python3
"""
trading/operabilidad.py (V9.0 - CORREGIDO)
Sistema de decisión de operabilidad para el Bot de Trading.

RESPONSABILIDAD:
- Decidir si un símbolo es operable en este momento
- Basado en score, régimen, horario y condiciones de mercado
- NO contiene lógica de ejecución o trading

CORRECCIONES V9.0:
- Importación correcta de HorarioMercado
- Eliminación de dependencia circular
- Manejo de None en horario
"""

from enum import Enum
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
import logging
from datetime import datetime, timezone

logger = logging.getLogger('BotTrading.Operabilidad')


# ============================================================
# ENUMS Y DATACLASSES
# ============================================================

class NivelOperabilidad(Enum):
    """Niveles de operabilidad de un símbolo."""
    NO_OPERABLE = "NO_OPERABLE"
    MARGINAL = "MARGINAL"
    OPERABLE = "OPERABLE"
    OPTIMO = "OPTIMO"
    ELITE = "ELITE"


@dataclass
class DecisionOperabilidad:
    """Decisión de operabilidad con todos los detalles."""
    operable: bool
    nivel: NivelOperabilidad
    score_final: float
    confianza: float
    razon: str
    recomendacion: str
    umbrales_usados: Dict[str, float]
    detalles: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class DecisorOperabilidad:
    """
    Decide si un símbolo es operable en este momento.
    V9.0 - CORREGIDO.
    """
    
    # ============================================================
    # UMBRALES BASE POR RÉGIMEN (PRODUCCIÓN)
    # ============================================================
    UMBRALES_BASE = {
        'TREND_ALCISTA_FUERTE': {'elite': 80, 'optimo': 65, 'operable': 50, 'marginal': 40},
        'TREND_BAJISTA_FUERTE': {'elite': 80, 'optimo': 65, 'operable': 50, 'marginal': 40},
        'TREND_ALCISTA_DEBIL': {'elite': 75, 'optimo': 60, 'operable': 48, 'marginal': 38},
        'TREND_BAJISTA_DEBIL': {'elite': 75, 'optimo': 60, 'operable': 48, 'marginal': 38},
        'RANGO_AMPLIO': {'elite': 70, 'optimo': 55, 'operable': 45, 'marginal': 35},
        'RANGO_APRETADO': {'elite': 65, 'optimo': 50, 'operable': 42, 'marginal': 35},
        'CHOP_VOLATIL': {'elite': 75, 'optimo': 60, 'operable': 50, 'marginal': 40},
        'BREAKOUT_INMINENTE': {'elite': 70, 'optimo': 55, 'operable': 45, 'marginal': 35},
        'INCERTO': {'elite': 80, 'optimo': 65, 'operable': 55, 'marginal': 45},
    }
    
    # ============================================================
    # UMBRALES PARA BACKTEST (REDUCIDOS)
    # ============================================================
    UMBRALES_BACKTEST = {
        'TREND_ALCISTA_FUERTE': {'elite': 45, 'optimo': 38, 'operable': 30, 'marginal': 20},
        'TREND_BAJISTA_FUERTE': {'elite': 45, 'optimo': 38, 'operable': 30, 'marginal': 20},
        'TREND_ALCISTA_DEBIL': {'elite': 40, 'optimo': 35, 'operable': 28, 'marginal': 18},
        'TREND_BAJISTA_DEBIL': {'elite': 40, 'optimo': 35, 'operable': 28, 'marginal': 18},
        'RANGO_AMPLIO': {'elite': 35, 'optimo': 30, 'operable': 25, 'marginal': 18},
        'RANGO_APRETADO': {'elite': 30, 'optimo': 25, 'operable': 20, 'marginal': 15},
        'CHOP_VOLATIL': {'elite': 40, 'optimo': 35, 'operable': 28, 'marginal': 18},
        'BREAKOUT_INMINENTE': {'elite': 35, 'optimo': 30, 'operable': 25, 'marginal': 18},
        'INCERTO': {'elite': 40, 'optimo': 35, 'operable': 28, 'marginal': 20},
    }
    
    # ============================================================
    # AJUSTES POR MODO
    # ============================================================
    AJUSTES_POR_MODO = {
        'RETEST': {'elite': 5, 'optimo': 3, 'operable': 0, 'marginal': -5},
        'BREAKOUT': {'elite': 10, 'optimo': 5, 'operable': 0, 'marginal': -5},
        'PULLBACK': {'elite': 10, 'optimo': 5, 'operable': 0, 'marginal': -5},
        'NIVEL_FUERTE': {'elite': 5, 'optimo': 3, 'operable': 0, 'marginal': -5},
        'PATRON': {'elite': 10, 'optimo': 5, 'operable': 0, 'marginal': -5},
        'RUPTURA_FALSA': {'elite': 15, 'optimo': 10, 'operable': 5, 'marginal': 0},
        'VELA_BORDE': {'elite': 15, 'optimo': 10, 'operable': 5, 'marginal': 0},
        'RETEST_FALLBACK': {'elite': 10, 'optimo': 5, 'operable': 0, 'marginal': -5},
        'SNIPER_ELITE': {'elite': 0, 'optimo': 0, 'operable': 0, 'marginal': 0},
        'DESCONOCIDO': {'elite': 10, 'optimo': 5, 'operable': 0, 'marginal': -5},
    }
    
    def __init__(self, 
                 config: Optional[Any] = None,
                 horario: Optional[Any] = None,  # ← Usar Any para evitar importación circular
                 modo_backtest: bool = False):
        """
        Inicializa el decisor de operabilidad.
        
        Args:
            config: Configuración (opcional)
            horario: Gestor de horarios (opcional) - puede ser None
            modo_backtest: Modo backtest
        """
        self.config = config
        self.horario = horario  # Puede ser None
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.Operabilidad')
        
        # Si no hay horario, intentar crearlo
        if self.horario is None:
            self.horario = self._crear_horario()
        
        # Cargar umbrales personalizados
        self._cargar_umbrales()
        
        self.logger.info(f"🎯 DecisorOperabilidad V9.0 inicializado")
        self.logger.info(f"   Backtest: {modo_backtest}")
        self.logger.info(f"   Horario: {'✅' if self.horario else '❌'}")
    
    def _crear_horario(self):
        """Crea una instancia de HorarioMercado si es posible."""
        try:
            # Intentar importar HorarioMercado
            from utils.tiempo import HorarioMercado
            return HorarioMercado(zona_usuario='COLOMBIA')
        except ImportError as e:
            self.logger.warning(f"⚠️ No se pudo importar HorarioMercado: {e}")
            return None
        except Exception as e:
            self.logger.warning(f"⚠️ Error creando HorarioMercado: {e}")
            return None
    
    def _cargar_umbrales(self):
        """Carga umbrales desde config."""
        if self.config:
            if hasattr(self.config, 'OPERABILIDAD_UMBRALES_BACKTEST'):
                self.UMBRALES_BACKTEST.update(self.config.OPERABILIDAD_UMBRALES_BACKTEST)
    
    # ============================================================
    # MÉTODO PRINCIPAL
    # ============================================================
    
    def decidir(self,
                simbolo: str,
                score_final: float,
                regimen: str,
                hora_utc: float,
                score_h1: float = 0,
                score_m15: float = 0,
                score_m5: float = 0,
                metrica_calidad: Optional[Dict] = None,
                es_reversal: bool = False,
                en_nivel_clave: bool = False,
                volumen_relativo: float = 1.0,
                adx_h1: float = 0,
                patron_calidad: float = 0,
                ob_cercano: bool = False,
                divergencia_rsi: Optional[str] = None,
                wyckoff_confianza: float = 0,
                modo: str = 'RETEST',
                capital: float = 1000.0) -> DecisionOperabilidad:
        """
        Decide si un símbolo es operable.
        
        Args:
            simbolo: Símbolo
            score_final: Score final (0-100)
            regimen: Régimen de mercado
            hora_utc: Hora UTC en formato float
            score_h1: Score H1
            score_m15: Score M15
            score_m5: Score M5
            metrica_calidad: Métricas adicionales
            es_reversal: Si es reversal
            en_nivel_clave: Si está en nivel clave
            volumen_relativo: Volumen relativo
            adx_h1: ADX H1
            patron_calidad: Calidad del patrón
            ob_cercano: Order Block cercano
            divergencia_rsi: Divergencia RSI
            wyckoff_confianza: Confianza Wyckoff
            modo: Modo de entrada
            capital: Capital actual
        
        Returns:
            DecisionOperabilidad
        """
        # 1. Validaciones básicas
        if not self._validar_basico(score_final, regimen):
            return self._crear_decision_no_operable(
                score_final, "Validaciones básicas fallaron"
            )
        
        # 2. Verificar horario (si está disponible)
        if self.horario:
            valido, razon = self._validar_horario(simbolo)
            if not valido:
                return self._crear_decision_no_operable(
                    score_final, f"Horario: {razon}"
                )
        else:
            # Si no hay horario, continuar con advertencia
            self.logger.debug(f"⚠️ Horario no disponible para {simbolo}, omitiendo validación")
        
        # 3. Seleccionar umbrales
        umbrales = self._obtener_umbrales(regimen, modo)
        
        # 4. Ajustar por hora (si es asiático)
        if 0 <= hora_utc < 7 or 21 <= hora_utc < 24:
            umbrales = {k: v + 5 for k, v in umbrales.items()}
        elif 12 <= hora_utc < 16:
            umbrales = {k: v - 3 for k, v in umbrales.items()}
        
        # 5. Ajustar por nivel clave
        if en_nivel_clave:
            umbrales = {k: v - 3 for k, v in umbrales.items()}
        
        # 6. Clasificar
        nivel = self._clasificar_por_score(score_final, umbrales)
        
        # 7. Verificar condiciones mínimas
        condiciones_ok, razon_condiciones = self._verificar_condiciones_minimas(
            simbolo, score_h1, score_m15, score_m5, regimen, es_reversal, modo
        )
        
        if not condiciones_ok:
            return self._crear_decision_no_operable(
                score_final, razon_condiciones, nivel
            )
        
        # 8. Calcular confianza
        confianza = self._calcular_confianza(
            score_final=score_final,
            nivel=nivel,
            regimen=regimen,
            volumen_relativo=volumen_relativo,
            adx_h1=adx_h1,
            patron_calidad=patron_calidad,
            es_reversal=es_reversal,
            en_nivel_clave=en_nivel_clave,
            ob_cercano=ob_cercano,
            divergencia_rsi=divergencia_rsi,
            wyckoff_confianza=wyckoff_confianza,
            modo=modo,
            capital=capital
        )
        
        # 9. Determinar recomendación
        recomendacion = self._determinar_recomendacion(nivel, confianza, modo)
        
        # 10. Decisión final
        operable = nivel in [NivelOperabilidad.OPERABLE, NivelOperabilidad.OPTIMO, NivelOperabilidad.ELITE]
        
        confianza_minima = 20 if self.modo_backtest else 40
        if operable and confianza < confianza_minima:
            nivel = NivelOperabilidad.MARGINAL
            operable = False
            recomendacion = "CONFIANZA INSUFICIENTE"
        
        return DecisionOperabilidad(
            operable=operable,
            nivel=nivel,
            score_final=score_final,
            confianza=confianza,
            razon=f"Score {score_final:.1f} - {recomendacion}",
            recomendacion=recomendacion,
            umbrales_usados=umbrales,
            detalles={
                'score_h1': score_h1,
                'score_m15': score_m15,
                'score_m5': score_m5,
                'regimen': regimen,
                'hora_utc': hora_utc,
                'modo': modo,
                'en_nivel_clave': en_nivel_clave,
                'es_backtest': self.modo_backtest,
                'capital': capital,
                'horario_disponible': self.horario is not None
            }
        )
    
    # ============================================================
    # MÉTODOS DE VALIDACIÓN
    # ============================================================
    
    def _validar_basico(self, score_final: float, regimen: str) -> bool:
        """Validaciones básicas."""
        if score_final < 0:
            return False
        if regimen not in self.UMBRALES_BASE:
            return False
        return True
    
    def _validar_horario(self, simbolo: str) -> Tuple[bool, str]:
        """Valida el horario usando HorarioMercado."""
        if self.horario is None:
            return True, "Sin horario configurado"
        
        try:
            ahora = datetime.now(timezone.utc)
            if not self.horario.mercado_abierto(ahora):
                return False, "Mercado cerrado"
            
            operativo, razon = self.horario.es_horario_operativo(simbolo, ahora)
            return operativo, razon
        except Exception as e:
            self.logger.debug(f"Error validando horario: {e}")
            return True, "Error en horario (permitiendo)"
    
    # ============================================================
    # MÉTODOS DE UMBRALES
    # ============================================================
    
    def _obtener_umbrales(self, regimen: str, modo: str) -> Dict[str, float]:
        """Obtiene umbrales para régimen y modo."""
        if self.modo_backtest:
            umbrales = self.UMBRALES_BACKTEST.get(regimen, self.UMBRALES_BACKTEST['INCERTO']).copy()
        else:
            umbrales = self.UMBRALES_BASE.get(regimen, self.UMBRALES_BASE['INCERTO']).copy()
        
        # Ajuste por modo
        ajuste = self.AJUSTES_POR_MODO.get(modo, {'elite': 0, 'optimo': 0, 'operable': 0, 'marginal': 0})
        for key in umbrales:
            umbrales[key] = umbrales[key] + ajuste.get(key, 0)
        
        return umbrales
    
    # ============================================================
    # MÉTODOS DE CLASIFICACIÓN
    # ============================================================
    
    def _clasificar_por_score(self, score: float, umbrales: Dict[str, float]) -> NivelOperabilidad:
        """Clasifica según score."""
        if score >= umbrales['elite']:
            return NivelOperabilidad.ELITE
        elif score >= umbrales['optimo']:
            return NivelOperabilidad.OPTIMO
        elif score >= umbrales['operable']:
            return NivelOperabilidad.OPERABLE
        elif score >= umbrales['marginal']:
            return NivelOperabilidad.MARGINAL
        else:
            return NivelOperabilidad.NO_OPERABLE
    
    def _verificar_condiciones_minimas(self,
                                       simbolo: str,
                                       score_h1: float,
                                       score_m15: float,
                                       score_m5: float,
                                       regimen: str,
                                       es_reversal: bool,
                                       modo: str) -> Tuple[bool, str]:
        """Verifica condiciones mínimas."""
        # Score H1
        if self.modo_backtest:
            score_h1_min = 15
        else:
            score_h1_min = 40
        
        if modo in ['BREAKOUT', 'PULLBACK', 'SNIPER_ELITE']:
            score_h1_min += 5
        
        if score_h1 < score_h1_min:
            return False, f"Score H1 bajo ({score_h1:.1f} < {score_h1_min})"
        
        # Score M15 (solo producción)
        if not self.modo_backtest:
            if score_m15 < 10 and score_h1 > 70:
                return False, f"M15 contradictorio ({score_m15:.1f})"
        
        # Régimen específico
        if regimen == 'CHOP_VOLATIL':
            chop_min = 35 if self.modo_backtest else 70
            if score_h1 < chop_min:
                return False, f"CHOP requiere score H1 > {chop_min}"
        
        if regimen == 'RANGO_APRETADO':
            if not self.modo_backtest and score_h1 < 42:
                return False, f"RANGO_APRETADO requiere score H1 > 42"
        
        return True, "OK"
    
    # ============================================================
    # MÉTODOS DE CONFIANZA
    # ============================================================
    
    def _calcular_confianza(self,
                            score_final: float,
                            nivel: NivelOperabilidad,
                            regimen: str,
                            volumen_relativo: float,
                            adx_h1: float,
                            patron_calidad: float,
                            es_reversal: bool,
                            en_nivel_clave: bool,
                            ob_cercano: bool,
                            divergencia_rsi: Optional[str],
                            wyckoff_confianza: float,
                            modo: str,
                            capital: float) -> float:
        """Calcula la confianza (0-100)."""
        confianza = 0.0
        
        # 1. Base por score
        if score_final > 80:
            confianza += 40
        elif score_final > 70:
            confianza += 35
        elif score_final > 60:
            confianza += 30
        elif score_final > 50:
            confianza += 20
        elif score_final > 40:
            confianza += 10
        elif score_final > 30:
            confianza += 5
        
        # 2. Bono por nivel
        bonos_nivel = {
            NivelOperabilidad.ELITE: 20,
            NivelOperabilidad.OPTIMO: 15,
            NivelOperabilidad.OPERABLE: 10,
            NivelOperabilidad.MARGINAL: 5,
            NivelOperabilidad.NO_OPERABLE: 0
        }
        confianza += bonos_nivel.get(nivel, 0)
        
        # 3. Bono por régimen
        if regimen in ['TREND_ALCISTA_FUERTE', 'TREND_BAJISTA_FUERTE']:
            confianza += 15
        elif regimen in ['TREND_ALCISTA_DEBIL', 'TREND_BAJISTA_DEBIL']:
            confianza += 10
        elif regimen == 'BREAKOUT_INMINENTE':
            confianza += 12
        
        # 4. Bono por modo
        bonos_modo = {
            'SNIPER_ELITE': 10,
            'NIVEL_FUERTE': 8,
            'RETEST': 5,
            'PULLBACK': 5,
            'BREAKOUT': 5,
            'PATRON': 4,
        }
        confianza += bonos_modo.get(modo, 0)
        
        # 5. Bono por volumen
        if volumen_relativo > 2.5:
            confianza += 10
        elif volumen_relativo > 2.0:
            confianza += 8
        elif volumen_relativo > 1.5:
            confianza += 5
        
        # 6. Bono por ADX
        if adx_h1 > 35:
            confianza += 10
        elif adx_h1 > 25:
            confianza += 7
        
        # 7. Bonos adicionales
        if en_nivel_clave:
            confianza += 8
        if ob_cercano:
            confianza += 5
        if divergencia_rsi:
            confianza += 4
        if patron_calidad > 60:
            confianza += 5
        if wyckoff_confianza > 60:
            confianza += 4
        
        # 8. Ajuste por capital
        if capital < 500:
            confianza *= 0.9
        
        # Mínimo en backtest
        if self.modo_backtest:
            confianza = max(25.0, confianza * 0.9)
        
        return min(100.0, max(0.0, confianza))
    
    # ============================================================
    # MÉTODOS DE RECOMENDACIÓN
    # ============================================================
    
    def _determinar_recomendacion(self, nivel: NivelOperabilidad, 
                                  confianza: float, modo: str) -> str:
        """Determina la recomendación."""
        if nivel == NivelOperabilidad.ELITE:
            return "ENTRADA PRIORITARIA"
        elif nivel == NivelOperabilidad.OPTIMO:
            if confianza > 60:
                return "ENTRADA RECOMENDADA"
            return "ENTRADA CON PRECAUCIÓN"
        elif nivel == NivelOperabilidad.OPERABLE:
            if confianza > 50:
                return "ENTRADA CON PRECAUCIÓN"
            return "ENTRADA SOLO CON CONFIRMACIÓN"
        elif nivel == NivelOperabilidad.MARGINAL:
            if confianza > 40:
                return "ENTRADA SOLO CON CONFIRMACIÓN"
            return "NO ENTRAR (CONFIRMACIÓN INSUFICIENTE)"
        else:
            return "NO ENTRAR"
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def _crear_decision_no_operable(self, score_final: float, razon: str,
                                    nivel: NivelOperabilidad = NivelOperabilidad.NO_OPERABLE) -> DecisionOperabilidad:
        """Crea una decisión NO OPERABLE."""
        return DecisionOperabilidad(
            operable=False,
            nivel=nivel,
            score_final=score_final,
            confianza=0,
            razon=razon,
            recomendacion="NO ENTRAR",
            umbrales_usados={},
            detalles={}
        )
    
    def obtener_umbrales_para_modo(self, modo: str, regimen: str) -> Dict[str, float]:
        """Obtiene umbrales para un modo y régimen."""
        return self._obtener_umbrales(regimen, modo)
    
    def set_modo_backtest(self, modo: bool = True):
        """Activa/desactiva modo backtest."""
        self.modo_backtest = modo
        self.logger.info(f"🔧 Modo backtest: {'ACTIVADO' if modo else 'DESACTIVADO'}")


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_decisor_operabilidad(config=None, horario=None, modo_backtest: bool = False) -> DecisorOperabilidad:
    """Crea una instancia de DecisorOperabilidad."""
    return DecisorOperabilidad(
        config=config,
        horario=horario,
        modo_backtest=modo_backtest
    )