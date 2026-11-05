@echo off
cd /d "%~dp0"
if exist "%~dp0dist\AlbumVideo.exe" (
  start "" "%~dp0dist\AlbumVideo.exe"
  exit /b
)
python "%~dp0album_video.py"
if errorlevel 1 pause
