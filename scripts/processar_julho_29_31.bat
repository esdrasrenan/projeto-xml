@echo off
REM ======================================================
REM Script para processar dias 29, 30 e 31 de julho 2025
REM Não altera state.json - apenas baixa XMLs faltantes
REM ======================================================

echo ==========================================
echo PROCESSAMENTO ESPECIFICO - JULHO 29-31
echo ==========================================
echo.
echo Este script ira:
echo  - Processar TODAS as empresas
echo  - Focar APENAS em julho 2025
echo  - Baixar APENAS dias 29, 30 e 31
echo  - NAO alterar state.json
echo  - Baixar apenas XMLs que faltam
echo.
echo IMPORTANTE: Este processo pode demorar varias horas!
echo.

REM Ativar ambiente virtual
echo Ativando ambiente virtual...
call .venv\Scripts\activate

REM Executar processamento
echo.
echo Iniciando processamento dos dias 29, 30 e 31 de julho...
echo.
python processar_julho_29_31.py

echo.
echo ==========================================
echo PROCESSAMENTO FINALIZADO!
echo ==========================================
echo.
pause