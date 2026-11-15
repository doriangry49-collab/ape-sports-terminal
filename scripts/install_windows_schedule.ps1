param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BatchPath = Join-Path $ProjectRoot "scripts\run_scheduled_digest.bat"
$TaskPrefix = "APE_SportsEngine_Digest"
$ScheduleTimes = @("11:00", "15:00", "19:00")

if ($Uninstall) {
    foreach ($t in $ScheduleTimes) {
        $name = "${TaskPrefix}_$($t.Replace(':', ''))"
        schtasks.exe /Delete /TN $name /F 2>$null | Out-Null
        Write-Host "Removed scheduled task (if existed): $name"
    }
    exit 0
}

if (-not (Test-Path $BatchPath)) {
    throw "Batch runner not found: $BatchPath"
}

foreach ($t in $ScheduleTimes) {
    $name = "${TaskPrefix}_$($t.Replace(':', ''))"
    $cmd = "`"$BatchPath`""
    schtasks.exe /Create /SC DAILY /TN $name /TR $cmd /ST $t /F | Out-Null
    Write-Host "Registered Windows Scheduled Task: $name at $t daily -> $BatchPath"
}

Write-Host "Done. Verify with: schtasks /Query /TN ${TaskPrefix}_1100"
