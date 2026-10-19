' NexusX launcher without any console window (double-click, or use as shortcut target).
' Arguments are passed through, e.g.:  NexusX.vbs --minimized   (start directly in the tray)
Option Explicit
Dim sh, fso, dir, args, a, exe, rc
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir

args = ""
For Each a In WScript.Arguments
    args = args & " """ & a & """"
Next

' pythonw = Python without console; pyw = the same through the Windows "py" launcher
For Each exe In Array("pythonw", "pyw")
    On Error Resume Next
    rc = sh.Run(exe & " """ & dir & "\NexusX.pyw""" & args, 0, False)
    If Err.Number = 0 Then WScript.Quit 0
    Err.Clear
    On Error GoTo 0
Next

MsgBox "Python (pythonw.exe) nu a fost gasit in PATH." & vbCrLf & _
       "Instaleaza Python 3 si ruleaza install_deps.bat.", vbExclamation, "NexusX"
