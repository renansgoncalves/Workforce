import pandas as pd
import numpy as np
from datetime import datetime
from config import STATUS_PROD, STATUS_NEG, STATUS_POS, CPC_IGNORE
from utils import time_str_to_minutes

class WFMProcessor:
    def __init__(self):
        self.now = datetime.now()

    def process_info(self, path: str) -> pd.DataFrame:
        try:
            df = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig')
            df.columns = df.columns.str.strip().str.upper()
            def get_c(cols, default=''):
                return next((df[c].astype(str).str.strip().replace('nan', '') for c in cols if c in df.columns), pd.Series(default, index=df.index))
            return pd.DataFrame({
                'CONSULTOR': get_c(['NOME', 'CONSULTOR']).str.upper(),
                'DRIVE_ID': get_c(['ID_DRIVE', 'ID DRIVE', 'FOTO']),
                'EQUIPE_INFO': get_c(['EQUIPE']),
                'ENTRADA': get_c(['ENTRADA']),
                'SAIDA': get_c(['SAÍDA', 'SAIDA']),
                'CARGA_HORARIA_RAW': get_c(['CARGA HORÁRIA', 'CARGA HORARIA'])
            })
        except: return pd.DataFrame()

    def clean_engagements(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path, sep=';', encoding='utf-8').drop_duplicates()
        if 'COD_USUARIO' in df.columns:
            df.rename(columns={'COD_USUARIO': 'Atendente', 'Tabulacao': 'Status'}, inplace=True)
            df['Hora'] = df['Data'].astype(str) + " " + df['Inicio_Contato'].astype(str)
        
        df['Atendente'] = df['Atendente'].astype(str).str.split('_').str[0].str.strip().str.upper()
        df = df[~df['Atendente'].isin(['ABANDONADA', 'NONE'])]
        df['Status'] = df.get('Status', pd.Series(['']*len(df))).fillna('')
        df['Hora_dt'] = pd.to_datetime(df['Hora'].str.replace('"', ''), dayfirst=True, errors='coerce')
        
        # Tempo vetorizado
        fim = pd.to_datetime(df['Fim_Contato'], format='%H:%M:%S', errors='coerce')
        ini = pd.to_datetime(df['Inicio_Contato'], format='%H:%M:%S', errors='coerce')
        df['Tempo'] = (fim - ini).dt.total_seconds().fillna(0)
        df['Tempo'] = np.where(df['Tempo'] < 0, df['Tempo'] + 86400, df['Tempo'])
        df['Hora_fim_dt'] = df['Hora_dt'] + pd.to_timedelta(df['Tempo'], unit='s')
        
        return df.drop_duplicates(subset=['Atendente', 'Hora_dt'])

    def clean_breaks(self, path: str, df_info: pd.DataFrame) -> pd.DataFrame:
        df = pd.read_csv(path, sep=';', encoding='utf-8').drop_duplicates()
        df['OPERADOR'] = df['OPERADOR'].astype(str).str.split('_').str[0].str.strip().str.upper()
        df['inicio_dt'] = pd.to_datetime(df['Data_INICIO'] + ' ' + df['INICIO_PAUSA'], dayfirst=True, errors='coerce')
        df['fim_dt'] = pd.to_datetime(df['DATA_FIM'] + ' ' + df['FINAL_PAUSA'], dayfirst=True, errors='coerce')
        
        # Sanitização de fim de pausa
        saida_map = df_info.set_index('CONSULTOR')['SAIDA'].to_dict()
        def sanitize(r):
            ini = r['inicio_dt']
            if pd.notnull(r['fim_dt']) and r['fim_dt'] > ini: return r['fim_dt']
            saida_str = str(saida_map.get(r['OPERADOR'], "")).strip()
            if saida_str and ":" in saida_str:
                try:
                    dt_s = pd.to_datetime(f"{ini.strftime('%Y-%m-%d')} {saida_str}")
                    if dt_s > ini: return dt_s
                except: pass
            return self.now if ini.date() == self.now.date() else ini

        df['fim_dt'] = df.apply(sanitize, axis=1)
        return df.drop_duplicates(subset=['OPERADOR', 'inicio_dt', 'PAUSA'] if 'PAUSA' in df.columns else ['OPERADOR', 'inicio_dt'])

    def calc_idleness(self, calls: list, breaks: list) -> float:
        if len(calls) < 2: return 0.0
        calls.sort(key=lambda x: x[0])
        idle_s = 0.0
        for (c_s, c_e), (n_s, n_e) in zip(calls, calls[1:]):
            gap = (n_s - c_e).total_seconds()
            if 0 < gap <= 3600:
                if not any(max(c_e, b_s) < min(n_s, b_e) for b_s, b_e in breaks):
                    idle_s += gap
        return idle_s / 60

    def get_metrics(self, df_eng, df_brk, df_info):
        # Agregação de engajamento
        def agg_e(g):
            st = g['Status']
            prod = g[st.isin(STATUS_PROD)]
            return pd.Series({
                'DATA': str(g['Hora'].iloc[0]).split(' ')[0],
                'NÚMERO DE ACIONAMENTOS': len(g), 'ACIONAMENTOS PRODUTIVOS': len(prod),
                'TEMPO EM LIGAÇÃO_raw': g['Tempo'].sum() / 60,
                'CPC': len(prod[~prod['Status'].isin(CPC_IGNORE)]),
                'AGENTE NÃO TABULOU': (st == "Agente Nao Tabulou").sum(), 'ENGANO': (st == "ENGANO").sum(),
                'PROPOSTAS': st.isin(STATUS_NEG | STATUS_POS).sum(),
                'STATUS NEGATIVOS': st.isin(STATUS_NEG).sum(), 'STATUS POSITIVOS': st.isin(STATUS_POS).sum(),
                'VENDA FEITA': (st == "VENDA_FEITA").sum(), 'SEM POSSIBILIDADE': (st == "SEM_POSSIBILIDADES").sum(),
                'SEM MARGEM': (st == "SEM_MARGEM").sum(), 'SEM PORT': (st == "SEM_PORT").sum()
            })
        rep_eng = df_eng.groupby('Atendente').apply(agg_e, include_groups=False).reset_index().rename(columns={'Atendente': 'CONSULTOR'})

        # Agregação de pausas
        def agg_b(g):
            t_p, alm, ban, n_p = 0, 0, 0, 0
            for r in g.itertuples():
                tipo = str(r.PAUSA).upper()
                dur = (r.fim_dt - r.inicio_dt).total_seconds() / 60
                if any(k in tipo for k in ["ALMOCO", "LANCHE", "REFEICAO"]): alm += dur
                else:
                    t_p += dur
                    n_p += 1
                    if "BANHEIRO" in tipo: ban += dur
            return pd.Series({'NÚMERO DE PAUSAS': n_p, 'TEMPO TOTAL DE PAUSA_raw': t_p, 'ALMOÇO_raw': alm, 'BANHEIRO_raw': ban})
        rep_brk = df_brk.groupby('OPERADOR').apply(agg_b, include_groups=False).reset_index().rename(columns={'OPERADOR': 'CONSULTOR'})

        # Merge final
        df = rep_eng.merge(rep_brk, on='CONSULTOR', how='left').fillna(0).merge(df_info, on='CONSULTOR', how='left').fillna('')
        
        # Tempo de ociosidade
        c_map = df_eng.groupby('Atendente').apply(lambda g: list(zip(g['Hora_dt'], g['Hora_fim_dt']))).to_dict()
        b_map = df_brk.groupby('OPERADOR').apply(lambda g: list(zip(g['inicio_dt'], g['fim_dt']))).to_dict()
        df['TEMPO DE OCIOSIDADE_raw'] = df['CONSULTOR'].apply(lambda c: self.calc_idleness(c_map.get(c, []), b_map.get(c, [])))

        # Tempo não tabelado
        def untracked(r):
            cg, ent, sai = time_str_to_minutes(r.get('CARGA_HORARIA_RAW')), time_str_to_minutes(r.get('ENTRADA')), time_str_to_minutes(r.get('SAIDA'))
            if not cg: return 0
            p_tot = r.get('TEMPO TOTAL DE PAUSA_raw', 0) + r.get('ALMOÇO_raw', 0)
            s_min = sai if sai else ent + cg
            c_min = self.now.hour * 60 + self.now.minute
            is_past = pd.to_datetime(r.get('DATA',''), dayfirst=True).date() < self.now.date()
            t_base = cg if is_past or c_min >= s_min else max(0, c_min - ent)
            return max(0, t_base - (p_tot + r.get('TEMPO EM LIGAÇÃO_raw', 0)))

        df['TEMPO NÃO TABELADO_raw'] = df.apply(untracked, axis=1) - df['TEMPO DE OCIOSIDADE_raw']
        df['TEMPO NÃO TABELADO_raw'] = df['TEMPO NÃO TABELADO_raw'].clip(lower=0)
        
        return df