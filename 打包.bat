@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在打包，请不要关闭这个窗口。
echo.
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m PyInstaller --noconsole --onedir --name TikView --clean --noconfirm app.py
if errorlevel 1 goto fail
copy /Y ".env" "dist\TikView\.env" >nul
echo.
echo 打包完成。把 dist\TikView 整个文件夹压缩后发给同事，让他双击里面的 TikView.exe。
echo 不要把这个压缩包发到公开的地方，里面有 .env。
echo.
pause
exit /b 0

:fail
echo.
echo 打包失败。请把上面的报错留在这个窗口里。
echo.
pause
exit /b 1
