@echo off
cd /d "C:\Users\Ryan.Casale\OneDrive - IQPC WBR\Field service East\fse_sdr_agent"
C:\Users\Ryan.Casale\AppData\Local\Python\pythoncore-3.14-64\python.exe tiga_contacts.py --min-score 70
echo Done at %DATE% %TIME%
pause
