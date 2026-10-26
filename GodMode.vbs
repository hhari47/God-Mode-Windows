Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strDir
If fso.FileExists(strDir & "\.venv\Scripts\pythonw.exe") Then
    WshShell.Run Chr(34) & strDir & "\.venv\Scripts\pythonw.exe" & Chr(34) & " run.py", 0, False
Else
    WshShell.Run "pythonw run.py", 0, False
End If
Set WshShell = Nothing
Set fso = Nothing
