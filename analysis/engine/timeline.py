import pandas as pd
from config import EVENT_MAPPING

class TimelineGenerator:

    def get_timeline(self, df_eng: pd.DataFrame, df_brk: pd.DataFrame) -> pd.DataFrame:
        if df_eng.empty and df_brk.empty:
            return pd.DataFrame()

        df_calls = pd.DataFrame({
            'CONSULTOR': df_eng['Atendente'],
            'DATE': df_eng['Hora_dt'].dt.strftime('%d/%m/%Y'),
            'EVENT': 'Joytec',
            'START_DT': df_eng['Hora_dt'],
            'END_DT': df_eng['Hora_fim_dt']
        })

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

        df_time = pd.concat([df_calls, df_pauses], ignore_index=True)
        df_time = df_time.dropna(subset=['START_DT', 'END_DT'])
        df_time.sort_values(by=['CONSULTOR', 'START_DT'], inplace=True)

        has_changed = (df_time['CONSULTOR'] != df_time['CONSULTOR'].shift(1)) | \
                      (df_time['EVENT'] != df_time['EVENT'].shift(1))
        
        df_time['BLOCK_ID'] = has_changed.cumsum()

        df_grouped = df_time.groupby(['CONSULTOR', 'DATE', 'EVENT', 'BLOCK_ID'], as_index=False).agg(
            START_DT=('START_DT', 'min'),
            END_DT=('END_DT', 'max')
        )
        df_grouped.sort_values(by=['CONSULTOR', 'START_DT'], inplace=True)

        duration_seconds = (df_grouped['END_DT'] - df_grouped['START_DT']).dt.total_seconds()
        df_grouped = df_grouped[duration_seconds >= 210.0].copy()

        has_changed_after = (df_grouped['CONSULTOR'] != df_grouped['CONSULTOR'].shift(1)) | \
                            (df_grouped['EVENT'] != df_grouped['EVENT'].shift(1))
        
        df_grouped['BLOCK_ID_FINAL'] = has_changed_after.cumsum()

        df_final = df_grouped.groupby(['CONSULTOR', 'DATE', 'EVENT', 'BLOCK_ID_FINAL'], as_index=False).agg(
            START_DT=('START_DT', 'min'),
            END_DT=('END_DT', 'max')
        )
        df_final.sort_values(by=['CONSULTOR', 'START_DT'], inplace=True)

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

        df_final.rename(columns={
            'DATE': 'DATA', 
            'EVENT': 'EVENTO', 
            'START': 'INICIO', 
            'END': 'FIM',
            'DURATION': 'DURAÇÃO'
        }, inplace=True)

        return df_final[['CONSULTOR', 'DATA', 'EVENTO', 'INICIO', 'FIM', 'DURAÇÃO']]