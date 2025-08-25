@echo off
setlocal EnableDelayedExpansion

echo ===============================================================
echo         GERENCIADOR DE SERVICO XML DOWNLOADER SIEG
echo ===============================================================
echo.

REM Verificar se está rodando como administrador
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRO] Este script precisa ser executado como Administrador.
    echo.
    echo Para resolver:
    echo 1. Clique com o botao direito no PowerShell ou CMD
    echo 2. Selecione "Executar como administrador"
    echo 3. Execute novamente este script.
    echo.
    pause
    exit /b 1
)

echo [OK] Executando como Administrador.
echo.

REM Verificar se o ambiente virtual existe
if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual nao encontrado em .venv\
    echo.
    echo Para resolver:
    echo 1. Execute: python -m venv .venv
    echo 2. Ative: .venv\Scripts\activate
    echo 3. Instale: pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo [OK] Ambiente virtual encontrado.
echo.

:MENU
echo ===============================================================
echo                        MENU PRINCIPAL
echo ===============================================================
echo.
echo Escolha uma opcao:
echo.
echo [1] Validar ambiente
echo [2] Instalar servico Windows
echo [3] Iniciar servico
echo [4] Ver status do servico
echo [5] Parar servico
echo [6] Remover servico
echo [0] Sair
echo.
set /p choice="Digite sua opcao (0-6): "

if "%choice%"=="0" goto END
if "%choice%"=="1" goto VALIDATE
if "%choice%"=="2" goto INSTALL
if "%choice%"=="3" goto START
if "%choice%"=="4" goto STATUS
if "%choice%"=="5" goto STOP
if "%choice%"=="6" goto REMOVE

echo [ERRO] Opcao invalida. Tente novamente.
pause
goto MENU

:VALIDATE
echo.
echo ===============================================================
echo                   VALIDANDO AMBIENTE
echo ===============================================================
echo.
.venv\Scripts\python.exe scripts\xml_service_manager.py validate
echo.
pause
goto MENU

:INSTALL
echo.
echo ===============================================================
echo                  INSTALANDO SERVICO
echo ===============================================================
echo.
echo [ATENCAO] O servico sera configurado para:
echo   - Executar automaticamente ao iniciar o Windows
echo   - Reiniciar automaticamente em caso de falha
echo   - Executar em modo loop continuo
echo   - Ignorar taxas de falha (ultra-robusto)
echo.
set /p confirm="Deseja continuar? (S/N): "
if /i not "%confirm%"=="S" goto MENU

.venv\Scripts\python.exe scripts\xml_service_manager.py install
echo.
echo [OK] Instalacao concluida!
echo.
set /p start_now="Deseja iniciar o servico agora? (S/N): "
if /i "%start_now%"=="S" (
    .venv\Scripts\python.exe scripts\xml_service_manager.py start
)
echo.
pause
goto MENU

:START
echo.
echo ===============================================================
echo                   INICIANDO SERVICO
echo ===============================================================
echo.
.venv\Scripts\python.exe scripts\xml_service_manager.py start
echo.
pause
goto MENU

:STATUS
echo.
echo ===============================================================
echo                   STATUS DO SERVICO
echo ===============================================================
echo.
.venv\Scripts\python.exe scripts\xml_service_manager.py status
echo.
pause
goto MENU

:STOP
echo.
echo ===============================================================
echo                    PARANDO SERVICO
echo ===============================================================
echo.
set /p confirm="Tem certeza que deseja parar o servico? (S/N): "
if /i not "%confirm%"=="S" goto MENU

.venv\Scripts\python.exe scripts\xml_service_manager.py stop
echo.
pause
goto MENU

:REMOVE
echo.
echo ===============================================================
echo                   REMOVENDO SERVICO
echo ===============================================================
echo.
echo [ATENCAO] Esta acao ira:
echo   - Parar o servico (se estiver rodando)
echo   - Remover completamente o servico do Windows
echo   - O servico nao iniciara mais automaticamente
echo.
set /p confirm="Tem certeza que deseja remover o servico? (S/N): "
if /i not "%confirm%"=="S" goto MENU

.venv\Scripts\python.exe scripts\xml_service_manager.py remove
echo.
pause
goto MENU

:END
echo.
echo ===============================================================
echo                        SAINDO
echo ===============================================================
echo.
echo Obrigado por usar o XML Downloader SIEG!
echo.
echo Para verificar logs:
echo   - Logs do servico: logs\service.log
echo   - Logs da aplicacao: logs\global.log
echo.
pause 