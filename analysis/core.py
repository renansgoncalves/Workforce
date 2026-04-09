import pandas as pd
import numpy as np
from datetime import datetime
from config import STATUS_PROD, STATUS_NEG, STATUS_POS, CPC_IGNORE, MAX_IDLE_GAP_SECONDS, SECONDS_IN_MINUTE, SECONDS_IN_DAY
from utils import time_str_to_minutes

class WFMProcessor:
    
    # --- 1. INICIALIZAÇÃO ---
    def __init__(self):
        self.now = datetime.now()

    # --- 2. TRATAMENTO DE CADASTRO ---
    def process_info(self, path: str) -> pd.DataFrame:
        try:
            df = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig')
            df.columns = df.columns.str.strip().str.upper()
            
            def get_col(cols: list, default: str = '') -> pd.Series:
                return next((df[c].astype(str).str.strip().replace('nan', '') for c in cols if c in df.columns), pd.Series(default, index=df.index))
            
            return pd.DataFrame({
                'CONSULTOR': get_col(['NOME', 'CONSULTOR']).str.upper(),
                'DRIVE_ID': get_col(['ID_DRIVE', 'ID DRIVE', 'FOTO']),
                'EQUIPE_INFO': get_col(['EQUIPE']),
                'ENTRADA': get_col(['ENTRADA']),
                'SAIDA': get_col(['SAÍDA', 'SAIDA']),
                'CARGA_HORARIA_RAW': get_col(['CARGA HORÁRIA', 'CARGA HORARIA'])
            })
        except Exception:
            return pd.DataFrame()

    # --- 3. LIMPEZA DE LIGAÇÕES ---
    def clean_engagements(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path, sep=';', encoding='utf-8').drop_duplicates()
        
        df.columns = df.columns.str.strip().str.replace(' ', '_')
            
        df['Data_Hora_Str'] = df['Data'].astype(str) + " " + df['Inicio_Contato'].astype(str)
        
        df['Atendente'] = df['Atendente'].astype(str).str.split('_').str[0].str.strip().str.upper()
        df = df[~df['Atendente'].isin(['ABANDONADA', 'NONE'])]
        df['Status'] = df.get('Status', pd.Series([''] * len(df))).fillna('')
        
        df['Hora_dt'] = pd.to_datetime(df['Data_Hora_Str'].str.replace('"', ''), dayfirst=True, errors='coerce')
        
        end_time = pd.to_datetime(df['Fim_Contato'], format='%H:%M:%S', errors='coerce')
        start_time = pd.to_datetime(df['Inicio_Contato'], format='%H:%M:%S', errors='coerce')
        
        df['Tempo'] = (end_time - start_time).dt.total_seconds().fillna(0.0)
        df['Tempo'] = np.where(df['Tempo'] < 0.0, df['Tempo'] + SECONDS_IN_DAY, df['Tempo'])
        df['Hora_fim_dt'] = df['Hora_dt'] + pd.to_timedelta(df['Tempo'], unit='s')
        
        return df.drop_duplicates(subset=['Atendente', 'Hora_dt'])

    # --- 4. SANITIZAÇÃO DE PAUSAS ---
    def clean_breaks(self, path: str, df_info: pd.DataFrame) -> pd.DataFrame:
        df = pd.read_csv(path, sep=';', encoding='utf-8').drop_duplicates()
        df['OPERADOR'] = df['OPERADOR'].astype(str).str.split('_').str[0].str.strip().str.upper()
        df['inicio_dt'] = pd.to_datetime(df['Data_INICIO'] + ' ' + df['INICIO_PAUSA'], dayfirst=True, errors='coerce')
        df['fim_dt'] = pd.to_datetime(df['DATA_FIM'] + ' ' + df['FINAL_PAUSA'], dayfirst=True, errors='coerce')
        
        exit_map = df_info.set_index('CONSULTOR')['SAIDA'].to_dict()
        
        def sanitize_break(row):
            start_dt = row['inicio_dt']
            
            if pd.notnull(row['fim_dt']) and row['fim_dt'] >= start_dt:
                return row['fim_dt'] 
                
            # Protocolo de sanitização para pausas esquecidas abertas
            exit_str = str(exit_map.get(row['OPERADOR'], "")).strip()
            if exit_str and ":" in exit_str:
                try:
                    exit_dt = pd.to_datetime(f"{start_dt.strftime('%Y-%m-%d')} {exit_str}")
                    if exit_dt > start_dt:
                        return exit_dt 
                except Exception:
                    pass
            return self.now if start_dt.date() == self.now.date() else start_dt

        df['fim_dt'] = df.apply(sanitize_break, axis=1)
        subset_cols = ['OPERADOR', 'inicio_dt', 'PAUSA'] if 'PAUSA' in df.columns else ['OPERADOR', 'inicio_dt']
        return df.drop_duplicates(subset=subset_cols)

    # --- 5. ALGORITMO DE OCIOSIDADE ---
    def calc_idleness(self, calls: list, breaks: list) -> float:
        if len(calls) < 2:
            return 0.0
            
        calls.sort(key=lambda x: x[0])
        idle_seconds = 0.0
        
        for (curr_start, curr_end), (next_start, next_end) in zip(calls, calls[1:]):
            gap = (next_start - curr_end).total_seconds()
            
            if 0.0 < gap <= MAX_IDLE_GAP_SECONDS:
                if not any(max(curr_end, break_start) < min(next_start, break_end) for break_start, break_end in breaks):
                    idle_seconds += gap 
                    
        return idle_seconds / SECONDS_IN_MINUTE

    # --- 6. MOTOR DE AGREGAÇÃO DE MÉTRICAS ---
    def get_metrics(self, df_eng: pd.DataFrame, df_brk: pd.DataFrame, df_info: pd.DataFrame) -> pd.DataFrame:
        
        def aggregate_engagements(group):
            status_col = group['Status']
            productive = group[status_col.isin(STATUS_PROD)]
            
            cpc_calls = productive[~productive['Status'].isin(CPC_IGNORE)]
            cpc_count = len(cpc_calls)
            
            cpc_total_minutes = cpc_calls['Tempo'].sum() / SECONDS_IN_MINUTE
            avg_cpc_time = cpc_total_minutes / cpc_count if cpc_count > 0 else 0.0
            
            return pd.Series({
                'DATA': str(group['Data'].iloc[0]),
                'NÚMERO DE ACIONAMENTOS': len(group),
                'ACIONAMENTOS PRODUTIVOS': len(productive),
                'TEMPO EM LIGAÇÃO_raw': group['Tempo'].sum() / SECONDS_IN_MINUTE,
                'CPC': cpc_count,
                'MEDIA_TEMPO_CPC_raw': avg_cpc_time,
                'AGENTE NÃO TABULOU': (status_col == "Agente Nao Tabulou").sum(),
                'ENGANO': (status_col == "ENGANO").sum(),
                'PROPOSTAS': status_col.isin(STATUS_NEG | STATUS_POS).sum(),
                'STATUS NEGATIVOS': status_col.isin(STATUS_NEG).sum(),
                'STATUS POSITIVOS': status_col.isin(STATUS_POS).sum(),
                'VENDA FEITA': (status_col == "VENDA_FEITA").sum(),
                'SEM POSSIBILIDADE': (status_col == "SEM_POSSIBILIDADES").sum(),
                'SEM MARGEM': (status_col == "SEM_MARGEM").sum(),
                'SEM PORT': (status_col == "SEM_PORT").sum()
            })
            
        rep_eng = df_eng.groupby('Atendente').apply(aggregate_engagements, include_groups=False).reset_index().rename(columns={'Atendente': 'CONSULTOR'})

        def aggregate_breaks(group):
            total_pause, lunch, bathroom, num_breaks = 0.0, 0.0, 0.0, 0
            for row in group.itertuples():
                break_type = str(row.PAUSA).upper()
                duration_minutes = (row.fim_dt - row.inicio_dt).total_seconds() / SECONDS_IN_MINUTE
                
                if any(k in break_type for k in ["ALMOCO", "LANCHE", "REFEICAO"]):
                    lunch += duration_minutes
                else:
                    total_pause += duration_minutes
                    num_breaks += 1
                    if "BANHEIRO" in break_type:
                        bathroom += duration_minutes
                        
            return pd.Series({
                'NÚMERO DE PAUSAS': num_breaks, 
                'TEMPO TOTAL DE PAUSA_raw': total_pause, 
                'ALMOÇO_raw': lunch, 
                'BANHEIRO_raw': bathroom
            })
            
        rep_brk = df_brk.groupby('OPERADOR').apply(aggregate_breaks, include_groups=False).reset_index().rename(columns={'OPERADOR': 'CONSULTOR'})

        df = rep_eng.merge(rep_brk, on='CONSULTOR', how='left').fillna(0.0).merge(df_info, on='CONSULTOR', how='left').fillna('')
        
        calls_map = df_eng.groupby('Atendente').apply(lambda g: list(zip(g['Hora_dt'], g['Hora_fim_dt']))).to_dict()
        breaks_map = df_brk.groupby('OPERADOR').apply(lambda g: list(zip(g['inicio_dt'], g['fim_dt']))).to_dict()
        df['TEMPO DE OCIOSIDADE_raw'] = df['CONSULTOR'].apply(lambda c: self.calc_idleness(calls_map.get(c, []), breaks_map.get(c, [])))

        def calc_untracked(row):
            workload = time_str_to_minutes(row.get('CARGA_HORARIA_RAW'))
            entry_time = time_str_to_minutes(row.get('ENTRADA'))
            exit_time = time_str_to_minutes(row.get('SAIDA'))
            
            if not workload:
                return 0.0
                
            total_pauses = row.get('TEMPO TOTAL DE PAUSA_raw', 0.0) + row.get('ALMOÇO_raw', 0.0)
            expected_exit = exit_time if exit_time else entry_time + workload
            current_minutes = self.now.hour * SECONDS_IN_MINUTE + self.now.minute
            
            is_past_date = pd.to_datetime(row.get('DATA', ''), dayfirst=True).date() < self.now.date()
            base_time = workload if is_past_date or current_minutes >= expected_exit else max(0.0, current_minutes - entry_time)
            
            return max(0.0, base_time - (total_pauses + row.get('TEMPO EM LIGAÇÃO_raw', 0.0)))

        df['TEMPO NÃO TABELADO_raw'] = df.apply(calc_untracked, axis=1) - df['TEMPO DE OCIOSIDADE_raw']
        df['TEMPO NÃO TABELADO_raw'] = df['TEMPO NÃO TABELADO_raw'].clip(lower=0.0)
        
        return df