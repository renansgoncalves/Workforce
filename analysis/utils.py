import pandas as pd
import urllib.request
from PIL import Image
from io import BytesIO
import re

def format_to_ms(m_float: float) -> str:
    """Converte minutos decimais para o formato HH:MM:SS."""
    if pd.isna(m_float) or m_float <= 0: return "0:00:00"
    s = int(round(m_float * 60))
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}" if s >= 3600 else f"0:{s//60:02d}:{s%60:02d}"

def time_str_to_minutes(time_str: str) -> int:
    """Transforma qualquer string de tempo ('08:00' ou '8h') em minutos totais."""
    try:
        if pd.isna(time_str): return 0
        time_str = str(time_str).strip()
        if ':' in time_str:
            h, m = map(int, time_str.split(':')[:2])
            return h * 60 + m
        nums = re.sub(r'\D', '', time_str)
        return int(nums) * 60 if nums else 0
    except: return 0

def fetch_avatar(url: str) -> BytesIO:
    """Faz o download e redimensionamento da imagem de perfil do Drive."""
    req = urllib.request.Request(url.replace("export=view", "export=download"), headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as resp:
        img = Image.open(BytesIO(resp.read()))
        img.thumbnail((95, 95), Image.Resampling.LANCZOS)
        img_byte_arr = BytesIO()
        img.save(img_byte_arr, format='PNG')
        return img_byte_arr