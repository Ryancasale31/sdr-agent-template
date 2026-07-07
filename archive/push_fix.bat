@echo off
cd /d "C:\Users\Ryan.Casale\OneDrive - IQPC WBR\Field service East\fse_sdr_agent"
git add app.py
git commit -m "Fix pipeline export: use st.download_button for cloud"
git push origin master
echo.
echo Done! Refresh your app at https://ryan-fse-sdr-agent.streamlit.app/
pause
