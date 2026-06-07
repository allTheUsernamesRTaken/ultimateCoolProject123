$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$App = Join-Path $Root "ui\app.py"
$Port = if ($env:PORT) { $env:PORT } else { "8501" }
$HostAddress = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }

$Candidates = @()
if ($env:PYTHON) {
    $Candidates += $env:PYTHON
}

$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path $BundledPython) {
    $Candidates += $BundledPython
}

$Candidates += "python"
$Candidates += "py"

$Python = $null
foreach ($Candidate in $Candidates) {
    try {
        & $Candidate -c "import streamlit" *> $null
        if ($LASTEXITCODE -eq 0) {
            $Python = $Candidate
            break
        }
    } catch {
    }
}

if (-not $Python) {
    Write-Host "Could not find a Python with Streamlit installed." -ForegroundColor Red
    Write-Host "Install dependencies, then run this command again:"
    Write-Host "  python -m pip install -r requirements.txt"
    exit 1
}

if ($args -contains "--check") {
    Write-Host "Using Python: $Python"
    & $Python -c "import streamlit; print('Streamlit:', streamlit.__version__)"
    exit $LASTEXITCODE
}

Write-Host "Starting teacher dashboard at http://${HostAddress}:$Port"
Write-Host "Press Ctrl+C to stop."
& $Python -m streamlit run $App --server.port $Port --server.address $HostAddress
