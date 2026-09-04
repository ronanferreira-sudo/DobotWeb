@echo off
echo ========================================================
echo Configurando o DobotWeb...
echo ========================================================

echo.
echo [1/4] Removendo o ambiente virtual antigo (quebrado)...
if exist ".venv" rmdir /s /q ".venv"

echo.
echo [2/4] Criando um novo ambiente virtual para o seu computador...
python -m venv .venv
if errorlevel 1 (
    echo.
    echo ERRO: O Python nao foi encontrado! 
    echo Por favor, instale o Python pela Microsoft Store ou python.org,
    echo marque a caixa "Add Python to PATH" na instalacao e tente novamente.
    pause
    exit /b
)

echo.
echo [3/4] Instalando as dependencias...
call .venv\Scripts\activate.bat
pip install -r requirements.txt

echo.
echo [4/4] Tudo pronto! Iniciando o servidor...
python app.py
pause
