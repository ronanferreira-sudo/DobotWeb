@echo off
echo ========================================================
echo Iniciando o DobotWeb...
echo ========================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Criando ambiente virtual...
    python -m venv .venv
    if errorlevel 1 (
        echo ERRO: O Python nao foi encontrado! 
        echo Por favor, instale o Python e tente novamente.
        pause
        exit /b
    )
    echo Instalando dependencias...
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

echo.
echo Abrindo o navegador e iniciando o servidor...
start http://127.0.0.1:5000
python app.py
pause
