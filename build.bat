@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ==========================================
echo  PlayLine -- Build de Distribuicao
echo ==========================================
echo.

:: Verifica PyInstaller
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Instalando PyInstaller...
    pip install pyinstaller
    if errorlevel 1 ( echo ERRO: falha ao instalar PyInstaller & exit /b 1 )
)

:: Limpa builds anteriores
if exist "backend\build"    rmdir /s /q "backend\build"
if exist "backend\dist"     rmdir /s /q "backend\dist"
if exist "playingest\build" rmdir /s /q "playingest\build"
if exist "playingest\dist"  rmdir /s /q "playingest\dist"

echo [1/5] Compilando daemon (PlayLine-daemon.exe)...
cd backend

:: Converte logo PNG para ICO (requer Pillow)
echo Gerando icone...
python -c "from PIL import Image; img=Image.open('logos/FavPlayline.png').convert('RGBA'); img.save('FavPlayline.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(256,256)])"
if errorlevel 1 ( echo AVISO: nao foi possivel gerar o icone, continuando sem ele... )
set ICON_ARG=
if exist "FavPlayline.ico" ( set ICON_ARG=--icon "FavPlayline.ico" )
python -m PyInstaller --onefile --noconsole --noconfirm ^
    --name PlayLine-daemon ^
    --add-binary "libmpv-2.dll;." ^
    --paths "." ^
    %ICON_ARG% ^
    mpv_daemon.py
if errorlevel 1 ( echo. & echo ERRO ao compilar daemon & cd .. & pause & exit /b 1 )

echo.
echo [2/5] Compilando servidor principal (PlayLine.exe)...

set FFMPEG_ARG=
if exist "ffmpeg.exe" ( set FFMPEG_ARG=--add-binary "ffmpeg.exe;." )

python -m PyInstaller --onedir --noconsole --noconfirm ^
    --name PlayLine ^
    --add-binary "libmpv-2.dll;." ^
    --add-data "../frontend;frontend" ^
    --paths "." ^
    --collect-all webview ^
    --hidden-import clr ^
    %FFMPEG_ARG% ^
    %ICON_ARG% ^
    main.py
if errorlevel 1 ( echo. & echo ERRO ao compilar servidor & cd .. & pause & exit /b 1 )

echo.
echo [3/5] Compilando cliente (PlayLine-Client.exe)...
python -m PyInstaller --onefile --noconsole --noconfirm ^
    --name PlayLine-Client ^
    --add-data "logos;logos" ^
    --collect-all webview ^
    --hidden-import clr ^
    --paths "." ^
    %ICON_ARG% ^
    main_client.py
if errorlevel 1 ( echo. & echo ERRO ao compilar cliente & cd .. & pause & exit /b 1 )

echo.
echo [4/5] Compilando PlayIngest (PlayIngest.exe)...
cd ..\playingest
set INGEST_ICON=
if exist "..\backend\FavPlayline.ico" ( set INGEST_ICON=--icon "..\backend\FavPlayline.ico" )
python -m PyInstaller --onefile --noconsole --noconfirm ^
    --name PlayIngest ^
    --add-data "ui;ui" ^
    --collect-all webview ^
    --hidden-import clr ^
    --paths "." ^
    %INGEST_ICON% ^
    main_ingest.py
if errorlevel 1 ( echo. & echo ERRO ao compilar PlayIngest & cd .. & pause & exit /b 1 )
cd ..\backend

echo.
echo [5/5] Montando pasta final...

:: Copia o daemon para dentro da pasta do app principal
copy /y "dist\PlayLine-daemon.exe" "dist\PlayLine\"

:: Cria pasta de logos e copia logos do sistema
if not exist "dist\PlayLine\logos" mkdir "dist\PlayLine\logos"
if exist "logos" ( xcopy /e /i /y "logos\*" "dist\PlayLine\logos\" >nul 2>&1 )

:: Cria pasta Biblioteca vazia
if not exist "dist\PlayLine\Biblioteca" mkdir "dist\PlayLine\Biblioteca"

:: Copia artefatos de distribuicao para a raiz do projeto
copy /y "dist\PlayLine-Client.exe" "..\PlayLine-Client.exe" >nul 2>&1
copy /y "..\playingest\dist\PlayIngest.exe" "..\PlayIngest.exe" >nul 2>&1

cd ..

echo.
echo ==========================================
echo  Pronto!
echo  Servidor : backend\dist\PlayLine\
echo  Cliente  : PlayLine-Client.exe
echo  Ingest   : PlayIngest.exe
echo.
echo  Servidor: copie a pasta PlayLine\ e execute PlayLine.exe
echo  Cliente : copie PlayLine-Client.exe e informe o IP do servidor
echo  Ingest  : copie PlayIngest.exe para qualquer maquina da rede
echo ==========================================
pause
