# Instalación / actualización del motor live en el VPS Windows (Darwinex MT5).
#
# Uso en PowerShell como administrador:
#   iwr https://raw.githubusercontent.com/dgarciagud/Forex/ccr-cc40f003-7upz2d/live/install_vps.ps1 -OutFile $env:TEMP\install_vps.ps1
#   powershell -ExecutionPolicy Bypass -File $env:TEMP\install_vps.ps1 -Mode live -Pairs EURUSD,USDJPY
#
# Parámetros (solo se aplican al CREAR la configuración, o con -ResetConfig):
#   -Mode    dry_run (por defecto) | live
#   -Pairs   pares que operan (los demás quedan con enabled = false). Vacío = los 5.
#            Cada par activo lleva weight = 0.2: el riesgo crece al añadir pares (20 % con los 5).
#   -ResetConfig  rehace C:\Carver\config.toml desde la plantilla
#
# Estructura:
#   C:\Carver\app          código (se reemplaza en cada actualización)
#   C:\Carver\config.toml  configuración del VPS (se crea una vez y NO se toca al actualizar)
#   C:\Carver\state, logs  bloqueos y registros (se conservan)
#
# expect_server se fija al servidor al que está conectado el MT5 al instalar: el motor solo
# operará en esa cuenta. Con -Mode live opera de verdad en cuanto actives 'Algo Trading'.

param(
    [ValidateSet("dry_run", "live")][string]$Mode = "dry_run",
    [string[]]$Pairs = @(),
    [switch]$ResetConfig
)
$ErrorActionPreference = "Stop"
$Branch = "ccr-cc40f003-7upz2d"
$Base = "C:\Carver"
$App = Join-Path $Base "app"
$Cfg = Join-Path $Base "config.toml"
$Mt5 = "C:\Program Files\Darwinex MetaTrader 5\terminal64.exe"
$TaskName = "CarverLive"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

Step "1. Comprobaciones"
$Python = (Get-Command python -ErrorAction Stop).Source
& $Python --version
if (-not (Test-Path $Mt5)) { throw "No encuentro MT5 en $Mt5" }
New-Item -ItemType Directory -Force $Base | Out-Null

Step "2. Parar el motor si ya estaba en marcha"
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*live.engine*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "parado PID $($_.ProcessId)" }

Step "3. Descargar el código (rama $Branch)"
$Zip = Join-Path $env:TEMP "forex.zip"
$Tmp = Join-Path $env:TEMP "forex_extract"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest "https://github.com/dgarciagud/Forex/archive/refs/heads/$Branch.zip" -OutFile $Zip -UseBasicParsing
if (Test-Path $Tmp) { Remove-Item $Tmp -Recurse -Force }
Expand-Archive $Zip -DestinationPath $Tmp
if (Test-Path $App) { Remove-Item $App -Recurse -Force }
Move-Item (Get-ChildItem $Tmp | Select-Object -First 1).FullName $App
Remove-Item $Zip, $Tmp -Recurse -Force
# Los datos históricos del backtest no hacen falta en el VPS (ahorra disco)
Remove-Item (Join-Path $App "data") -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "código en $App"

Step "4. Paquetes de Python (sin Anaconda)"
& $Python -m pip install --quiet --upgrade MetaTrader5 pandas numpy pytest
if ($LASTEXITCODE -ne 0) { throw "pip falló" }

Step "5. Configuración del VPS"
if ($ResetConfig -or -not (Test-Path $Cfg)) {
    # Servidor al que está conectado el MT5 (la configuración solo operará en ese servidor)
    $server = (& $Python -c "import MetaTrader5 as m; m.initialize(path=r'$Mt5') or exit(1); print(m.account_info().server); m.shutdown()").Trim()
    if (-not $server) { throw "No puedo leer la cuenta de MT5: ábrelo e inicia sesión" }
    $text = Get-Content (Join-Path $App "live\config.toml") -Raw -Encoding UTF8
    $text = $text -replace '(?m)^mode = "(live|dry_run)"', "mode = `"$Mode`""
    $text = $text -replace '(?m)^path = ""', "path = '$Mt5'"
    $text = $text -replace '(?m)^expect_server = "[^"]*"', "expect_server = `"$server`""
    $all = "EURUSD", "USDJPY", "EURCHF", "USDCAD", "EURNOK"
    $on = if ($Pairs.Count) { $Pairs | ForEach-Object { $_.Split(",") } | ForEach-Object { $_.Trim().ToUpper() } } else { $all }
    foreach ($p in $on) { if ($all -notcontains $p) { throw "par desconocido: $p" } }
    foreach ($p in $all) {
        if ($on -contains $p) {
            $text = $text -replace "(?m)^symbol = `"$p`"", "symbol = `"$p`"`r`nweight = 0.2"
        } else {
            $text = [regex]::Replace($text, "(?s)(symbol = `"$p`".*?)enabled = true", '${1}enabled = false')
        }
    }
    [IO.File]::WriteAllText($Cfg, $text, (New-Object Text.UTF8Encoding $false))
    Write-Host "creada $Cfg  (modo $Mode, servidor $server, pares: $($on -join ', '))"
} else {
    Write-Host "se conserva tu $Cfg (usa -ResetConfig para rehacerla)"
}
Select-String -Path $Cfg -Pattern '^(mode|capital|expect_server|path|symbol|weight|enabled) ' | ForEach-Object { $_.Line }

Step "6. Pruebas"
Push-Location $App
& $Python -m pytest live\tests -q
$tests = $LASTEXITCODE
Pop-Location
if ($tests -ne 0) { throw "las pruebas fallan; no se instala el arranque automático" }

Step "7. Estado contra tu MT5 (solo lectura, no opera)"
Push-Location $App
& $Python -m live.engine --config $Cfg --status
Pop-Location

Step "8. Arranque automático y reinicio si se cae"
$Bat = Join-Path $Base "run_forever.bat"
@"
@echo off
rem Motor live de Carver: se reinicia solo si se cae. Configuración: $Cfg
cd /d $App
if not exist $Base\logs mkdir $Base\logs
:loop
"$Python" -m live.engine --config $Cfg
echo [%date% %time%] el motor se ha detenido; reinicio en 30 s >> $Base\logs\reinicios.log
timeout /t 30 /nobreak > nul
goto loop
"@ | Set-Content -Path $Bat -Encoding ASCII
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Bat`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "tarea '$TaskName' creada y arrancada"

Step "9. Energía: sin suspensión ni hibernación"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /hibernate off 2>$null

if ($Mode -eq "live") {
    Write-Host "`nIMPORTANTE: en MT5 activa el botón 'Algo Trading'; sin él el motor no envía órdenes." -ForegroundColor Yellow
}

Step "Listo"
Write-Host "Motor en marcha en modo:" ((Select-String -Path $Cfg -Pattern '^mode = "(live|dry_run)"').Line -replace '\s*#.*$', '')
Write-Host "Registros: $Base\logs\live.log   |   Parar: crea el archivo $Base\STOP"
Write-Host "Actualizar: vuelve a ejecutar este script (conserva config.toml, state y logs)."
