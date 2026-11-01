param([Parameter(ValueFromRemainingArguments=$true)][string[]]$ToolArguments)
$ErrorActionPreference = 'Stop'
$pythonCandidates = [System.Collections.Generic.List[string]]::new()
$explicitPython = -not [string]::IsNullOrWhiteSpace($env:MINGXUE_PYTHON)
if ($explicitPython) {
    $command = Get-Command $env:MINGXUE_PYTHON -ErrorAction SilentlyContinue | Select-Object -First 1
    $pythonCandidates.Add($(if ($command) { $command.Source } else { $env:MINGXUE_PYTHON }))
} else {
    foreach ($name in @('python3.12.exe', 'python.exe', 'python3.exe')) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($command.Source) { $pythonCandidates.Add($command.Source) }
        }
    }
    $uvRoots = @()
    if ($env:UV_PYTHON_INSTALL_DIR) { $uvRoots += $env:UV_PYTHON_INSTALL_DIR }
    foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
        if ($base) { $uvRoots += (Join-Path $base 'uv\python') }
    }
    if ($env:USERPROFILE) { $uvRoots += (Join-Path $env:USERPROFILE '.local\share\uv\python') }
    foreach ($root in $uvRoots) {
        if (Test-Path -LiteralPath $root -PathType Container) {
            foreach ($directory in @(Get-ChildItem -LiteralPath $root -Directory -Filter 'cpython-3.12*' | Sort-Object Name -Descending)) {
                $pythonCandidates.Add((Join-Path $directory.FullName 'python.exe'))
            }
        }
    }
    if ($env:LOCALAPPDATA) { $pythonCandidates.Add((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')) }
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($base) { $pythonCandidates.Add((Join-Path $base 'Python312\python.exe')) }
    }
}
$probeCode = "import sys,json,struct;print(json.dumps({'version':list(sys.version_info[:2]),'bits':struct.calcsize('P')*8,'implementation':sys.implementation.name}))"
$selected = $null
$rejected = @()
foreach ($candidate in @($pythonCandidates | Select-Object -Unique)) {
    if ($candidate -match '(?i)[\\/]Microsoft[\\/]WindowsApps[\\/](pythonw?[0-9.]*|pyw?)(\.exe)?$') {
        $rejected += @{ path = $candidate; reason = 'WindowsApps execution alias' }
        continue
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    try {
        $raw = & $candidate -I -S -B -X utf8 -c $probeCode 2>$null
        if ($LASTEXITCODE -ne 0) { continue }
        $runtime = ($raw -join "`n") | ConvertFrom-Json
        if ($runtime.implementation -eq 'cpython' -and $runtime.bits -eq 64 -and ($runtime.version -join '.') -eq '3.12') {
            $selected = (Resolve-Path -LiteralPath $candidate).Path
            break
        }
    } catch { $rejected += @{ path = $candidate; reason = 'runtime probe failed' } }
}
if (-not $selected) {
    @{ status = 'needs_setup'; message = 'No existing CPython 3.12 / 64-bit found. Set MINGXUE_PYTHON to a real interpreter; no installation was attempted.'; rejected_candidates = $rejected } | ConvertTo-Json -Depth 5
    exit 3
}
$bootstrap = Join-Path $PSScriptRoot 'scripts\bootstrap.py'
& $selected -X utf8 -B $bootstrap @ToolArguments
exit $LASTEXITCODE
