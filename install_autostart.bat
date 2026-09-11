@echo off
:: Registra o PlayLine para iniciar sozinho no logon do Windows (Agendador de
:: Tarefas). Rode uma vez, como administrador, na maquina da emissora, depois
:: do build.bat. Combinado com o auto-resume (checkpoint) do servidor, uma
:: queda de energia volta ao ar sem intervencao: o Windows sobe, loga, o
:: PlayLine abre e retoma o item que estava no ar.
::
:: Uso:  install_autostart.bat          -> instala
::       install_autostart.bat remove   -> remove a tarefa
setlocal
set "EXE=%~dp0backend\dist\PlayLine\PlayLine.exe"
set "TASK=PlayLine"

if /i "%~1"=="remove" (
    schtasks /delete /tn "%TASK%" /f
    exit /b %errorlevel%
)

if not exist "%EXE%" (
    echo ERRO: %EXE% nao encontrado. Rode build.bat primeiro.
    exit /b 1
)

:: /delay 30s da tempo pra rede, placa de captura e audio ficarem prontos
schtasks /create /tn "%TASK%" /tr "\"%EXE%\"" /sc onlogon /rl highest /delay 0000:30 /f
if errorlevel 1 (
    echo ERRO ao criar a tarefa. Execute este script como administrador.
    exit /b 1
)
echo Tarefa "%TASK%" criada: o PlayLine inicia 30s apos o logon.
echo Para o autostart funcionar sem ninguem na frente da maquina, configure
echo logon automatico do Windows (netplwiz) na conta que opera o playout.
endlocal
