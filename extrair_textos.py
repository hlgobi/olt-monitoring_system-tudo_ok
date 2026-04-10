import os, sys, subprocess
from pathlib import Path

BINARIAS = {'.exe','.dll','.png','.jpg','.mp4','.zip','.pdf','.pyc'}
DIR_IGNORAR = {'__pycache__','.venv','venv','env','node_modules','.git','.idea','dist'}
PADROES_AUX = ['log','logs','history','cache','tmp','temp','backup','debug','test','teste','tests','spec','mock','sample','demo']

def copiar_clipboard(texto):
    try:
        import pyperclip
        pyperclip.copy(texto)
        return True
    except (ImportError, Exception):
        pass
    try:
        if sys.platform == 'win32':
            subprocess.run(['powershell', '-Command', 
                '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $input | Set-Clipboard'],
                input=texto, text=True, encoding='utf-8', check=True)
            return True
        elif sys.platform == 'darwin':
            subprocess.run(['pbcopy'], input=texto, text=True, encoding='utf-8', check=True)
            return True
        else:
            subprocess.run(['xclip','-selection','clipboard'], input=texto, text=True, encoding='utf-8', check=True)
            return True
    except Exception:
        return False

def gerar_arvore(raiz, saida, ignorar_dirs):
    raiz = Path(raiz).resolve()
    saida.write(f"\nESTRUTURA: {raiz.name}\n{'='*60}\n")
    def _linhas(p, prefixo=''):
        try:
            itens = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return [f"{prefixo}[acesso negado]"]
        linhas = []
        for i, item in enumerate(itens):
            ultimo = (i == len(itens)-1)
            if item.is_dir():
                if ignorar_dirs and (item.name in DIR_IGNORAR or item.name.startswith('.')):
                    continue
                linhas.append(f"{prefixo}{'└── ' if ultimo else '├── '}{item.name}/")
                linhas.extend(_linhas(item, prefixo+('    ' if ultimo else '│   ')))
            else:
                linhas.append(f"{prefixo}{'└── ' if ultimo else '├── '}{item.name}")
        return linhas
    for linha in _linhas(raiz):
        saida.write(linha+'\n')
    saida.write('='*60+'\n\n')

def extrair_textos(pasta, extensoes=None, saida_txt='textos.txt', ignorar_dirs=True, processar_aux=False, copiar=False, verbose=False):
    raiz = Path(pasta).resolve()
    saida_abs = Path(saida_txt).resolve()
    if extensoes:
        extensoes = [e.lower() if e.startswith('.') else f'.{e.lower()}' for e in extensoes]
    proc = bin_skip = aux_skip = 0
    with open(saida_txt, 'w', encoding='utf-8') as out:
        gerar_arvore(raiz, out, ignorar_dirs)
        out.write("CONTEÚDO DOS ARQUIVOS\n"+'='*60+'\n\n')
        for arq in raiz.rglob('*'):
            if not arq.is_file() or arq.resolve() == saida_abs: continue
            if ignorar_dirs and any(p in DIR_IGNORAR or p.startswith('.') for p in arq.parent.parts[len(raiz.parts):]): continue
            if extensoes and arq.suffix.lower() not in extensoes: continue
            if not extensoes and arq.suffix.lower() in BINARIAS:
                bin_skip += 1
                if verbose: print(f'  [~] Binário: {arq.relative_to(raiz)}')
                continue
            if not processar_aux and any(p in str(arq).lower() for p in PADROES_AUX):
                aux_skip += 1
                if verbose: print(f'  [~] Auxiliar: {arq.relative_to(raiz)}')
                continue
            try:
                with open(arq, 'r', encoding='utf-8', errors='replace') as f:
                    conteudo = f.read()
            except Exception:
                continue
            out.write(f"\n\n{'='*60}\nARQUIVO: {arq.relative_to(raiz)}\n{'='*60}\n\n{conteudo}")
            proc += 1
            print(f'  [+] {arq.relative_to(raiz)}')
    print(f"\nProcessados: {proc} | Binários: {bin_skip} | Auxiliares: {aux_skip}")
    if copiar:
        with open(saida_txt, 'r', encoding='utf-8') as f:
            ok = copiar_clipboard(f.read())
        if ok:
            print("✅ Copiado para a área de transferência.")
        else:
            print("❌ Falha na cópia automática. Abra o arquivo gerado e copie manualmente.")
            print(f"   Caminho: {saida_abs}")

if __name__ == '__main__':
    print("=== EXTRATOR DE TEXTOS + MAPEAMENTO ===\n")
    pasta = input("Pasta: ").strip() or sys.exit()
    ign_dir = input("Ignorar .venv/__pycache__/.git? (S/n): ").lower() != 'n'
    proc_aux = input("Processar logs/histórico/testes? (s/N): ").lower() in ('s','sim')
    ext = input("Extensões (ex: py,json,txt) ou Enter: ").strip()
    exts = [e.strip() for e in ext.split(',')] if ext else None
    nome = input("Arquivo saída (textos.txt): ").strip() or 'textos.txt'
    copiar = input("Copiar para clipboard? (s/N): ").lower() in ('s','sim')
    verb = input("Modo verbose? (s/N): ").lower() in ('s','sim')
    extrair_textos(pasta, exts, nome, ign_dir, proc_aux, copiar, verb)
    print("\nConcluído!")