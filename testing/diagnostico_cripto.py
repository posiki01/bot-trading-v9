#!/usr/bin/env python3
"""
testing/diagnostico_cripto.py (V1.0)
Diagnóstico específico para cripto (BTC, ETH) en sábado.
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from colorama import Fore, Style, init

sys.path.insert(0, str(Path(__file__).parent.parent))

init(autoreset=True)

CYAN = Fore.CYAN
GREEN = Fore.GREEN
YELLOW = Fore.YELLOW
RED = Fore.RED
WHITE = Fore.WHITE
RESET = Style.RESET_ALL

from config.settings import Config
from utils.tiempo import HorarioMercado
from utils.helpers import get_tipo_activo
from core.orquestador import Orquestador
from utils.adaptacion_mercado import AdaptadorMercado


class DiagnosticoCripto:
    """
    Diagnóstico específico para cripto en sábado.
    V1.0.
    """
    
    def __init__(self, modo_depuracion: bool = True):
        """Inicializa el diagnóstico."""
        self.modo_depuracion = modo_depuracion
        self.orquestador = Orquestador(modo_depuracion=modo_depuracion)
        self.horario = HorarioMercado(zona_usuario='COLOMBIA')
        self.adaptador = AdaptadorMercado()
    
    def diagnosticar(self, simbolo: str = 'BTCUSD'):
        """Diagnostica un símbolo cripto."""
        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}🔍 DIAGNÓSTICO DE {simbolo}{RESET}")
        print(f"{CYAN}{'='*80}{RESET}")
        
        # ============================================================
        # 1. CONECTAR A MT5
        # ============================================================
        print(f"\n{WHITE}📍 CONECTANDO A MT5...{RESET}")
        if not self.orquestador.mt5.conectar():
            print(f"{RED}❌ No se pudo conectar a MT5{RESET}")
            return
        
        print(f"{GREEN}✅ Conectado a MT5{RESET}")
        
        # ============================================================
        # 2. VERIFICAR QUE EL SÍMBOLO EXISTE
        # ============================================================
        info = self.orquestador.mt5.obtener_info_simbolo(simbolo)
        if info is None:
            print(f"{RED}❌ {simbolo}: No existe en MT5{RESET}")
            return
        
        print(f"\n{WHITE}📍 INFO DEL SÍMBOLO:{RESET}")
        print(f"  {GREEN}✅ Símbolo: {getattr(info, 'name', simbolo)}{RESET}")
        print(f"  Digits: {getattr(info, 'digits', 'N/A')}")
        print(f"  Point: {getattr(info, 'point', 'N/A')}")
        print(f"  Volume Min: {getattr(info, 'volume_min', 'N/A')}")
        print(f"  Volume Max: {getattr(info, 'volume_max', 'N/A')}")
        
        # ============================================================
        # 3. PIP VALUE
        # ============================================================
        print(f"\n{WHITE}📍 PIP VALUE:{RESET}")
        pip_conector = self.orquestador.mt5._pip_size_simbolo(simbolo, info)
        print(f"  {GREEN}✅ Desde conector: {pip_conector}{RESET}")
        print(f"  {WHITE}Desde fallback: 1.0{RESET}")
        
        # ============================================================
        # 4. OBTENER PRECIO ACTUAL
        # ============================================================
        print(f"\n{WHITE}📍 PRECIO ACTUAL:{RESET}")
        tick = self.orquestador.mt5.obtener_precio(simbolo)
        if tick:
            print(f"  {GREEN}✅ Bid: {tick.get('bid')}{RESET}")
            print(f"  {GREEN}✅ Ask: {tick.get('ask')}{RESET}")
            print(f"  {GREEN}✅ Spread (pips): {tick.get('spread_pips')}{RESET}")
            precio_actual = float(tick.get('bid', 0))
        else:
            print(f"  {RED}❌ No se pudo obtener tick{RESET}")
            precio_actual = 60000.0  # Dummy
        
        # ============================================================
        # 5. VERIFICAR HORARIO
        # ============================================================
        print(f"\n{WHITE}📍 HORARIO:{RESET}")
        es_operativo, razon = self.horario.es_horario_operativo(simbolo)
        calidad = self.horario.obtener_calidad_horario(simbolo)
        print(f"  Operativo: {es_operativo} ({razon})")
        print(f"  Calidad: {calidad['calidad']}")
        print(f"  Score mínimo: {calidad['score_minimo']}")
        
        # ============================================================
        # 6. OBTENER DATOS FRESCOS (BROKER)
        # ============================================================
        print(f"\n{WHITE}📍 OBTENIENDO DATOS FRESCOS...{RESET}")
        
        # M5
        df_m5 = self.orquestador.mt5.obtener_datos(simbolo, n_velas=500, timeframe=5)
        if df_m5 is not None and len(df_m5) > 0:
            print(f"  {GREEN}✅ M5: {len(df_m5)} velas{RESET}")
            print(f"     Última: {df_m5.index[-1]}")
        else:
            print(f"  {RED}❌ M5: Sin datos{RESET}")
        
        # H1
        df_h1 = self.orquestador.mt5.obtener_datos(simbolo, n_velas=100, timeframe=60)
        if df_h1 is not None and len(df_h1) > 0:
            print(f"  {GREEN}✅ H1: {len(df_h1)} velas{RESET}")
            print(f"     Última: {df_h1.index[-1]}")
        else:
            print(f"  {RED}❌ H1: Sin datos{RESET}")
        
        # ============================================================
        # 7. ANÁLISIS RÁPIDO
        # ============================================================
        print(f"\n{WHITE}📍 ANÁLISIS RÁPIDO (M5):{RESET}")
        if df_m5 is not None and len(df_m5) > 20:
            rapido = self.orquestador.analisis_capas.analisis_rapido(df_m5, simbolo, precio_actual)
            if rapido:
                print(f"  {GREEN}✅ RSI: {rapido.rsi:.1f}{RESET}")
                print(f"  {GREEN}✅ Volumen relativo: {rapido.volumen_relativo:.2f}x{RESET}")
                print(f"  {GREEN}✅ Tendencia: {rapido.tendencia_corta}{RESET}")
                print(f"  {GREEN}✅ ATR: {rapido.atr:.4f}{RESET}")
                print(f"  {GREEN}✅ Pasa filtro: {rapido.pasa_filtro}{RESET}")
                if not rapido.pasa_filtro:
                    print(f"  {YELLOW}⚠️ Razón rechazo: {rapido.razon_rechazo}{RESET}")
        
        # ============================================================
        # 8. ANÁLISIS MEDIO (H1)
        # ============================================================
        print(f"\n{WHITE}📍 ANÁLISIS MEDIO (H1):{RESET}")
        if df_h1 is not None and len(df_h1) > 50:
            medio = self.orquestador.analisis_capas.analisis_medio(df_h1, simbolo, rapido, {})
            if medio:
                print(f"  {GREEN}✅ ADX: {medio.adx:.1f}{RESET}")
                print(f"  {GREEN}✅ RSI: {medio.rsi:.1f}{RESET}")
                print(f"  {GREEN}✅ MACD: {medio.macd_histogram:.4f}{RESET}")
                print(f"  {GREEN}✅ ATR: {medio.atr:.4f}{RESET}")
                print(f"  {GREEN}✅ Soporte: {medio.soporte_cercano}{RESET}")
                print(f"  {GREEN}✅ Resistencia: {medio.resistencia_cercana}{RESET}")
                print(f"  {GREEN}✅ Pasa filtro: {medio.pasa_filtro}{RESET}")
                if not medio.pasa_filtro:
                    print(f"  {YELLOW}⚠️ Razón rechazo: {medio.razon_rechazo}{RESET}")
        
        # ============================================================
        # 9. AJUSTES DINÁMICOS
        # ============================================================
        print(f"\n{WHITE}📍 AJUSTES DINÁMICOS:{RESET}")
        if df_h1 is not None and df_m5 is not None:
            ajustes = self.adaptador.obtener_ajustes(
                simbolo=simbolo,
                df_m5=df_m5,
                df_h1=df_h1
            )
            print(f"  Tolerancia nivel: {ajustes['tolerancia_nivel']:.2f}")
            print(f"  Volumen mínimo: {ajustes['volumen_minimo']:.2f}")
            print(f"  Score mínimo: {ajustes['score_minimo']:.2f}")
            print(f"  R:R mínimo: {ajustes['rr_minimo']:.2f}")
            
            activos = {k: v for k, v in ajustes.items() if abs(v - 1.0) > 0.05}
            if activos:
                print(f"  {YELLOW}⚠️ Ajustes ACTIVOS:{RESET}")
                for k, v in activos.items():
                    print(f"     {k}: {v:.2f}")
            else:
                print(f"  {GREEN}✅ Ajustes normales{RESET}")
        
        # ============================================================
        # 10. VALIDAR SL/TP
        # ============================================================
        print(f"\n{WHITE}📍 VALIDAR SL/TP:{RESET}")
        sl_min = self.orquestador.gestor_stops.SL_MIN_POR_ACTIVO.get(simbolo, 80)
        sl_max = self.orquestador.gestor_stops.SL_MAX_POR_ACTIVO.get(simbolo, 300)
        print(f"  SL mínimo: {sl_min} pips")
        print(f"  SL máximo: {sl_max} pips")
        
        # Validar con precio actual
        valido, razon, sl, tp, tp2 = self.orquestador.gestor_stops.validar_sl_tp(
            simbolo=simbolo,
            entry_price=precio_actual,
            sl=precio_actual - (sl_min * 1.0),
            tp=precio_actual + (sl_min * 2.0),
            direccion='COMPRA',
            modo='RETEST',
            regimen='TREND_ALCISTA_FUERTE',
            calidad_horario='EXCELENTE'
        )
        
        if valido:
            print(f"  {GREEN}✅ SL/TP válido:{RESET}")
            print(f"     SL: {sl:.2f}")
            print(f"     TP: {tp:.2f}")
            print(f"     R:R: {abs(tp - precio_actual) / abs(precio_actual - sl):.2f}")
        else:
            print(f"  {RED}❌ SL/TP inválido: {razon}{RESET}")
        
        # ============================================================
        # 11. CÁLCULO DE LOTES
        # ============================================================
        print(f"\n{WHITE}📍 CÁLCULO DE LOTES:{RESET}")
        capital = float(self.orquestador.gestion_riesgo.capital_actual)
        lotes = self.orquestador.gestion_riesgo.calcular_lotes(
            entrada=precio_actual,
            stop_loss=sl if valido else precio_actual - (sl_min * 1.0),
            probabilidad=75,
            simbolo=simbolo,
            capital=capital,
            pip_size=1.0,
            tick_value=0.01,
            tick_size=0.01,
            point=0.01
        )
        
        print(f"  {GREEN}✅ Capital: ${capital:.2f}{RESET}")
        print(f"  {GREEN}✅ Lotes calculados: {lotes:.3f}{RESET}")
        
        # ============================================================
        # 12. RESUMEN
        # ============================================================
        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}📋 RESUMEN DE {simbolo}{RESET}")
        print(f"{CYAN}{'='*80}{RESET}")
        print(f"  {GREEN}✅ Tipo: {get_tipo_activo(simbolo)}{RESET}")
        print(f"  {GREEN}✅ Horario: {calidad['calidad']}{RESET}")
        print(f"  {GREEN}✅ RSI M5: {rapido.rsi:.1f}{RESET}")
        print(f"  {GREEN}✅ ADX H1: {medio.adx:.1f}{RESET}")
        print(f"  {GREEN}✅ Score H1: {self.orquestador.score_engine.calcular_score_h1(medio.adx, medio.rsi, 0, 0).score:.1f}{RESET}")
        print(f"  {GREEN}✅ Lotes: {lotes:.3f}{RESET}")
        
        # Desconectar
        self.orquestador.mt5.desconectar()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Diagnóstico específico para cripto")
    parser.add_argument("--simbolo", type=str, default='BTCUSD', help="Símbolo a diagnosticar")
    parser.add_argument("--depuracion", action="store_true", help="Modo depuración")
    
    args = parser.parse_args()
    
    diagnostico = DiagnosticoCripto(modo_depuracion=args.depuracion)
    diagnostico.diagnosticar(args.simbolo)