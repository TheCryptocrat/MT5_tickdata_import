# Weekly wrapper invoked by the scheduled task. Rebuilds manifest then runs
# tdm_export.py in resume mode so a power-loss restart only repeats one symbol.
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "C:\Users\me\AppData\Local\Programs\Python\Python313\python.exe"

# Refresh the inventory in case Cree added new symbol folders since last run
& $python (Join-Path $here "inventory.py")
if ($LASTEXITCODE -ne 0) {
    Write-Error "inventory.py failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

# Run the export — resume mode picks up where we left off if state.json exists
& $python (Join-Path $here "tdm_export.py") --resume
exit $LASTEXITCODE
