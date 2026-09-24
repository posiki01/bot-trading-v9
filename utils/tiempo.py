#!/usr/bin/env python3
"""
utils/tiempo.py (V10.0 - REFACTORIZADO COMPLETAMENTE)
Sistema unificado de gestión de horarios de mercado.

CORRECCIONES V10.0:
- ✅ es_horario_operativo limpio (eliminado código duplicado e inalcanzable)
- ✅ Cache real con TTL (antes el caché no se usaba)
- ✅ Lógica unificada de sábado/domingo/viernes
- ✅ Eliminado el import circular con noticias
- ✅ Métodos de calidad de horario simplificados
- ✅ Uso de Umbrales centralizados
- ✅ Métodos de compatibilidad (legacy) preservados
"""

import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional, Any
from enum import Enum
from zoneinfo import ZoneInfo
from utils.reloj import now_utc

try:
    from config.umbrales import Umbrales
except ImportError:
    Umbrales = None

logger = logging.getLogger('BotTrading.Tiempo')


# ============================================================
# ENUMS
# ============================================================

class EstadoMercado(Enum):
    """Estados posibles del mercado."""
    ABIERTO = "ABIERTO"
    CERRADO = "CERRADO"
    ROLLOVER = "ROLLOVER"
    FIN_SEMANA = "FIN_SEMANA"
    SIN_DATOS = "SIN_DATOS"


class SesionMercado(Enum):
    """Sesiones de mercado principales."""
    ASIAN = "ASIAN"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OVERLAP_LONDON_NY = "LDN_NY"
    OVERLAP_ASIAN_LONDON = "TOK_LDN"
    CRYPTO = "24/7"


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class HorarioMercado:
    """
    Gestión unificada de horarios de mercado.
    V10.0 - REFACTORIZADO.
    """

    # ============================================================
    # ZONAS HORARIAS
    # ============================================================

    ZONAS = {
        'COLOMBIA': ZoneInfo("America/Bogota"),
        'UTC': ZoneInfo("UTC"),
        'LONDON': ZoneInfo("Europe/London"),
        'NEW_YORK': ZoneInfo("America/New_York"),
        'TOKYO': ZoneInfo("Asia/Tokyo"),
        'SYDNEY': ZoneInfo("Australia/Sydney"),
    }

    # ============================================================
    # SESIONES (rangos en UTC)
    # ============================================================

    SESIONES = {
        'ASIAN': (0.0, 8.0),
        'LONDON': (8.0, 16.0),
        'NEW_YORK': (13.0, 22.0),
        'LDN_NY': (8.0, 22.0),
        'TOK_LDN': ((0.0, 2.0), (8.0, 16.0)),
        '24/7': None,
    }

    # ============================================================
    # CONJUNTOS DE SÍMBOLOS POR TIPO
    # ============================================================

    SIMBOLOS_CRIPTO = {'BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'DOT', 'LINK', 'UNI', 'MATIC'}
    SIMBOLOS_METALES = {'XAU', 'XAG', 'XPT', 'XPD'}
    SIMBOLOS_INDICES = {'US30', 'NAS100', 'US500', 'SP500', 'GER40', 'UK100', 'DAX', 'SPX'}

    # Pares forex reconocidos (códigos de divisa)
    DIVISAS_FOREX = {'EUR', 'GBP', 'USD', 'CHF', 'JPY', 'AUD', 'CAD', 'NZD'}

    def __init__(
        self,
        zona_usuario: str = 'COLOMBIA',
        config_activos: Optional[Dict] = None,
        modo_backtest: bool = False,
        cache_ttl: int = 60,
    ):
        """
        Inicializa el gestor de horarios.

        Args:
            zona_usuario: Zona horaria del usuario
            config_activos: Configuración de activos (opcional)
            modo_backtest: Modo backtest
            cache_ttl: TTL de caché de validaciones (segundos)
        """
        self.zona_usuario = zona_usuario
        self.zona_tz = self.ZONAS.get(zona_usuario, self.ZONAS['COLOMBIA'])
        self.config_activos = config_activos or {}
        self.modo_backtest = modo_backtest
        self.cache_ttl = cache_ttl

        # Cargar horarios desde Umbrales o Config
        self.horarios_sesion = self._cargar_horarios_sesion()

        # Caché de validaciones
        self._cache_validacion: Dict[str, Tuple[Any, float]] = {}

        logger.info(f"🕐 HorarioMercado V10.0 inicializado")
        logger.info(f"   Zona: {zona_usuario} | Hora: {self.hora_usuario_str()}")
        logger.info(f"   Backtest: {modo_backtest}")

    # ============================================================
    # CARGA DE CONFIGURACIÓN
    # ============================================================

    def _cargar_horarios_sesion(self) -> Dict[str, Dict]:
        """Carga horarios desde Umbrales o Config."""
        horarios: Dict[str, Dict] = {}

        # Prioridad 1: Umbrales
        if Umbrales is not None and hasattr(Umbrales, 'HORARIOS_POR_ACTIVO'):
            horarios.update(Umbrales.HORARIOS_POR_ACTIVO)

        # Prioridad 2: Config
        try:
            from config.settings import Config
            if hasattr(Config, 'HORARIOS_POR_ACTIVO'):
                horarios.update(Config.HORARIOS_POR_ACTIVO)
        except ImportError:
            pass

        # Defaults si no hay nada
        if not horarios:
            horarios = {
                'EURUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
                'GBPUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
                'USDJPY': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
                'XAUUSD': {'inicio': 2, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
                'US30': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
                'BTCUSD': {'inicio': 0, 'fin': 24, 'dias': [0, 1, 2, 3, 4, 5, 6]},
            }

        return horarios

    # ============================================================
    # MÉTODOS DE TIEMPO
    # ============================================================

    def ahora_utc(self) -> datetime:
        """Retorna hora UTC."""
        return now_utc()

    def ahora_usuario(self) -> datetime:
        """Retorna hora en zona del usuario."""
        return self.ahora_utc().astimezone(self.zona_tz)

    def hora_usuario_str(self) -> str:
        """Hora del usuario en formato legible."""
        return self.ahora_usuario().strftime("%H:%M:%S")

    def hora_utc_str(self) -> str:
        """Hora UTC en formato legible."""
        return self.ahora_utc().strftime("%H:%M:%S")

    def hora_float(self, dt: Optional[datetime] = None) -> float:
        """Convierte una hora a formato float (0-24) en UTC."""
        if dt is None:
            dt = self.ahora_utc()
        return dt.hour + dt.minute / 60.0 + dt.second / 3600.0

    def hora_colombia_float(self, dt: Optional[datetime] = None) -> float:
        """Hora en formato float en zona Colombia."""
        if dt is None:
            dt = self.ahora_utc()
        hora_col = dt.astimezone(self.ZONAS['COLOMBIA'])
        return hora_col.hour + hora_col.minute / 60.0

    # ============================================================
    # CLASIFICACIÓN DE SÍMBOLOS
    # ============================================================

    def _es_cripto(self, simbolo: str) -> bool:
        """Verifica si es cripto."""
        simbolo_upper = simbolo.upper()
        return any(c in simbolo_upper for c in self.SIMBOLOS_CRIPTO)

    def _es_metal(self, simbolo: str) -> bool:
        """Verifica si es metal."""
        simbolo_upper = simbolo.upper()
        return any(m in simbolo_upper for m in self.SIMBOLOS_METALES)

    def _es_indice(self, simbolo: str) -> bool:
        """Verifica si es índice."""
        simbolo_upper = simbolo.upper()
        return any(i in simbolo_upper for i in self.SIMBOLOS_INDICES)

    def _es_forex(self, simbolo: str) -> bool:
        """Verifica si es par forex."""
        if len(simbolo) != 6:
            return False
        base = simbolo[:3].upper()
        quote = simbolo[3:].upper()
        return base in self.DIVISAS_FOREX and quote in self.DIVISAS_FOREX

    # ============================================================
    # ✅ MÉTODO PRINCIPAL: es_horario_operativo (LIMPIO)
    # ============================================================

    def es_horario_operativo(
        self,
        simbolo: str,
        ahora: Optional[datetime] = None,
        usar_cache: bool = True,
    ) -> Tuple[bool, str]:
        """
        Verifica si un símbolo está en horario operativo.
        V10.0 - REFACTORIZADO: Una sola ruta de decisión.

        Returns:
            (operativo, razón)
        """
        # ============================================================
        # 1. CACHÉ
        # ============================================================
        if ahora is None:
            ahora = self.ahora_utc()

        simbolo_upper = simbolo.upper().strip()
        cache_key = f"{simbolo_upper}_{ahora.strftime('%Y-%m-%d %H:%M')}"

        if usar_cache and cache_key in self._cache_validacion:
            cached, ts = self._cache_validacion[cache_key]
            if time.time() - ts < self.cache_ttl:
                return cached

        # ============================================================
        # 2. CRIPTO: SIEMPRE OPERATIVO (24/7)
        # ============================================================
        if self._es_cripto(simbolo_upper):
            resultado = (True, "24/7 (Cripto)")
            self._cache_validacion[cache_key] = (resultado, time.time())
            return resultado

        # ============================================================
        # 3. CALCULAR HORA COLOMBIA
        # ============================================================
        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        weekday = hora_col.weekday()  # 0=Lunes, 6=Domingo
        hora_float = hora_col.hour + hora_col.minute / 60.0

        # ============================================================
        # 4. SÁBADO: SOLO CRIPTO
        # ============================================================
        if weekday == 5:
            resultado = (False, "Sábado - solo cripto opera")
            self._cache_validacion[cache_key] = (resultado, time.time())
            return resultado

        # ============================================================
        # 5. DOMINGO: FOREX/ÍNDICES/METALES DESDE CIERTA HORA
        # ============================================================
        if weekday == 6:
            # Forex abre 17:00 COT
            if self._es_forex(simbolo_upper) or self._es_metal(simbolo_upper):
                if hora_float >= 17.0:
                    resultado = (True, "Domingo - apertura 17:00 COT")
                else:
                    resultado = (False, f"Domingo - apertura 17:00 COT (actual {hora_float:.1f})")
                self._cache_validacion[cache_key] = (resultado, time.time())
                return resultado

            # Índices abren 18:00 COT
            if self._es_indice(simbolo_upper):
                if hora_float >= 18.0:
                    resultado = (True, "Domingo - apertura 18:00 COT (índices)")
                else:
                    resultado = (False, f"Domingo - apertura 18:00 COT (actual {hora_float:.1f})")
                self._cache_validacion[cache_key] = (resultado, time.time())
                return resultado

            resultado = (False, "Domingo - sin apertura")
            self._cache_validacion[cache_key] = (resultado, time.time())
            return resultado

        # ============================================================
        # 6. VIERNES: CIERRES ANTICIPADOS
        # ============================================================
        if weekday == 4:
            # Índices y metales cierran 16:00 COT
            if self._es_indice(simbolo_upper) or self._es_metal(simbolo_upper):
                if hora_float >= 16.0:
                    resultado = (False, f"Viernes - cierre índices/metales 16:00 COT")
                else:
                    resultado = (True, f"Viernes - índices/metales (hasta 16:00 COT)")
                self._cache_validacion[cache_key] = (resultado, time.time())
                return resultado

            # Forex cierra 17:00 COT
            if self._es_forex(simbolo_upper):
                if hora_float >= 17.0:
                    resultado = (False, f"Viernes - cierre Forex 17:00 COT")
                else:
                    resultado = (True, f"Viernes - Forex (hasta 17:00 COT)")
                self._cache_validacion[cache_key] = (resultado, time.time())
                return resultado

        # ============================================================
        # 7. LUNES A JUEVES (Y VIERNES PRE-CIERRE): HORARIO CONFIGURADO
        # ============================================================
        config = self.horarios_sesion.get(simbolo_upper)

        # Si no hay config, permitir L-V (fallback permisivo)
        if not config:
            if weekday in [0, 1, 2, 3, 4]:
                resultado = (True, "Horario normal (sin config específica)")
            else:
                resultado = (False, "Sin horario configurado")
            self._cache_validacion[cache_key] = (resultado, time.time())
            return resultado

        # Verificar día operativo
        dias_operativos = config.get('dias', [0, 1, 2, 3, 4])
        if weekday not in dias_operativos:
            dias_nombre = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
            resultado = (False, f"{dias_nombre[weekday]} - no operativo")
            self._cache_validacion[cache_key] = (resultado, time.time())
            return resultado

        # Verificar horario
        inicio = config.get('inicio', 0)
        fin = config.get('fin', 24)

        # 24 horas
        if inicio == fin:
            resultado = (True, "24 horas")
            self._cache_validacion[cache_key] = (resultado, time.time())
            return resultado

        # Rango normal
        if inicio < fin:
            if inicio <= hora_float < fin:
                resultado = (True, f"Operativo ({inicio:02d}-{fin:02d} COT)")
            else:
                resultado = (False, f"Fuera de horario ({inicio:02d}-{fin:02d} COT, actual {hora_float:.1f})")
            self._cache_validacion[cache_key] = (resultado, time.time())
            return resultado

        # Rango que cruza medianoche (ej: 22:00 - 06:00)
        if hora_float >= inicio or hora_float < fin:
            resultado = (True, f"Operativo ({inicio:02d}-{fin:02d} COT)")
        else:
            resultado = (False, f"Fuera de horario ({inicio:02d}-{fin:02d} COT, actual {hora_float:.1f})")
        self._cache_validacion[cache_key] = (resultado, time.time())
        return resultado

    # ============================================================
    # ESTADO DEL MERCADO
    # ============================================================

    def estado_mercado(self, ahora: Optional[datetime] = None) -> EstadoMercado:
        """Estado detallado del mercado global."""
        if ahora is None:
            ahora = self.ahora_utc()

        if self.es_horario_rollover(ahora):
            return EstadoMercado.ROLLOVER

        if self.es_fin_de_semana_cerrado(ahora):
            return EstadoMercado.FIN_SEMANA

        if not self.mercado_abierto(ahora):
            return EstadoMercado.CERRADO

        return EstadoMercado.ABIERTO

    def mercado_abierto(self, ahora: Optional[datetime] = None) -> bool:
        """
        Determina si el mercado tradicional está abierto.
        Nota: cripto siempre está abierto, pero este método es para mercado tradicional.
        """
        if ahora is None:
            ahora = self.ahora_utc()

        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        weekday = hora_col.weekday()
        hora_float = hora_col.hour + hora_col.minute / 60.0

        # Sábado
        if weekday == 5:
            return False

        # Domingo antes de 17:00 COT
        if weekday == 6 and hora_float < 17.0:
            return False

        # Viernes después de 17:00 COT
        if weekday == 4 and hora_float >= 17.0:
            return False

        return True

    def es_fin_de_semana_cerrado(
        self,
        ahora: Optional[datetime] = None,
        simbolo: Optional[str] = None,
    ) -> bool:
        """
        Verifica si está cerrado por fin de semana.
        Si `simbolo` es cripto → siempre False.
        """
        if ahora is None:
            ahora = self.ahora_utc()

        if simbolo and self._es_cripto(simbolo):
            return False

        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        weekday = hora_col.weekday()
        hora_float = hora_col.hour + hora_col.minute / 60.0

        # Sábado: cerrado
        if weekday == 5:
            return True

        # Domingo antes de 17:00 COT: cerrado
        if weekday == 6 and hora_float < 17.0:
            return True

        # Viernes después del cierre según activo
        if weekday == 4:
            if simbolo:
                if self._es_indice(simbolo) or self._es_metal(simbolo):
                    return hora_float >= 16.0
                if self._es_forex(simbolo):
                    return hora_float >= 17.0
            return hora_float >= 16.0

        return False

    def es_horario_rollover(self, ahora: Optional[datetime] = None) -> bool:
        """Detecta horario de rollover (16:45 - 17:30 NY)."""
        if ahora is None:
            ahora = self.ahora_utc()
        ny_time = ahora.astimezone(self.ZONAS['NEW_YORK'])
        hora = ny_time.hour + ny_time.minute / 60.0
        return 16.75 <= hora <= 17.50

    # ============================================================
    # SESIONES
    # ============================================================

    def sesion_actual(self, ahora: Optional[datetime] = None) -> Optional[SesionMercado]:
        """Determina la sesión de mercado actual."""
        if ahora is None:
            ahora = self.ahora_utc()

        hora = self.hora_float(ahora)

        # Asia: 00-08 UTC
        if 0.0 <= hora < 8.0:
            return SesionMercado.ASIAN

        # Overlap LDN-NY: 13-16 UTC
        if 13.0 <= hora < 16.0:
            return SesionMercado.OVERLAP_LONDON_NY

        # Londres: 08-16 UTC
        if 8.0 <= hora < 16.0:
            return SesionMercado.LONDON

        # NY: 13-22 UTC
        if 16.0 <= hora < 22.0:
            return SesionMercado.NEW_YORK

        return None

    # ============================================================
    # CALIDAD DE HORARIO
    # ============================================================

    def obtener_calidad_horario(
        self,
        simbolo: str,
        ahora: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Obtiene la calidad del horario para un símbolo.

        Returns:
            {
                'calidad': 'EXCELENTE'|'BUENA'|'REGULAR'|'MALA'|'PESIMA',
                'puntaje': 0-100,
                'razon': str,
                'es_optimo': bool,
                'score_minimo': int,
            }
        """
        if ahora is None:
            ahora = self.ahora_utc()

        simbolo_upper = simbolo.upper()

        # Cripto: siempre excelente
        if self._es_cripto(simbolo_upper):
            return self._crear_calidad('EXCELENTE', 100, '24/7 (Cripto)', 0)

        # Verificar si está cerrado
        operativo, razon = self.es_horario_operativo(simbolo_upper, ahora)
        if not operativo:
            return self._crear_calidad('PESIMA', 0, razon, 999)

        # Calcular según sesión
        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        hora_float = hora_col.hour + hora_col.minute / 60.0

        # Overlap LDN-NY: 07:00-11:00 COT
        if 7.0 <= hora_float <= 11.0:
            return self._crear_calidad('EXCELENTE', 100, 'Overlap LDN-NY (máxima liquidez)', 0)

        # Londres: 02:00-07:00 COT
        if 2.0 <= hora_float < 7.0:
            if any(c in simbolo_upper for c in ['GBP', 'EUR', 'CHF']):
                return self._crear_calidad('BUENA', 85, 'Londres - par europeo', 35)
            return self._crear_calidad('REGULAR', 55, 'Londres - liquidez media', 55)

        # NY: 11:00-16:00 COT
        if 11.0 <= hora_float < 16.0:
            if 'CAD' in simbolo_upper:
                return self._crear_calidad('BUENA', 75, 'NY - par CAD', 40)
            return self._crear_calidad('REGULAR', 60, 'NY - liquidez media', 50)

        # Asiático: 18:00-02:00 COT
        if hora_float >= 18.0 or hora_float < 2.0:
            if any(c in simbolo_upper for c in ['JPY', 'AUD', 'NZD']):
                return self._crear_calidad('REGULAR', 60, 'Asiático - par del Pacífico', 60)
            return self._crear_calidad('MALA', 30, 'Asiático - baja liquidez', 80)

        return self._crear_calidad('REGULAR', 50, 'Horario normal', 50)

    def _crear_calidad(self, calidad: str, puntaje: int, razon: str, score_min: int) -> Dict[str, Any]:
        """Helper para construir el dict de calidad."""
        return {
            'calidad': calidad,
            'puntaje': puntaje,
            'razon': razon,
            'es_optimo': calidad in ('EXCELENTE', 'BUENA'),
            'score_minimo': score_min,
        }

    def obtener_score_minimo_por_horario(
        self,
        simbolo: str,
        ahora: Optional[datetime] = None,
    ) -> int:
        """Score mínimo requerido según horario."""
        calidad = self.obtener_calidad_horario(simbolo, ahora)
        return calidad.get('score_minimo', 50)

    # ============================================================
    # ESTADO PARA MÚLTIPLES SÍMBOLOS
    # ============================================================

    def obtener_estado_mercado(self, simbolos: List[str]) -> Dict[str, Any]:
        """
        Clasifica símbolos en operables y no operables.

        Returns:
            Dict con operables, no_operables, razones, etc.
        """
        ahora = self.ahora_utc()
        estado_general = self.estado_mercado(ahora)

        operables: List[str] = []
        no_operables: List[str] = []
        razones: Dict[str, str] = {}
        horarios_estado: Dict[str, str] = {}

        for simbolo in simbolos:
            operativo, razon = self.es_horario_operativo(simbolo, ahora)
            if operativo:
                operables.append(simbolo)
                horarios_estado[simbolo] = 'OPERATIVO'
            else:
                no_operables.append(simbolo)
                razones[simbolo] = razon
                horarios_estado[simbolo] = 'NO_OPERATIVO'

        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        weekday = hora_col.weekday()

        return {
            'operables': operables,
            'no_operables': no_operables,
            'razones': razones,
            'horarios_estado': horarios_estado,
            'estado_general': estado_general.value,
            'hora_utc': ahora.strftime('%H:%M:%S'),
            'hora_usuario': self.hora_usuario_str(),
            'zona_usuario': self.zona_usuario,
            'es_fin_semana': self.es_fin_de_semana_cerrado(ahora),
            'es_rollover': self.es_horario_rollover(ahora),
            'es_cierre_viernes': weekday == 4,
            'total_operables': len(operables),
            'total_no_operables': len(no_operables),
            'weekday_col': weekday,
        }

    # ============================================================
    # UTILIDADES
    # ============================================================

    def es_cierre_viernes_inminente(
        self,
        ahora: Optional[datetime] = None,
        simbolo: Optional[str] = None,
        minutos_anticipacion: int = 30,
    ) -> bool:
        """Verifica si el cierre de viernes es inminente."""
        if ahora is None:
            ahora = self.ahora_utc()

        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        if hora_col.weekday() != 4:
            return False

        hora_float = hora_col.hour + hora_col.minute / 60.0
        anticipacion_h = minutos_anticipacion / 60.0

        if simbolo:
            simbolo_upper = simbolo.upper()
            if self._es_cripto(simbolo_upper):
                return False

            if self._es_indice(simbolo_upper) or self._es_metal(simbolo_upper):
                return 0 < (16.0 - hora_float) <= anticipacion_h

            if self._es_forex(simbolo_upper):
                return 0 < (17.0 - hora_float) <= anticipacion_h

        return 0 < (16.0 - hora_float) <= anticipacion_h

    def debe_cerrar_por_viernes(
        self,
        ahora: Optional[datetime] = None,
        simbolo: Optional[str] = None,
    ) -> bool:
        """Determina si se deben cerrar posiciones por viernes."""
        if ahora is None:
            ahora = self.ahora_utc()

        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        if hora_col.weekday() != 4:
            return False

        hora_float = hora_col.hour + hora_col.minute / 60.0

        if simbolo:
            simbolo_upper = simbolo.upper()
            if self._es_cripto(simbolo_upper):
                return False

            if self._es_indice(simbolo_upper) or self._es_metal(simbolo_upper):
                return hora_float >= 15.5

            if self._es_forex(simbolo_upper):
                return hora_float >= 16.5

        return hora_float >= 15.5

    def obtener_proxima_apertura(
        self,
        ahora: Optional[datetime] = None,
    ) -> Tuple[str, str]:
        """Próxima apertura del mercado."""
        if ahora is None:
            ahora = self.ahora_utc()

        dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        hoy = ahora.weekday()
        hora_utc = self.hora_float(ahora)

        if hoy == 4 and hora_utc >= 22.0:
            prox = ahora.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=2)
            dia = "Domingo"
        elif hoy == 5:
            prox = ahora.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=1)
            dia = "Domingo"
        elif hoy == 6 and hora_utc < 22.0:
            prox = ahora.replace(hour=22, minute=0, second=0, microsecond=0)
            dia = "Domingo"
        else:
            prox = ahora.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            dia = dias_semana[prox.weekday()]

        hora_col = prox.astimezone(self.ZONAS['COLOMBIA'])
        hora_12h = hora_col.strftime("%I:%M %p").lstrip("0")
        return dia, hora_12h

    def tiempo_para_cierre(self, ahora: Optional[datetime] = None) -> str:
        """Tiempo restante hasta el cierre."""
        if ahora is None:
            ahora = self.ahora_utc()

        weekday = ahora.weekday()
        hora_utc = self.hora_float(ahora)

        if weekday == 4 and hora_utc < 22.0:
            horas = int(22.0 - hora_utc)
            minutos = int((22.0 - hora_utc) * 60) % 60
            return f"{horas}h {minutos}min"

        if weekday == 6 and hora_utc < 22.0:
            horas = int(22.0 - hora_utc)
            minutos = int((22.0 - hora_utc) * 60) % 60
            return f"{horas}h {minutos}min para apertura"

        return "N/A"

    def es_horario_seguro_para_abrir(
        self,
        simbolo: str,
        ahora: Optional[datetime] = None,
    ) -> Tuple[bool, str]:
        """Verifica si es seguro abrir una operación."""
        if ahora is None:
            ahora = self.ahora_utc()

        # Cripto siempre
        if self._es_cripto(simbolo):
            return True, "Cripto 24/7"

        # Cierre de viernes inminente
        if self.es_cierre_viernes_inminente(ahora, simbolo, minutos_anticipacion=60):
            return False, "Cierre de viernes inminente"

        # Horario operativo
        return self.es_horario_operativo(simbolo, ahora)

    # ============================================================
    # MANTENIMIENTO
    # ============================================================

    def limpiar_cache(self):
        """Limpia la caché de validaciones."""
        self._cache_validacion.clear()
        logger.debug("🧹 Caché de horarios limpiada")

    # ============================================================
    # COMPATIBILIDAD (LEGACY)
    # ============================================================

    def es_horario_operativo_legacy(self, simbolo: str) -> Tuple[bool, str]:
        """Versión legacy."""
        return self.es_horario_operativo(simbolo)


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_horario_mercado(
    zona_usuario: str = 'COLOMBIA',
    config_activos: Optional[Dict] = None,
    modo_backtest: bool = False,
) -> HorarioMercado:
    """Crea una instancia de HorarioMercado."""
    return HorarioMercado(
        zona_usuario=zona_usuario,
        config_activos=config_activos,
        modo_backtest=modo_backtest,
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    horario = HorarioMercado(zona_usuario='COLOMBIA', modo_backtest=True)

    print(f"🕐 Hora Colombia: {horario.hora_usuario_str()}")
    print(f"🕐 Hora UTC: {horario.hora_utc_str()}")
    print(f"📊 Mercado abierto: {horario.mercado_abierto()}")
    print(f"📊 Estado: {horario.estado_mercado().value}")

    simbolos = ['EURUSD', 'USDJPY', 'BTCUSD', 'XAUUSD', 'US30']
    print(f"\n📊 Estado por símbolo:")
    for s in simbolos:
        operativo, razon = horario.es_horario_operativo(s)
        calidad = horario.obtener_calidad_horario(s)
        print(f"   {s}: {'✅' if operativo else '❌'} {razon} | Calidad: {calidad['calidad']} (score min: {calidad['score_minimo']})")