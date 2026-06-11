@echo off
echo Setting up CleanWave...

pip install -r requirements.txt

if not exist "%USERPROFILE%\.cleanwave" mkdir "%USERPROFILE%\.cleanwave"
if not exist "%USERPROFILE%\.cleanwave\config.yaml" copy cleanwave_config.yaml "%USERPROFILE%\.cleanwave\config.yaml"

echo.
echo Setup complete! Run: python cleanwave_main.py --help