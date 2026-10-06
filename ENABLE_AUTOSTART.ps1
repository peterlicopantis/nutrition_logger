$ErrorActionPreference = 'Stop'
$melbRoot = $PSScriptRoot
$melbPython = Join-Path $melbRoot '.venv\Scripts\pythonw.exe'
$melbRunner = Join-Path $melbRoot 'START_MELB_BACKGROUND.py'
if (-not (Test-Path -LiteralPath $melbPython)) {
    throw 'Run SETUP_WINDOWS.bat before enabling automatic startup.'
}
$melbStartupFolder = [Environment]::GetFolderPath('Startup')
$melbShortcutPath = Join-Path $melbStartupFolder 'MELB Nutrition.lnk'
$melbShell = New-Object -ComObject WScript.Shell
$melbShortcut = $melbShell.CreateShortcut($melbShortcutPath)
$melbShortcut.TargetPath = $melbPython
$melbShortcut.Arguments = '"' + $melbRunner + '"'
$melbShortcut.WorkingDirectory = $melbRoot
$melbShortcut.IconLocation = (Join-Path $melbRoot 'static\favicon.ico') + ',0'
$melbShortcut.Description = 'Start MELB Nutrition in the background at Windows sign-in'
$melbShortcut.WindowStyle = 7
$melbShortcut.Save()
Write-Output 'MELB will now start automatically when you sign in to Windows.'
