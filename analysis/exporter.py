import pandas as pd
from utils import fetch_avatar

def export_reports(df: pd.DataFrame, paths: dict, col_order: list):
    """Exporta para Excel (com e sem imagens) com cabeçalho fixo e sem gaps."""
    
    def save_excel(path, with_images):
        df_temp = df.copy()
        
        if not with_images: 
            df_temp['FOTO'] = '=IMAGE("' + df_temp['FOTO_URL'] + '")'
        else: 
            df_temp['FOTO'] = ""
            
        df_out = df_temp[col_order]

        with pd.ExcelWriter(path, engine='xlsxwriter') as writer:
            df_out.to_excel(writer, sheet_name='Relatório', index=False, header=False, startrow=1)
            
            wb, ws = writer.book, writer.sheets['Relatório']
            
            fmt = wb.add_format({'align': 'center', 'valign': 'vcenter'})
            h_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'text_wrap': True, 'bold': True, 'bottom': 1, 'bg_color': '#F2F2F2'})
            
            ws.set_row(0, 40)
            
            ws.freeze_panes(1, 0)
            
            for i, col in enumerate(df_out.columns):
                ws.write(0, i, col, h_fmt)
                
                w = 14 if col == 'FOTO' else (12 if col == '% CONVERSÃO' else (7 if col == 'CPC' else (25 if col == 'OBSERVAÇÕES' else (20 if col == 'CONSULTOR' else max(min(df_out[col].astype(str).str.len().max() + 2, 16), (len(col) // 2) + 5, 11)))))
                ws.set_column(i, i, w, fmt)
                
            for row_idx, row in enumerate(df_temp.itertuples(), start=1):
                ws.set_row(row_idx, 80 if with_images else 60)
                if with_images and "ui-avatars" not in str(row.FOTO_URL) and row.FOTO_URL:
                    try:
                        img_bytes = fetch_avatar(row.FOTO_URL)
                        ws.insert_image(row_idx, 2, 'foto.png', {'image_data': img_bytes, 'object_position': 1, 'x_offset': 4, 'y_offset': 11})
                    except: pass

    save_excel(paths['sheets_out'], False)
    save_excel(paths['excel_out'], True)