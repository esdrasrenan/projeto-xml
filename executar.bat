@echo off
setlocal
echo ================================================
echo   EXECUTANDO EM MODO LOOP CONTINUO ROBUSTO
echo ================================================
echo.
echo O script sera executado indefinidamente sem pausas.
echo Pressione Ctrl+C na janela do script Python para interromper.
echo.

REM Evita warnings desnecessários do Python
set PYTHONWARNINGS=ignore

REM FORÇA Python a não usar cache bytecode
set PYTHONDONTWRITEBYTECODE=1

REM Verifica se o ambiente virtual existe
if not exist ".venv\Scripts\activate.bat" (
    echo ERRO: Ambiente virtual nao encontrado em .venv\Scripts\
    echo Execute primeiro: python -m venv .venv
    pause
    exit /b 1
)

echo Ativando ambiente virtual...
call .venv\Scripts\activate
if errorlevel 1 (
    echo ERRO: Falha ao ativar ambiente virtual!
    pause
    exit /b 1
)

echo Ambiente virtual ativado com sucesso!
echo.

REM URL do SharePoint - modifique se necessário
set "EXCEL_URL=https://paulicon1-my.sharepoint.com/:x:/g/personal/marco_fiscal_paulicon_com_br/ETn_H2eKSChJpUtk7rbccSwB08_zGcoxB4KyHX64ggwFyQ?e=WdMz8a&download=1"

echo Iniciando execucao do script Python em modo loop...
echo Excel URL: %EXCEL_URL%
echo.
echo ================================================
echo   IMPORTANTE: O script agora e ULTRA-ROBUSTO
echo   - NUNCA para por conta propria (exceto Ctrl+C)
echo   - Captura e ignora sys.exit em modo loop
echo   - Continua mesmo com falhas de empresas
echo ================================================
echo.

REM Executa o Python - separando os comandos para maior robustez
python -m app.run --excel "%EXCEL_URL%" --loop --loop-interval 0 --log-level INFO

REM Se chegou aqui, houve encerramento (normal ou erro)
echo.
echo ================================================
echo   O script Python foi encerrado
echo ================================================
echo.
echo Possiveis causas:
echo 1. Ctrl+C pressionado (normal)
echo 2. Erro critico nao capturado (verificar logs)
echo 3. Problema no ambiente virtual
echo 4. Problema na URL do Excel
echo.
echo Verificar logs em: logs\global.log
echo.
pause