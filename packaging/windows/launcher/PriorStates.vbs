' Launch the PriorStates desktop GUI with no console window.
' Uses the windowed Python launcher (pyw); falls back to pythonw.
On Error Resume Next
Dim sh
Set sh = CreateObject("WScript.Shell")
sh.Run "pyw -3 -m priorstates gui", 0, False
If Err.Number <> 0 Then
  Err.Clear
  sh.Run "pythonw -m priorstates gui", 0, False
End If
