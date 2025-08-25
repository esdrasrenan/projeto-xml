@echo off
echo ===============================================================
echo         TESTE DO WRAPPER DO SERVICO
echo ===============================================================
echo.
echo Este script testa se o wrapper esta funcionando corretamente.
echo Ele executara o script Python por alguns segundos para verificar.
echo.
echo Pressione Ctrl+C para parar o teste.
echo.
pause

REM Executar o wrapper
call "%~dp0service_wrapper.bat"

echo.
echo ===============================================================
echo         TESTE CONCLUIDO
echo ===============================================================
echo.
echo Se voce viu os logs do script Python acima, o wrapper esta OK!
echo Se houve erros, verifique o arquivo service_wrapper.bat
echo.
pause 