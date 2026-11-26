"""Exercise the real launcher function without starting services or containers."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


LAUNCHER = Path(__file__).resolve().parents[1] / 'dev' / 'dev.ps1'
POWERSHELL = shutil.which('powershell.exe')
HARNESS = r'''
param([string]$Launcher, [string]$Scenario)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Launcher, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Launcher has PowerShell parse errors.' }
$definition = $ast.Find({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-ServiceProcess'
}, $false)
. ([scriptblock]::Create($definition.Extent.Text))
$runtimeDir = $env:TEMP
$script:stops = 0
$script:freshProcess = [pscustomobject]@{
    Id = 24680
    StartTime = [datetime]'2026-10-08T01:02:03Z'
    Pinned = $false
    RefreshCount = 0
    PathReads = 0
    HasExited = $Scenario -eq 'exited'
}
$script:freshProcess | Add-Member ScriptProperty Handle {
    $this.Pinned = $true
    return [IntPtr]123
}
$script:freshProcess | Add-Member ScriptProperty Path {
    $this.PathReads++
    if ($Scenario -eq 'missing') { return $null }
    if ($Scenario -eq 'blank') { return ' ' }
    # Process metadata can be unavailable on creation and cached until Refresh.
    if ($Scenario -eq 'delayed' -and $this.RefreshCount -lt 2) { return $null }
    if ($Scenario -eq 'dll-only' -or ($Scenario -eq 'dll-first' -and $this.RefreshCount -lt 2)) {
        return 'C:\Windows\System32\ntdll.dll'
    }
    return 'C:\observed\node.exe'
}
$script:freshProcess | Add-Member ScriptMethod Refresh {
    if (-not $this.Pinned) { throw 'Process handle must be pinned before waiting.' }
    $this.RefreshCount++
}
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru,
        $RedirectStandardOutput, $RedirectStandardError)
    if ($WindowStyle -ne 'Hidden') { throw 'Launch must remain hidden.' }
    return $script:freshProcess
}
function Get-Process { throw 'Never reacquire the fresh process by PID.' }
function Stop-ProcessTree($Process) {
    if (-not [object]::ReferenceEquals($Process, $script:freshProcess)) { throw 'Wrong process cleaned up.' }
    if (-not $Process.Pinned) { throw 'Cleanup handle was not pinned.' }
    $script:stops++
    $Process.HasExited = $true
}
$timer = [Diagnostics.Stopwatch]::StartNew()
$service = $null
$failure = $null
try { $service = Start-ServiceProcess 'frontend' 'C:\requested\node.exe' @('test.js') $env:TEMP }
catch { $failure = $_.Exception.Message }
[pscustomobject]@{
    service = $service
    failure = $failure
    stops = $script:stops
    pinned = $script:freshProcess.Pinned
    path_reads = $script:freshProcess.PathReads
    elapsed_ms = $timer.ElapsedMilliseconds
} | ConvertTo-Json -Depth 4 -Compress
'''


@unittest.skipUnless(os.name == 'nt' and POWERSHELL, 'Windows PowerShell launcher')
class DevProcessIdentityTests(unittest.TestCase):
    def test_reads_only_api_runtime_settings_with_process_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / '.env'
            receipt = (root / 'science results' / 'tabular.json').as_posix()
            pin = 'a' * 64
            config.write_text(
                f'PAPERASSIST_BIO_TABULAR_RUNTIME_MANIFEST="{receipt}"\n'
                'PAPERASSIST_BULK_MODEL_RUNTIME_MANIFEST=file-value\n'
                'PAPERASSIST_SKILL_WORKFLOWS=sci_narrative_review\n'
                f'PAPERASSIST_SKILLS_MANIFEST_SHA256={pin}\n'
                'PAPERASSIST_LAUNCHER_TEST_PRIVATE=ignored\n', encoding='utf-8-sig',
            )
            harness = root / 'manifests.ps1'
            harness.write_text(r'''
param([string]$Launcher, [string]$Python, [string]$Config)
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Launcher, [ref]$tokens, [ref]$errors)
$definition = $ast.Find({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Import-ApiRuntimeSettings'
}, $false)
if (-not $definition) { throw 'No API runtime settings loader.' }
. ([scriptblock]::Create($definition.Extent.Text))
Remove-Item Env:PAPERASSIST_BIO_TABULAR_RUNTIME_MANIFEST -ErrorAction SilentlyContinue
Remove-Item Env:PAPERASSIST_LAUNCHER_TEST_PRIVATE -ErrorAction SilentlyContinue
Remove-Item Env:PAPERASSIST_SKILLS_MANIFEST_SHA256 -ErrorAction SilentlyContinue
$env:PAPERASSIST_BULK_MODEL_RUNTIME_MANIFEST = 'process-value'
$env:PAPERASSIST_SKILL_WORKFLOWS = 'statistical_explanation'
Import-ApiRuntimeSettings $Python $Config
[pscustomobject]@{
    tabular = $env:PAPERASSIST_BIO_TABULAR_RUNTIME_MANIFEST
    bulk = $env:PAPERASSIST_BULK_MODEL_RUNTIME_MANIFEST
    workflows = $env:PAPERASSIST_SKILL_WORKFLOWS
    pin = $env:PAPERASSIST_SKILLS_MANIFEST_SHA256
    private = $env:PAPERASSIST_LAUNCHER_TEST_PRIVATE
} | ConvertTo-Json -Compress
''', encoding='utf-8')
            result = subprocess.run(
                [POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                 '-File', str(harness), str(LAUNCHER), sys.executable, str(config)],
                capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), dict(tabular=receipt, bulk='process-value', private=None,
                                                       workflows='statistical_explanation', pin=pin))

    def test_status_runs_worker_with_workspace_python_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dev = root / 'script' / 'dev'
            dev.mkdir(parents=True)
            launcher = dev / 'dev.ps1'
            shutil.copyfile(LAUNCHER, launcher)
            (dev / 'worker_stack.py').write_text(
                "import sys\nprint('probe:', sys.executable, sys.argv[1])\n", encoding='utf8')
            runtime = dev.parent / '.runtime'
            runtime.mkdir()
            (runtime / 'dev-python.txt').write_text(sys.executable, encoding='utf8')
            result = subprocess.run(
                [POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                 '-File', str(launcher), 'status'], cwd=root.parent, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'probe: {sys.executable} status'.lower(), result.stdout.lower())

    def run_scenario(self, scenario):
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'identity.ps1'
            harness.write_text(HARNESS, encoding='utf-8')
            result = subprocess.run(
                [POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                 '-File', str(harness), str(LAUNCHER), scenario],
                capture_output=True, text=True, timeout=12,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_waits_for_observed_path_before_returning_identity(self):
        result = self.run_scenario('delayed')
        self.assertIsNone(result['failure'])
        self.assertEqual(result['service']['executable'], r'C:\observed\node.exe')
        self.assertEqual(result['service']['process_id'], 24680)
        self.assertEqual(result['service']['started_utc'], '2026-10-08T01:02:03.0000000Z')
        self.assertTrue(result['pinned'])
        self.assertGreaterEqual(result['path_reads'], 2)
        self.assertEqual(result['stops'], 0)

    def test_missing_path_fails_with_bounded_cleanup_of_fresh_process(self):
        for scenario in ('missing', 'blank', 'dll-only'):
            with self.subTest(scenario=scenario):
                result = self.run_scenario(scenario)
                self.assertIsNone(result['service'])
                self.assertIn('identity', result['failure'].lower())
                self.assertEqual(result['stops'], 1)
                self.assertTrue(result['pinned'])
                self.assertLess(result['elapsed_ms'], 6000)

    def test_waits_for_node_image_when_windows_initially_reports_a_dll(self):
        result = self.run_scenario('dll-first')
        self.assertIsNone(result['failure'])
        self.assertEqual(result['service']['executable'], r'C:\observed\node.exe')
        self.assertEqual(result['stops'], 0)

    def test_exited_process_never_returns_identity_or_stops_another_process(self):
        result = self.run_scenario('exited')
        self.assertIsNone(result['service'])
        self.assertIn('exited', result['failure'].lower())
        self.assertEqual(result['stops'], 0)
        self.assertTrue(result['pinned'])
        self.assertLess(result['elapsed_ms'], 1000)


if __name__ == '__main__':
    unittest.main()
