import os

OUT_DIR = os.path.join("output")
os.makedirs(OUT_DIR, exist_ok=True)

PATHS = {
    'engagements': os.path.join("data", "engagements.csv"),
    'breaks': os.path.join("data", "breaks.csv"),
    'consultores_info': os.path.join("data", "consultores_info.csv"),
    'sheets_out': os.path.join(OUT_DIR, "sheets_relatorio.xlsx"),
    'excel_out': os.path.join(OUT_DIR, "excel_relatorio.xlsx")
}

STATUS_PROD = {"Negociando", "Agendamento", "CLIENTE JA FECHADO", "ENGANO", "FALECIDO", "LIGACAO_CAIU_COM_CLIENTE", "LIGAR DEPOIS", "MARGEM_NEGATIVA", "NAO LIGAR - LIGACAO IMPORTUNA", "NAO_ASSINA", "NAO_ESTA", "PROPOSTA_WHATSAPP", "RECUSOU_OUVIR_A_PROPOSTA", "SEM INTERESSE", "SEM_MARGEM", "SEM_PORT", "SEM_POSSIBILIDADES", "VENDA_FEITA"}
STATUS_NEG = {"SEM INTERESSE", "RECUSOU_OUVIR_A_PROPOSTA"}
STATUS_POS = {"Negociando", "PROPOSTA_WHATSAPP"}
CPC_IGNORE = {"NAO_ESTA", "FALECIDO", "ENGANO"}

COL_ORDER = [
    'DATA', 'CONSULTOR', 'FOTO', 'EQUIPE',
    'TEMPO NÃO TABELADO', 'TEMPO DE OCIOSIDADE', 'TEMPO EM LIGAÇÃO', 'TEMPO TOTAL DE PAUSA',
    'NÚMERO DE PAUSAS', 'NÚMERO DE ACIONAMENTOS', 'ACIONAMENTOS PRODUTIVOS', 'CPC', 'PROPOSTAS', 
    'STATUS NEGATIVOS', 'STATUS POSITIVOS', '% CONVERSÃO', 'OBSERVAÇÕES', 'VENDA FEITA', 
    'ALMOÇO', 'BANHEIRO',
    'AGENTE NÃO TABULOU', 'ENGANO', '% ENGANO', 'SEM POSSIBILIDADE', 'SEM MARGEM', 'SEM PORT'
]