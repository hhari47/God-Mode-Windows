Set WshShell = CreateObject("WScript.Shell")
strDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strDir
WshShell.Run Chr(34) & strDir & "\.venv\Scripts\pythonw.exe" & Chr(34) & " run.py", 0, False
Set WshShell = Nothing
