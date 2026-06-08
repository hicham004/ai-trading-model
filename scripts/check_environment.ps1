$ErrorActionPreference = "Continue"

$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"

$checks = @(
    @{ Name = "Git"; Command = "git"; Arguments = @("--version") },
    @{ Name = "Python"; Command = "python"; Arguments = @("--version") },
    @{ Name = "Node.js"; Command = "node"; Arguments = @("--version") },
    @{ Name = "npm"; Command = "npm"; Arguments = @("--version") },
    @{ Name = "Docker"; Command = "docker"; Arguments = @("--version") },
    @{ Name = "VS Code"; Command = "code"; Arguments = @("--version") },
    @{ Name = "WSL"; Command = "wsl"; Arguments = @("--status") }
)

Write-Host "AI trading workstation environment check"
Write-Host "========================================"

foreach ($check in $checks) {
    $installed = Get-Command $check.Command -ErrorAction SilentlyContinue

    if (-not $installed) {
        Write-Host ("[MISSING] {0}" -f $check.Name) -ForegroundColor Yellow
        continue
    }

    $output = & $check.Command @($check.Arguments) 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host ("[INSTALLED] {0}" -f $check.Name) -ForegroundColor Green
    } else {
        Write-Host ("[FAILED] {0}" -f $check.Name) -ForegroundColor Red
    }

    $output | Select-Object -First 3
}
