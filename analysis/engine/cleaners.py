import pandas as pd
import numpy as np
from datetime import datetime
from config import SECONDS_IN_DAY

class DataCleaner:
    
    def __init__(self, current_time: datetime):
        # Recebe o tempo atual instanciado no main para garantir sincronia em todos os módulos
        self.now = current_time

    def process_info(self, path: str) -> pd.DataFrame:
        """Função para ler e higienizar a base de cadastro (nomes, equipes, horários de turno)."""
        try:
            df = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig')
            
            # Padroniza os nomes de todas as colunas removendo espaços nas pontas e convertendo para maiúsculo
            df.columns = df.columns.str.strip().str.upper()
            
            # Procura pelo nome de uma coluna em uma lista de variações.
            def get_col(cols: list, default: str = '') -> pd.Series:
                return next((df[c].astype(str).str.strip().replace('nan', '') for c in cols if c in df.columns), pd.Series(default, index=df.index))
            
            # Constrói e retorna um dataframe final apenas com as colunas essenciais padronizadas
            return pd.DataFrame({
                'CONSULTOR': get_col(['NOME', 'CONSULTOR']).str.upper(),
                'DRIVE_ID': get_col(['ID_DRIVE', 'ID DRIVE', 'FOTO']),
                'EQUIPE_INFO': get_col(['EQUIPE']),
                'ENTRADA': get_col(['ENTRADA']),
                'SAIDA': get_col(['SAÍDA', 'SAIDA']),
                'CARGA_HORARIA_RAW': get_col(['CARGA HORÁRIA', 'CARGA HORARIA'])
            })
        except Exception:
            # Se o arquivo não existir ou estiver corrompido, devolve uma tabela vazia sem derrubar o sistema
            return pd.DataFrame()

    def clean_engagements(self, path: str) -> pd.DataFrame:
        """Lê e higieniza o relatório cru de ligações extraído do sistema."""
        df = pd.read_csv(path, sep=';', encoding='utf-8').drop_duplicates()
        
        # Remove espaços e substitui por underline nos nomes das colunas
        df.columns = df.columns.str.strip().str.replace(' ', '_')
            
        # Concatena a data e a hora de início em uma única string
        df['Data_Hora_Str'] = df['Data'].astype(str) + " " + df['Inicio_Contato'].astype(str)
        
        # Limpeza do nome do atendente
        df['Atendente'] = df['Atendente'].astype(str).str.split('_').str[0].str.strip().str.upper()
        
        # Remove ligações fantasmas
        df = df[~df['Atendente'].isin(['ABANDONADA', 'NONE'])]
        df['Status'] = df.get('Status', pd.Series([''] * len(df))).fillna('')
        
        # Converte as strings temporais puras para objetos Datetime
        df['Hora_dt'] = pd.to_datetime(df['Data_Hora_Str'].str.replace('"', ''), dayfirst=True, errors='coerce')
        end_time = pd.to_datetime(df['Fim_Contato'], format='%H:%M:%S', errors='coerce')
        start_time = pd.to_datetime(df['Inicio_Contato'], format='%H:%M:%S', errors='coerce')
        
        # Calcula a duração e corrige viradas de dia em ligações (23:55 a 00:05)
        df['Tempo'] = (end_time - start_time).dt.total_seconds().fillna(0.0)
        df['Tempo'] = np.where(df['Tempo'] < 0.0, df['Tempo'] + SECONDS_IN_DAY, df['Tempo'])
        
        # Hora final exata
        df['Hora_fim_dt'] = df['Hora_dt'] + pd.to_timedelta(df['Tempo'], unit='s')
        
        return df.drop_duplicates(subset=['Atendente', 'Hora_dt'])

    def format_breaks_dates(self, path: str) -> pd.DataFrame:
        """Lê o arquivo de pausas cru, formata nomes e converte as colunas temporais."""
        try:
            df = pd.read_csv(path, sep=';', encoding='utf-8').drop_duplicates()
        except Exception:
            return pd.DataFrame()
            
        if df.empty:
            return df
            
        df['OPERADOR'] = df['OPERADOR'].astype(str).str.split('_').str[0].str.strip().str.upper()
        df['inicio_dt'] = pd.to_datetime(df['Data_INICIO'] + ' ' + df['INICIO_PAUSA'], dayfirst=True, errors='coerce')
        df['fim_dt'] = pd.to_datetime(df['DATA_FIM'] + ' ' + df['FINAL_PAUSA'], dayfirst=True, errors='coerce')
        
        return df

    def apply_shift_rules(self, df_eng: pd.DataFrame, df_brk: pd.DataFrame, df_info: pd.DataFrame) -> tuple:
        """
        Aplica a Regra 1 (corrente de 5 mins antes do turno) e a Regra 2 (deslizamento de 10 mins de jornada).
        Retorna df_eng filtrado, df_brk filtrado e o novo cadastro (df_info_dynamic).
        """
        if df_info.empty:
            return df_eng, df_brk, df_info

        # 1. Cria a linha do tempo mestre apenas com o início das atividades
        events = []
        if not df_eng.empty:
            events.append(df_eng[['Atendente', 'Hora_dt']].rename(columns={'Atendente': 'CONSULTOR', 'Hora_dt': 'DT'}))
        if not df_brk.empty:
            events.append(df_brk[['OPERADOR', 'inicio_dt']].rename(columns={'OPERADOR': 'CONSULTOR', 'inicio_dt': 'DT'}))
            
        if not events:
            return df_eng, df_brk, df_info

        df_timeline = pd.concat(events, ignore_index=True).dropna(subset=['DT'])
        df_timeline['DATE_ONLY'] = df_timeline['DT'].dt.date
        df_timeline.sort_values(by=['CONSULTOR', 'DT'], inplace=True)

        dynamic_info_list = []
        valid_cutoffs = {}

        # 2. Avalia consultor por consultor as regras de tempo
        for _, row in df_info.iterrows():
            consultant = row['CONSULTOR']
            
            if not str(row['ENTRADA']).strip() or not str(row['SAIDA']).strip():
                dynamic_info_list.append(row)
                continue

            consultant_events = df_timeline[df_timeline['CONSULTOR'] == consultant]
            
            if consultant_events.empty:
                dynamic_info_list.append(row)
                continue

            for date_val, group in consultant_events.groupby('DATE_ONLY'):
                try:
                    official_entry = pd.to_datetime(f"{date_val} {row['ENTRADA']}")
                    official_exit = pd.to_datetime(f"{date_val} {row['SAIDA']}")
                except Exception:
                    continue

                event_times = group['DT'].sort_values().reset_index(drop=True)
                
                # -- Regra 1: Validação de sujeira pré-turno (5 minutos) --
                pre_shift_events = event_times[event_times < official_entry]
                cutoff_time = pd.Timestamp.min
                
                if not pre_shift_events.empty:
                    # Avalia do evento mais próximo da entrada até o mais antigo
                    pre_shift_reversed = pre_shift_events.iloc[::-1].reset_index(drop=True)
                    current_compare_time = official_entry
                    last_valid_time = official_entry
                    
                    for ev_time in pre_shift_reversed:
                        gap_seconds = (current_compare_time - ev_time).total_seconds()
                        if gap_seconds <= 300.0:  # 5 minutos
                            last_valid_time = ev_time
                            current_compare_time = ev_time
                        else:
                            cutoff_time = last_valid_time
                            break
                            
                    if cutoff_time == pd.Timestamp.min:
                         cutoff_time = last_valid_time
                else:
                    cutoff_time = official_entry

                # Salva o corte temporal desse dia
                valid_cutoffs[(consultant, date_val)] = cutoff_time
                
                # -- Regra 2: Deslizamento de jornada (10 minutos) --
                valid_events = event_times[event_times >= cutoff_time]
                
                dynamic_row = row.copy()
                dynamic_row['DATA'] = date_val.strftime('%d/%m/%Y')
                
                if not valid_events.empty:
                    first_valid_event = valid_events.iloc[0]
                    last_valid_event = valid_events.iloc[-1]
                    delay_seconds = (first_valid_event - official_entry).total_seconds()
                    
                    if delay_seconds >= 600.0:  # 10 minutos
                        shift_duration = official_exit - official_entry
                        new_exit_target = first_valid_event + shift_duration
                        
                        if last_valid_event > official_exit:
                            final_exit = min(new_exit_target, last_valid_event)
                            dynamic_row['ENTRADA'] = first_valid_event.strftime('%H:%M:%S')
                            dynamic_row['SAIDA'] = final_exit.strftime('%H:%M:%S')

                dynamic_info_list.append(dynamic_row)

        df_info_dynamic = pd.DataFrame(dynamic_info_list)

        # 3. Aplica a linha de corte (regra 1) descartando as sujeiras
        if not df_eng.empty and valid_cutoffs:
            df_eng['DATE_ONLY'] = df_eng['Hora_dt'].dt.date
            def is_valid_eng(r):
                cutoff = valid_cutoffs.get((r['Atendente'], r['DATE_ONLY']), pd.Timestamp.min)
                return r['Hora_dt'] >= cutoff
            df_eng = df_eng[df_eng.apply(is_valid_eng, axis=1)].drop(columns=['DATE_ONLY'])

        if not df_brk.empty and valid_cutoffs:
            df_brk['DATE_ONLY'] = df_brk['inicio_dt'].dt.date
            def is_valid_brk(r):
                cutoff = valid_cutoffs.get((r['OPERADOR'], r['DATE_ONLY']), pd.Timestamp.min)
                return r['inicio_dt'] >= cutoff
            df_brk = df_brk[df_brk.apply(is_valid_brk, axis=1)].drop(columns=['DATE_ONLY'])

        return df_eng, df_brk, df_info_dynamic

    def close_breaks(self, df_brk: pd.DataFrame, df_info_dynamic: pd.DataFrame, df_eng: pd.DataFrame) -> pd.DataFrame:
        """Fecha pausas abertas cruzando as atividades com o cadastro dinâmico gerado."""
        if df_brk.empty:
            return df_brk
            
        if 'DATA' in df_info_dynamic.columns:
            exit_map = df_info_dynamic.set_index(['CONSULTOR', 'DATA'])['SAIDA'].to_dict()
        else:
            exit_map = df_info_dynamic.set_index('CONSULTOR')['SAIDA'].to_dict()
            
        all_starts = []
        if not df_eng.empty:
            all_starts.append(df_eng[['Atendente', 'Hora_dt']].rename(columns={'Atendente': 'CONSULTOR', 'Hora_dt': 'DT'}))
        
        all_starts.append(df_brk[['OPERADOR', 'inicio_dt']].rename(columns={'OPERADOR': 'CONSULTOR', 'inicio_dt': 'DT'}))
        
        df_activities = pd.concat(all_starts, ignore_index=True).dropna(subset=['DT'])
        df_activities.sort_values(by=['CONSULTOR', 'DT'], inplace=True)
        starts_dict = df_activities.groupby('CONSULTOR')['DT'].apply(lambda x: x.values).to_dict()
        
        def get_next_activity(consultor: str, current_dt: pd.Timestamp) -> pd.Timestamp:
            if consultor not in starts_dict or pd.isnull(current_dt):
                return pd.NaT
            times = starts_dict[consultor]
            mask = times > current_dt.to_numpy()
            if mask.any():
                return pd.Timestamp(times[mask][0])
            return pd.NaT
        
        def sanitize_break(row):
            start_dt = row['inicio_dt']
            sys_end = row['fim_dt'] if pd.notnull(row['fim_dt']) and row['fim_dt'] >= start_dt else pd.NaT
            next_dt = get_next_activity(row['OPERADOR'], start_dt)
            
            possible_ends = []
            if pd.notnull(sys_end): possible_ends.append(sys_end)
            if pd.notnull(next_dt): possible_ends.append(next_dt)
                
            # Busca o horário de saída dinâmico (baseado na data e no consultor)
            date_str = start_dt.strftime('%d/%m/%Y')
            exit_str = exit_map.get((row['OPERADOR'], date_str)) if 'DATA' in df_info_dynamic.columns else exit_map.get(row['OPERADOR'])
            
            if exit_str and ":" in str(exit_str):
                try:
                    exit_dt = pd.to_datetime(f"{start_dt.strftime('%Y-%m-%d')} {exit_str}")
                    if exit_dt > start_dt:
                        possible_ends.append(exit_dt)
                except Exception:
                    pass
            
            if possible_ends:
                return min(possible_ends)
                    
            return self.now if start_dt.date() == self.now.date() else start_dt

        df_brk['fim_dt'] = df_brk.apply(sanitize_break, axis=1)
        subset_cols = ['OPERADOR', 'inicio_dt', 'PAUSA'] if 'PAUSA' in df_brk.columns else ['OPERADOR', 'inicio_dt']
        
        return df_brk.drop_duplicates(subset=subset_cols)