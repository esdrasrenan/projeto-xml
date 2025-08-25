@echo off
REM Wrapper para o servico Windows XML Downloader SIEG
REM Este arquivo garante que o servico seja executado no diretorio correto

REM Obter o diretorio onde este script esta localizado
set SCRIPT_DIR=%~dp0

REM Mudar para o diretorio pai (raiz do projeto)
cd /d "%SCRIPT_DIR%.."

REM Executar o Python com todos os parametros necessarios
"%CD%\.venv\Scripts\python.exe" "%CD%\app\run.py" --excel "https://paulicon1-my.sharepoint.com/:x:/g/personal/marco_fiscal_paulicon_com_br/ETn_H2eKSChJpUtk7rbccSwB08_zGcoxB4KyHX64ggwFyQ?e=WdMz8a&download=1" --loop --loop-interval 0 --log-level INFO --ignore-failure-rates

REM Se o script Python encerrar por algum motivo, o servico tambem encerrara
exit /b %ERRORLEVEL% 