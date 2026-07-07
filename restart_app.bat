@echo off
echo Stopping old app...
taskkill /F /IM python.exe /T 2>nul
echo Starting app...
cd /d "C:\Users\Ryan.Casale\OneDrive - IQPC WBR\Field service East\fse_sdr_agent"
C:\Users\Ryan.Casale\AppData\Local\Python\pythoncore-3.14-64\python.exe -m streamlit run app.py
pause
