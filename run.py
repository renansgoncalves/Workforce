import subprocess, sys, argparse, time
from datetime import datetime

def run(label, path, *args):
    print(f"\n>> {label}...")
    if subprocess.run([sys.executable, path, *args]).returncode:
        sys.exit(f"\n[!] Falha no {label}.")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date"); p.add_argument("--only-process", action="store_true")
    args = p.parse_args()

    if not args.only_process:
        while (ans := input("[?] Baixar novos dados? (s/n): ").lower().strip()) not in ['s', 'n', '']:
            print("[!] Responda apenas 's' ou 'n'.")

        if ans == 'n':
            args.only_process = True
        elif not args.date:
            while True:
                d = input("[?] Data (DD/MM/YYYY) ou Enter p/ hoje: ").strip()
                if not d: break 
                try:
                    datetime.strptime(d, "%d/%m/%Y")
                    args.date = d
                    break
                except ValueError:
                    print("[!] Formato inválido. Use DD/MM/YYYY (ex: 06/09/2016).")

    start = time.time()

    if not args.only_process:
        run("SCRAPER", "scraper/main.py", *(['--date', args.date] if args.date else []))
    else:
        print("\n>> Scraper ignorado.")

    run("ANÁLISE", "analysis/main.py")

    print(f"\n{'*' * 24}")
    print(f"\nTempo decorrido: {int((t := time.time() - start) // 60)}m {int(t % 60)}s")
    print(f"\n{'*' * 24}")

if __name__ == "__main__":
    main()