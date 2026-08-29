#!/usr/bin/env python3
"""
verificar_sl_tp.py (V1.0)
Verifica el cálculo de SL/TP para TODOS los símbolos.
Prueba en COMPRA y VENTA para detectar errores.
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
# SÍMBOLOS A VERIFICAR
# ============================================================

SIMBOLOS = [
    'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF',
    'EURJPY', 'GBPJPY', 'AUDJPY', 'XAUUSD', 'XAGUSD',
    'US30', 'NAS100', 'US500', 'BTCUSD', 'ETHUSD', 'SOLUSD'
]

# ============================================================
# PRECIOS DE REFERENCIA (basados en datos reales del broker)
# ============================================================

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

class VerificadorSLTP:
    """Verifica SL/TP para todos los símbolos."""
    
    def __init__(self):
        self.resultados = []
        self.total = 0
        self.pasados = 0
        self.fallados = 0
    
    def verificar(self, simbolo: str, precio: float) -> dict:
        """Verifica SL/TP para un símbolo."""
        from trading.sniper.sniper_checklist import SniperChecklist
        from trading.stops import GestorStops
        from utils.parametros_simbolo import get_parametros_simbolo
        
        # Obtener parámetros del símbolo
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
        
        # Verificar COMPRA
        sl_compra, tp_compra, rr_compra = checklist._calcular_sl_tp_estructura(
            simbolo=simbolo,
            precio_actual=precio,
            direccion='COMPRA',
            modo='RETEST',
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
            modo='RETEST',
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
        
        # Verificar SL mínimo
        sl_min = checklist._obtener_sl_minimo_universal(simbolo)
        sl_max = checklist._obtener_sl_maximo_universal(simbolo)
        
        sl_dist_compra = abs(precio - sl_compra) / pip_val if pip_val > 0 else 0
        sl_dist_venta = abs(precio - sl_venta) / pip_val if pip_val > 0 else 0
        
        if sl_dist_compra < sl_min:
            errores.append(f"COMPRA: SL {sl_dist_compra:.1f} pips < mínimo {sl_min} pips")
        if sl_dist_venta < sl_min:
            errores.append(f"VENTA: SL {sl_dist_venta:.1f} pips < mínimo {sl_min} pips")
        
        if sl_dist_compra > sl_max:
            errores.append(f"COMPRA: SL {sl_dist_compra:.1f} pips > máximo {sl_max} pips")
        if sl_dist_venta > sl_max:
            errores.append(f"VENTA: SL {sl_dist_venta:.1f} pips > máximo {sl_max} pips")
        
        return {
            'simbolo': simbolo,
            'precio': precio,
            'pip_val': pip_val,
            'digits': digits,
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
        """Ejecuta la verificación para todos los símbolos."""
        print("=" * 80)
        print(f"{Fore.CYAN}🚀 VERIFICACIÓN DE SL/TP PARA TODOS LOS SÍMBOLOS{Style.RESET_ALL}")
        print("=" * 80)
        print()
        
        from utils.parametros_simbolo import get_parametros_simbolo
        
        for simbolo in SIMBOLOS:
            precio = PRECIOS_REFERENCIA.get(simbolo, 1.0)
            self.total += 1
            
            print(f"\n{Fore.YELLOW}📊 {simbolo} (Precio: {precio}){Style.RESET_ALL}")
            
            try:
                params = get_parametros_simbolo(simbolo)
                resultado = self.verificar(simbolo, precio)
                
                # Mostrar parámetros
                print(f"  {Fore.CYAN}Parámetros: digits={params['digits']}, pip_val={params['pip_val']}{Style.RESET_ALL}")
                print(f"  {Fore.CYAN}SL mínimo: {resultado['sl_min']} pips, SL máximo: {resultado['sl_max']} pips{Style.RESET_ALL}")
                
                # Mostrar COMPRA
                compra = resultado['compra']
                print(f"  {Fore.GREEN}COMPRA:{Style.RESET_ALL}")
                print(f"    Entry: {precio:.{params['digits']}f}")
                print(f"    SL: {compra['sl']:.{params['digits']}f} ({compra['sl_dist_pips']:.1f} pips)")
                print(f"    TP: {compra['tp']:.{params['digits']}f}")
                print(f"    R:R: {compra['rr']:.2f}")
                
                # Mostrar VENTA
                venta = resultado['venta']
                print(f"  {Fore.RED}VENTA:{Style.RESET_ALL}")
                print(f"    Entry: {precio:.{params['digits']}f}")
                print(f"    SL: {venta['sl']:.{params['digits']}f} ({venta['sl_dist_pips']:.1f} pips)")
                print(f"    TP: {venta['tp']:.{params['digits']}f}")
                print(f"    R:R: {venta['rr']:.2f}")
                
                # Mostrar errores
                if resultado['errores']:
                    self.fallados += 1
                    print(f"  {Fore.RED}❌ ERRORES:{Style.RESET_ALL}")
                    for error in resultado['errores']:
                        print(f"    {Fore.RED}  - {error}{Style.RESET_ALL}")
                else:
                    self.pasados += 1
                    print(f"  {Fore.GREEN}✅ CORRECTO{Style.RESET_ALL}")
                
                self.resultados.append(resultado)
                
            except Exception as e:
                self.fallados += 1
                print(f"  {Fore.RED}❌ ERROR: {e}{Style.RESET_ALL}")
                self.resultados.append({
                    'simbolo': simbolo,
                    'errores': [f"Error: {e}"]
                })
        
        # Resumen
        print("\n" + "=" * 80)
        print(f"{Fore.CYAN}📊 RESUMEN DE VERIFICACIÓN{Style.RESET_ALL}")
        print("=" * 80)
        print(f"Total: {self.total}")
        print(f"{Fore.GREEN}✅ Correctos: {self.pasados}{Style.RESET_ALL}")
        print(f"{Fore.RED}❌ Con errores: {self.fallados}{Style.RESET_ALL}")
        print("=" * 80)
        
        # Mostrar tabla resumen
        print("\n📋 TABLA RESUMEN:")
        print(f"{'Símbolo':<10} {'Pip_Val':<10} {'SL_Min':<10} {'SL_Max':<10} {'SL_Compra':<12} {'SL_Venta':<12} {'Estado':<10}")
        print("-" * 75)
        
        for r in self.resultados:
            simbolo = r.get('simbolo', '?')
            pip_val = r.get('pip_val', '?')
            sl_min = r.get('sl_min', '?')
            sl_max = r.get('sl_max', '?')
            
            if 'compra' in r:
                sl_c = f"{r['compra']['sl']:.{r['digits']}f}"
                sl_v = f"{r['venta']['sl']:.{r['digits']}f}"
            else:
                sl_c = '?'
                sl_v = '?'
            
            estado = '✅' if not r.get('errores') else '❌'
            
            print(f"{simbolo:<10} {pip_val:<10} {sl_min:<10} {sl_max:<10} {sl_c:<12} {sl_v:<12} {estado:<10}")
        
        print("=" * 75)


# ============================================================
# EJECUCIÓN PRINCIPAL
# ============================================================

if __name__ == "__main__":
    verificador = VerificadorSLTP()
    verificador.ejecutar()