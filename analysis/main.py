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

    required_keys = ['engagements', 'breaks', 'info'] 
    if not all(os.path.exists(PATHS[key]) for key in required_keys):
        print("[!] Erro: Arquivos CSV de entrada não encontrados.")
        return

    print(">> Calculando métricas de WFM e aplicando regras de jornada...")
    
    df_info_raw = cleaner.process_info(PATHS['info'])
    df_eng_raw = cleaner.clean_engagements(PATHS['engagements'])
    df_brk_formatted = cleaner.format_breaks_dates(PATHS['breaks'])

    if not df_eng_raw.empty:
        target_date_str = str(df_eng_raw['Data'].iloc[0])
    elif not df_brk_formatted.empty:
        target_date_str = df_brk_formatted['inicio_dt'].iloc[0].strftime("%d/%m/%Y")
    else:
        target_date_str = current_time.strftime("%d/%m/%Y")

    target_date_obj = datetime.strptime(target_date_str, "%d/%m/%Y")
    file_date_str = target_date_obj.strftime("%d-%m-%y")
    
    PATHS['excel_out'] = os.path.join(
        PATHS.get('excel_out_dir', ''), 
        f"relatório-{file_date_str}.xlsx"
    )

    df_eng, df_brk_filtered, df_info_dynamic = cleaner.apply_shift_rules(
        df_eng_raw, df_brk_formatted, df_info_raw
    )

    # Fecha as pausas de acordo com a jornada real do dia
    df_brk = cleaner.close_breaks(df_brk_filtered, df_info_dynamic, df_eng)

    df_database = metrics_engine.get_metrics(df_eng, df_brk, df_info_dynamic, target_date_str)

    df_timeline = timeline_gen.get_timeline(df_eng, df_brk)

    if not df_database.empty:
        df_database['% ENGANOS'] = (df_database['ENGANOS'] / df_database['ACIONAMENTOS'] * 100).fillna(0).astype(int).astype(str) + "%"
        df_database['% CONVERSÃO'] = (df_database['PROPOSTAS POSITIVAS'] / df_database['PROPOSTAS'] * 100).fillna(0).astype(int).astype(str) + "%"
        df_database['EQUIPE'] = df_database['EQUIPE_INFO']

        export_to_bi(df_database, df_timeline, PATHS, BI_COL_ORDER)

        time_columns = ['TEMPO EM LIGAÇÃO', 'TEMPO NÃO TABELADO', 'TEMPO DE OCIOSIDADE', 'ALMOÇO', 'BANHEIRO', 'TEMPO EM PAUSA']
        for col in time_columns: 
            raw_col_name = f"{col if 'TOTAL' not in col else 'TEMPO EM PAUSA'}_raw"
            if raw_col_name in df_database.columns:
                df_database[col] = df_database[raw_col_name].apply(format_to_ms)
        
        def construct_avatar_url(drive_id):
            if drive_id:
                return f"https://drive.google.com/uc?export=view&id={drive_id}"
            return "https://ui-avatars.com/api/?name=User&format=png"
            
        df_database['FOTO_URL'] = df_database['DRIVE_ID'].apply(construct_avatar_url)
        df_database['OBSERVAÇÕES'] = ""

        export_to_excel(df_database, PATHS, EXCEL_COL_ORDER)
        print(f"OK: Relatório Excel gerado em: {PATHS['excel_out']}")
    else:
        print("[!] Aviso: Dados insuficientes para gerar os relatórios. O processo foi abortado.")

if __name__ == "__main__":
    main()