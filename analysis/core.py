import pandas as pd
import numpy as np
from datetime import datetime
from config import STATUS_PROD, STATUS_NEG, STATUS_POS, CPC_IGNORE, MAX_IDLE_GAP_SECONDS, SECONDS_IN_MINUTE, SECONDS_IN_DAY, EVENT_MAPPING, PATHS
from utils import time_str_to_minutes

class WFMProcessor:
    
    # --- 1. INICIALIZAÇÃO ---
    def __init__(self):
        # Trava o relógio no momento da execução para cálculos precisos de tempo em tempo real
        self.now = datetime.now()

    # --- 2. TRATAMENTO DE CADASTRO ---
    def process_info(self, path: str) -> pd.DataFrame:
        try:
            # Leitura flexível para ignorar erros de delimitador e problemas de codificação
            df = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig')
            df.columns = df.columns.str.strip().str.upper()
            
            # Função interna para buscar colunas que podem ter variações de nomenclatura
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
            # Falha silenciosa segura: retorna dataframe vazio caso o arquivo não exista ou esteja corrompido
            return pd.DataFrame()

    # --- 3. LIMPEZA DE LIGAÇÕES ---
    def clean_engagements(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path, sep=';', encoding='utf-8').drop_duplicates()
        df.columns = df.columns.str.strip().str.replace(' ', '_')
            
        df['Data_Hora_Str'] = df['Data'].astype(str) + " " + df['Inicio_Contato'].astype(str)
        
        # Padroniza o nome do atendente, removendo sufixos após o underline
        df['Atendente'] = df['Atendente'].astype(str).str.split('_').str[0].str.strip().str.upper()
        df = df[~df['Atendente'].isin(['ABANDONADA', 'NONE'])]
        df['Status'] = df.get('Status', pd.Series([''] * len(df))).fillna('')
        
        # Conversão de strings temporais para objetos datetime
        df['Hora_dt'] = pd.to_datetime(df['Data_Hora_Str'].str.replace('"', ''), dayfirst=True, errors='coerce')
        end_time = pd.to_datetime(df['Fim_Contato'], format='%H:%M:%S', errors='coerce')
        start_time = pd.to_datetime(df['Inicio_Contato'], format='%H:%M:%S', errors='coerce')
        
        # Calcula a duração e corrige ligações que cruzaram a meia-noite (gerando valores negativos)
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
                
            # Corta pausas esquecidas abertas no horário previsto de saída do consultor
            exit_str = str(exit_map.get(row['OPERADOR'], "")).strip()
            if exit_str and ":" in exit_str:
                try:
                    exit_dt = pd.to_datetime(f"{start_dt.strftime('%Y-%m-%d')} {exit_str}")
                    if exit_dt > start_dt:
                        return exit_dt 
                except Exception:
                    pass
                    
            # Se for hoje e não houver saída prevista, corta no momento exato da extração
            return self.now if start_dt.date() == self.now.date() else start_dt

        df['fim_dt'] = df.apply(sanitize_break, axis=1)
        subset_cols = ['OPERADOR', 'inicio_dt', 'PAUSA'] if 'PAUSA' in df.columns else ['OPERADOR', 'inicio_dt']
        return df.drop_duplicates(subset=subset_cols)

    # --- 5. ALGORITMO DE OCIOSIDADE ---
    def calc_idleness(self, calls: list, breaks: list) -> float:
        """Calcula o tempo "fantasma" entre ligações, descontando intervalos de pausa oficiais."""
        if len(calls) < 2:
            return 0.0
            
        calls.sort(key=lambda x: x[0])
        idle_seconds = 0.0
        
        for (curr_start, curr_end), (next_start, next_end) in zip(calls, calls[1:]):
            gap = (next_start - curr_end).total_seconds()
            
            # Só contabiliza se o buraco temporal estiver dentro do limite máximo de análise
            if 0.0 < gap <= MAX_IDLE_GAP_SECONDS:
                # Verifica se a ociosidade se cruza com alguma pausa formal
                if not any(max(curr_end, break_start) < min(next_start, break_end) for break_start, break_end in breaks):
                    idle_seconds += gap 
                    
        return idle_seconds / SECONDS_IN_MINUTE

    # --- 6. INTEGRAÇÃO DE VENDAS EXTERNAS ---
    def fetch_external_sales(self, url: str) -> pd.DataFrame:
        """Busca vendas cadastradas manualmente em planilhas externas via URL CSV e agrupa por cliente único."""
        if not url:
            return pd.DataFrame()
            
        try:
            df_ext = pd.read_csv(url)
            df_ext.columns = df_ext.columns.str.strip().str.upper()
            df_ext = df_ext.dropna(subset=['CONSULTOR', 'DATA'])
            
            # Formata datas curtas inseridas manualmente (ex: '30/03' -> '30/03/YYYY')
            def fix_date(d):
                d = str(d).strip()
                if len(d) <= 5: 
                    return f"{d}/{self.now.year}"
                return d
                
            df_ext['DATA'] = df_ext['DATA'].apply(fix_date)
            
            # Remove espaços para facilitar o cruzamento de dados
            df_ext['CONSULTOR_EXTERNO'] = df_ext['CONSULTOR'].astype(str).str.upper().str.replace(' ', '')
            
            if 'CLIENTE' in df_ext.columns:
                # Remove espaços em branco nas pontas e deixa maiúsculo para evitar duplicação de clientes
                df_ext['CLIENTE_CLEAN'] = df_ext['CLIENTE'].astype(str).str.strip().str.upper()
                
                # Conta apenas clientes únicos por dia/consultor
                sales_count = df_ext.groupby(['DATA', 'CONSULTOR_EXTERNO'])['CLIENTE_CLEAN'].nunique().reset_index(name='VENDAS_EXTERNAS')
            
            return sales_count
        except Exception as e:
            print(f"[!] Aviso: Não foi possível carregar as vendas externas. Erro: {e}")
            return pd.DataFrame()

    # --- 7. MOTOR DE AGREGAÇÃO DE MÉTRICAS ---
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

        # Unifica todas as bases consolidadas utilizando o nome do consultor como chave primária
        df = rep_eng.merge(rep_brk, on='CONSULTOR', how='left').fillna(0.0).merge(df_info, on='CONSULTOR', how='left').fillna('')
        
        # --- 7.1. Injeção de vendas externas ---
        df_ext = self.fetch_external_sales(PATHS.get('external_sales', ''))
        
        if not df_ext.empty:
            # Inteligência de mapeamento para localizar o consultor pelo primeiro nome
            def match_consultor(row):
                date_val = row['DATA']
                cons_ext = row['CONSULTOR_EXTERNO']
                
                df_day = df[df['DATA'] == date_val]
                match = df_day[df_day['CONSULTOR'].str.startswith(cons_ext)]
                
                if not match.empty:
                    return match['CONSULTOR'].iloc[0]
                return cons_ext 
                
            df_ext['CONSULTOR'] = df_ext.apply(match_consultor, axis=1)
            df_ext_grouped = df_ext.groupby(['DATA', 'CONSULTOR'])['VENDAS_EXTERNAS'].sum().reset_index()
            
            # Faz a fusão e soma os valores externos à coluna principal de vendas
            df = df.merge(df_ext_grouped, on=['DATA', 'CONSULTOR'], how='left').fillna(0.0)
            df['VENDA FEITA'] = df['VENDA FEITA'] + df['VENDAS_EXTERNAS']
            df.drop(columns=['VENDAS_EXTERNAS'], inplace=True)

        # --- 7.2. Cálculo final de tempos não tabelados ---
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
    
    # --- 8. TIMELINE DE EVENTOS ---
    def get_timeline(self, df_eng: pd.DataFrame, df_brk: pd.DataFrame) -> pd.DataFrame:
        """Gera o log sequencial de atividades para visualização de jornada no Power BI."""
        if df_eng.empty and df_brk.empty:
            return pd.DataFrame()

        # 1. Isolação e padronização das chamadas
        df_calls = pd.DataFrame({
            'CONSULTOR': df_eng['Atendente'],
            'DATE': df_eng['Hora_dt'].dt.strftime('%d/%m/%Y'),
            'EVENT': 'Joytec',
            'START_DT': df_eng['Hora_dt'],
            'END_DT': df_eng['Hora_fim_dt']
        })

        # 2. Isolação das pausas com aplicação do dicionário global de nomenclatura
        raw_events = df_brk['PAUSA'].astype(str).str.strip().str.upper()
        mapped_events = raw_events.map(EVENT_MAPPING)
        fallback_events = raw_events.str.replace('_', ' ').str.title()

        df_pauses = pd.DataFrame({
            'CONSULTOR': df_brk['OPERADOR'],
            'DATE': df_brk['inicio_dt'].dt.strftime('%d/%m/%Y'),
            'EVENT': mapped_events.fillna(fallback_events),
            'START_DT': df_brk['inicio_dt'],
            'END_DT': df_brk['fim_dt']
        })

        # 3. Ordenação cronológica absoluta
        df_time = pd.concat([df_calls, df_pauses], ignore_index=True)
        df_time = df_time.dropna(subset=['START_DT', 'END_DT'])
        df_time.sort_values(by=['CONSULTOR', 'START_DT'], inplace=True)

        # Funde eventos sequenciais idênticos em blocos maiores para reduzir ruído visual
        has_changed = (df_time['CONSULTOR'] != df_time['CONSULTOR'].shift(1)) | \
                      (df_time['EVENT'] != df_time['EVENT'].shift(1))
        
        df_time['BLOCK_ID'] = has_changed.cumsum()

        df_grouped = df_time.groupby(['CONSULTOR', 'DATE', 'EVENT', 'BLOCK_ID'], as_index=False).agg(
            START_DT=('START_DT', 'min'),
            END_DT=('END_DT', 'max')
        )
        df_grouped.sort_values(by=['CONSULTOR', 'START_DT'], inplace=True)

        # Elimina micro-pausas e oscilações irrelevantes (<= 3.5 minutos)
        duration_seconds = (df_grouped['END_DT'] - df_grouped['START_DT']).dt.total_seconds()
        df_grouped = df_grouped[duration_seconds >= 210.0].copy()

        # Reconecta os blocos principais que foram fragmentados pelos micro-eventos filtrados
        has_changed_after = (df_grouped['CONSULTOR'] != df_grouped['CONSULTOR'].shift(1)) | \
                            (df_grouped['EVENT'] != df_grouped['EVENT'].shift(1))
        
        df_grouped['BLOCK_ID_FINAL'] = has_changed_after.cumsum()

        df_final = df_grouped.groupby(['CONSULTOR', 'DATE', 'EVENT', 'BLOCK_ID_FINAL'], as_index=False).agg(
            START_DT=('START_DT', 'min'),
            END_DT=('END_DT', 'max')
        )
        df_final.sort_values(by=['CONSULTOR', 'START_DT'], inplace=True)

        # 7. Conversão temporal para compatibilidade com o Power BI
        df_final['START'] = df_final['START_DT'].dt.strftime('%H:%M:%S')
        df_final['END'] = df_final['END_DT'].dt.strftime('%H:%M:%S')
        
        duration_components = (df_final['END_DT'] - df_final['START_DT']).dt.components

        def format_duration(row):
            h = int(row['hours'])
            m = int(row['minutes'])
            s = int(row['seconds'])
            
            if h == 0 and m > 9:
                return f"{m:02d}min"
            elif h == 0 and m <= 9:
                return f"{m}min"
            else:
                return f"{h}h {m:02d}min"

        df_final['DURATION'] = duration_components.apply(format_duration, axis=1)

        # Tradução final das colunas para ingestão no Dashboard
        df_final.rename(columns={
            'DATE': 'DATA', 
            'EVENT': 'EVENTO', 
            'START': 'INICIO', 
            'END': 'FIM',
            'DURATION': 'DURAÇÃO'
        }, inplace=True)

        return df_final[['CONSULTOR', 'DATA', 'EVENTO', 'INICIO', 'FIM', 'DURAÇÃO']]