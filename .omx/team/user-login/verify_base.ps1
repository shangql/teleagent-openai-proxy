<#
    .omx/team/user-login/verify_base.ps1
    ===================================
    Merge-gate verification harness for the user-login feature.

    NOTE: intentionally ASCII-only. Windows PowerShell 5.1 reads .ps1 files as
    ANSI unless a BOM is present, which corrupts non-ASCII literals and breaks
    parsing. Keep this file ASCII; put Chinese notes in the .md artifacts.

    Usage:
        powershell -ExecutionPolicy Bypass -File .omx\team\user-login\verify_base.ps1
        powershell -ExecutionPolicy Bypass -File .omx\team\user-login\verify_base.ps1 -Port 18099

    Guarantees:
      - Never touches the live instance (8088 / live PID): the proxy is started
        from a COPY in a temp dir on a spare port.
      - Never modifies repository files (read-only checks + temp dir only).
      - Exit code 0 = no FAIL. PENDING means "not wired yet by its owning lane".
#>

param(
    [int]$Port = 18089
)

$ErrorActionPreference = 'Continue'
$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param([string]$Name, [string]$State, [string]$Detail)
    $script:results.Add([pscustomobject]@{ Check = $Name; State = $State; Detail = $Detail })
    $color = switch ($State) { "PASS" { "Green" } "PENDING" { "Yellow" } "FAIL" { "Red" } default { "Gray" } }
    Write-Host ("[{0,-7}] {1}  {2}" -f $State, $Name, $Detail) -ForegroundColor $color
}

$here = (Get-Item $PSScriptRoot).Parent.Parent.Parent.FullName
$py = "$env:USERPROFILE\.local\share\TeleAgent\runtimes\python\python.exe"
if (-not (Test-Path $py)) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source }
}
$git = "C:\Program Files\Git\cmd\git.exe"

Write-Host "repo   : $here"
Write-Host "python : $py"
Write-Host ""

# ---------------------------------------------------------------- live baseline
$liveBefore = Get-NetTCPConnection -State Listen -LocalPort 8088 -ErrorAction SilentlyContinue | Select-Object -First 1
$livePidBefore = 0
if ($liveBefore) { $livePidBefore = $liveBefore.OwningProcess }

# ---------------------------------------------------------------- T1 syntax gate
$compileTargets = @()
foreach ($f in @("openai_proxy.py", "user_auth.py")) {
    if (Test-Path (Join-Path $here $f)) { $compileTargets += (Join-Path $here $f) }
}
if ($compileTargets.Count -gt 0) {
    & $py -m py_compile @compileTargets
    if ($LASTEXITCODE -eq 0) { Add-Result "T1 py_compile" "PASS" ("compiled: " + ($compileTargets.Count).ToString() + " file(s)") }
    else { Add-Result "T1 py_compile" "FAIL" "exit code $LASTEXITCODE" }
} else {
    Add-Result "T1 py_compile" "FAIL" "no target files found"
}

# ---------------------------------------------------------------- T2 unit tests
Push-Location $here
$utOut = & $py -m unittest discover -s tests 2>&1 | Out-String
$utExit = $LASTEXITCODE
Pop-Location
$utSummary = (($utOut -split "`r?`n") | Where-Object { $_ -match '^(Ran |OK|FAILED)' }) -join " ; "
if ($utExit -eq 0) { Add-Result "T2 unittest discover" "PASS" $utSummary }
else {
    $tail = (($utOut -split "`r?`n") | Select-Object -Last 6) -join " / "
    Add-Result "T2 unittest discover" "FAIL" ($utSummary + " | " + $tail)
}

# ---------------------------------------------------------------- T3 secrets not tracked
$tracked = & $git ls-files 2>&1
$secretLeaks = @()
foreach ($f in @("auth.json", "users.json", "auth_users.json")) {
    if ($tracked -contains $f) { $secretLeaks += $f }
}
$ignored = (& $git check-ignore auth.json users.json 2>&1) -join ", "
if ($secretLeaks.Count -eq 0) {
    Add-Result "T3 secrets not tracked" "PASS" ("ignored by git: " + $ignored)
} else {
    Add-Result "T3 secrets not tracked" "FAIL" ("tracked: " + ($secretLeaks -join ", "))
}

# ---------------------------------------------------------------- start a COPY of the proxy
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("tap-verify-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
foreach ($f in @("openai_proxy.py", "user_auth.py")) {
    if (Test-Path (Join-Path $here $f)) { Copy-Item (Join-Path $here $f) (Join-Path $tmp $f) -Force }
}
$outLog = Join-Path $tmp "stdout.log"
$errLog = Join-Path $tmp "stderr.log"
$proc = $null
try {
    $proc = Start-Process -FilePath $py -ArgumentList @((Join-Path $tmp "openai_proxy.py"), "--host", "127.0.0.1", "--port", "$Port") -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
} catch {
    Add-Result "T4 copy instance ready" "FAIL" $_.Exception.Message
}

function Get-Code {
    param([string]$Url, [string]$Method = "GET", [string]$Body = $null)
    try {
        if ($Body) {
            $resp = Invoke-WebRequest -Uri $Url -Method $Method -Body $Body -ContentType "application/json" -UseBasicParsing -TimeoutSec 15
        } else {
            $resp = Invoke-WebRequest -Uri $Url -Method $Method -UseBasicParsing -TimeoutSec 15
        }
        return @{ code = [int]$resp.StatusCode; body = [string]$resp.Content }
    } catch {
        $code = 0
        if ($_.Exception.Response) { try { $code = [int]$_.Exception.Response.StatusCode } catch { $code = 0 } }
        return @{ code = $code; body = "" }
    }
}

$base = "http://127.0.0.1:$Port"
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $h = Get-Code -Url "$base/health"
    if ($h.code -eq 200) { $ready = $true; break }
}

if ($ready) {
    Add-Result "T4 copy instance ready" "PASS" "port $Port (live 8088 untouched)"

    $r = Get-Code -Url "$base/health"
    if ($r.code -eq 200) { Add-Result "T5 GET /health" "PASS" "200" } else { Add-Result "T5 GET /health" "FAIL" "code=$($r.code)" }

    $r = Get-Code -Url "$base/v1/models"
    if ($r.code -eq 200) { Add-Result "T6 GET /v1/models (data plane)" "PASS" "200" } else { Add-Result "T6 GET /v1/models (data plane)" "FAIL" "code=$($r.code)" }

    $r = Get-Code -Url "$base/api/status"
    if ($r.code -eq 200) { Add-Result "T7 GET /api/status (local bypass)" "PASS" "200" } else { Add-Result "T7 GET /api/status (local bypass)" "FAIL" "code=$($r.code)" }

    $r = Get-Code -Url "$base/console"
    if ($r.code -eq 200) { Add-Result "T8 GET /console" "PASS" "200" } else { Add-Result "T8 GET /console" "FAIL" "code=$($r.code)" }

    $r = Get-Code -Url "$base/api/auth/me"
    if ($r.code -eq 404) { Add-Result "T9 GET /api/auth/me" "PENDING" "404 - lane A not wired yet (expected)" }
    else { Add-Result "T9 GET /api/auth/me" "PENDING" "code=$($r.code) - lane A not wired yet" }

    $r = Get-Code -Url "$base/api/auth/login" -Method "POST" -Body '{"username":"x","password":"y"}'
    if ($r.code -eq 404) { Add-Result "T10 POST /api/auth/login" "PENDING" "404 - lane A not wired yet (expected)" }
    else { Add-Result "T10 POST /api/auth/login" "PENDING" "code=$($r.code)" }
} else {
    $tail = (Get-Content $errLog -ErrorAction SilentlyContinue | Select-Object -Last 5) -join " / "
    Add-Result "T4 copy instance ready" "FAIL" ("not ready in 60s; stderr: " + $tail)
}

# ---------------------------------------------------------------- live instance untouched
$liveAfter = Get-NetTCPConnection -State Listen -LocalPort 8088 -ErrorAction SilentlyContinue | Select-Object -First 1
$livePidAfter = 0
if ($liveAfter) { $livePidAfter = $liveAfter.OwningProcess }
if ($livePidBefore -ne 0 -and $livePidBefore -eq $livePidAfter) {
    Add-Result "T11 live instance untouched" "PASS" "PID $livePidAfter unchanged"
} elseif ($livePidBefore -eq 0) {
    Add-Result "T11 live instance untouched" "PASS" "nothing listening on 8088"
} else {
    Add-Result "T11 live instance untouched" "FAIL" "PID changed: $livePidBefore -> $livePidAfter"
}

if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 300

Write-Host ""
$fails = @($results | Where-Object { $_.State -eq "FAIL" }).Count
$pends = @($results | Where-Object { $_.State -eq "PENDING" }).Count
$passes = $results.Count - $fails - $pends
Write-Host ("summary: total {0} | PASS {1} | PENDING {2} | FAIL {3}" -f $results.Count, $passes, $pends, $fails)
if ($fails -gt 0) { exit 1 } else { exit 0 }
