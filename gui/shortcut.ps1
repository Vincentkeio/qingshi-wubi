param(
    [Parameter(Mandatory=$true)][string]$LinkPath,
    [Parameter(Mandatory=$true)][string]$Executable,
    [string]$Arguments = ''
)
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($LinkPath)
$shortcut.TargetPath = $Executable
$shortcut.Arguments = $Arguments
$shortcut.WorkingDirectory = [System.IO.Path]::GetDirectoryName($Executable)
$shortcut.IconLocation = "$Executable,0"
$shortcut.Save()
