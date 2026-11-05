Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
base = files.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = base
If files.FileExists(base & "\dist\AlbumVideo.exe") Then
  shell.Run """" & base & "\dist\AlbumVideo.exe""", 1, False
Else
  shell.Run "pythonw """ & base & "\album_video.py""", 1, False
End If
