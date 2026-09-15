@echo off
rem Claude Assistant 后台启动(无终端窗口,纯右下角托盘)
rem 双击即用;要开机自启,把本文件的快捷方式放进 shell:startup
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath '%~dp0.venv\Scripts\pythonw.exe' -ArgumentList 'main.py' -WorkingDirectory '%~dp0'"
