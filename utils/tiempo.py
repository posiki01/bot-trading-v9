#!/usr/bin/env python3
"""
utils/tiempo.py (V9.0 - REFACTORIZADO COMPLETAMENTE)
Sistema unificado de gestión de horarios de mercado para el Bot de Trading.

PROPÓSITO:
- Unificar toda la lógica de horarios en un solo lugar
- Manejar correctamente la zona horaria de Colombia (UTC-5)
- Detectar sesiones de mercado (Asia, Londres, Nueva York)
- Validar horarios de rollover, fines de semana y cierres
- Proveer información de calidad de horario

MEJORAS V9.0:
- Eliminación de código duplicado
- Integración con umbrales centralizados
- Caché con TTL configurable
- Métodos de compatibilidad para migración
- Logs más informativos
- Soporte para backtest
"""

import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional, Set, Any, Union
from enum import Enum
from zoneinfo import ZoneInfo

# Importar umbrales centralizados
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
    FERIADO = "FERIADO"
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
    V9.0 - COMPLETAMENTE REFACTORIZADO.
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
    # CALIDAD DE HORARIO - SCORE MÍNIMO
    # ============================================================
    
    SCORE_MINIMO_POR_CALIDAD = {
        'EXCELENTE': 0,
        'BUENA': 0,
        'REGULAR': 55,
        'MALA': 75,
        'PESIMA': 90,
    }
    
    def __init__(self,
                 zona_usuario: str = 'COLOMBIA',
                 config_activos: Optional[Dict] = None,
                 noticias: Optional[Any] = None,
                 modo_backtest: bool = False,
                 cache_ttl: int = 60):
        """
        Inicializa el gestor de horarios.
        
        Args:
            zona_usuario: Zona horaria del usuario
            config_activos: Configuración de activos
            noticias: Sistema de noticias (opcional)
            modo_backtest: Modo backtest
            cache_ttl: TTL de caché en segundos
        """
        self.zona_usuario = zona_usuario
        self.zona_tz = self.ZONAS.get(zona_usuario, self.ZONAS['COLOMBIA'])
        self.config_activos = config_activos or {}
        self.noticias = noticias
        self.modo_backtest = modo_backtest
        self.cache_ttl = cache_ttl
        
        # Cargar horarios desde config
        self.horarios_sesion = self._cargar_horarios_sesion()
        
        # Caché
        self._cache_validacion: Dict[str, Tuple[Any, float]] = {}
        self._ultima_notificacion: Optional[float] = None
        self._notificacion_intervalo = 3600
        
        # Cargar umbrales
        self._cargar_umbrales()
        
        logger.info(f"🕐 HorarioMercado V9.0 inicializado")
        logger.info(f"   Zona usuario: {zona_usuario}")
        logger.info(f"   Backtest: {modo_backtest}")
        logger.info(f"   Hora actual: {self.hora_usuario_str()}")
    
    def _cargar_umbrales(self):
        """Carga umbrales desde configuración centralizada."""
        if Umbrales is not None:
            if hasattr(Umbrales, 'SCORE_MINIMO_POR_CALIDAD'):
                self.SCORE_MINIMO_POR_CALIDAD.update(Umbrales.SCORE_MINIMO_POR_CALIDAD)
    
    def _cargar_horarios_sesion(self) -> Dict:
        """Carga horarios desde config."""
        horarios = {
            'EURUSD': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'GBPUSD': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'USDJPY': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'AUDUSD': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'USDCAD': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'USDCHF': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'EURJPY': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'GBPJPY': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'AUDJPY': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'EURGBP': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'XAUUSD': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'XAGUSD': {'inicio': 22, 'fin': 22, 'dias': [0, 1, 2, 3, 4]},
            'US30': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
            'NAS100': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
            'US500': {'inicio': 7, 'fin': 16, 'dias': [0, 1, 2, 3, 4]},
            'BTCUSD': {'inicio': 0, 'fin': 24, 'dias': [0, 1, 2, 3, 4, 5, 6]},
            'ETHUSD': {'inicio': 0, 'fin': 24, 'dias': [0, 1, 2, 3, 4, 5, 6]},
            'SOLUSD': {'inicio': 0, 'fin': 24, 'dias': [0, 1, 2, 3, 4, 5, 6]},
        }
        
        try:
            from config.settings import Config
            if hasattr(Config, 'HORARIOS_POR_ACTIVO'):
                horarios.update(Config.HORARIOS_POR_ACTIVO)
        except ImportError:
            pass
        
        return horarios
    
    # ============================================================
    # MÉTODOS DE TIEMPO
    # ============================================================
    
    def ahora_utc(self) -> datetime:
        """Retorna la hora actual en UTC."""
        return datetime.now(timezone.utc)
    
    def ahora_usuario(self) -> datetime:
        """Retorna la hora actual en la zona del usuario."""
        return self.ahora_utc().astimezone(self.zona_tz)
    
    def hora_usuario_str(self) -> str:
        """Retorna la hora del usuario en formato legible."""
        return self.ahora_usuario().strftime("%H:%M:%S")
    
    def hora_utc_str(self) -> str:
        """Retorna la hora UTC en formato legible."""
        return self.ahora_utc().strftime("%H:%M:%S")
    
    def hora_float(self, dt: Optional[datetime] = None) -> float:
        """Convierte una hora a formato float (0-24)."""
        if dt is None:
            dt = self.ahora_utc()
        return dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    
    def hora_colombia_float(self, dt: Optional[datetime] = None) -> float:
        """Convierte hora a formato float en zona Colombia."""
        if dt is None:
            dt = self.ahora_utc()
        hora_col = dt.astimezone(self.ZONAS['COLOMBIA'])
        return hora_col.hour + hora_col.minute / 60.0
    
    # ============================================================
    # VALIDACIÓN DE MERCADO GLOBAL
    # ============================================================
    
        
    def estado_mercado(self, ahora: Optional[datetime] = None) -> EstadoMercado:
        """
        Obtiene el estado detallado del mercado global.
        
        Args:
            ahora: Fecha de referencia
        
        Returns:
            EstadoMercado
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        if self.es_horario_rollover(ahora):
            return EstadoMercado.ROLLOVER
        
        if not self.mercado_abierto(ahora):
            if self.es_fin_de_semana_cerrado(ahora):
                return EstadoMercado.FIN_SEMANA
            return EstadoMercado.CERRADO
        
        return EstadoMercado.ABIERTO
    
    def es_horario_rollover(self, ahora: Optional[datetime] = None) -> bool:
        """
        Detecta horario de rollover (spreads amplios).
        
        Args:
            ahora: Fecha de referencia
        
        Returns:
            True si está en horario de rollover
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        ny_time = ahora.astimezone(self.ZONAS['NEW_YORK'])
        hora = self.hora_float(ny_time)
        
        # Rollover: 16:45 - 17:30 NY time
        return 16.75 <= hora <= 17.50
    
    # ============================================================
    # VALIDACIÓN DE FIN DE SEMANA
    # ============================================================
    
    def es_fin_de_semana_cerrado(self,
                                 ahora: Optional[datetime] = None,
                                 simbolo: Optional[str] = None) -> bool:
        """
        Verifica si el mercado está cerrado por fin de semana.
        
        Args:
            ahora: Fecha de referencia
            simbolo: Símbolo (para validación por tipo)
        
        Returns:
            True si está cerrado
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        weekday_col = hora_col.weekday()
        hora_col_float = hora_col.hour + hora_col.minute / 60.0
        
        # Sábado → siempre cerrado
        if weekday_col == 5:
            return True
        
        # Domingo → cerrado hasta 17:00 COT
        if weekday_col == 6 and hora_col_float < 17.0:
            return True
        
        # Viernes → depende del tipo de activo
        if weekday_col == 4:
            if simbolo:
                simbolo_upper = simbolo.upper()
                
                # CRIPTO: 24/7
                if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                    return False
                
                # ÍNDICES y METALES: cierran a las 16:00 COT
                if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']) or \
                   any(x in simbolo_upper for x in ['XAU', 'XAG']):
                    return hora_col_float >= 16.0
                
                # FOREX: cierra a las 17:00 COT
                return hora_col_float >= 17.0
            
            # Si no hay símbolo, usar cierre más temprano
            return hora_col_float >= 16.0
        
        # ✅ Lunes → NO es fin de semana
        if weekday_col == 0:
            return False
        
        return False
    
    # ============================================================
    # VALIDACIÓN POR SÍMBOLO
    # ============================================================
    
    def es_horario_operativo(
        self,
        simbolo: str,
        ahora: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Verifica si un símbolo está en horario operativo.
        V9.10 - CORREGIDO DEFINITIVO: Maneja sábado y domingo correctamente.
        """
        # ============================================================
        # 1. VALIDAR / OBTENER HORA ACTUAL
        # ============================================================
        if ahora is None:
            ahora = self.ahora_utc()

        hora_col = ahora.astimezone(self.ZONAS["COLOMBIA"])
        weekday_col = hora_col.weekday()
        hora_col_float = (
            hora_col.hour
            + hora_col.minute / 60.0
            + hora_col.second / 3600.0
        )

        simbolo_upper = simbolo.upper().strip()

        # ============================================================
        # 2. ✅ CRIPTO: SIEMPRE OPERATIVO (24/7)
        # ============================================================
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return (True, "24/7 (Cripto)")

        # ============================================================
        # 3. ✅ SÁBADO: SOLO CRIPTO OPERA
        # ============================================================
        if weekday_col == 5:  # Sábado
            return (False, "Sábado - Solo cripto opera")

        # ============================================================
        # 4. ✅ DOMINGO: CRIPTO SIEMPRE, FOREX/ÍNDICES DESDE CIERTA HORA
        # ============================================================
        if weekday_col == 6:  # Domingo
            # Forex: abre 22:00 UTC (17:00 COT)
            if hora_col_float >= 17.0:
                # ¿Es forex?
                if self._es_forex(simbolo_upper):
                    return (True, "Domingo - Forex abierto desde 17:00 COT")
            
            # Índices y Metales: abren 23:00 UTC (18:00 COT)
            if hora_col_float >= 18.0:
                if self._es_indice(simbolo_upper) or self._es_metal(simbolo_upper):
                    return (True, "Domingo - Índices/Metales abiertos desde 18:00 COT")
            
            return (False, f"Domingo - Apertura próxima (Forex 17:00, Índices 18:00)")

        # ============================================================
        # 5. ✅ LUNES A VIERNES: HORARIO NORMAL
        # ============================================================
        
        # VIERNES: Cierres anticipados
        if weekday_col == 4:  # Viernes
            # ÍNDICES y METALES: cierran a las 16:00 COT
            if self._es_indice(simbolo_upper) or self._es_metal(simbolo_upper):
                if hora_col_float >= 16.0:
                    return (False, "Viernes - Cierre de índices/metales (16:00 COT)")
                else:
                    return (True, "Viernes - Índices/Metales abiertos")
            
            # FOREX: cierra a las 17:00 COT
            if self._es_forex(simbolo_upper):
                if hora_col_float >= 17.0:
                    return (False, "Viernes - Cierre de Forex (17:00 COT)")
                else:
                    return (True, "Viernes - Forex abierto")
        
        # ============================================================
        # 6. OBTENER CONFIGURACIÓN DEL SÍMBOLO
        # ============================================================
        config = self.horarios_sesion.get(simbolo)
        if not config:
            # Si no hay configuración específica, usar horario genérico
            if weekday_col in [0, 1, 2, 3, 4]:  # Lunes a Viernes
                return (True, "Horario normal")
            else:
                return (False, "Sin horario configurado")

        # ============================================================
        # 7. VERIFICAR DÍA OPERATIVO
        # ============================================================
        dias_operativos = config.get("dias", [0, 1, 2, 3, 4])
        if weekday_col not in dias_operativos:
            dias_nombre = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
            return (False, f"{dias_nombre[weekday_col]} - No operativo")

        # ============================================================
        # 8. OBTENER HORARIO CONFIGURADO
        # ============================================================
        inicio = config.get("inicio", 0)
        fin = config.get("fin", 24)

        # Operación 24 horas
        if inicio == fin:
            return (True, "24 horas")

        # Rango normal (ej: 08:00 -> 17:00)
        if inicio < fin:
            if inicio <= hora_col_float < fin:
                return (True, f"Operativo ({inicio:02d}:00-{fin:02d}:00 COT)")
            return (False, f"Fuera de horario ({inicio:02d}:00-{fin:02d}:00 COT)")

        # Rango que cruza medianoche (ej: 22:00 -> 06:00)
        if hora_col_float >= inicio or hora_col_float < fin:
            return (True, f"Operativo ({inicio:02d}:00-{fin:02d}:00 COT)")
        return (False, f"Fuera de horario ({inicio:02d}:00-{fin:02d}:00 COT)")

    # ============================================================
    # MÉTODOS AUXILIARES PARA DETECCIÓN DE TIPO DE ACTIVO
    # ============================================================

    def _es_forex(self, simbolo: str) -> bool:
        """Verifica si es un par de divisas."""
        # Pares forex conocidos
        pares_forex = [
            'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF',
            'EURGBP', 'EURJPY', 'GBPJPY', 'AUDJPY', 'EURNZD', 'GBPAUD',
            'EURCHF', 'GBPCHF', 'AUDCAD', 'AUDCHF', 'AUDNZD', 'CADJPY',
            'CHFJPY', 'EURAUD', 'EURCAD', 'GBPAUD', 'GBPCAD', 'GBPCHF',
            'NZDJPY', 'NZDUSD', 'USDSGD', 'USDHKD', 'USDMXN', 'USDZAR'
        ]
        return simbolo in pares_forex

    def _es_indice(self, simbolo: str) -> bool:
        """Verifica si es un índice."""
        indices = ['US30', 'NAS100', 'US500', 'SP500', 'GER40', 'UK100', 'DAX', 'SPX']
        return any(x in simbolo for x in indices)

    def _es_metal(self, simbolo: str) -> bool:
        """Verifica si es un metal precioso."""
        metales = ['XAU', 'XAG', 'XPT', 'XPD']
        return any(x in simbolo for x in metales)
        # ============================================================
        # 3. FUNCIÓN INTERNA PARA GUARDAR Y RETORNAR
        # ============================================================
        def finalizar(
            operativo: bool,
            motivo: str
        ) -> Tuple[bool, str]:

            resultado = (operativo, motivo)

            self._cache_validacion[cache_key] = (
                resultado,
                time.time()
            )

            return resultado

        # ============================================================
        # ✅ CRIPTO: SIEMPRE OPERATIVO (24/7)
        # ============================================================
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return (True, "24/7 (Cripto)")
        
        # ============================================================
        # ✅ VERIFICAR SÁBADO
        # ============================================================
        if weekday_col == 5:
            return (False, "Sábado - mercado cerrado")
        
        # ============================================================
        # ✅ VERIFICAR DOMINGO
        # ============================================================
        if weekday_col == 6:
            if hora_col_float < 17.0:
                return (False, f"Domingo - apertura 17:00 COT")
            else:
                return (True, "Domingo - mercado abierto")
        
        # ============================================================
        # ✅ VERIFICAR VIERNES
        # ============================================================
        if weekday_col == 4:
            # ÍNDICES y METALES: cierran a las 16:00 COT
            if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']) or \
            any(x in simbolo_upper for x in ['XAU', 'XAG']):
                if hora_col_float >= 16.0:
                    return (False, "Viernes - cierre de índices/metales (16:00 COT)")
                else:
                    return (True, "Viernes - mercado abierto")
            
            # FOREX: cierra a las 17:00 COT
            if hora_col_float >= 17.0:
                return (False, "Viernes - cierre de Forex (17:00 COT)")
            else:
                return (True, "Viernes - mercado abierto")
        
        # ============================================================
        # ✅ LUNES: SIEMPRE ABIERTO
        # ============================================================
        if weekday_col == 0:
            return (True, "Lunes - mercado abierto")
        
        # ============================================================
        # ✅ OBTENER CONFIGURACIÓN DEL SÍMBOLO
        # ============================================================
        config = self.horarios_sesion.get(simbolo)
        if not config:
            if weekday_col in [0, 1, 2, 3, 4]:
                return (True, "Horario normal")
            else:
                return (False, "Sin horario configurado")
        # ============================================================
        # 10. VERIFICAR DÍA OPERATIVO
        # ============================================================
        dias_operativos = config.get(
            "dias",
            [0, 1, 2, 3, 4]
        )

        if weekday_col not in dias_operativos:

            dias_nombre = (
                "Lunes",
                "Martes",
                "Miércoles",
                "Jueves",
                "Viernes",
                "Sábado",
                "Domingo"
            )

            return finalizar(
                False,
                f"{dias_nombre[weekday_col]} - no operativo"
            )

        # ============================================================
        # 11. OBTENER HORARIO CONFIGURADO
        # ============================================================
        inicio = config.get("inicio", 0)
        fin = config.get("fin", 24)

        # ============================================================
        # 12. OPERACIÓN 24 HORAS
        # ============================================================
        if inicio == fin:
            return finalizar(
                True,
                "24 horas"
            )

        # ============================================================
        # 13. RANGO NORMAL
        #    Ejemplo: 08:00 -> 17:00
        # ============================================================
        if inicio < fin:

            if inicio <= hora_col_float < fin:
                return finalizar(
                    True,
                    f"Operativo ({inicio:02d}:00-{fin:02d}:00 COT)"
                )

            return finalizar(
                False,
                f"Fuera de horario ({inicio:02d}:00-{fin:02d}:00 COT)"
            )

        # ============================================================
        # 14. RANGO QUE CRUZA MEDIANOCHE
        #    Ejemplo: 22:00 -> 06:00
        # ============================================================
        if hora_col_float >= inicio or hora_col_float < fin:

            return finalizar(
                True,
                f"Operativo ({inicio:02d}:00-{fin:02d}:00 COT)"
            )

        return finalizar(
            False,
            f"Fuera de horario ({inicio:02d}:00-{fin:02d}:00 COT)"
        )
    # ============================================================
    # VALIDACIÓN DE CIERRE DE VIERNES
    # ============================================================
    
    def es_cierre_viernes_inminente(self,
                                    ahora: Optional[datetime] = None,
                                    simbolo: Optional[str] = None,
                                    minutos_anticipacion: int = 30) -> bool:
        """
        Verifica si el cierre de viernes es inminente.
        
        Args:
            ahora: Fecha de referencia
            simbolo: Símbolo
            minutos_anticipacion: Minutos de anticipación
        
        Returns:
            True si el cierre es inminente
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        weekday_col = hora_col.weekday()
        hora_col_float = hora_col.hour + hora_col.minute / 60.0
        
        if weekday_col != 4:  # No es viernes
            return False
        
        if simbolo:
            simbolo_upper = simbolo.upper()
            
            # CRIPTO: nunca cierra
            if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                return False
            
            # ÍNDICES y METALES: cierran a las 16:00 COT
            if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']) or \
               any(x in simbolo_upper for x in ['XAU', 'XAG']):
                tiempo_restante = 16.0 - hora_col_float
                return 0 < tiempo_restante <= (minutos_anticipacion / 60.0)
            
            # FOREX: cierra a las 17:00 COT
            tiempo_restante = 17.0 - hora_col_float
            return 0 < tiempo_restante <= (minutos_anticipacion / 60.0)
        
        # Si no hay símbolo, usar cierre más temprano (16:00 COT)
        tiempo_restante = 16.0 - hora_col_float
        return 0 < tiempo_restante <= (minutos_anticipacion / 60.0)
    
    def debe_cerrar_por_viernes(self,
                                ahora: Optional[datetime] = None,
                                simbolo: Optional[str] = None) -> bool:
        """
        Determina si se deben cerrar posiciones por cierre de viernes.
        
        Args:
            ahora: Fecha de referencia
            simbolo: Símbolo
        
        Returns:
            True si se deben cerrar posiciones
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        weekday_col = hora_col.weekday()
        hora_col_float = hora_col.hour + hora_col.minute / 60.0
        
        if weekday_col != 4:  # No es viernes
            return False
        
        if simbolo:
            simbolo_upper = simbolo.upper()
            
            # CRIPTO: nunca cierra
            if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
                return False
            
            # ÍNDICES y METALES: cerrar después de 15:30 COT (30 min antes)
            if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']) or \
               any(x in simbolo_upper for x in ['XAU', 'XAG']):
                return hora_col_float >= 15.5
            
            # FOREX: cerrar después de 16:30 COT (30 min antes)
            return hora_col_float >= 16.5
        
        # Si no hay símbolo, cerrar después de 15:30 COT
        return hora_col_float >= 15.5
    
    # ============================================================
    # SESIONES
    # ============================================================
    
    def sesion_actual(self, ahora: Optional[datetime] = None) -> Optional[SesionMercado]:
        """
        Determina la sesión de mercado actual.
        
        Args:
            ahora: Fecha de referencia
        
        Returns:
            SesionMercado o None
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        if not self.mercado_abierto(ahora):
            return None
        
        hora = self.hora_float(ahora)
        
        if 0.0 <= hora < 8.0:
            return SesionMercado.ASIAN
        elif 8.0 <= hora < 16.0:
            if 13.0 <= hora < 16.0:
                return SesionMercado.OVERLAP_LONDON_NY
            return SesionMercado.LONDON
        elif 13.0 <= hora < 22.0:
            return SesionMercado.NEW_YORK
        
        return None
    
    def validar_sesion_simbolo(self,
                               simbolo: str,
                               ahora: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Valida si un símbolo está en su sesión operativa.
        
        Args:
            simbolo: Símbolo
            ahora: Fecha de referencia
        
        Returns:
            (es_valido, razon)
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        # Verificar caché
        cache_key = f"sesion_{simbolo}_{ahora.strftime('%Y-%m-%d %H:%M')}"
        if cache_key in self._cache_validacion:
            cached, timestamp = self._cache_validacion[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached
        
        # Verificar si el mercado está abierto
        if not self.mercado_abierto(ahora):
            resultado = (False, "Mercado cerrado")
            self._cache_validacion[cache_key] = (resultado, time.time())
            return resultado
        
        # Obtener sesión del símbolo
        conf = self.config_activos.get(simbolo, {})
        sesion = conf.get('sesion', '24/7')
        
        # 24/7 siempre válido
        if sesion == '24/7':
            resultado = (True, "24/7")
            self._cache_validacion[cache_key] = (resultado, time.time())
            return resultado
        
        # Validar sesión específica
        hora = self.hora_float(ahora)
        rangos = self.SESIONES.get(sesion)
        
        if rangos is None:
            resultado = (True, "Sin restricción")
            self._cache_validacion[cache_key] = (resultado, time.time())
            return resultado
        
        # Verificar si es rango continuo o discontinuo
        if isinstance(rangos[0], tuple):
            valido = any(r[0] <= hora < r[1] for r in rangos)
        else:
            valido = rangos[0] <= hora < rangos[1]
        
        razon = sesion if valido else f"{sesion} fuera de horario"
        resultado = (valido, razon)
        self._cache_validacion[cache_key] = (resultado, time.time())
        return resultado
    
    # ============================================================
    # CALIDAD DE HORARIO
    # ============================================================
    
    def obtener_calidad_horario(self,
                                simbolo: str,
                                ahora: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Obtiene la calidad del horario para un símbolo.
        
        Args:
            simbolo: Símbolo
            ahora: Fecha de referencia
        
        Returns:
            Diccionario con calidad, puntaje, razon, score_minimo
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        weekday_col = hora_col.weekday()
        hora_col_float = hora_col.hour + hora_col.minute / 60.0
        simbolo_upper = simbolo.upper()
        
        # ============================================================
        # 1. CRIPTO: 24/7
        # ============================================================
        if any(c in simbolo_upper for c in ['BTC', 'ETH', 'SOL']):
            return {
                'calidad': 'EXCELENTE',
                'puntaje': 100,
                'razon': '24/7 (Cripto)',
                'es_optimo': True,
                'score_minimo': 0
            }
        
        # ============================================================
        # 2. SÁBADO: PÉSIMO
        # ============================================================
        if weekday_col == 5:
            return {
                'calidad': 'PESIMA',
                'puntaje': 0,
                'razon': 'Sábado - mercado cerrado',
                'es_optimo': False,
                'score_minimo': 999
            }
        
        # ============================================================
        # 3. DOMINGO: PÉSIMO hasta 17:00 COT
        # ============================================================
        if weekday_col == 6:
            if hora_col_float < 17.0:
                return {
                    'calidad': 'PESIMA',
                    'puntaje': 0,
                    'razon': 'Domingo - apertura 17:00 COT',
                    'es_optimo': False,
                    'score_minimo': 999
                }
            return {
                'calidad': 'REGULAR',
                'puntaje': 40,
                'razon': 'Domingo - inicio de semana',
                'es_optimo': False,
                'score_minimo': 65
            }
        
        # ============================================================
        # 4. VIERNES: depende del tipo de activo
        # ============================================================
        if weekday_col == 4:
            # ÍNDICES y METALES
            if any(x in simbolo_upper for x in ['US30', 'NAS100', 'US500']) or \
               any(x in simbolo_upper for x in ['XAU', 'XAG']):
                if hora_col_float >= 16.0:
                    return {
                        'calidad': 'PESIMA',
                        'puntaje': 0,
                        'razon': 'Viernes - cierre de índices/metales',
                        'es_optimo': False,
                        'score_minimo': 999
                    }
                if 11.0 <= hora_col_float < 16.0:
                    return {
                        'calidad': 'BUENA',
                        'puntaje': 80,
                        'razon': 'NY - Índices/metales activos',
                        'es_optimo': True,
                        'score_minimo': 35
                    }
            
            # FOREX
            if hora_col_float >= 17.0:
                return {
                    'calidad': 'PESIMA',
                    'puntaje': 0,
                    'razon': 'Viernes - cierre de Forex',
                    'es_optimo': False,
                    'score_minimo': 999
                }
            if 11.0 <= hora_col_float < 17.0:
                return {
                    'calidad': 'BUENA',
                    'puntaje': 75,
                    'razon': 'NY - Forex activo',
                    'es_optimo': True,
                    'score_minimo': 40
                }
        
        # ============================================================
        # 5. OVERLAP LDN-NY (07:00-11:00 COT)
        # ============================================================
        if 7.0 <= hora_col_float <= 11.0:
            return {
                'calidad': 'EXCELENTE',
                'puntaje': 100,
                'razon': 'Overlap LDN-NY - Máxima liquidez',
                'es_optimo': True,
                'score_minimo': 0
            }
        
        # ============================================================
        # 6. LONDRES (02:00-07:00 COT)
        # ============================================================
        if 2.0 <= hora_col_float < 7.0:
            es_londres_par = any(c in simbolo_upper for c in ['GBP', 'EUR', 'CHF'])
            if es_londres_par:
                return {
                    'calidad': 'BUENA',
                    'puntaje': 85,
                    'razon': 'Londres - Bueno para pares GBP/EUR/CHF',
                    'es_optimo': True,
                    'score_minimo': 35
                }
            return {
                'calidad': 'REGULAR',
                'puntaje': 55,
                'razon': 'Londres - Liquidez media',
                'es_optimo': False,
                'score_minimo': 55
            }
        
        # ============================================================
        # 7. NY (11:00-16:00 COT)
        # ============================================================
        if 11.0 <= hora_col_float < 16.0:
            es_ny_par = 'CAD' in simbolo_upper
            if es_ny_par:
                return {
                    'calidad': 'BUENA',
                    'puntaje': 75,
                    'razon': 'NY - Bueno para pares CAD',
                    'es_optimo': True,
                    'score_minimo': 40
                }
            return {
                'calidad': 'REGULAR',
                'puntaje': 60,
                'razon': 'NY - Liquidez media',
                'es_optimo': False,
                'score_minimo': 50
            }
        
        # ============================================================
        # 8. ASIÁTICO (18:00-02:00 COT)
        # ============================================================
        if 18.0 <= hora_col_float <= 24.0 or 0.0 <= hora_col_float < 2.0:
            es_asiatico_par = any(c in simbolo_upper for c in ['JPY', 'AUD', 'NZD'])
            if es_asiatico_par:
                return {
                    'calidad': 'REGULAR',
                    'puntaje': 60,
                    'razon': 'Asiático - Bueno para pares JPY/AUD/NZD',
                    'es_optimo': False,
                    'score_minimo': 60
                }
            return {
                'calidad': 'MALA',
                'puntaje': 30,
                'razon': 'Asiático - Baja liquidez',
                'es_optimo': False,
                'score_minimo': 80
            }
        
        # ============================================================
        # 9. DEFAULT
        # ============================================================
        return {
            'calidad': 'REGULAR',
            'puntaje': 50,
            'razon': 'Horario normal',
            'es_optimo': False,
            'score_minimo': 50
        }
    
    def obtener_score_minimo_por_horario(self,
                                         simbolo: str,
                                         ahora: Optional[datetime] = None) -> int:
        """
        Obtiene el score mínimo requerido según el horario.
        
        Args:
            simbolo: Símbolo
            ahora: Fecha de referencia
        
        Returns:
            Score mínimo requerido
        """
        calidad = self.obtener_calidad_horario(simbolo, ahora)
        return calidad.get('score_minimo', 50)
    
    # ============================================================
    # ESTADO DE MERCADO PARA MÚLTIPLES SÍMBOLOS
    # ============================================================
    
    def obtener_estado_mercado(self, simbolos: List[str]) -> Dict[str, Any]:
        """
        Clasifica símbolos en operables y no operables.
        V9.0 - ÚNICA DEFINICIÓN.
        
        Args:
            simbolos: Lista de símbolos
        
        Returns:
            Diccionario con estado detallado
        """
        ahora = self.ahora_utc()
        estado_general = self.estado_mercado(ahora)
        
        operables = []
        no_operables = []
        razones = {}
        sesiones_actuales = set()
        horarios_estado = {}
        
        # Calcular hora Colombia
        hora_col = ahora.astimezone(self.ZONAS['COLOMBIA'])
        weekday_col = hora_col.weekday()
        hora_col_float = hora_col.hour + hora_col.minute / 60.0
        
        # Detectar cierre de viernes
        es_viernes_cierre = False
        if weekday_col == 4:
            if self.debe_cerrar_por_viernes(ahora):
                es_viernes_cierre = True
        
        for simbolo in simbolos:
            # 1. Verificar si el mercado está cerrado por fin de semana
            if self.es_fin_de_semana_cerrado(ahora, simbolo):
                no_operables.append(simbolo)
                razones[simbolo] = "Mercado cerrado (fin de semana)"
                horarios_estado[simbolo] = 'NO_OPERATIVO'
                continue
            
            # 2. Verificar cierre de viernes
            if es_viernes_cierre and self.debe_cerrar_por_viernes(ahora, simbolo):
                no_operables.append(simbolo)
                razones[simbolo] = "Cierre de viernes"
                horarios_estado[simbolo] = 'NO_OPERATIVO'
                continue
            
            # 3. Verificar horario operativo
            operativo, razon_operativo = self.es_horario_operativo(simbolo, ahora)
            
            # 4. Verificar sesión
            valido, razon_sesion = self.validar_sesion_simbolo(simbolo, ahora)
            
            # 5. Verificar cierre inminente
            if self.es_cierre_viernes_inminente(ahora, simbolo, minutos_anticipacion=30):
                no_operables.append(simbolo)
                razones[simbolo] = "Cierre inminente"
                horarios_estado[simbolo] = 'NO_OPERATIVO'
                continue
            
            # 6. Combinar validaciones
            if operativo and valido:
                operables.append(simbolo)
                conf = self.config_activos.get(simbolo, {})
                sesion = conf.get('sesion', '24/7')
                if sesion != '24/7':
                    sesiones_actuales.add(sesion)
                horarios_estado[simbolo] = 'OPERATIVO'
            else:
                no_operables.append(simbolo)
                if not operativo:
                    razones[simbolo] = razon_operativo
                else:
                    razones[simbolo] = razon_sesion
                horarios_estado[simbolo] = 'NO_OPERATIVO'
        
        return {
            'operables': operables,
            'no_operables': no_operables,
            'razones': razones,
            'horarios_estado': horarios_estado,
            'estado_general': estado_general.value,
            'hora_utc': ahora.strftime('%H:%M:%S'),
            'hora_usuario': self.hora_usuario_str(),
            'zona_usuario': self.zona_usuario,
            'sesiones_activas': list(sesiones_actuales),
            'es_fin_semana': self.es_fin_de_semana_cerrado(ahora),
            'es_rollover': self.es_horario_rollover(ahora),
            'es_cierre_viernes': es_viernes_cierre,
            'total_operables': len(operables),
            'total_no_operables': len(no_operables),
            'weekday_col': weekday_col,
            'hora_col_float': hora_col_float,
        }
    
    # ============================================================
    # MÉTODOS DE UTILIDAD
    # ============================================================
    
    def obtener_proxima_apertura(self, ahora: Optional[datetime] = None) -> Tuple[str, str]:
        """
        Calcula la próxima apertura del mercado.
        
        Args:
            ahora: Fecha de referencia
        
        Returns:
            (dia, hora) en formato legible
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        
        hoy = ahora.weekday()
        hora_utc = self.hora_float(ahora)
        
        if hoy == 4:  # Viernes
            if hora_utc >= 22.0:
                prox = ahora.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=2)
                dia = "Domingo"
            else:
                prox = ahora.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                dia = dias_semana[prox.weekday()]
        elif hoy == 5:  # Sábado
            prox = ahora.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=1)
            dia = "Domingo"
        elif hoy == 6:  # Domingo
            if hora_utc < 22.0:
                prox = ahora.replace(hour=22, minute=0, second=0, microsecond=0)
                dia = "Domingo"
            else:
                prox = ahora.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                dia = "Lunes"
        else:
            prox = ahora.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            dia = dias_semana[prox.weekday()]
        
        hora_col = prox.astimezone(self.ZONAS['COLOMBIA'])
        hora_12h = hora_col.strftime("%I:%M %p").lstrip("0")
        
        return dia, hora_12h
    
    def tiempo_para_cierre(self, ahora: Optional[datetime] = None) -> str:
        """
        Retorna el tiempo restante hasta el cierre.
        
        Args:
            ahora: Fecha de referencia
        
        Returns:
            Tiempo restante en formato legible
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        weekday = ahora.weekday()
        hora_utc = self.hora_float(ahora)
        
        if weekday == 4:  # Viernes
            if hora_utc < 22.0:
                horas = int(22.0 - hora_utc)
                minutos = int((22.0 - hora_utc) * 60) % 60
                return f"{horas}h {minutos}min"
            return "Mercado cerrado"
        
        if weekday == 6:  # Domingo
            if hora_utc < 22.0:
                horas = int(22.0 - hora_utc)
                minutos = int((22.0 - hora_utc) * 60) % 60
                return f"{horas}h {minutos}min para apertura"
            return "Mercado abierto"
        
        return "No aplica"
    
    def es_horario_seguro_para_abrir(self,
                                     simbolo: str,
                                     ahora: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Verifica si es seguro abrir una operación.
        
        Args:
            simbolo: Símbolo
            ahora: Fecha de referencia
        
        Returns:
            (es_seguro, razon)
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        # 1. Verificar si el mercado está cerrado
        if self.es_fin_de_semana_cerrado(ahora, simbolo):
            return False, "Mercado cerrado (fin de semana)"
        
        # 2. Verificar si el cierre es inminente
        if self.es_cierre_viernes_inminente(ahora, simbolo, minutos_anticipacion=60):
            return False, "Cierre inminente"
        
        # 3. Verificar horario operativo
        operativo, razon = self.es_horario_operativo(simbolo, ahora)
        if not operativo:
            return False, razon
        
        # 4. Verificar sesión
        valido, razon_sesion = self.validar_sesion_simbolo(simbolo, ahora)
        if not valido:
            return False, razon_sesion
        
        return True, "Horario seguro"
    
    def limpiar_cache(self):
        """Limpia la caché de validaciones."""
        self._cache_validacion.clear()
        logger.debug("🧹 Caché de horarios limpiada")
    
    # ============================================================
    # MÉTODOS DE COMPATIBILIDAD (LEGACY)
    # ============================================================
    
    def mercado_abierto(self, ahora: Optional[datetime] = None) -> bool:
        """
        Determina si el mercado está abierto.
        V9.10 - CORREGIDO: Considera cripto 24/7.
        """
        if ahora is None:
            ahora = self.ahora_utc()
        
        weekday_utc = ahora.weekday()
        hora_utc_float = ahora.hour + ahora.minute / 60.0
        
        # ============================================================
        # ✅ CRIPTO: SIEMPRE ABIERTO (24/7)
        # ============================================================
        # Este método es para mercado tradicional.
        # El filtrado por símbolo se hace en es_horario_operativo().
        
        # Sábado: cerrado para Forex/Índices/Metales
        if weekday_utc == 5:
            return False
        
        # Domingo: cerrado hasta 22:00 UTC (17:00 COT)
        if weekday_utc == 6 and hora_utc_float < 22.0:
            return False
        
        # Viernes: cerrado después de 22:00 UTC (17:00 COT)
        if weekday_utc == 4 and hora_utc_float >= 22.0:
            return False
        
        return True
        
    def es_horario_operativo_legacy(self, simbolo: str) -> Tuple[bool, str]:
        """
        Versión legacy de es_horario_operativo.
        DEPRECADO - Usar es_horario_operativo() en su lugar.
        """
        return self.es_horario_operativo(simbolo)


# ============================================================
# FUNCIÓN DE UTILIDAD
# ============================================================

def create_horario_mercado(zona_usuario: str = 'COLOMBIA',
                           config_activos: Optional[Dict] = None,
                           noticias: Optional[Any] = None,
                           modo_backtest: bool = False) -> HorarioMercado:
    """
    Crea una instancia de HorarioMercado.
    
    Args:
        zona_usuario: Zona horaria del usuario
        config_activos: Configuración de activos
        noticias: Sistema de noticias (opcional)
        modo_backtest: Modo backtest
    
    Returns:
        HorarioMercado
    """
    return HorarioMercado(
        zona_usuario=zona_usuario,
        config_activos=config_activos,
        noticias=noticias,
        modo_backtest=modo_backtest
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    # Prueba rápida
    horario = HorarioMercado(zona_usuario='COLOMBIA', modo_backtest=True)
    
    print(f"🕐 Hora Colombia: {horario.hora_usuario_str()}")
    print(f"🕐 Hora UTC: {horario.hora_utc_str()}")
    print(f"📊 Mercado abierto: {horario.mercado_abierto()}")
    print(f"📊 Estado: {horario.estado_mercado().value}")
    print(f"📊 Sesión actual: {horario.sesion_actual()}")
    
    # Probar símbolos
    simbolos = ['EURUSD', 'USDJPY', 'BTCUSD', 'XAUUSD', 'US30']
    estado = horario.obtener_estado_mercado(simbolos)
    
    print(f"\n📊 Estado de mercado:")
    print(f"  Operables: {estado['operables']}")
    print(f"  No operables: {estado['no_operables']}")
    for s in estado['no_operables']:
        print(f"    {s}: {estado['razones'].get(s, 'N/A')}")
    
    print(f"\n📊 Calidad de horario:")
    for s in simbolos:
        calidad = horario.obtener_calidad_horario(s)
        print(f"  {s}: {calidad['calidad']} (score min: {calidad['score_minimo']})")
    
    print("\n✅ Prueba completada")