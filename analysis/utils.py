import pandas as pd
import urllib.request
from PIL import Image
from io import BytesIO
import re

def format_to_ms(minutes_float: float) -> str:
    """Converte minutos decimais para o formato de string legível (HH:MM:SS)."""
    if pd.isna(minutes_float) or minutes_float <= 0.0:
        return "0:00:00"
        
    total_seconds = int(round(minutes_float * 60.0))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if hours >= 1:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"0:{minutes:02d}:{seconds:02d}"

def time_str_to_minutes(time_str: str) -> float:
    """Transforma qualquer string de tempo ('08:00' ou '8h') em minutos totais float."""
    try:
        if pd.isna(time_str):
            return 0.0
            
        time_str = str(time_str).strip()
        if ':' in time_str:
            hours, minutes = map(int, time_str.split(':')[:2])
            return float(hours * 60 + minutes)
            
        numeric_only = re.sub(r'\D', '', time_str)
        return float(int(numeric_only) * 60) if numeric_only else 0.0
    except Exception:
        return 0.0

def fetch_avatar(url: str) -> BytesIO:
    """Faz o download seguro e o redimensionamento da imagem de perfil hospedada no Drive."""
    download_url = url.replace("export=view", "export=download")
    request = urllib.request.Request(download_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    with urllib.request.urlopen(request) as response:
        image = Image.open(BytesIO(response.read()))
        image.thumbnail((95, 95), Image.Resampling.LANCZOS)
        
        image_byte_array = BytesIO()
        image.save(image_byte_array, format='PNG')
        return image_byte_array