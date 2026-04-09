import pandas as pd
import os

def export_to_bi(df: pd.DataFrame, paths: dict, col_order: list):
    """Gera um arquivo plano ordenado e projetado para o Power BI."""
    df_bi = df.copy()
    
    cols_to_drop = ['EQUIPE_INFO', 'DRIVE_ID']
    df_bi.drop(columns=[c for c in cols_to_drop if c in df_bi.columns], inplace=True, errors='ignore')
    
    available_columns = [col for col in col_order if col in df_bi.columns]
    df_bi = df_bi[available_columns]
    
    df_bi.to_csv(paths['bi_out'], index=False, encoding='utf-8-sig', sep=';', decimal=',')
    print(f"OK: Base de dados Power BI exportada em: {paths['bi_out']}")