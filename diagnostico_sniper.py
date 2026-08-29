# scripts/diagnostico_sniper.py

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

def diagnosticar():
    """Diagnostica qué módulos del sniper se están usando."""
    
    print("🔍 DIAGNÓSTICO DEL SNIPER")
    print("=" * 50)
    
    # 1. Verificar imports
    try:
        from trading.sniper import SniperChecklist
        print("✅ SniperChecklist importado correctamente")
    except ImportError as e:
        print(f"❌ Error importando SniperChecklist: {e}")
        return
    
    # 2. Verificar submódulos
    try:
        from trading.sniper import SniperValidador
        print("✅ SniperValidador disponible")
    except ImportError:
        print("❌ SniperValidador NO disponible")
    
    try:
        from trading.sniper import DetectorModos
        print("✅ DetectorModos disponible")
    except ImportError:
        print("❌ DetectorModos NO disponible")
    
    try:
        from trading.sniper import CalculadorSLTP
        print("✅ CalculadorSLTP disponible")
    except ImportError:
        print("❌ CalculadorSLTP NO disponible")
    
    try:
        from trading.sniper import CalculadorScoreSniper
        print("✅ CalculadorScoreSniper disponible")
    except ImportError:
        print("❌ CalculadorScoreSniper NO disponible")
    
    try:
        from trading.sniper import ValidadorCalidad
        print("✅ ValidadorCalidad disponible")
    except ImportError:
        print("❌ ValidadorCalidad NO disponible")
    
    print("=" * 50)
    
    # 3. Verificar la función evaluar_sniper_optimizado
    try:
        import inspect
        from trading.sniper import SniperChecklist
        source = inspect.getsource(SniperChecklist.evaluar_sniper_optimizado)
        
        # Verificar si usa detector_modos
        if 'detector_modos.detectar' in source:
            print("✅ evaluar_sniper_optimizado usa detector_modos REAL")
        else:
            print("❌ evaluar_sniper_optimizado NO usa detector_modos REAL")
        
        # Verificar si usa calculador_score
        if 'calculador_score.calcular_score_m5' in source:
            print("✅ evaluar_sniper_optimizado usa calculador_score REAL")
        else:
            print("❌ evaluar_sniper_optimizado NO usa calculador_score REAL")
        
        # Verificar si usa calculador_sltp
        if 'calculador_sltp.calcular' in source:
            print("✅ evaluar_sniper_optimizado usa calculador_sltp REAL")
        else:
            print("❌ evaluar_sniper_optimizado NO usa calculador_sltp REAL")
            
    except Exception as e:
        print(f"❌ Error inspeccionando: {e}")
    
    print("=" * 50)

if __name__ == "__main__":
    diagnosticar()