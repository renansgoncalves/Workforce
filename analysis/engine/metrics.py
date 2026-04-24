# analysis/engine/metrics.py

import pandas as pd
import urllib.request
import urllib.parse
import unicodedata
import io
import numpy as np
from datetime import datetime
from config import STATUS_PROD, STATUS_NEG, STATUS_POS, CPC_IGNORE, MAX_IDLE_GAP_SECONDS, SECONDS_IN_MINUTE, PATHS
from utils import time_str_to_minutes

class MetricsEngine:
    
    def __init__(self, current_time: datetime):
        # Recebe o tempo atual instanciado no main para garantir sincronia em todos os módulos
        self.now = current_time

    def calc_idleness(self, calls: list, breaks: list) -> float:
        """Calcula o tempo que o consultor passou esperando cair ligação na discadora."""
        # Se o consultor fez menos de 2 ligações no dia, é impossível calcular o intervalo entre elas
        if len(calls) < 2:
            return 0.0
            
        # Ordena a lista de ligações cronologicamente pelo horário de início
        calls.sort(key=lambda x: x[0])
        idle_seconds = 0.0
        
        # Faz um loop comparando o fim de uma ligação com o início da próxima
        for (curr_start, curr_end), (next_start, next_end) in zip(calls, calls[1:]):
            gap = (next_start - curr_end).total_seconds()
            
            # Só contabiliza se o buraco temporal for maior que zero e estiver dentro do limite aceitável
            if 0.0 < gap <= MAX_IDLE_GAP_SECONDS:
                # Verifica se esse "buraco" se cruza com alguma pausa oficial
                if not any(max(curr_end, break_start) < min(next_start, break_end) for break_start, break_end in breaks):
                    idle_seconds += gap 
                    
        # Converte o total de segundos para minutos e retorna
        return idle_seconds / SECONDS_IN_MINUTE

    def fetch_external_sales(self, url: str, target_date_str: str) -> pd.DataFrame:
        """Busca, valida e processa planilhas do Google Sheets."""
        if not url:
            return pd.DataFrame()
            
        try:
            # Mascara a requisição web simulando ser um navegador comum (Mozilla) para evitar bloqueios de segurança
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            
            with urllib.request.urlopen(req) as response:
                filename = response.info().get_filename()
                
                if filename:
                    filename_upper = urllib.parse.unquote(filename).upper()
                    filename_clean = unicodedata.normalize('NFKD', filename_upper).encode('ASCII', 'ignore').decode('utf-8')
                    
                    pt_months = {
                        1: 'JANEIRO', 2: 'FEVEREIRO', 3: 'MARCO', 4: 'ABRIL', 
                        5: 'MAIO', 6: 'JUNHO', 7: 'JULHO', 8: 'AGOSTO', 
                        9: 'SETEMBRO', 10: 'OUTUBRO', 11: 'NOVEMBRO', 12: 'DEZEMBRO'
                    }
                    
                    target_month_int = int(target_date_str.split('/')[1])
                    target_month_name = pt_months[target_month_int]
                    
                    if target_month_name not in filename_clean:
                        print(f"[!] Vendas externas desconsideradas. Mês alvo: {target_month_name}. Atualize o link.")
                        return pd.DataFrame()
            
                csv_data = response.read()
                df_ext = pd.read_csv(io.BytesIO(csv_data))
                
            df_ext.columns = df_ext.columns.str.strip().str.upper()
            df_ext = df_ext.dropna(subset=['CONSULTOR', 'DATA'])
            
            def fix_date(d):
                d = str(d).strip()
                if len(d) <= 5: 
                    return f"{d}/{self.now.year}"
                return d
                
            df_ext['DATA'] = df_ext['DATA'].apply(fix_date)
            df_ext['CONSULTOR_EXTERNO'] = df_ext['CONSULTOR'].astype(str).str.upper().str.replace(' ', '')
            
            if 'CLIENTE' in df_ext.columns:
                df_ext['CLIENTE_CLEAN'] = df_ext['CLIENTE'].astype(str).str.strip().str.upper()
                sales_count = df_ext.groupby(['DATA', 'CONSULTOR_EXTERNO'])['CLIENTE_CLEAN'].nunique().reset_index(name='VENDAS_EXTERNAS')
            else:
                sales_count = df_ext.groupby(['DATA', 'CONSULTOR_EXTERNO']).size().reset_index(name='VENDAS_EXTERNAS')
                
            return sales_count
        except Exception as e:
            print(f"[!] Aviso: Não foi possível carregar as vendas externas. Erro: {e}")
            return pd.DataFrame()

    def get_metrics(self, df_eng: pd.DataFrame, df_brk: pd.DataFrame, df_info: pd.DataFrame, target_date_str: str) -> pd.DataFrame:
        """Consolida todas as bases em um único arquivo mestre para o Power BI."""
        
        def aggregate_engagements(group):
            status_col = group['Status']
            productive = group[status_col.isin(STATUS_PROD)]
            
            cpc_calls = productive[~productive['Status'].isin(CPC_IGNORE)]
            cpc_count = len(cpc_calls)
            
            cpc_total_minutes = cpc_calls['Tempo'].sum() / SECONDS_IN_MINUTE
            avg_cpc_time = cpc_total_minutes / cpc_count if cpc_count > 0 else 0.0
            
            return pd.Series({
                'DATA': str(group['Data'].iloc[0]),
                'ACIONAMENTOS': len(group),
                'ACIONAMENTOS PRODUTIVOS': len(productive),
                'TEMPO EM LIGAÇÃO_raw': group['Tempo'].sum() / SECONDS_IN_MINUTE,
                'CPC': cpc_count,
                'MEDIA_TEMPO_CPC_raw': avg_cpc_time,
                'NÃO TABULADOS': (status_col == "Agente Nao Tabulou").sum(),
                'ENGANOS': (status_col == "ENGANO").sum(),
                'PROPOSTAS': status_col.isin(STATUS_NEG | STATUS_POS).sum(),
                'PROPOSTAS NEGATIVAS': status_col.isin(STATUS_NEG).sum(),
                'PROPOSTAS POSITIVAS': status_col.isin(STATUS_POS).sum(),
                'VENDAS': 0,
                'SEM POSSIB.': (status_col == "SEM_POSSIBILIDADES").sum(),
                'SEM MARGEM': (status_col == "SEM_MARGEM").sum(),
                'SEM PORT.': (status_col == "SEM_PORT").sum(),
                'MUDOS': (status_col == "MUDA").sum()
            })

        # Se não houver ligações, cria uma estrutura vazia idêntica para evitar falhas no merge
        if df_eng.empty:
            rep_eng = pd.DataFrame(columns=[
                'CONSULTOR', 'DATA', 'ACIONAMENTOS', 'ACIONAMENTOS PRODUTIVOS', 
                'TEMPO EM LIGAÇÃO_raw', 'CPC', 'MEDIA_TEMPO_CPC_raw', 'NÃO TABULADOS', 
                'ENGANOS', 'PROPOSTAS', 'PROPOSTAS NEGATIVAS', 'PROPOSTAS POSITIVAS', 
                'VENDAS', 'SEM POSSIB.', 'SEM MARGEM', 'SEM PORT.'
            ])
        else:
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
                'TEMPO EM PAUSA_raw': total_pause, 
                'ALMOÇO_raw': lunch, 
                'BANHEIRO_raw': bathroom
            })
            
        # Blindagem contra ausência de pausas
        if df_brk.empty:
            rep_brk = pd.DataFrame(columns=['CONSULTOR', 'PAUSAS', 'TEMPO EM PAUSA_raw', 'ALMOÇO_raw', 'BANHEIRO_raw'])
        else:
            rep_brk = df_brk.groupby('OPERADOR').apply(aggregate_breaks, include_groups=False).reset_index().rename(columns={'OPERADOR': 'CONSULTOR'})

        df = rep_eng.merge(rep_brk, on='CONSULTOR', how='outer').fillna(0.0)
        
        if 'DATA' in df.columns:
            df['DATA'] = df['DATA'].replace(0.0, target_date_str)
        else:
            df['DATA'] = target_date_str

        if 'DATA' in df_info.columns:
            df = df.merge(df_info, on=['CONSULTOR', 'DATA'], how='left').fillna('')
        else:
            df = df.merge(df_info, on='CONSULTOR', how='left').fillna('')
        
        # Chama a função validada do Google Sheets
        df_ext = self.fetch_external_sales(PATHS.get('external_sales', ''), target_date_str)
        
        if not df_ext.empty:
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
            
            df = df.merge(df_ext_grouped, on=['DATA', 'CONSULTOR'], how='left').fillna(0.0)
            
            if 'VENDAS' not in df.columns:
                df['VENDAS'] = 0.0
                
            df['VENDAS'] = df['VENDAS'] + df['VENDAS_EXTERNAS']
            df.drop(columns=['VENDAS_EXTERNAS'], inplace=True, errors='ignore')
        
        calls_map = df_eng.groupby('Atendente').apply(lambda g: list(zip(g['Hora_dt'], g['Hora_fim_dt']))).to_dict() if not df_eng.empty else {}
        breaks_map = df_brk.groupby('OPERADOR').apply(lambda g: list(zip(g['inicio_dt'], g['fim_dt']))).to_dict() if not df_brk.empty else {}
        
        # Calcula e cria a coluna de ociosidade cruzando os dicionários criados
        df['TEMPO DE OCIOSIDADE_raw'] = df['CONSULTOR'].apply(lambda c: self.calc_idleness(calls_map.get(c, []), breaks_map.get(c, [])))

        def calc_untracked(row):
            workload = time_str_to_minutes(row.get('CARGA_HORARIA_RAW', ''))
            entry_time = time_str_to_minutes(row.get('ENTRADA', ''))
            exit_time = time_str_to_minutes(row.get('SAIDA', ''))
            
            if not workload:
                return 0.0
                
            total_pauses = row.get('TEMPO EM PAUSA_raw', 0.0) + row.get('ALMOÇO_raw', 0.0)
            expected_exit = exit_time if exit_time else entry_time + workload
            
            current_minutes = self.now.hour * SECONDS_IN_MINUTE + self.now.minute
            
            try:
                is_past_date = pd.to_datetime(row.get('DATA', ''), dayfirst=True).date() < self.now.date()
            except Exception:
                is_past_date = False
                
            base_time = workload if is_past_date or current_minutes >= expected_exit else max(0.0, current_minutes - entry_time)
            return max(0.0, base_time - (total_pauses + row.get('TEMPO EM LIGAÇÃO_raw', 0.0)))

        df['TEMPO NÃO TABELADO_raw'] = df.apply(calc_untracked, axis=1) - df['TEMPO DE OCIOSIDADE_raw']
        df['TEMPO NÃO TABELADO_raw'] = df['TEMPO NÃO TABELADO_raw'].clip(lower=0.0)
        
        return df