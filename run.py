import subprocess
import sys
import argparse
import time
import tkinter as tk
from tkinter import messagebox
from tkcalendar import Calendar
from datetime import timedelta  # Importação necessária para a matemática de dias

SCRAPER_SCRIPT = "scraper/main.py"
ANALYSIS_SCRIPT = "analysis/main.py"

def run_script(name: str, path: str, *args):
    """Executa um script Python em um subprocesso de forma segura."""
    print(f"\n>> {name}...")
    if subprocess.run([sys.executable, path, *args]).returncode != 0:
        sys.exit(f"\n[!] Falha fatal no módulo: {name}.")

def prompt_for_date(root: tk.Tk) -> str:
    """Monta a interface do calendário e retorna a data escolhida."""
    top = tk.Toplevel(root)
    top.title("Selecionar data")
    top.geometry("300x260")
    top.resizable(False, False)
    top.attributes('-topmost', True)
    
    top.update_idletasks()
    root.eval(f'tk::PlaceWindow {str(top)} center')

    selected_date = [""]

    def on_closing(event=None):
        selected_date[0] = None
        top.destroy()

    top.protocol("WM_DELETE_WINDOW", on_closing)
    top.bind("<Escape>", on_closing) # Pressionar Esc cancela a operação

    cal = Calendar(top, selectmode='day', date_pattern='dd/mm/yyyy')
    cal.pack(pady=15, padx=20)
    
    # --- NAVEGAÇÃO PERSONALIZADA COM SETAS ---
    def move_date(event):
        try:
            # Pega a data atual selecionada como um objeto de data real
            current_date = cal.selection_get()
            
            # Adiciona ou subtrai dias com base na seta pressionada
            if event.keysym == 'Left':
                new_date = current_date - timedelta(days=1)
            elif event.keysym == 'Right':
                new_date = current_date + timedelta(days=1)
            elif event.keysym == 'Up':
                new_date = current_date - timedelta(days=7)
            elif event.keysym == 'Down':
                new_date = current_date + timedelta(days=7)
            else:
                return

            # Atualiza o calendário visualmente
            cal.selection_set(new_date)
            cal.see(new_date) # Garante que a página mude de mês se passar do dia 30/31
        except Exception:
            pass

    # Associa as setinhas do teclado à nossa nova função de movimento
    top.bind('<Left>', move_date)
    top.bind('<Right>', move_date)
    top.bind('<Up>', move_date)
    top.bind('<Down>', move_date)

    cal.focus_set()

    def confirm(event=None):
        selected_date[0] = cal.get_date()
        top.destroy()

    # Associa a tecla Enter à função de confirmar
    top.bind("<Return>", confirm)

    btn = tk.Button(top, text="Confirmar", command=confirm, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
    btn.pack(pady=10)
    
    root.wait_window(top)
    
    if selected_date[0] is None:
        root.destroy()
        sys.exit("\n[!] Operação cancelada pelo usuário.")
        
    return selected_date[0]

def get_config() -> tuple[bool, str]:
    """Define as configurações lendo os argumentos do terminal ou usando a interface gráfica."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="")
    parser.add_argument("--only-process", action="store_true")
    args = parser.parse_args()

    if args.only_process or args.date:
        return not args.only_process, args.date

    root = tk.Tk()
    root.withdraw()

    should_download = messagebox.askyesno("Atualização", "Deseja baixar novos dados da web?", parent=root)
    
    if should_download is None:
        root.destroy()
        sys.exit("\n[!] Operação cancelada pelo usuário.")

    target_date = prompt_for_date(root) if should_download else ""
    
    root.destroy() 
    return should_download, target_date

def main():
    should_download, target_date = get_config()

    start_time = time.time()

    if should_download:
        args = ['--date', target_date] if target_date else []
        run_script("SCRAPER", SCRAPER_SCRIPT, *args)
    else:
        print("\n>> Execução do Scraper ignorada.")

    run_script("ETL", ANALYSIS_SCRIPT)

    mins, secs = divmod(time.time() - start_time, 60)
    
    print(f"\n{'*' * 30}")
    print(f"\nTempo total decorrido: {int(mins)}m {int(secs)}s")
    print(f"\n{'*' * 30}")

if __name__ == "__main__":
    main()