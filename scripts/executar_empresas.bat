:: executar_empresas.bat (processa N primeiras empresas - Padrão: 3)
@echo off

:: Define o limite. Se nenhum argumento for passado (%1), usa 3.
set LIMIT=%1
if [%LIMIT%]==[] set LIMIT=3

echo Processando as primeiras %LIMIT% empresas...

:: Ativa o ambiente virtual e executa o script com a URL e o limite
:: O script agora roda em loop contínuo por padrão.
call .venv\Scripts\activate && python -m app.run --excel="https://paulicon1-my.sharepoint.com/:x:/g/personal/marco_fiscal_paulicon_com_br/ETn_H2eKSChJpUtk7rbccSwB08_zGcoxB4KyHX64ggwFyQ?e=WdMz8a&download=1" --limit=%LIMIT%

:: Mantém a janela aberta no final para ver erros
cmd /k 