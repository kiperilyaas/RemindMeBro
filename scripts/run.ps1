# =============================================================================
#  Remind Me Bro - Run & Go (Windows, PowerShell 5.1+)
#
#  Installs everything that is missing, starts the app and opens the browser.
#  uv, Python and the virtualenv live in the project's ".runtime" folder.
#  Ollama is installed per-user (no admin) if it is missing; the AI model is
#  stored by Ollama in %USERPROFILE%\.ollama (about 2 GB).
#
#  Options (environment variables): RMB_MODEL, RMB_NO_AI=1, RMB_NO_BROWSER=1,
#    RMB_SHARE=1 (public ngrok link + QR code; run-share-windows.bat sets it),
#    NGROK_AUTHTOKEN=... (skips the token question)
# =============================================================================
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow with the progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$AppDir    = Split-Path -Parent $PSScriptRoot
$RT        = Join-Path $AppDir ".runtime"
$Venv      = Join-Path $RT "venv"
$VenvPy    = Join-Path $Venv "Scripts\python.exe"
$Logs      = Join-Path $RT "logs"
$Model     = if ($env:RMB_MODEL) { $env:RMB_MODEL } else { "llama3.2" }
$PyVersion = "3.12"
$OllamaUrl = "http://127.0.0.1:11434"

$script:BackendProc = $null
$script:UnisisProc  = $null
$script:UnilearnProc = $null
$script:UnicommsProc = $null
$script:OllamaProc  = $null
$script:NgrokProc   = $null

function Step($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "    [ok] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "    [!] $t" -ForegroundColor Yellow }
function Fail($t) {
  Write-Host ""; Write-Host "[x] $t" -ForegroundColor Red
  Write-Host "    Logs: $Logs"
  Read-Host "Press Enter to close this window" | Out-Null
  Stop-All
  exit 1
}
function Stop-All {
  if ($script:WhisperProc -and -not $script:WhisperProc.HasExited) { Stop-Process -Id $script:WhisperProc.Id -Force -ErrorAction SilentlyContinue }
  if ($script:NgrokProc -and -not $script:NgrokProc.HasExited) { Write-Host "Closing the public link..."; Stop-Process -Id $script:NgrokProc.Id -Force -ErrorAction SilentlyContinue }
  if ($script:UnilearnProc -and -not $script:UnilearnProc.HasExited) { Write-Host "Stopping UniLearn..."; Stop-Process -Id $script:UnilearnProc.Id -Force -ErrorAction SilentlyContinue }
  if ($script:UnicommsProc -and -not $script:UnicommsProc.HasExited) { Write-Host "Stopping UniComms..."; Stop-Process -Id $script:UnicommsProc.Id -Force -ErrorAction SilentlyContinue }
  if ($script:UnisisProc -and -not $script:UnisisProc.HasExited) { Write-Host "Stopping UniSIS..."; Stop-Process -Id $script:UnisisProc.Id -Force -ErrorAction SilentlyContinue }
  if ($script:BackendProc -and -not $script:BackendProc.HasExited) { Write-Host "Stopping the app..."; Stop-Process -Id $script:BackendProc.Id -Force -ErrorAction SilentlyContinue }
  if ($script:OllamaProc -and -not $script:OllamaProc.HasExited)   { Write-Host "Stopping Ollama...";  Stop-Process -Id $script:OllamaProc.Id -Force -ErrorAction SilentlyContinue }
}
function Test-Http($url) {
  try { $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3; return ($r.StatusCode -lt 400) } catch { return $false }
}
function Get-Http($url) {
  try { return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3).Content } catch { return "" }
}
function Download($url, $dest) {
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if ($curl) {
    & $curl.Source -fL --retry 3 --connect-timeout 15 --progress-bar -o $dest $url
    if ($LASTEXITCODE -ne 0) { Fail "Download failed: $url (check the internet connection)" }
  } else {
    try { Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing } catch { Fail "Download failed: $url" }
  }
}
# Windows PowerShell 5.1 turns redirected stderr of native tools into errors when
# $ErrorActionPreference is "Stop": run them with "Continue" and check the exit code.
function Invoke-Logged($exe, [string[]]$argList, $log) {
  $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try { & $exe @argList *> $log; return $LASTEXITCODE } finally { $ErrorActionPreference = $old }
}
function Open-Browser($url) { if ($env:RMB_NO_BROWSER -ne "1") { Start-Process $url } }

# ---------- share with friends: ngrok tunnel to the hub + QR code ----------
function Start-Share($port) {
  Step "Link for friends (ngrok)"
  $ngDir = Join-Path $RT "ngrok"
  $ngExe = Join-Path $ngDir "ngrok.exe"
  if (-not (Test-Path $ngExe)) {
    $sys = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($sys) { $ngExe = $sys.Source } else {
      $pkg = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "windows-arm64.zip" } else { "windows-amd64.zip" }
      Write-Host "    Downloading ngrok (first time only)..."
      New-Item -ItemType Directory -Force -Path $ngDir | Out-Null
      $zip = Join-Path $ngDir "ngrok.zip"
      try {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
          & $curl.Source -fL --retry 3 --connect-timeout 15 --progress-bar -o $zip "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-$pkg"
          if ($LASTEXITCODE -ne 0) { throw "download" }
        } else { Invoke-WebRequest -Uri "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-$pkg" -OutFile $zip -UseBasicParsing }
        Expand-Archive -Path $zip -DestinationPath $ngDir -Force
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
      } catch { Warn "Could not download ngrok: the app works only on this computer"; return }
    }
  }
  if (-not (Test-Path $ngExe)) { Warn "ngrok not found: the app works only on this computer"; return }
  $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try {
    Ok ("ngrok " + ((& $ngExe version 2>$null) -split " ")[2])
    # ngrok needs a free account token, asked once and kept in ngrok's own settings
    if ($env:NGROK_AUTHTOKEN) { & $ngExe config add-authtoken $env:NGROK_AUTHTOKEN *> $null }
    $check = (& $ngExe config check 2>$null) -join " "
    $cfg = if ($check -match "configuration file at (.+)$") { $Matches[1].Trim() } else { "" }
    $hasToken = $cfg -and (Test-Path $cfg) -and ((Get-Content $cfg -Raw) -match "authtoken")
    if (-not $hasToken) {
      Write-Host ""
      Write-Host "    ngrok needs your (free) authtoken, only the first time:"
      Write-Host "      1. sign up / log in at https://dashboard.ngrok.com"
      Write-Host "      2. copy the token from https://dashboard.ngrok.com/get-started/your-authtoken"
      $token = (Read-Host "    Paste it here and press Enter (empty = skip)").Trim()
      if (-not $token) { Warn "No token: the app works only on this computer"; return }
      & $ngExe config add-authtoken $token *> $null
      if ($LASTEXITCODE -ne 0) { Warn "ngrok did not accept the token"; return }
      Ok "Token saved"
    }
    $ngLog = Join-Path $Logs "ngrok.log"
    $script:NgrokProc = Start-Process -FilePath $ngExe -ArgumentList "http", "$port", "--log=stdout", "--log-format=logfmt" `
      -WorkingDirectory $AppDir -NoNewWindow -PassThru -RedirectStandardOutput $ngLog -RedirectStandardError (Join-Path $Logs "ngrok.err.log")
    $env:PYTHONIOENCODING = "utf-8"
    & $VenvPy (Join-Path $AppDir "scripts\share.py") --out (Join-Path $RT "share") --log $ngLog
    if ($LASTEXITCODE -ne 0) {
      Stop-Process -Id $script:NgrokProc.Id -Force -ErrorAction SilentlyContinue
      Warn "No public link: the app works only on this computer (log: $ngLog)"
      return
    }
    Open-Browser (Join-Path $RT "share\qr.html")
    Write-Host ""
    Write-Host "    Friends open the link or scan the QR code. It works while this window stays open." -ForegroundColor White
    Write-Host '    The ngrok page "You are about to visit" may appear first: press "Visit Site".'
  } finally { $ErrorActionPreference = $old }
}

# ---------- 0. preliminary checks ----------
Write-Host "Remind Me Bro - Run & Go  (Academic Unified Hub & AI Assistant)" -ForegroundColor White
Write-Host "First start: 5-15 minutes (downloads ~3-4 GB on Windows). Next starts: a few seconds."
Set-Location $AppDir
New-Item -ItemType Directory -Force -Path (Join-Path $RT "bin"), $Logs | Out-Null
# Files extracted from a downloaded zip carry the "Mark of the Web": unblock our own files
Get-ChildItem -Path $AppDir -Force | Where-Object { $_.Name -ne ".runtime" -and $_.Name -ne ".venv" } | ForEach-Object {
  if ($_.PSIsContainer) { Get-ChildItem -Path $_.FullName -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue }
  else { Unblock-File -Path $_.FullName -ErrorAction SilentlyContinue }
}

foreach ($p in 8000..8005) {
  if ((Get-Http "http://127.0.0.1:$p/api/health") -match "Academic Unified Hub") {
    Ok "The app is already running on port $p"
    Open-Browser "http://127.0.0.1:$p/"
    exit 0
  }
}

try {
  # ---------- 1. uv ----------
  Step "1/5  Python tools"
  $UvExe = Join-Path $RT "bin\uv.exe"
  if (-not (Test-Path $UvExe)) {
    $sys = Get-Command uv -ErrorAction SilentlyContinue
    if ($sys) { $UvExe = $sys.Source } else {
      $target = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64-pc-windows-msvc" } else { "x86_64-pc-windows-msvc" }
      Write-Host "    Downloading uv..."
      $zip = Join-Path $RT "uv.zip"
      Download "https://github.com/astral-sh/uv/releases/latest/download/uv-$target.zip" $zip
      $tmp = Join-Path $RT "uv-tmp"
      Expand-Archive -Path $zip -DestinationPath $tmp -Force
      $found = Get-ChildItem -Path $tmp -Recurse -Filter "uv.exe" | Select-Object -First 1
      if (-not $found) { Fail "uv.exe not found in the archive" }
      Move-Item -Force $found.FullName (Join-Path $RT "bin\uv.exe")
      Remove-Item -Recurse -Force $tmp, $zip
    }
  }
  $env:UV_PYTHON_INSTALL_DIR = Join-Path $RT "python"
  $env:UV_PYTHON_PREFERENCE = "only-managed"
  Ok ("uv " + ((& $UvExe --version) -split " ")[1])

  # ---------- 2. Python + dependencies ----------
  Step "2/5  Python $PyVersion and app dependencies"
  $stampFile = Join-Path $RT ".req_stamp"
  # The environment stores absolute paths: if the folder was moved, renamed or copied,
  # its python no longer works and it must be rebuilt.
  $venvOk = $false
  if (Test-Path $VenvPy) { & $VenvPy -c "import sys" *> $null; $venvOk = ($LASTEXITCODE -eq 0) }
  if (-not $venvOk) {
    if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
    if (Test-Path $stampFile) { Remove-Item -Force $stampFile }
    & $UvExe venv $Venv --python $PyVersion --quiet
    if ($LASTEXITCODE -ne 0) { Fail "Cannot create the Python environment" }
  }
  $reqHash = (Get-FileHash (Join-Path $AppDir "requirements.txt") -Algorithm SHA256).Hash
  $stamp = if (Test-Path $stampFile) { (Get-Content $stampFile -Raw).Trim() } else { "" }
  & $VenvPy -c "import uvicorn, fastapi, sqlalchemy, chromadb, ollama, jose, passlib, jinja2, httpx, pypdf, pptx, docx" *> $null
  $pkgsOk = ($LASTEXITCODE -eq 0)
  if ($stamp -ne $reqHash -or -not $pkgsOk) {
    Write-Host "    Installing packages (first time only, ~1-3 min)..."
    $code = Invoke-Logged $UvExe @("pip", "install", "--python", $VenvPy, "-r", "requirements.txt") (Join-Path $Logs "pip.log")
    if ($code -ne 0) { Get-Content (Join-Path $Logs "pip.log") -Tail 20; Fail "Package installation failed" }
    Set-Content -Path $stampFile -Value $reqHash
  }
  Ok (& $VenvPy --version)
  # Smart Notes: speech-to-text for lesson recordings (optional: the app starts even if this fails)
  $whisperStampFile = Join-Path $Rt ".whisper_stamp"
  $whisperHash = (Get-FileHash (Join-Path $AppDir "requirements-whisper.txt") -Algorithm SHA256).Hash
  $whisperStamp = if (Test-Path $whisperStampFile) { (Get-Content $whisperStampFile -Raw).Trim() } else { "" }
  & $VenvPy -c "import faster_whisper" *> $null
  if ($whisperStamp -ne $whisperHash -or $LASTEXITCODE -ne 0) {
    Write-Host "    Installing speech-to-text for Smart Notes (first time only)..."
    $code = Invoke-Logged $UvExe @("pip", "install", "--python", $VenvPy, "-r", "requirements-whisper.txt") (Join-Path $Logs "pip-whisper.log")
    if ($code -eq 0) { Set-Content -Path $whisperStampFile -Value $whisperHash; Ok "Speech-to-text ready (faster-whisper)" }
    else { Warn "Speech-to-text could not be installed (see $Logs\pip-whisper.log): Smart Notes will skip audio and video" }
  }

  # ---------- 3. Ollama ----------
  Step "3/5  Local AI (Ollama + $Model)"
  if ($env:RMB_NO_AI -eq "1") {
    Warn "RMB_NO_AI=1: skipping Ollama (AI features will show as unavailable)"
  } else {
    $OllamaExe = $null
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { $OllamaExe = $cmd.Source }
    elseif (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe") { $OllamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }

    if (-not $OllamaExe) {
      Write-Host "    Downloading the Ollama installer (~1.5 GB)..."
      $setup = Join-Path $RT "OllamaSetup.exe"
      Download "https://ollama.com/download/OllamaSetup.exe" $setup
      Write-Host "    Installing Ollama for this user (no admin needed)..."
      Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
      Remove-Item -Force $setup -ErrorAction SilentlyContinue
      $OllamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
      if (-not (Test-Path $OllamaExe)) { Fail "Ollama installation failed. Install it from https://ollama.com/download and run again." }
    }
    Ok "Ollama: $OllamaExe"

    if (Test-Http "$OllamaUrl/api/version") { Ok "Ollama server already running" }
    else {
      $script:OllamaProc = Start-Process -FilePath $OllamaExe -ArgumentList "serve" -NoNewWindow -PassThru `
        -RedirectStandardOutput (Join-Path $Logs "ollama.log") -RedirectStandardError (Join-Path $Logs "ollama.err.log")
      for ($i = 0; $i -lt 40; $i++) { if (Test-Http "$OllamaUrl/api/version") { break }; Start-Sleep -Milliseconds 500 }
      if (-not (Test-Http "$OllamaUrl/api/version")) { Fail "Ollama did not start" }
      Ok "Ollama server started"
    }

    $modelTag = if ($Model -like "*:*") { $Model } else { "$Model`:latest" }
    if ((Get-Http "$OllamaUrl/api/tags") -match [regex]::Escape("`"name`":`"$modelTag`"")) {
      Ok "Model $modelTag already downloaded"
    } else {
      Write-Host "    Downloading the AI model $Model (~2 GB, first time only)..."
      & $OllamaExe pull $Model
      if ($LASTEXITCODE -ne 0) { Fail "Model download failed" }
      Ok "Model $Model ready"
    }
  }
  $env:OLLAMA_MODEL = $Model
  $env:OLLAMA_HOST = $OllamaUrl
  $env:ANONYMIZED_TELEMETRY = "False"

  # ---------- 4. Semantic search model ----------
  Step "4/5  Semantic search"
  $embStamp = Join-Path $RT ".embeddings_ready"
  if (-not (Test-Path $embStamp)) {
    Write-Host "    Preparing the search model (first time only)..."
    $code = Invoke-Logged $VenvPy @("-c", "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction as E; E()(['warm up'])") (Join-Path $Logs "embeddings.log")
    if ($code -eq 0) { New-Item -ItemType File -Force -Path $embStamp | Out-Null; Ok "Ready" }
    else { Warn "Could not prepare it now: it will be downloaded on the first Sync" }
  } else { Ok "Ready" }

  # ---------- 5. Start the app ----------
  Step "5/5  Starting UniSIS, UniLearn, UniComms and Remind Me Bro"
  function Get-FreePort($from, $to) {
    foreach ($p in $from..$to) {
      try { $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p); $l.Start(); $l.Stop(); return $p } catch { }
    }
    return $null
  }

  # UniSIS: our student information system (separate service, real OAuth 2.0 API)
  # The hub's port is chosen first so UniSIS and UniLearn can link back to it ("open the student hub")
  $Port = Get-FreePort 8000 8010
  if (-not $Port) { Fail "No free port between 8000 and 8010" }
  $env:RMB_HUB_URL = "http://127.0.0.1:$Port/"
  $UPort = Get-FreePort 8100 8110
  if (-not $UPort) { Fail "No free port between 8100 and 8110 for UniSIS" }
  $UnisisUrl = "http://127.0.0.1:$UPort"
  $env:UNISIS_PUBLIC_URL = $UnisisUrl
  $env:UNISIS_URL = $UnisisUrl
  $script:UnisisProc = Start-Process -FilePath $VenvPy -ArgumentList "-m", "uvicorn", "unisis.main:app", "--host", "127.0.0.1", "--port", "$UPort" `
    -WorkingDirectory $AppDir -NoNewWindow -PassThru `
    -RedirectStandardOutput (Join-Path $Logs "unisis.log") -RedirectStandardError (Join-Path $Logs "unisis.err.log")
  for ($i = 0; $i -lt 60; $i++) {
    if (Test-Http "$UnisisUrl/.well-known/oauth-authorization-server") { break }
    if ($script:UnisisProc.HasExited) { break }
    Start-Sleep -Milliseconds 500
  }
  if (-not (Test-Http "$UnisisUrl/.well-known/oauth-authorization-server")) {
    Get-Content (Join-Path $Logs "unisis.err.log") -Tail 25 -ErrorAction SilentlyContinue
    Fail "UniSIS did not start"
  }
  Ok "UniSIS running at $UnisisUrl"

  # UniLearn: our Moodle-compatible LMS (separate service, Moodle web-service API)
  $LPort = Get-FreePort 8200 8210
  if (-not $LPort) { Fail "No free port between 8200 and 8210 for UniLearn" }
  $UnilearnUrl = "http://127.0.0.1:$LPort"
  $env:UNILEARN_PUBLIC_URL = $UnilearnUrl
  $env:UNILEARN_URL = $UnilearnUrl
  $script:UnilearnProc = Start-Process -FilePath $VenvPy -ArgumentList "-m", "uvicorn", "unilearn.main:app", "--host", "127.0.0.1", "--port", "$LPort" `
    -WorkingDirectory $AppDir -NoNewWindow -PassThru `
    -RedirectStandardOutput (Join-Path $Logs "unilearn.log") -RedirectStandardError (Join-Path $Logs "unilearn.err.log")
  for ($i = 0; $i -lt 60; $i++) {
    if (Test-Http "$UnilearnUrl/login") { break }
    if ($script:UnilearnProc.HasExited) { break }
    Start-Sleep -Milliseconds 500
  }
  if (-not (Test-Http "$UnilearnUrl/login")) {
    Get-Content (Join-Path $Logs "unilearn.err.log") -Tail 25 -ErrorAction SilentlyContinue
    Fail "UniLearn did not start"
  }
  Ok "UniLearn running at $UnilearnUrl"

  # UniComms: the university's mail (like Outlook) and chat (like Teams): lecturers write, the hub reads
  $CPort = Get-FreePort 8300 8310
  if (-not $CPort) { Fail "No free port between 8300 and 8310 for UniComms" }
  $UnicommsUrl = "http://127.0.0.1:$CPort"
  $env:UNICOMMS_URL = $UnicommsUrl
  $script:UnicommsProc = Start-Process -FilePath $VenvPy -ArgumentList "-m", "uvicorn", "unicomms.main:app", "--host", "127.0.0.1", "--port", "$CPort" `
    -WorkingDirectory $AppDir -NoNewWindow -PassThru `
    -RedirectStandardOutput (Join-Path $Logs "unicomms.log") -RedirectStandardError (Join-Path $Logs "unicomms.err.log")
  for ($i = 0; $i -lt 60; $i++) {
    if (Test-Http "$UnicommsUrl/api/v1/health") { break }
    if ($script:UnicommsProc.HasExited) { break }
    Start-Sleep -Milliseconds 500
  }
  if (-not (Test-Http "$UnicommsUrl/api/v1/health")) {
    Get-Content (Join-Path $Logs "unicomms.err.log") -Tail 25 -ErrorAction SilentlyContinue
    Fail "UniComms did not start"
  }
  Ok "UniComms running at $UnicommsUrl"


  $script:BackendProc = Start-Process -FilePath $VenvPy -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port" `
    -WorkingDirectory $AppDir -NoNewWindow -PassThru `
    -RedirectStandardOutput (Join-Path $Logs "backend.log") -RedirectStandardError (Join-Path $Logs "backend.err.log")
  for ($i = 0; $i -lt 90; $i++) {
    if (Test-Http "http://127.0.0.1:$Port/api/health") { break }
    if ($script:BackendProc.HasExited) { break }
    Start-Sleep -Milliseconds 500
  }
  if (-not (Test-Http "http://127.0.0.1:$Port/api/health")) {
    Get-Content (Join-Path $Logs "backend.err.log") -Tail 25 -ErrorAction SilentlyContinue
    Fail "The app did not start"
  }

  $Url = "http://127.0.0.1:$Port/"
  Ok "Running at $Url"
  # Smart Notes: download the Whisper model in the background (once, ~150 MB), so the first recording is quick
  & $VenvPy -c "import faster_whisper" *> $null
  if ($LASTEXITCODE -eq 0) {
    $script:WhisperProc = Start-Process -FilePath $VenvPy -ArgumentList "-m", "app.services.notes.transcribe", "--download" `
      -WorkingDirectory $AppDir -NoNewWindow -PassThru `
      -RedirectStandardOutput (Join-Path $Logs "whisper.log") -RedirectStandardError (Join-Path $Logs "whisper.err.log")
  }
  # every staff password in one file (the services write their own part at start-up)
  $staffFile = Join-Path $AppDir "data\STAFF-PASSWORDS.txt"
  $parts = @("data\STAFF-PASSWORDS-hub.txt", "data\unisis\STAFF-PASSWORDS.txt", "data\unilearn\STAFF-PASSWORDS.txt") | ForEach-Object { Join-Path $AppDir $_ } | Where-Object { Test-Path $_ }
  $text = @("# Staff passwords of the demo. Only on this computer: never share this file or show it on screen.", "") + ($parts | ForEach-Object { Get-Content $_; "" })
  Set-Content -Path $staffFile -Value $text -Encoding UTF8
  Open-Browser $Url

  Write-Host ""
  Write-Host "Remind Me Bro is running  ->  $Url   (previous interface: ${Url}classic)" -ForegroundColor Green
  Write-Host ""
  Write-Host "  Students create their own account on the sign-in page ('Create account'). Demo student: student@demo.it"
  Write-Host "  Lecturers and staff sign in ONLY on this computer. Their passwords: data\STAFF-PASSWORDS.txt"
  Write-Host "    Lecturer  chiara.neri@demo.it   (also marco.rossi, laura.bianchi, giovanni.verdi, paolo.conti)"
  Write-Host ""
  Write-Host "  UniSIS (student information system)  ->  $UnisisUrl"
  Write-Host "    Student Office  registrar                    ->  $UnisisUrl/staff  (courses, timetable, exams, apps & keys)"
  Write-Host ""
  Write-Host "  UniLearn (Moodle-compatible LMS)     ->  $UnilearnUrl"
  Write-Host "    Teaching        marco.rossi, laura.bianchi, ...  ->  $UnilearnUrl/staff  (create courses)"
  Write-Host "    Admin           admin                        (also Web services: live API call log and tokens)"
  Write-Host ""
  Write-Host "  UniComms (mail like Outlook + Teams) ->  $UnicommsUrl/staff  (only on this computer, no password)"
  Write-Host "    Lecturers send emails and Teams posts to a course or to one student: they reach the Inbox by themselves"
  Write-Host ""
  Write-Host "  Everything starts empty and today's date is used. Create courses in UniLearn /staff and UniSIS /staff"
  Write-Host "  (same code in both), then as Giulia: Connect -> UniLearn and UniSIS, and Sync. Your data is kept."
  Write-Host ""
  Write-Host "Keep this window open. Close it (or press Ctrl+C) to stop the app." -ForegroundColor Yellow

  if ($env:RMB_SHARE -eq "1") { Start-Share $Port }

  while (-not $script:BackendProc.HasExited) { Start-Sleep -Seconds 1 }
}
finally {
  Stop-All
}
