Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
pythonw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
  MsgBox "找不到 .venv\Scripts\pythonw.exe", 16, "TikView"
  WScript.Quit 1
End If
shell.Run """" & pythonw & """ """ & root & "\app.py""", 0, False
