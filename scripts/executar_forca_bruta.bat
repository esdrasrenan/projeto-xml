@echo off
setlocal
echo ================================================
echo   MODO FORÇA-BRUTA: REINICIO AUTOMATICO
echo ================================================
echo.
echo Este script GARANTIRA que o Python nunca pare:
echo - Reinicia automaticamente se o Python encerrar
echo - Mostra erros detalhados antes de reiniciar
echo - Para apenas com Ctrl+C NESTA janela
echo.
echo ================================================
echo   OPCOES DISPONIVEIS:
echo   1. AUTOMATICO - Reinicia em 10 segundos
echo   2. MANUAL - Aguarda Enter para reiniciar
echo ================================================
echo.
set /p MODO="Digite 1 para AUTOMATICO ou 2 para MANUAL (default=1): "
if "%MODO%"=="" set MODO=1
if "%MODO%"=="2" (
    echo MODO MANUAL selecionado - aguardara Enter para reiniciar
    set PAUSE_MODE=1
) else (
    echo MODO AUTOMATICO selecionado - reinicia em 10 segundos
    set PAUSE_MODE=0
)
echo.

REM Navegar para o diretório raiz do projeto
cd /d "%~dp0\.."

REM Evita warnings desnecessários do Python
set PYTHONWARNINGS=ignore

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

set RESTART_COUNT=0

:loop_principal
set /a RESTART_COUNT+=1
echo.
echo ================================================
echo   INICIALIZACAO #%RESTART_COUNT%
echo ================================================
echo.
echo Excel URL: %EXCEL_URL%
echo Horario: 
powershell -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"
echo.

REM Executa o Python
python -m app.run --excel "%EXCEL_URL%" --loop --loop-interval 0 --log-level INFO

REM Captura o código de saída
set PYTHON_EXIT_CODE=%ERRORLEVEL%

REM Se chegou aqui, o Python encerrou (por qualquer motivo)
echo.
echo ================================================
echo   Python encerrou (Inicializacao #%RESTART_COUNT%)
echo ================================================
echo.
echo Codigo de saida: %PYTHON_EXIT_CODE%
echo Horario do encerramento: 
powershell -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"
echo.

REM Analisar código de saída
if %PYTHON_EXIT_CODE%==0 (
    echo Status: Encerramento NORMAL
    echo Motivo provavel: Ctrl+C no Python
) else if %PYTHON_EXIT_CODE%==1 (
    echo Status: ERRO LEVE
    echo Motivo provavel: Taxa de falha elevada ou problema de configuracao
) else if %PYTHON_EXIT_CODE%==2 (
    echo Status: ERRO CRITICO
    echo Motivo provavel: Taxa de falha critica ou erro fatal
) else (
    echo Status: ERRO DESCONHECIDO ^(%PYTHON_EXIT_CODE%^)
    echo Motivo provavel: Excecao nao capturada ou problema do sistema
)

echo.
echo Outros motivos possiveis:
echo - Problema temporario na rede/API
echo - Problema na URL do Excel
echo - Erro nao capturado no codigo
echo - Problema no ambiente virtual
echo.

REM Mostrar últimas linhas do log se existir
if exist "logs\global.log" (
    echo ================================================
    echo   ULTIMAS 10 LINHAS DO LOG:
    echo ================================================
    powershell -Command "Get-Content 'logs\global.log' -Tail 10"
    echo.
)

REM Decidir como pausar baseado no modo
if %PAUSE_MODE%==1 (
    echo ================================================
    echo   MODO MANUAL ATIVO
    echo ================================================
    echo.
    echo Opcoes:
    echo 1. Pressione ENTER para REINICIAR
    echo 2. Pressione Ctrl+C para SAIR
    echo.
    pause > nul
    echo Reiniciando Python...
) else (
    echo ================================================
    echo   MODO AUTOMATICO ATIVO
    echo ================================================
    echo.
    echo Reiniciando em 10 segundos...
    echo Pressione Ctrl+C AGORA se nao quiser reiniciar!
    echo.
    timeout /t 10 /nobreak > nul
    echo Reiniciando Python...
)

goto loop_principal 