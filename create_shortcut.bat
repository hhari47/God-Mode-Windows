@echo off
cd /d "%~dp0"
echo Creating Desktop Shortcut for GodMode...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $shortcutPath = [System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'GodMode.lnk'); $s = $ws.CreateShortcut($shortcutPath); $exePath = '%~dp0dist\GodMode\GodMode.exe'; if (Test-Path $exePath) { $s.TargetPath = $exePath; $s.WorkingDirectory = '%~dp0dist\GodMode'; } else { $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%~dp0GodMode.vbs\"'; $s.WorkingDirectory = '%~dp0'; } $iconPath = '%~dp0assets\icon.ico'; if (Test-Path $iconPath) { $s.IconLocation = $iconPath; } $s.Description = 'GodMode — AI Question Solver for Windows'; $s.Save()"
echo Done! GodMode shortcut with custom icon has been created on your Desktop.
pause
