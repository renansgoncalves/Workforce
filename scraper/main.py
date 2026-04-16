import os, sys, argparse
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

def parse_target_date(date_str):
    """Tenta converter a data de DD/MM/YYYY ou YYYY-MM-DD para o padrão DD/MM/YYYY."""
    if not date_str:
        return datetime.now().strftime("%d/%m/%Y")
    
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
            
    sys.exit(f"[!] Erro: Formato de data '{date_str}' inválido. Use DD/MM/YYYY.")

def run_scraper(date_raw=None):
    target_date = parse_target_date(date_raw)
    
    user = os.getenv("SITE_USER")
    pw = os.getenv("SITE_PASS")
    out_dir = "data"
    os.makedirs(out_dir, exist_ok=True)

    with sync_playwright() as p:
        print(f">> Iniciando scraper...")
        print(f">> Buscando dados para a data: {target_date}...")
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # 1. Login
        page.goto("http://sistema.joytec.com.br/login.php")
        page.fill('input[name="login"]', user)
        page.fill('input[name="senha"]', pw)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # 2. Relatório de acionamentos
        print(f">> Baixando acionamentos...")
        page.goto("http://sistema.joytec.com.br/index.php?page=acionamentos")
        page.wait_for_selector("#agenda")
        page.fill("#agenda", target_date)
        page.fill("#agendafim", target_date)
        
        # Ajuste de menu para liberar o seletor
        page.click(".nav.pull-right.top-menu")
        page.wait_for_timeout(500)
        page.select_option("select", label="Geral")
        page.click("#pesquisar_acionamento", force=True)

        try:
            icon_eng = 'button:has-text("Exportação Padrão")'
            page.wait_for_selector(icon_eng, timeout=50000)
            with page.expect_download() as dl:
                page.click(icon_eng, timeout=100000)
            dl.value.save_as(os.path.join(out_dir, "engagements.csv"))
            print("OK: engagements.csv")
        except Exception as e:
            print(f"[!] Erro ao tentar baixar acionamentos: {e}")

        # 3. Relatório de pausas
        print(f">> Baixando pausas...")
        page.goto("http://sistema.joytec.com.br/index.php?page=relatorio_pausa")
        page.wait_for_selector('input[name="de"]')
        page.fill('input[name="de"]', target_date)
        page.fill('input[name="ate"]', target_date)
        
        page.click(".nav.pull-right.top-menu")
        page.wait_for_timeout(500)
        page.click("#enviar", force=True)

        try:
            icon_brk = 'input[src*="CSV.png"]'
            page.wait_for_selector(icon_brk, timeout=15000)
            with page.expect_download() as dl:
                page.click(icon_brk)
            dl.value.save_as(os.path.join(out_dir, "breaks.csv"))
            print("OK: breaks.csv")
        except Exception as e:
            print(f"[!] Erro ao tentar baixar pausas: {e}")

        browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Data alvo")
    args = parser.parse_args()
    
    run_scraper(args.date)