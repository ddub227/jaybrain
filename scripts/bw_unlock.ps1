# Unlock Bitwarden vault and save session token for JayBrain tools.
# Usage: Right-click > Run with PowerShell, or from terminal: .\scripts\bw_unlock.ps1

Write-Host "Unlocking Bitwarden vault..." -ForegroundColor Cyan
$session = bw unlock --raw

if ($session) {
    $sessionFile = Join-Path $HOME ".bw_session"
    $session | Out-File -FilePath $sessionFile -NoNewline -Encoding utf8
    $env:BW_SESSION = $session
    Write-Host "Vault unlocked. Session saved to $sessionFile" -ForegroundColor Green
    Write-Host "Token valid until vault locks again (timeout or manual lock)." -ForegroundColor DarkGray
} else {
    Write-Host "Unlock failed. Check your master password." -ForegroundColor Red
}

Write-Host ""
Write-Host "You can close this window." -ForegroundColor DarkGray
pause
