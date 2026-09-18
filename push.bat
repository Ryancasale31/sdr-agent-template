@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================================
echo   SDR Agent - push code to GitHub (master)
echo ==========================================================
echo.

REM ---- git present? --------------------------------------------------------
where git >nul 2>&1
if errorlevel 1 (
  echo ERROR: git is not installed, or not on your PATH.
  echo Install "Git for Windows" from https://git-scm.com/download/win
  echo then run this file again.
  echo.
  pause
  exit /b 1
)

REM ---- read GITHUB_TOKEN out of .env ---------------------------------------
set "GH_TOKEN="
if not exist ".env" (
  echo ERROR: no .env file found in this folder.
  echo.
  pause
  exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
  if /i "%%A"=="GITHUB_TOKEN" set "GH_TOKEN=%%B"
)
if not defined GH_TOKEN (
  echo ERROR: GITHUB_TOKEN is not set in .env
  echo.
  pause
  exit /b 1
)

git remote set-url origin https://x-access-token:%GH_TOKEN%@github.com/Ryancasale31/sdr-agent-template.git
if errorlevel 1 (
  echo ERROR: could not set the remote. Is this folder still a git repo?
  echo.
  pause
  exit /b 1
)

REM ---- stage CODE ONLY -----------------------------------------------------
REM Data files are deliberately left alone. pipeline.json, icp_summary.json and
REM the radar finds are owned by the 'data' branch; pushing the local copies
REM over them is how contact edits get silently destroyed. If you actually mean
REM to update data, that is a separate, merge-aware job - ask Claude for it.
git add -A .
git reset -q -- pipeline.json icp_summary.json scored_companies.json radar_finds.json "*_radar_finds.json" "*.csv" events

git diff --cached --quiet
if not errorlevel 1 (
  echo Nothing to commit - your code already matches the last commit.
  echo.
  pause
  exit /b 0
)

echo Files that will be committed:
echo.
git diff --cached --name-status
echo.

REM ---- show what is being skipped, so it is never a surprise ---------------
git status --porcelain --untracked-files=normal | findstr /R /C:"^ M" /C:"^??" >nul
if not errorlevel 1 (
  echo Left OUT of this commit ^(data files and anything untracked^):
  git status --porcelain --untracked-files=normal | findstr /R /C:"^ M" /C:"^??"
  echo.
)

set "MSG="
set /p MSG=Commit message (blank to cancel):
if not defined MSG (
  echo Cancelled. Nothing was committed.
  git reset >nul
  echo.
  pause
  exit /b 0
)

git commit -m "%MSG%"
if errorlevel 1 (
  echo ERROR: commit failed. Nothing was pushed.
  echo.
  pause
  exit /b 1
)

REM ---- bring in anything that landed on master since you last pulled -------
echo.
echo Pulling remote changes first...
git pull --rebase origin master
if errorlevel 1 (
  echo.
  echo ERROR: the rebase hit a conflict, so nothing was pushed.
  echo Your commit is safe locally. Run:  git rebase --abort
  echo then ask Claude to sort the conflict out.
  echo.
  pause
  exit /b 1
)

echo.
echo Pushing to master...
git push origin master
if errorlevel 1 (
  echo.
  echo ERROR: push failed. Most likely the GITHUB_TOKEN in .env has expired.
  echo Make a new one at https://github.com/settings/tokens with 'repo' scope,
  echo paste it into .env as GITHUB_TOKEN=... and run this again.
  echo.
  pause
  exit /b 1
)

echo.
echo ==========================================================
echo   Pushed. Streamlit Cloud will redeploy in a minute or two:
echo   https://ryan-fse-sdr-agent.streamlit.app/
echo ==========================================================
echo.
pause
