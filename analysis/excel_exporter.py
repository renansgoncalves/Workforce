import pandas as pd
from utils import fetch_avatar

def export_to_excel(df: pd.DataFrame, paths: dict, col_order: list):
    """Exporta para o Excel com imagens e formatação condicional baseada em regras de negócio."""
    
    df_temp = df.copy()
    df_temp['FOTO'] = ""
        
    available_columns = [col for col in col_order if col in df_temp.columns]
    df_out = df_temp[available_columns]

    excel_path = paths['excel_out']

    with pd.ExcelWriter(excel_path, engine='xlsxwriter') as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet('Relatório')
        
        format_center = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
        format_header = workbook.add_format({
            'align': 'center', 'valign': 'vcenter', 'text_wrap': True, 
            'bold': True, 'bottom': 1, 'bg_color': '#F2F2F2'
        })
        
        # Paleta de formatação condicional
        format_red = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'font_color': '#9C0006', 'bg_color': '#FFC7CE'})
        format_green = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'font_color': '#006100', 'bg_color': '#C6EFCE'})
        
        worksheet.set_row(0, 40)
        worksheet.freeze_panes(1, 0)
        
        # 1. Escreve o cabeçalho
        for i, col in enumerate(df_out.columns):
            worksheet.write(0, i, col, format_header)
            
            col_width = 14 if col == 'FOTO' else (
                12 if col == '% CONVERSÃO' else (
                    7 if col == 'CPC' else (
                        25 if col == 'OBSERVAÇÕES' else (
                            20 if col == 'CONSULTOR' else max(min(df_out[col].astype(str).str.len().max() + 2, 16), (len(col) // 2) + 5, 11)
                        )
                    )
                )
            )
            worksheet.set_column(i, i, col_width, format_center)
            
        # 2. Escreve as células e aplica regras
        for row_idx, (index, row) in enumerate(df_temp.iterrows(), start=1):
            worksheet.set_row(row_idx, 80)
            
            # Inserção de Imagem do Drive
            if "ui-avatars" not in str(row.get('FOTO_URL', '')) and row.get('FOTO_URL'):
                try:
                    img_bytes = fetch_avatar(row['FOTO_URL'])
                    col_index = df_out.columns.get_loc('FOTO')
                    worksheet.insert_image(
                        row_idx, col_index, 'foto.png', 
                        {'image_data': img_bytes, 'object_position': 1, 'x_offset': 4, 'y_offset': 11}
                    )
                except Exception:
                    pass
                    
            # Iteração coluna por coluna
            for col_idx, col_name in enumerate(df_out.columns):
                val = row[col_name]
                if pd.isna(val):
                    val = ""
                    
                cell_fmt = format_center # Estilo neutro padrão
                
                # --- REGRAS DE NEGÓCIO ---
                # A lógica matemática puxa os dados das colunas _raw ou calcula porcentagens reais
                
                if col_name == 'TEMPO NÃO TABELADO':
                    if row.get('TEMPO NÃO TABELADO_raw', 0) > 30.0 or row.get('TEMPO NÃO TABELADO_raw', 0) == 0.0:
                        cell_fmt = format_red
                        
                elif col_name == 'TEMPO DE OCIOSIDADE':
                    if row.get('TEMPO DE OCIOSIDADE_raw', 0) > row.get('TEMPO EM LIGAÇÃO_raw', 0):
                        cell_fmt = format_red
                        
                elif col_name == 'TEMPO EM LIGAÇÃO':
                    if row.get('TEMPO EM LIGAÇÃO_raw', 0) < 60.0:
                        cell_fmt = format_red
                        
                elif col_name == 'TEMPO TOTAL DE PAUSA':
                    if row.get('TEMPO TOTAL DE PAUSA_raw', 0) > 150.0:
                        cell_fmt = format_red
                        
                elif col_name == 'ALMOÇO':
                    if row.get('ALMOÇO_raw', 0) > 65.0: # 1 hora e 05 minutos
                        cell_fmt = format_red
                        
                elif col_name == 'BANHEIRO':
                    if row.get('BANHEIRO_raw', 0) > 10.0:
                        cell_fmt = format_red
                        
                elif col_name == '% CONVERSÃO':
                    props = row.get('PROPOSTAS', 0)
                    pos = row.get('STATUS POSITIVOS', 0)
                    if props > 0 and (pos / props) > 0.5: # Maior que 50%
                        cell_fmt = format_green
                        
                elif col_name == '% ENGANO':
                    ac = row.get('NÚMERO DE ACIONAMENTOS', 0)
                    eng = row.get('ENGANO', 0)
                    if ac > 0 and (eng / ac) > 0.5: # Maior que 50%
                        cell_fmt = format_red
                        
                # 3. Escreve a célula com o valor string visual, mas pintada pela regra matemática
                worksheet.write(row_idx, col_idx, val, cell_fmt)