@echo off
cd /d "C:\Users\Ryan.Casale\OneDrive - IQPC WBR\Field service East\fse_sdr_agent"
C:\Users\Ryan.Casale\AppData\Local\Python\pythoncore-3.14-64\python.exe test_all_connections.py %*
echo.
echo Finished. Results saved to connection_test_results.txt
pause
