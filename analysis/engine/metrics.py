import pandas as pd
import urllib.request
import urllib.parse
import unicodedata
import io
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
            
            # Só contabiliza se o buraco temporal for maior que zero e estiver dentro do limite aceitável (ex: <= 1 hora)
            if 0.0 < gap <= MAX_IDLE_GAP_SECONDS:
                # Verifica se esse "buraco" se cruza com alguma pausa oficial (almoço, banheiro)
                # Se não houver cruzamento, significa que ele estava ocioso de fato, então soma o tempo
                if not any(max(curr_end, break_start) < min(next_start, break_end) for break_start, break_end in breaks):
                    idle_seconds += gap 
                    
        # Converte o total de segundos para minutos e retorna
        return idle_seconds / SECONDS_IN_MINUTE


    def fetch_external_sales(self, url: str, target_date_str: str) -> pd.DataFrame:
        """Busca, valida e processa planilhas do Google Sheets."""

        if not url:
            return pd.DataFrame()
            
        try:
            # Mascara a requisição web simulando ser um navegador comum (Mozilla) para evitar bloqueios de segurança do Google
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            
            with urllib.request.urlopen(req) as response:
                # Extrai o nome original do arquivo que vem escondido nos cabeçalhos HTTP da resposta
                filename = response.info().get_filename()
                
                if filename:
                    # Remove codificações de URL (ex: transforma %20 em espaços normais) e joga para maiúsculo
                    filename_upper = urllib.parse.unquote(filename).upper()
                    
                    # Remove acentuação para garantir uma comparação perfeita depois
                    filename_clean = unicodedata.normalize('NFKD', filename_upper).encode('ASCII', 'ignore').decode('utf-8')
                    
                    # Dicionário de tradução dos meses
                    pt_months = {
                        1: 'JANEIRO', 2: 'FEVEREIRO', 3: 'MARCO', 4: 'ABRIL', 
                        5: 'MAIO', 6: 'JUNHO', 7: 'JULHO', 8: 'AGOSTO', 
                        9: 'SETEMBRO', 10: 'OUTUBRO', 11: 'NOVEMBRO', 12: 'DEZEMBRO'
                    }
                    
                    # Extrai o mês especificamente do target_date do scraper (ex: de "15/04/2026", pega o "04" e converte pra inteiro)
                    target_month_int = int(target_date_str.split('/')[1])
                    target_month_name = pt_months[target_month_int]
                    
                    # Valida se o mês extraído do Scraper está escrito no nome da planilha do Google
                    # Isso impede que vendas do mês passado entrem no relatório do mês atual por não atualizar o link
                    if target_month_name not in filename_clean:
                        print(f"[!] Vendas externas desconsideradas. Mês alvo: {target_month_name}. Atualize o link.")
                        return pd.DataFrame()
            
                # Se passou pela validação de segurança, lê o CSV diretamente da memória RAM
                csv_data = response.read()
                df_ext = pd.read_csv(io.BytesIO(csv_data))
                
            # Padroniza as colunas da planilha externa
            df_ext.columns = df_ext.columns.str.strip().str.upper()
            df_ext = df_ext.dropna(subset=['CONSULTOR', 'DATA'])
            
            # Função para corrigir datas preenchidas de forma preguiçosa (ex: "30/03" vira "30/03/YYYY")
            def fix_date(d):
                d = str(d).strip()
                if len(d) <= 5: 
                    return f"{d}/{self.now.year}"
                return d
                
            df_ext['DATA'] = df_ext['DATA'].apply(fix_date)
            # Limpa o nome do consultor removendo espaços para facilitar a fusão futura com o banco principal
            df_ext['CONSULTOR_EXTERNO'] = df_ext['CONSULTOR'].astype(str).str.upper().str.replace(' ', '')
            
            # Aplica a inteligência de desduplicação, que diz que se houverem várias linhas para o mesmo cliente, é igual a 1 venda
            if 'CLIENTE' in df_ext.columns:
                df_ext['CLIENTE_CLEAN'] = df_ext['CLIENTE'].astype(str).str.strip().str.upper()
                sales_count = df_ext.groupby(['DATA', 'CONSULTOR_EXTERNO'])['CLIENTE_CLEAN'].nunique().reset_index(name='VENDAS_EXTERNAS')
            else:
                # Se não tiver a coluna CLIENTE, conta o número de linhas (size) normalmente
                sales_count = df_ext.groupby(['DATA', 'CONSULTOR_EXTERNO']).size().reset_index(name='VENDAS_EXTERNAS')
                
            return sales_count
        except Exception as e:
            print(f"[!] Aviso: Não foi possível carregar as vendas externas. Erro: {e}")
            return pd.DataFrame()


    def get_metrics(self, df_eng: pd.DataFrame, df_brk: pd.DataFrame, df_info: pd.DataFrame, target_date_str: str) -> pd.DataFrame:
        """Consolida todas as bases em um único arquivo mestre para o Power BI."""
        
        # Sub-função para processar a tabela de ligações
        def aggregate_engagements(group):
            status_col = group['Status']
            productive = group[status_col.isin(STATUS_PROD)]
            
            # Filtra as chamadas produtivas ignorando as que estão na lista de CPC_IGNORE
            cpc_calls = productive[~productive['Status'].isin(CPC_IGNORE)]
            cpc_count = len(cpc_calls)
            
            # Calcula o tempo total em minutos gasto apenas em chamadas CPC para achar a média
            cpc_total_minutes = cpc_calls['Tempo'].sum() / SECONDS_IN_MINUTE
            avg_cpc_time = cpc_total_minutes / cpc_count if cpc_count > 0 else 0.0
            
            # Retorna uma série com os totais de cada indicador de negócio somados
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

        # Aplica a agregação criando uma linha para cada atendente
        rep_eng = df_eng.groupby('Atendente').apply(aggregate_engagements, include_groups=False).reset_index().rename(columns={'Atendente': 'CONSULTOR'})

        # Sub-função para processar a tabela de pausas
        def aggregate_breaks(group):
            total_pause, lunch, bathroom, num_breaks = 0.0, 0.0, 0.0, 0
            for row in group.itertuples():
                break_type = str(row.PAUSA).upper()
                # Duração da pausa em minutos
                duration_minutes = (row.fim_dt - row.inicio_dt).total_seconds() / SECONDS_IN_MINUTE
                
                # Separa pausas de alimentação (não soma ao tempo total de pausa)
                if any(k in break_type for k in ["ALMOCO", "LANCHE", "REFEICAO"]):
                    lunch += duration_minutes
                else:
                    total_pause += duration_minutes
                    num_breaks += 1
                    # Destaca a pausa de banheiro para uma coluna separada (mas continua somando ao tempo total de pausa)
                    if "BANHEIRO" in break_type:
                        bathroom += duration_minutes
                        
            return pd.Series({
                'NÚMERO DE PAUSAS': num_breaks, 
                'TEMPO TOTAL DE PAUSA_raw': total_pause, 
                'ALMOÇO_raw': lunch, 
                'BANHEIRO_raw': bathroom
            })
            
        # Aplica a agregação criando uma linha para cada operador
        rep_brk = df_brk.groupby('OPERADOR').apply(aggregate_breaks, include_groups=False).reset_index().rename(columns={'OPERADOR': 'CONSULTOR'})

        # Faz o merge usando o nome do consultor como chave, juntando ligações, pausas e cadastro
        df = rep_eng.merge(rep_brk, on='CONSULTOR', how='left').fillna(0.0).merge(df_info, on='CONSULTOR', how='left').fillna('')
        
        # Chama a função validada do Google Sheets
        df_ext = self.fetch_external_sales(PATHS.get('external_sales', ''), target_date_str)
        
        if not df_ext.empty:
            # Se na planilha externa está "VITORIA" e no Joytec está "VITORIABARBOSA", a função associa os dois
            def match_consultor(row):
                date_val = row['DATA']
                cons_ext = row['CONSULTOR_EXTERNO']
                
                df_day = df[df['DATA'] == date_val]
                match = df_day[df_day['CONSULTOR'].str.startswith(cons_ext)]
                
                if not match.empty:
                    return match['CONSULTOR'].iloc[0]
                return cons_ext 
                
            df_ext['CONSULTOR'] = df_ext.apply(match_consultor, axis=1)
            # Soma as vendas externas por dia e por consultor
            df_ext_grouped = df_ext.groupby(['DATA', 'CONSULTOR'])['VENDAS_EXTERNAS'].sum().reset_index()
            
            # Funde com o dataframe principal e adiciona o valor de fora na coluna "VENDA FEITA" original
            df = df.merge(df_ext_grouped, on=['DATA', 'CONSULTOR'], how='left').fillna(0.0)
            df['VENDA FEITA'] = df['VENDA FEITA'] + df['VENDAS_EXTERNAS']
            df.drop(columns=['VENDAS_EXTERNAS'], inplace=True)
        
        # Cria dicionários com listas de horários de início e fim para jogar no algoritmo de ociosidade
        calls_map = df_eng.groupby('Atendente').apply(lambda g: list(zip(g['Hora_dt'], g['Hora_fim_dt']))).to_dict()
        breaks_map = df_brk.groupby('OPERADOR').apply(lambda g: list(zip(g['inicio_dt'], g['fim_dt']))).to_dict()
        # Calcula e cria a coluna de ociosidade cruzando os dicionários criados
        df['TEMPO DE OCIOSIDADE_raw'] = df['CONSULTOR'].apply(lambda c: self.calc_idleness(calls_map.get(c, []), breaks_map.get(c, [])))

        # Lógica para calcular o tempo em que o agente estava trabalhando mas não estava produzindo (tempo não tabelado )
        def calc_untracked(row):
            workload = time_str_to_minutes(row.get('CARGA_HORARIA_RAW'))
            entry_time = time_str_to_minutes(row.get('ENTRADA'))
            exit_time = time_str_to_minutes(row.get('SAIDA'))
            
            if not workload:
                return 0.0
                
            total_pauses = row.get('TEMPO TOTAL DE PAUSA_raw', 0.0) + row.get('ALMOÇO_raw', 0.0)
            expected_exit = exit_time if exit_time else entry_time + workload
            # Converte a hora atual do robô em minutos do dia
            current_minutes = self.now.hour * SECONDS_IN_MINUTE + self.now.minute
            
            # Se for um dia passado ou o turno já acabou, a base de tempo é a carga horária inteira
            # Se for no meio do expediente, a base de tempo é só os minutos que já se passaram desde que ele entrou
            is_past_date = pd.to_datetime(row.get('DATA', ''), dayfirst=True).date() < self.now.date()
            base_time = workload if is_past_date or current_minutes >= expected_exit else max(0.0, current_minutes - entry_time)
            
            # Tempo total disponível - (tempo em pausa + tempo falando no telefone)
            return max(0.0, base_time - (total_pauses + row.get('TEMPO EM LIGAÇÃO_raw', 0.0)))

        # Subtrai o tempo de ociosidade do tempo não tabelado
        df['TEMPO NÃO TABELADO_raw'] = df.apply(calc_untracked, axis=1) - df['TEMPO DE OCIOSIDADE_raw']
        df['TEMPO NÃO TABELADO_raw'] = df['TEMPO NÃO TABELADO_raw'].clip(lower=0.0)
        
        return df