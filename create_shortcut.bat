@echo off
cd /d "%~dp0"
echo Creating Desktop Shortcut for GodMode...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'GodMode.lnk')); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%~dp0GodMode.vbs\"'; $s.WorkingDirectory = '%~dp0'; $s.Save()"
echo Done! GodMode shortcut has been created on your Desktop.
pause
