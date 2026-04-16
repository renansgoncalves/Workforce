import os
from datetime import datetime
from config import PATHS, EXCEL_COL_ORDER, BI_COL_ORDER 
from excel_exporter import export_to_excel
from bi_exporter import export_to_bi
from utils import format_to_ms

from engine.cleaners import DataCleaner
from engine.metrics import MetricsEngine
from engine.timeline import TimelineGenerator

def main():
    current_time = datetime.now()
    
    cleaner = DataCleaner(current_time)
    metrics_engine = MetricsEngine(current_time)
    timeline_gen = TimelineGenerator()

    required_keys = ['engagements', 'breaks', 'consultores_info'] 
    if not all(os.path.exists(PATHS[key]) for key in required_keys):
        print("[!] Erro: Arquivos CSV de entrada não encontrados.")
        return

    print(">> Calculando métricas de WFM...")
    
    # --- FASE 1: LIMPEZA ---
    df_info = cleaner.process_info(PATHS['consultores_info'])
    df_eng = cleaner.clean_engagements(PATHS['engagements'])
    
    df_brk = cleaner.clean_breaks(PATHS['breaks'], df_info, df_eng)

    if not df_eng.empty:
        target_date_str = str(df_eng['Data'].iloc[0])
    elif not df_brk.empty:
        target_date_str = df_brk['inicio_dt'].iloc[0].strftime("%d/%m/%Y")
    else:
        target_date_str = current_time.strftime("%d/%m/%Y")

    # --- FASE 2: CÁLCULOS ---
    df_database = metrics_engine.get_metrics(df_eng, df_brk, df_info, target_date_str)

    # --- FASE 3: TIMELINE ---
    df_timeline = timeline_gen.get_timeline(df_eng, df_brk)

    # --- FASE 4: FORMATAÇÕES FINAIS E EXPORTAÇÃO ---
    df_database['% ENGANO'] = (df_database['ENGANO'] / df_database['NÚMERO DE ACIONAMENTOS'] * 100).fillna(0).astype(int).astype(str) + "%"
    df_database['% CONVERSÃO'] = (df_database['STATUS POSITIVOS'] / df_database['PROPOSTAS'] * 100).fillna(0).astype(int).astype(str) + "%"
    df_database['EQUIPE'] = df_database['EQUIPE_INFO']

    export_to_bi(df_database, df_timeline, PATHS, BI_COL_ORDER)

    time_columns = ['TEMPO EM LIGAÇÃO', 'TEMPO NÃO TABELADO', 'TEMPO DE OCIOSIDADE', 'ALMOÇO', 'BANHEIRO', 'TEMPO TOTAL DE PAUSA']
    for col in time_columns: 
        raw_col_name = f"{col if 'TOTAL' not in col else 'TEMPO TOTAL DE PAUSA'}_raw"
        df_database[col] = df_database[raw_col_name].apply(format_to_ms)
    
    def construct_avatar_url(drive_id):
        if drive_id:
            return f"https://drive.google.com/uc?export=view&id={drive_id}"
        return "https://ui-avatars.com/api/?name=User&format=png"
        
    df_database['FOTO_URL'] = df_database['DRIVE_ID'].apply(construct_avatar_url)
    df_database['OBSERVAÇÕES'] = ""

    export_to_excel(df_database, PATHS, EXCEL_COL_ORDER)
    print(f"OK: Relatório Excel gerado em: {PATHS['excel_out']}")

if __name__ == "__main__":
    main()