param(
    [Parameter(Mandatory=$true)][int]$WaitProcessId,
    [Parameter(Mandatory=$true)][string]$TargetDirectory
)
$ErrorActionPreference = 'Stop'
$target = [System.IO.Path]::GetFullPath($TargetDirectory).TrimEnd('\')
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\')
$parent = [System.IO.Path]::GetDirectoryName($target)
$leaf = [System.IO.Path]::GetFileName($target)
if ($parent -ne $tempRoot -or $leaf -notmatch '^qingshi-uninstall-[a-z0-9_]+$') {
    throw 'Cleanup target is outside the expected temporary directory.'
}
Wait-Process -Id $WaitProcessId -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    try {
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
        break
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
