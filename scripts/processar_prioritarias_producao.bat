@echo off
REM =====================================================
REM Script para processar empresas prioritárias na produção
REM =====================================================

echo ==========================================
echo PROCESSAMENTO DE EMPRESAS PRIORITARIAS
echo ==========================================
echo.

REM Navegar para a pasta do projeto na produção
cd /d C:\Users\operacional04\Downloads\Projeto-XML

REM Ativar ambiente virtual
echo Ativando ambiente virtual...
call .venv\Scripts\activate

REM Executar script Python com caminho correto
echo.
echo Executando processamento das empresas prioritarias...
echo.
python -c "
import sys
from pathlib import Path
sys.path.append('.')

# Importar as funções necessárias
from processar_empresas_prioritarias_v2 import EMPRESAS_PRIORITARIAS, criar_excel_filtrado
import subprocess

# Usar o arquivo correto da produção
excel_original = Path('data/SIEG (3).xlsx')
excel_prioritarias = Path('empresas_prioritarias_temp.xlsx')

if not excel_original.exists():
    print(f'ERRO: Arquivo não encontrado: {excel_original}')
    sys.exit(1)

print(f'Usando arquivo Excel: {excel_original}')

# Criar Excel filtrado
criar_excel_filtrado(excel_original, excel_prioritarias)

print('\n' + '='*60)
print('Iniciando processamento das empresas prioritárias...')
print('='*60 + '\n')

# Chamar o script principal com o Excel filtrado
result = subprocess.run([
    sys.executable,
    'app/run.py',
    str(excel_prioritarias)
])

# Limpar arquivo temporário
if excel_prioritarias.exists():
    excel_prioritarias.unlink()
    print(f'\nArquivo temporário removido: {excel_prioritarias}')

sys.exit(result.returncode)
"

echo.
echo ==========================================
echo PROCESSAMENTO CONCLUIDO!
echo ==========================================
echo.
echo Se houver erro, a janela permanecera aberta para debug.