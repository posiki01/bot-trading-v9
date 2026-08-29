#!/usr/bin/env python3
"""
verificar_modos_sniper.py (V2.0 - CORREGIDO)
Verifica SL/TP para TODOS los símbolos en TODOS los modos del sniper.
"""

import sys
import os
from pathlib import Path
from colorama import Fore, Style, init

# Inicializar colorama
init(autoreset=True)

# Agregar directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent))

# ============================================================
# SÍMBOLOS Y MODOS
# ============================================================

SIMBOLOS = [
    'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF',
    'EURJPY', 'GBPJPY', 'AUDJPY', 'XAUUSD', 'XAGUSD',
    'US30', 'NAS100', 'US500', 'BTCUSD', 'ETHUSD', 'SOLUSD'
]

MODOS = [
    'RETEST', 'BREAKOUT', 'PULLBACK', 'NIVEL_FUERTE',
    'PATRON', 'RUPTURA_FALSA', 'VELA_BORDE', 'RETEST_FALLBACK', 'SNIPER_ELITE'
]

PRECIOS_REFERENCIA = {
    'EURUSD': 1.16764,
    'GBPUSD': 1.36448,
    'USDJPY': 159.179,
    'AUDUSD': 0.71609,
    'USDCAD': 1.38271,
    'USDCHF': 0.80162,
    'EURJPY': 185.860,
    'GBPJPY': 217.263,
    'AUDJPY': 113.986,
    'XAUUSD': 4663.38,
    'XAGUSD': 69.105,
    'US30': 53563.0,
    'NAS100': 29145.2,
    'US500': 7668.4,
    'BTCUSD': 79163.98,
    'ETHUSD': 2466.00,
    'SOLUSD': 150.00
}

# ============================================================
# CLASE DE VERIFICACIÓN
# ============================================================

class VerificadorModosSniper:
    """Verifica SL/TP para todos los símbolos en todos los modos."""
    
    def __init__(self):
        self.resultados = []
        self.total = 0
        self.pasados = 0
        self.fallados = 0
        self.errores_detalle = []
    
    def verificar_modo(self, simbolo: str, precio: float, modo: str) -> dict:
        """Verifica SL/TP para un símbolo en un modo específico."""
        from trading.sniper.sniper_checklist import SniperChecklist
        from trading.stops import GestorStops
        from utils.parametros_simbolo import get_parametros_simbolo
        from config.umbrales import Umbrales
        
        # Obtener parámetros
        params = get_parametros_simbolo(simbolo)
        pip_val = params['pip_val']
        digits = params['digits']
        
        # Crear instancias
        gestor = GestorStops(modo_backtest=True)
        checklist = SniperChecklist(
            pipeline=None, analisis_capas=None, modo_selector=None,
            entry_timer=None, gestor_stops=gestor, config=None, almacen=None,
            mt5=None, noticias=None, patron_tracker=None, ml_optimizer=None,
            analysis_cache=None, modo_depuracion=True, modo_backtest=True
        )
        
        # Obtener configuración del modo
        sniper_config = getattr(Umbrales, 'SNIPER_CONFIG', {})
        cfg_modo = sniper_config.get(modo, {})
        
        # Obtener SL mínimo y máximo
        sl_min = checklist._obtener_sl_minimo_universal(simbolo, modo)
        sl_max = checklist._obtener_sl_maximo_universal(simbolo, modo)
        
        # Ajustar por modo
        if modo == 'SNIPER_ELITE':
            sl_min = max(sl_min, 20)
        elif modo == 'BREAKOUT':
            sl_min = max(sl_min, 30)
        elif modo == 'PULLBACK':
            sl_min = max(sl_min, 25)
        
        # Verificar COMPRA
        sl_compra, tp_compra, rr_compra = checklist._calcular_sl_tp_estructura(
            simbolo=simbolo,
            precio_actual=precio,
            direccion='COMPRA',
            modo=modo,
            analisis_medio=None,
            analisis_pesado=None,
            contexto_h1={
                'soporte_cercano': precio * 0.998,
                'resistencia_cercana': precio * 1.002,
                'niveles': {'soportes': [], 'resistencias': []}
            },
            df_m5=None,
            df_h1=None,
            atr_m5=50.0
        )
        
        # Verificar VENTA
        sl_venta, tp_venta, rr_venta = checklist._calcular_sl_tp_estructura(
            simbolo=simbolo,
            precio_actual=precio,
            direccion='VENTA',
            modo=modo,
            analisis_medio=None,
            analisis_pesado=None,
            contexto_h1={
                'soporte_cercano': precio * 0.998,
                'resistencia_cercana': precio * 1.002,
                'niveles': {'soportes': [], 'resistencias': []}
            },
            df_m5=None,
            df_h1=None,
            atr_m5=50.0
        )
        
        # Calcular distancias en pips
        sl_dist_compra = abs(precio - sl_compra) / pip_val if pip_val > 0 else 0
        sl_dist_venta = abs(precio - sl_venta) / pip_val if pip_val > 0 else 0
        
        # ✅ CRÍTICO: TOLERANCIA PARA EVITAR ERRORES DE REDONDEO
        tolerancia = 0.5  # 0.5 pips de tolerancia
        
        # Validaciones
        errores = []
        
        # COMPRA
        if sl_compra <= 0 or tp_compra <= 0:
            errores.append(f"COMPRA: SL/TP inválido ({sl_compra:.{digits}f}/{tp_compra:.{digits}f})")
        elif sl_compra >= precio:
            errores.append(f"COMPRA: SL {sl_compra:.{digits}f} >= Entry {precio:.{digits}f}")
        elif tp_compra <= precio:
            errores.append(f"COMPRA: TP {tp_compra:.{digits}f} <= Entry {precio:.{digits}f}")
        elif tp_compra <= sl_compra:
            errores.append(f"COMPRA: TP {tp_compra:.{digits}f} <= SL {sl_compra:.{digits}f}")
        elif rr_compra < 1.0:
            errores.append(f"COMPRA: R:R {rr_compra:.2f} < 1.0")
        
        # VENTA
        if sl_venta <= 0 or tp_venta <= 0:
            errores.append(f"VENTA: SL/TP inválido ({sl_venta:.{digits}f}/{tp_venta:.{digits}f})")
        elif sl_venta <= precio:
            errores.append(f"VENTA: SL {sl_venta:.{digits}f} <= Entry {precio:.{digits}f}")
        elif tp_venta >= precio:
            errores.append(f"VENTA: TP {tp_venta:.{digits}f} >= Entry {precio:.{digits}f}")
        elif tp_venta >= sl_venta:
            errores.append(f"VENTA: TP {tp_venta:.{digits}f} >= SL {sl_venta:.{digits}f}")
        elif rr_venta < 1.0:
            errores.append(f"VENTA: R:R {rr_venta:.2f} < 1.0")
        
        # ✅ CRÍTICO: Validar SL en rango CON TOLERANCIA
        if sl_dist_compra < sl_min - tolerancia:
            errores.append(f"COMPRA: SL {sl_dist_compra:.1f} pips < mínimo {sl_min} pips")
        if sl_dist_venta < sl_min - tolerancia:
            errores.append(f"VENTA: SL {sl_dist_venta:.1f} pips < mínimo {sl_min} pips")
        
        # ✅ CRÍTICO: Usar > con TOLERANCIA (NO sin tolerancia)
        if sl_dist_compra > sl_max + tolerancia:
            errores.append(f"COMPRA: SL {sl_dist_compra:.1f} pips > máximo {sl_max} pips")
        if sl_dist_venta > sl_max + tolerancia:
            errores.append(f"VENTA: SL {sl_dist_venta:.1f} pips > máximo {sl_max} pips")
        
        return {
            'simbolo': simbolo,
            'modo': modo,
            'precio': precio,
            'digits': digits,
            'pip_val': pip_val,
            'sl_min': sl_min,
            'sl_max': sl_max,
            'compra': {
                'sl': sl_compra,
                'tp': tp_compra,
                'rr': rr_compra,
                'sl_dist_pips': sl_dist_compra
            },
            'venta': {
                'sl': sl_venta,
                'tp': tp_venta,
                'rr': rr_venta,
                'sl_dist_pips': sl_dist_venta
            },
            'errores': errores
        }
    
    def ejecutar(self):
        """Ejecuta la verificación para todos los símbolos y modos."""
        print("=" * 100)
        print(f"{Fore.CYAN}🚀 VERIFICACIÓN DE SL/TP PARA TODOS LOS MODOS DEL SNIPER{Style.RESET_ALL}")
        print("=" * 100)
        print()
        
        from utils.parametros_simbolo import get_parametros_simbolo
        
        for simbolo in SIMBOLOS:
            precio = PRECIOS_REFERENCIA.get(simbolo, 1.0)
            
            print(f"\n{Fore.YELLOW}📊 {simbolo} (Precio: {precio}){Style.RESET_ALL}")
            
            for modo in MODOS:
                self.total += 1
                
                try:
                    params = get_parametros_simbolo(simbolo)
                    resultado = self.verificar_modo(simbolo, precio, modo)
                    
                    # Mostrar modo
                    compra = resultado['compra']
                    venta = resultado['venta']
                    
                    estado = '✅' if not resultado['errores'] else '❌'
                    
                    print(f"  {estado} {modo:<20} | COMPRA: SL={compra['sl']:.{params['digits']}f} ({compra['sl_dist_pips']:.1f}p) TP={compra['tp']:.{params['digits']}f} R:R={compra['rr']:.2f} | VENTA: SL={venta['sl']:.{params['digits']}f} ({venta['sl_dist_pips']:.1f}p) TP={venta['tp']:.{params['digits']}f} R:R={venta['rr']:.2f}")
                    
                    if resultado['errores']:
                        self.fallados += 1
                        for error in resultado['errores']:
                            print(f"    {Fore.RED}  - {error}{Style.RESET_ALL}")
                            self.errores_detalle.append(f"{simbolo} {modo}: {error}")
                    else:
                        self.pasados += 1
                    
                    self.resultados.append(resultado)
                    
                except Exception as e:
                    self.fallados += 1
                    print(f"  {Fore.RED}❌ {modo}: ERROR - {e}{Style.RESET_ALL}")
                    self.errores_detalle.append(f"{simbolo} {modo}: Error - {e}")
        
        # Resumen
        print("\n" + "=" * 100)
        print(f"{Fore.CYAN}📊 RESUMEN DE VERIFICACIÓN{Style.RESET_ALL}")
        print("=" * 100)
        print(f"Total: {self.total}")
        print(f"{Fore.GREEN}✅ Correctos: {self.pasados}{Style.RESET_ALL}")
        print(f"{Fore.RED}❌ Con errores: {self.fallados}{Style.RESET_ALL}")
        print("=" * 100)
        
        # Mostrar errores
        if self.errores_detalle:
            print(f"\n{Fore.YELLOW}📋 DETALLE DE ERRORES:{Style.RESET_ALL}")
            print("-" * 100)
            for error in self.errores_detalle[:30]:  # Mostrar primeros 30
                print(f"  {Fore.RED}❌ {error}{Style.RESET_ALL}")
            print("-" * 100)


# ============================================================
# EJECUCIÓN PRINCIPAL
# ============================================================

if __name__ == "__main__":
    verificador = VerificadorModosSniper()
    verificador.ejecutar()