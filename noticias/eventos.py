#!/usr/bin/env python3
"""
noticias/eventos.py (V9.1)
Dataclasses para el sistema de noticias.
Separado para evitar dependencias circulares.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from enum import Enum


class ImpactoNoticia(Enum):
    CRITICO = 4
    ALTO = 3
    MEDIO = 2
    BAJO = 1
    IRRELEVANTE = 0


@dataclass
class EventoNoticia:
    nombre: str
    divisa: str
    impacto: ImpactoNoticia
    hora: datetime
    sentimiento_esperado: float = 0.0
    fuente: str = ""
    descripcion: str = ""
    pais: str = ""
    actual: Optional[float] = None
    previo: Optional[float] = None
    consenso: Optional[float] = None
    
    hora_inicio_ventana: Optional[datetime] = None
    hora_fin_ventana: Optional[datetime] = None
    hora_pico: Optional[datetime] = None
    
    def __post_init__(self):
        if self.hora_inicio_ventana is None:
            self.hora_inicio_ventana = self.hora - timedelta(hours=2)
        if self.hora_fin_ventana is None:
            self.hora_fin_ventana = self.hora + timedelta(hours=2)
        if self.hora_pico is None:
            self.hora_pico = self.hora
    
    def ponderacion_actual(self, momento: datetime) -> float:
        """Calcula la ponderación actual del evento."""
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=timezone.utc)
        if self.hora.tzinfo is None:
            self.hora = self.hora.replace(tzinfo=timezone.utc)
        if self.hora_inicio_ventana.tzinfo is None:
            self.hora_inicio_ventana = self.hora_inicio_ventana.replace(tzinfo=timezone.utc)
        if self.hora_fin_ventana.tzinfo is None:
            self.hora_fin_ventana = self.hora_fin_ventana.replace(tzinfo=timezone.utc)
        
        if momento < self.hora_inicio_ventana or momento > self.hora_fin_ventana:
            return 0.0
        
        if momento < self.hora:
            horas_antes = (self.hora - momento).total_seconds() / 3600.0
            ponderacion = 1.0 - (horas_antes / 2.0) ** 1.5
        else:
            horas_despues = (momento - self.hora).total_seconds() / 3600.0
            ponderacion = max(0.0, 1.0 - (horas_despues / 2.0) ** 1.2)
        
        return max(0.0, min(1.0, ponderacion))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'nombre': self.nombre,
            'divisa': self.divisa,
            'impacto': self.impacto.value,
            'hora': self.hora.isoformat(),
            'sentimiento_esperado': self.sentimiento_esperado,
            'fuente': self.fuente,
            'descripcion': self.descripcion,
            'pais': self.pais,
            'actual': self.actual,
            'previo': self.previo,
            'consenso': self.consenso,
            'hora_inicio_ventana': self.hora_inicio_ventana.isoformat() if self.hora_inicio_ventana else None,
            'hora_fin_ventana': self.hora_fin_ventana.isoformat() if self.hora_fin_ventana else None,
            'hora_pico': self.hora_pico.isoformat() if self.hora_pico else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EventoNoticia':
        return cls(
            nombre=data.get('nombre', ''),
            divisa=data.get('divisa', 'ALL'),
            impacto=ImpactoNoticia(data.get('impacto', 0)),
            hora=datetime.fromisoformat(data['hora']),
            sentimiento_esperado=data.get('sentimiento_esperado', 0.0),
            fuente=data.get('fuente', ''),
            descripcion=data.get('descripcion', ''),
            pais=data.get('pais', ''),
            actual=data.get('actual'),
            previo=data.get('previo'),
            consenso=data.get('consenso'),
            hora_inicio_ventana=datetime.fromisoformat(data['hora_inicio_ventana']) if data.get('hora_inicio_ventana') else None,
            hora_fin_ventana=datetime.fromisoformat(data['hora_fin_ventana']) if data.get('hora_fin_ventana') else None,
            hora_pico=datetime.fromisoformat(data['hora_pico']) if data.get('hora_pico') else None,
        )