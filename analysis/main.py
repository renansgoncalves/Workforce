import os
# Adicionado BI_COL_ORDER aqui
from config import PATHS, EXCEL_COL_ORDER, BI_COL_ORDER 
from core import WFMProcessor
from excel_exporter import export_to_excel
from bi_exporter import export_to_bi
from utils import format_to_ms
import time

def main():
    required_keys = ['engagements', 'breaks', 'consultores_info']
    if not all(os.path.exists(PATHS[key]) for key in required_keys):
        print("[!] Erro: Arquivos CSV de entrada não encontrados.")
        return

    print(">> Calculando métricas de WFM...")
    wfm = WFMProcessor()
    
    df_info = wfm.process_info(PATHS['consultores_info'])
    df_eng = wfm.clean_engagements(PATHS['engagements'])
    df_brk = wfm.clean_breaks(PATHS['breaks'], df_info)

    df = wfm.get_metrics(df_eng, df_brk, df_info)

    df['% ENGANO'] = (df['ENGANO'] / df['NÚMERO DE ACIONAMENTOS'] * 100).fillna(0).astype(int).astype(str) + "%"
    df['% CONVERSÃO'] = (df['STATUS POSITIVOS'] / df['PROPOSTAS'] * 100).fillna(0).astype(int).astype(str) + "%"
    df['EQUIPE'] = df['EQUIPE_INFO']

    export_to_bi(df, PATHS, BI_COL_ORDER)

    time_columns = ['TEMPO EM LIGAÇÃO', 'TEMPO NÃO TABELADO', 'TEMPO DE OCIOSIDADE', 'ALMOÇO', 'BANHEIRO', 'TEMPO TOTAL DE PAUSA']
    for col in time_columns: 
        raw_col_name = f"{col if 'TOTAL' not in col else 'TEMPO TOTAL DE PAUSA'}_raw"
        df[col] = df[raw_col_name].apply(format_to_ms)
    
    def construct_avatar_url(drive_id):
        if drive_id:
            return f"https://drive.google.com/uc?export=view&id={drive_id}"
        return "https://ui-avatars.com/api/?name=User&format=png"
        
    df['FOTO_URL'] = df['DRIVE_ID'].apply(construct_avatar_url)
    df['OBSERVAÇÕES'] = ""

    export_to_excel(df, PATHS, EXCEL_COL_ORDER)
    print(f"OK: Relatório Excel gerado em: {PATHS['excel_out']}")

if __name__ == "__main__":
    main()