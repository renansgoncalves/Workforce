import os
from config import PATHS, COL_ORDER
from core import WFMProcessor
from exporter import export_reports
from utils import format_to_ms

def main():
    if not all(os.path.exists(PATHS[k]) for k in ['engagements', 'breaks', 'consultores_info']):
        return print("[!] Erro: Arquivos CSV de entrada não encontrados.")

    print(">> Calculando métricas de WFM...")
    wfm = WFMProcessor()
    
    # 1. Carregamento e limpeza
    df_info = wfm.process_info(PATHS['consultores_info'])
    df_eng = wfm.clean_engagements(PATHS['engagements'])
    df_brk = wfm.clean_breaks(PATHS['breaks'], df_info)

    # 2. Processamento de métricas
    df = wfm.get_metrics(df_eng, df_brk, df_info)

    # 3. Formatações finais
    for col in ['TEMPO EM LIGAÇÃO', 'TEMPO NÃO TABELADO', 'TEMPO DE OCIOSIDADE', 'ALMOÇO', 'BANHEIRO', 'TEMPO TOTAL DE PAUSA']: 
        df[col] = df[f"{col if 'TOTAL' not in col else 'TEMPO TOTAL DE PAUSA'}_raw"].apply(format_to_ms)
    
    df['% ENGANO'] = (df['ENGANO'] / df['ACIONAMENTOS PRODUTIVOS'] * 100).fillna(0).astype(int).astype(str) + "%"
    df['% CONVERSÃO'] = (df['STATUS POSITIVOS'] / df['PROPOSTAS'] * 100).fillna(0).astype(int).astype(str) + "%"
    df['EQUIPE'] = df['EQUIPE_INFO']
    df['FOTO_URL'] = df['DRIVE_ID'].apply(lambda d: f"https://drive.google.com/uc?export=view&id={d}" if d else "https://ui-avatars.com/api/?name=User&format=png")
    df['OBSERVAÇÕES'] = ""

    # 4. Exportação
    export_reports(df, PATHS, COL_ORDER)
    print(f"OK: Sucesso! Relatórios gerados em: {os.path.dirname(PATHS['sheets_out'])}")

if __name__ == "__main__":
    main()