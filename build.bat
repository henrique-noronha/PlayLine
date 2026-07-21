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
if exist "backend\build" rmdir /s /q "backend\build"
if exist "backend\dist"  rmdir /s /q "backend\dist"

echo [1/3] Compilando daemon (PlayLine-daemon.exe)...
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
echo [2/3] Compilando servidor principal (PlayLine.exe)...

:: Inclui ffmpeg.exe se disponivel na pasta backend
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
echo [3/3] Montando pasta final...

:: Copia o daemon para dentro da pasta do app principal
copy /y "dist\PlayLine-daemon.exe" "dist\PlayLine\"

:: Cria pasta de logos e copia logos do sistema
if not exist "dist\PlayLine\logos" mkdir "dist\PlayLine\logos"
if exist "logos" ( xcopy /e /i /y "logos\*" "dist\PlayLine\logos\" >nul 2>&1 )

:: Cria pasta Biblioteca vazia
if not exist "dist\PlayLine\Biblioteca" mkdir "dist\PlayLine\Biblioteca"

cd ..

echo.
echo ==========================================
echo  Pronto!
echo  Pasta gerada: backend\dist\PlayLine\
echo.
echo  Para instalar em outro computador:
echo  1. Copie a pasta PlayLine\ inteira
echo  2. Execute PlayLine.exe
echo  (sem instalar Python ou dependencias)
echo ==========================================
pause
