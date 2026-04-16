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
        
        # Remove espaços e substitui por underline nos nomes das colunas para facilitar a manipulação
        df.columns = df.columns.str.strip().str.replace(' ', '_')
            
        # Concatena a data e a hora de início em uma única string ("DD/MM/YYYY HH:MM:SS")
        df['Data_Hora_Str'] = df['Data'].astype(str) + " " + df['Inicio_Contato'].astype(str)
        
        # Divide a string do nome do atendente no '_' (se houver), pega a primeira parte, tira espaços e deixa maiúsculo
        df['Atendente'] = df['Atendente'].astype(str).str.split('_').str[0].str.strip().str.upper()
        
        # Remove ligações fantasmas ou de sistema atribuídas a "ABANDONADA" ou "NONE"
        df = df[~df['Atendente'].isin(['ABANDONADA', 'NONE'])]
        
        # Garante que a coluna 'Status' exista, preenchendo com vazio caso venha nula do extrator
        df['Status'] = df.get('Status', pd.Series([''] * len(df))).fillna('')
        
        # Converte as strings temporais puras para objetos do tipo Datetime do Pandas, permitindo cálculos de tempo reais
        df['Hora_dt'] = pd.to_datetime(df['Data_Hora_Str'].str.replace('"', ''), dayfirst=True, errors='coerce')
        end_time = pd.to_datetime(df['Fim_Contato'], format='%H:%M:%S', errors='coerce')
        start_time = pd.to_datetime(df['Inicio_Contato'], format='%H:%M:%S', errors='coerce')
        
        # Calcula a duração da ligação em segundos subtraindo o início do fim
        df['Tempo'] = (end_time - start_time).dt.total_seconds().fillna(0.0)
        
        # Se a ligação começou às 23:55 e terminou às 00:05, o cálculo acima daria negativo. Sendo assim,
        # o np.where detecta valores negativos e soma 24h para corrigir a duração
        df['Tempo'] = np.where(df['Tempo'] < 0.0, df['Tempo'] + SECONDS_IN_DAY, df['Tempo'])
        
        # Cria a coluna com a hora final exata da ligação, somando a duração ao momento de início
        df['Hora_fim_dt'] = df['Hora_dt'] + pd.to_timedelta(df['Tempo'], unit='s')
        
        # Retorna o dataframe removendo eventuais ligações exatamente simultâneas do mesmo atendente (erros do discador)
        return df.drop_duplicates(subset=['Atendente', 'Hora_dt'])


    def clean_breaks(self, path: str, df_info: pd.DataFrame, df_eng: pd.DataFrame = None) -> pd.DataFrame:
        """Fecha pausas esquecidas abertas baseando-se no comportamento do consultor."""

        df = pd.read_csv(path, sep=';', encoding='utf-8').drop_duplicates()
        
        # Limpeza padrão do nome do operador
        df['OPERADOR'] = df['OPERADOR'].astype(str).str.split('_').str[0].str.strip().str.upper()
        
        # Transforma strings em datetimes reais para as colunas de início e fim da pausa
        df['inicio_dt'] = pd.to_datetime(df['Data_INICIO'] + ' ' + df['INICIO_PAUSA'], dayfirst=True, errors='coerce')
        df['fim_dt'] = pd.to_datetime(df['DATA_FIM'] + ' ' + df['FINAL_PAUSA'], dayfirst=True, errors='coerce')
        
        # Cria um dicionário de busca rápida (hash map) relacionando o consultor ao seu horário de saída previsto no cadastro
        exit_map = df_info.set_index('CONSULTOR')['SAIDA'].to_dict()
        
        # Cria um mapeamento de todas as atividades para encontrar o próximo evento do operador (ligações + pausas)
        all_starts = []
        
        # Extrai quem atendeu e quando
        if df_eng is not None and not df_eng.empty:
            all_starts.append(df_eng[['Atendente', 'Hora_dt']].rename(columns={'Atendente': 'CONSULTOR', 'Hora_dt': 'DT'}))
        
        # Adiciona também os inícios de todas as pausas
        all_starts.append(df[['OPERADOR', 'inicio_dt']].rename(columns={'OPERADOR': 'CONSULTOR', 'inicio_dt': 'DT'}))
        
        # Funde ligações e pausas em uma única "linha do tempo mestre", removendo nulos e ordenando cronologicamente
        df_activities = pd.concat(all_starts, ignore_index=True).dropna(subset=['DT'])
        df_activities.sort_values(by=['CONSULTOR', 'DT'], inplace=True)
        
        # Agrupa essa linha do tempo por consultor, criando um dicionário onde a chave é o consultor e o valor é um array de horários
        starts_dict = df_activities.groupby('CONSULTOR')['DT'].apply(lambda x: x.values).to_dict()
        
        # Função auxiliar para buscar, dado um instante no tempo, qual foi a próxima coisa que aquele consultor fez
        def get_next_activity(consultor: str, current_dt: pd.Timestamp) -> pd.Timestamp:
            if consultor not in starts_dict or pd.isnull(current_dt):
                return pd.NaT
            times = starts_dict[consultor]
            
            # Filtra o array temporal para manter apenas horários que aconteceram estritamente depois do horário atual
            mask = times > current_dt.to_numpy()
            if mask.any():
                # Retorna o primeiro horário futuro encontrado
                return pd.Timestamp(times[mask][0])
            return pd.NaT
        
        def sanitize_break(row):
            """Função principal de sanitização, aplicada linha a linha (a cada pausa)."""

            start_dt = row['inicio_dt']
            
            # 1. Pega o fim original do sistema (se existir) e descarta o fim que for antes do começo
            sys_end = row['fim_dt'] if pd.notnull(row['fim_dt']) and row['fim_dt'] >= start_dt else pd.NaT
            
            # 2. Busca na linha do tempo mestre o início da próxima atividade (ligação ou outra pausa)
            next_dt = get_next_activity(row['OPERADOR'], start_dt)
            
            # 3. Cria uma lista vazia para armazenar todos os "finais possíveis" para essa pausa
            possible_ends = []
            
            # Se o sistema tem um horário de fim, adiciona na competição
            if pd.notnull(sys_end):
                possible_ends.append(sys_end)
                
            # Se achamos uma próxima atividade, adiciona na competição
            if pd.notnull(next_dt):
                possible_ends.append(next_dt)
                
            # 4. Verifica a que horas o consultor deveria deslogar
            exit_str = str(exit_map.get(row['OPERADOR'], "")).strip()
            if exit_str and ":" in exit_str:
                try:
                    # Constrói o datetime combinando a data da pausa com a hora de saída do cadastro
                    exit_dt = pd.to_datetime(f"{start_dt.strftime('%Y-%m-%d')} {exit_str}")
                    # Só considera válido se a saída for depois do começo da pausa
                    if exit_dt > start_dt:
                        possible_ends.append(exit_dt)
                except Exception:
                    pass
            
            # A função min() olha para a lista de candidatos e corta a pausa no horário mais cedo possível,
            # corrigindo sobreposições (ex: consultor esqueceu a pausa aberta e atendeu ligação)
            if possible_ends:
                return min(possible_ends)
                    
            # Para quando não tem próxima atividade, nem registro do sistema, nem fim de expediente cadastrado:
            # Se a pausa foi hoje, encerra ela no exato instante em que o robô está rodando. Se for de dias passados, anula a pausa
            return self.now if start_dt.date() == self.now.date() else start_dt

        # Aplica a função de sanitização em todas as linhas para sobrescrever a coluna de fim original
        df['fim_dt'] = df.apply(sanitize_break, axis=1)
        
        # Remove eventuais linhas duplicadas usando as colunas chave (operador, início e nome da pausa)
        subset_cols = ['OPERADOR', 'inicio_dt', 'PAUSA'] if 'PAUSA' in df.columns else ['OPERADOR', 'inicio_dt']
        return df.drop_duplicates(subset=subset_cols)