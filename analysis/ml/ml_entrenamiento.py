#!/usr/bin/env python3
"""
analysis/ml/ml_entrenamiento.py (V9.0)
Entrenamiento del modelo ML con Ridge regression.
"""

import logging
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error, r2_score
from typing import Dict, Any, List, Optional

logger = logging.getLogger('BotTrading.ML.Entrenamiento')


class EntrenadorML:
    """
    Entrenador del modelo ML con Ridge regression.
    V9.0 - INDEPENDIENTE.
    """
    
    def __init__(self,
                 pesos_defecto: Dict[str, float],
                 w_min_floor: float = 0.20,
                 bias_max_abs: float = 15.0,
                 max_cambio_peso: float = 0.35,
                 muestras_minimas: int = 30,
                 score_engine: Optional[Any] = None,
                 modo_backtest: bool = False):
        """
        Inicializa el entrenador.
        
        Args:
            pesos_defecto: Pesos por defecto
            w_min_floor: Mínimo peso
            bias_max_abs: Máximo bias
            max_cambio_peso: Máximo cambio de peso
            muestras_minimas: Muestras mínimas para entrenar
            score_engine: ScoreEngine
            modo_backtest: Modo backtest
        """
        self.pesos_defecto = pesos_defecto
        self.w_min_floor = w_min_floor
        self.bias_max_abs = bias_max_abs
        self.max_cambio_peso = max_cambio_peso
        self.muestras_minimas = muestras_minimas
        self.score_engine = score_engine
        self.modo_backtest = modo_backtest
        self.logger = logging.getLogger('BotTrading.ML.Entrenamiento')
    
    def ejecutar(self, datos: List[Dict], pesos_actuales: Dict[str, float],
                 forzado: bool = False) -> Dict[str, Any]:
        """
        Ejecuta el entrenamiento.
        
        Args:
            datos: Datos de entrenamiento
            pesos_actuales: Pesos actuales
            forzado: Forzar entrenamiento
        
        Returns:
            Diccionario con resultados
        """
        if len(datos) < self.muestras_minimas and not forzado:
            return {
                'exito': False,
                'razon': f"Datos insuficientes ({len(datos)}/{self.muestras_minimas})"
            }
        
        # Preparar features
        features = self._preparar_features(datos)
        
        if not features or len(features) < 5:
            return {
                'exito': False,
                'razon': "Features insuficientes"
            }
        
        # Entrenar modelo
        try:
            resultado = self._entrenar_modelo(features, forzado)
        except Exception as e:
            self.logger.error(f"Error entrenando modelo: {e}")
            return {
                'exito': False,
                'razon': f"Error: {e}"
            }
        
        if not resultado['exito']:
            return resultado
        
        # Actualizar pesos
        nuevos_pesos = self._actualizar_pesos(resultado, pesos_actuales)
        
        return {
            'exito': True,
            'pesos': nuevos_pesos,
            'r2_test': resultado.get('r2_test', 0),
            'mse_test': resultado.get('mse_test', 0),
            'n_muestras': len(features),
        }
    
    def _preparar_features(self, datos: List[Dict]) -> pd.DataFrame:
        """Prepara features para entrenamiento."""
        features = []
        
        for op in datos:
            try:
                # Extraer features
                pts_est = float(op.get('pts_estructura', 50))
                pts_mom = float(op.get('pts_momentum', 50))
                pts_conf = float(op.get('pts_confluencia', 50))
                pts_inst = float(op.get('pts_institucional', 50))
                
                # Dirección
                direccion = op.get('direccion', 'COMPRA')
                is_buy = 1 if direccion in ['COMPRA', 'BUY'] else 0
                is_sell = 1 if direccion in ['VENTA', 'SELL'] else 0
                
                # Ganancia neta
                ganancia = float(op.get('ganancia_neta', 0))
                
                # Modificador noticias
                mod_noticias = float(op.get('modificador_noticias', 0)) / 20.0
                sent_cot = float(op.get('sent_cot', 0))
                
                features.append({
                    'pts_estructura': pts_est,
                    'pts_momentum': pts_mom,
                    'pts_confluencia': pts_conf,
                    'pts_institucional': pts_inst,
                    'is_buy': is_buy,
                    'is_sell': is_sell,
                    'mod_noticias': mod_noticias,
                    'sent_cot': sent_cot,
                    'ganancia_neta': ganancia,
                })
            except Exception:
                continue
        
        if not features:
            return pd.DataFrame()
        
        df = pd.DataFrame(features)
        
        # Calcular capas
        df['capa_tecnica'] = (df['pts_estructura'] * 0.35 + 
                              df['pts_momentum'] * 0.30 + 
                              df['pts_confluencia'] * 0.20 + 
                              df['pts_institucional'] * 0.15)
        
        df['capa_institucional'] = df['pts_institucional']
        df['capa_fundamental'] = 50.0 + (df['mod_noticias'] * 25.0) + (df['sent_cot'] * 25.0)
        df['capa_fundamental'] = df['capa_fundamental'].clip(0, 100)
        
        # Ajustar ganancia (penalizar pérdidas)
        df['ganancia_ajustada'] = df['ganancia_neta'].apply(
            lambda x: x if x >= 0 else x * 2.0
        )
        
        return df
    
    def _entrenar_modelo(self, df: pd.DataFrame, forzado: bool) -> Dict[str, Any]:
        """Entrena el modelo Ridge."""
        # Features y target
        features = ['capa_tecnica', 'capa_institucional', 'capa_fundamental', 'is_buy', 'is_sell']
        X = df[features]
        y = df['ganancia_ajustada']
        
        if len(X) < 5:
            return {'exito': False, 'razon': "Datos insuficientes"}
        
        # División train/test
        train_size = int(len(X) * 0.8)
        if train_size < 3:
            train_size = max(3, len(X) - 2)
        
        X_train, X_test = X.iloc[:train_size], X.iloc[train_size:]
        y_train, y_test = y.iloc[:train_size], y.iloc[train_size:]
        
        # Ponderación exponencial
        n = len(X_train)
        decay = 0.99
        sample_weights = np.array([decay ** (n - i) for i in range(n)])
        sample_weights = sample_weights / sample_weights.sum() * n
        
        # Selección de alpha
        alphas = [0.01, 0.1, 1.0, 10.0, 100.0, 500.0]
        best_alpha = alphas[0]
        best_score = -float('inf')
        
        try:
            n_splits = min(3, max(2, len(X_train) - 1))
            tscv = TimeSeriesSplit(n_splits=n_splits)
            
            for alpha in alphas:
                fold_scores = []
                for train_idx, val_idx in tscv.split(X_train):
                    X_t, X_v = X_train.iloc[train_idx], X_train.iloc[val_idx]
                    y_t, y_v = y_train.iloc[train_idx], y_train.iloc[val_idx]
                    w_t = sample_weights[train_idx]
                    
                    try:
                        model = Ridge(alpha=alpha)
                        model.fit(X_t, y_t, sample_weight=w_t)
                        y_pred = model.predict(X_v)
                        fold_scores.append(r2_score(y_v, y_pred))
                    except Exception:
                        fold_scores.append(0.0)
                
                mean_score = float(np.mean(fold_scores)) if fold_scores else 0.0
                if mean_score > best_score:
                    best_score = mean_score
                    best_alpha = alpha
        except Exception as e:
            self.logger.debug(f"Error en validación: {e}")
        
        # Entrenar modelo final
        model = Ridge(alpha=best_alpha)
        try:
            model.fit(X_train, y_train, sample_weight=sample_weights)
        except Exception:
            try:
                model.fit(X_train, y_train)
            except Exception as e:
                return {'exito': False, 'razon': f"Error en fit: {e}"}
        
        # Validación en test
        y_pred_test = model.predict(X_test)
        r2_test = float(r2_score(y_test, y_pred_test)) if len(y_test) > 0 else -1.0
        
        if r2_test < 0.05 and not forzado:
            return {
                'exito': False,
                'razon': f"R2 insuficiente: {r2_test:.4f}",
                'r2_test': r2_test
            }
        
        return {
            'exito': True,
            'modelo': model,
            'r2_train': best_score,
            'r2_test': r2_test,
            'mse_test': float(mean_squared_error(y_test, y_pred_test)) if len(y_test) > 0 else 0,
            'coefs': model.coef_,
            'intercept': model.intercept_,
            'alpha': best_alpha,
        }
    
    def _actualizar_pesos(self, resultado: Dict, pesos_actuales: Dict) -> Dict[str, float]:
        """Actualiza pesos con amortiguación."""
        coefs = resultado['coefs']
        
        nuevos_pesos = self.pesos_defecto.copy()
        nuevos_pesos['w_tecnica'] = max(self.w_min_floor, float(coefs[0]))
        nuevos_pesos['w_institucional'] = max(self.w_min_floor, float(coefs[1]))
        nuevos_pesos['w_fundamental'] = max(self.w_min_floor, float(coefs[2]))
        nuevos_pesos['bias_compra'] = np.clip(float(coefs[3]), -self.bias_max_abs, self.bias_max_abs)
        nuevos_pesos['bias_venta'] = np.clip(float(coefs[4]), -self.bias_max_abs, self.bias_max_abs)
        nuevos_pesos['bias'] = np.clip(float(resultado['intercept']), -self.bias_max_abs, self.bias_max_abs)
        
        # Amortiguación
        pesos_amortiguados = {}
        for clave, valor_nuevo in nuevos_pesos.items():
            valor_anterior = float(pesos_actuales.get(clave, valor_nuevo))
            if valor_anterior == 0.0:
                pesos_amortiguados[clave] = valor_nuevo
                continue
            
            cambio_max = abs(valor_anterior) * self.max_cambio_peso
            limite_inf = valor_anterior - cambio_max
            limite_sup = valor_anterior + cambio_max
            pesos_amortiguados[clave] = float(np.clip(valor_nuevo, limite_inf, limite_sup))
        
        return pesos_amortiguados