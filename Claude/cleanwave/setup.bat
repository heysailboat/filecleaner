@echo off
echo CleanWave setup
echo.

python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt

if not exist "%USERPROFILE%\.cleanwave" mkdir "%USERPROFILE%\.cleanwave"

if not exist "%USERPROFILE%\.cleanwave\config.yaml" (
    copy config.yaml "%USERPROFILE%\.cleanwave\config.yaml" >nul
    echo Created config at %USERPROFILE%\.cleanwave\config.yaml
) else (
    echo Config already exists
)

if not exist .env (
    copy .env.example .env >nul
    echo Created .env - open it and add your GROQ_API_KEY
) else (
    echo .env already exists
)

echo.
echo Done! Next steps:
echo   1. Edit .env and add your GROQ_API_KEY (free at console.groq.com)
echo   2. Run:  python run.py --dry-run
echo   3. When happy:  python run.py
pause
