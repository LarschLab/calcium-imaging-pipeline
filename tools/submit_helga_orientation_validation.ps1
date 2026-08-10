param(
    [Parameter(Mandatory = $true)][string]$JobRoot,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$MicroscopyRoot,
    [string]$FishId = "L395_f11"
)

$codeRoot = Join-Path $JobRoot "code"
$outputRoot = Join-Path $JobRoot "output"
$stdoutPath = Join-Path $JobRoot "stdout.log"
$stderrPath = Join-Path $JobRoot "stderr.log"
$recordPath = Join-Path $JobRoot "job.json"
$scriptPath = Join-Path $codeRoot "validate_canonical_orientation_real_data.py"

$arguments = @(
    "-u",
    $scriptPath,
    "--microscopy-root", $MicroscopyRoot,
    "--fish-id", $FishId,
    "--output-dir", $outputRoot
)
$process = Start-Process `
    -FilePath $PythonPath `
    -ArgumentList $arguments `
    -WorkingDirectory $codeRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -WindowStyle Hidden `
    -PassThru

$record = [ordered]@{
    name = "canonical-spatial-L395-f11"
    pid = $process.Id
    submitted_at = (Get-Date).ToString("o")
    working_directory = $codeRoot
    command = $PythonPath
    arguments = $arguments
    stdout = $stdoutPath
    stderr = $stderrPath
    expected_report = (Join-Path $outputRoot "validation_report.json")
}
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $recordPath -Encoding UTF8
$record | ConvertTo-Json -Depth 5
