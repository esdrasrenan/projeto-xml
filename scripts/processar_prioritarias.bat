@echo off
REM =====================================================
REM Script simplificado para processar empresas prioritárias
REM =====================================================

echo ==========================================
echo PROCESSAMENTO DE EMPRESAS PRIORITARIAS
echo ==========================================
echo.
echo Este script processa apenas as 190 empresas
echo que tiveram problemas devido ao travamento.
echo.

REM Ativar ambiente virtual
echo [1/2] Ativando ambiente virtual...
call .venv\Scripts\activate

REM Executar script Python
echo.
echo [2/2] Executando processamento...
echo.
python processar_empresas_prioritarias_v2.py

if errorlevel 1 (
    echo.
    echo ==========================================
    echo ERRO DURANTE O PROCESSAMENTO!
    echo ==========================================
    echo.
    echo Pressione qualquer tecla para fechar...
    pause >nul
) else (
    echo.
    echo ==========================================
    echo PROCESSAMENTO CONCLUIDO COM SUCESSO!
    echo ==========================================
    echo.
    echo O arquivo fechara em 10 segundos...
    timeout /t 10 /nobreak >nul
)