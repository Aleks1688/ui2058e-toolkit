#requires -Version 5.1
<#
    Автопроверка окна замера: запускает measure_gui.ps1, заполняет поля,
    нажимает "СНЯТЬ ДАННЫЕ С ПРИБОРА", ждёт появления строки в master.csv
    и выводит текст результата.

    ВНИМАНИЕ: создаёт реальный замер (артикул SELFTEST) в data/.
    Запускать при подключённом приборе и закрытой UI2058.exe.

        powershell -ExecutionPolicy Bypass -File tools\selftest_gui.ps1
#>
param(
    [string]$Article = "SELFTEST",
    [string]$Sample = "0"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class W3 {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr hParent, EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder sb, int n);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, StringBuilder sb, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageW(IntPtr h, uint msg, IntPtr wp, string lp);
    [DllImport("user32.dll")] public static extern IntPtr SendMessageW(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageW(IntPtr h, uint msg, IntPtr wp, StringBuilder sb);
    [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    public struct RECT { public int L, T, R, B; }
}
"@
[void][W3]::SetProcessDPIAware()

function Get-Text([IntPtr]$h) {
    $sb = New-Object System.Text.StringBuilder 1024
    [void][W3]::GetWindowTextW($h, $sb, 1024)
    return $sb.ToString()
}
function Get-Cls([IntPtr]$h) {
    $sb = New-Object System.Text.StringBuilder 256
    [void][W3]::GetClassNameW($h, $sb, 256)
    return $sb.ToString()
}

$root = Split-Path -Parent $PSScriptRoot
$gui = Join-Path $root "measure_gui.ps1"
$master = Join-Path $root "data\master.csv"
if (-not (Test-Path $gui)) { Write-Output "не найден $gui"; exit 1 }

$before = 0
if (Test-Path $master) { $before = (Get-Content $master -Encoding UTF8).Count }

$proc = Start-Process powershell.exe -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", "`"$gui`"") -PassThru
Write-Output "started pid=$($proc.Id)"
$tpid = [uint32]$proc.Id

$hwnd = [IntPtr]::Zero
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 300
    $script:found = [IntPtr]::Zero
    $cb = [W3+EnumProc]{ param($h, $l)
        $wp = [uint32]0; [void][W3]::GetWindowThreadProcessId($h, [ref]$wp)
        if ($wp -eq $tpid -and [W3]::IsWindowVisible($h)) {
            $t = Get-Text $h
            if ($t -like "*UI2058E*") { $script:found = $h }
        }
        return $true }
    [void][W3]::EnumWindows($cb, [IntPtr]::Zero)
    if ($script:found -ne [IntPtr]::Zero) { $hwnd = $script:found; break }
}
if ($hwnd -eq [IntPtr]::Zero) { Write-Output "окно не появилось (exited=$($proc.HasExited))"; exit 1 }
Write-Output ("window=0x{0:X}" -f [Int64]$hwnd)
Start-Sleep -Milliseconds 600

function Get-Kids {
    $script:kids = @()
    $cb2 = [W3+EnumProc]{ param($h, $l)
        $r = New-Object W3+RECT
        [void][W3]::GetWindowRect($h, [ref]$r)
        $script:kids += [pscustomobject]@{ H = $h; Cls = (Get-Cls $h); Txt = (Get-Text $h);
            X = $r.L; Y = $r.T; W = ($r.R - $r.L); Hh = ($r.B - $r.T) }
        return $true }
    [void][W3]::EnumChildWindows($hwnd, $cb2, [IntPtr]::Zero)
    return $script:kids
}

$kids = Get-Kids
$edits = @($kids | Where-Object { $_.Cls -like "*EDIT*" } | Sort-Object Y, X)
$fields = @($edits | Where-Object { $_.Hh -lt 60 })
if ($fields.Count -lt 5) { Write-Output "поля не найдены"; [void][W3]::PostMessageW($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero); exit 1 }

# артикул, образец, тест, оператор, комментарий
$vals = @($Article, $Sample, "1", "selftest", "autotest okna")
for ($i = 0; $i -lt 5; $i++) { [void][W3]::SendMessageW($fields[$i].H, 0x000C, [IntPtr]::Zero, $vals[$i]) }
Start-Sleep -Milliseconds 300

$run = @($kids | Where-Object { $_.Cls -like "*BUTTON*" -and $_.Txt -like "*СНЯТЬ*" }) | Select-Object -First 1
if (-not $run) { Write-Output "кнопка замера не найдена"; exit 1 }

Write-Output "нажимаю кнопку замера..."
[void][W3]::SendMessageW($run.H, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)

$ok = $false
for ($i = 0; $i -lt 80; $i++) {
    Start-Sleep -Milliseconds 500
    if ((Test-Path $master) -and (Get-Content $master -Encoding UTF8).Count -gt $before) { $ok = $true; break }
}
Write-Output "new_row=$ok"
Start-Sleep -Milliseconds 900

$kids2 = Get-Kids
$txt = @($kids2 | Where-Object { $_.Cls -like "*EDIT*" -and $_.Hh -ge 60 }) | Select-Object -First 1
if ($txt) {
    $len = [int]([W3]::SendMessageW($txt.H, 0x000E, [IntPtr]::Zero, [IntPtr]::Zero))
    $sb = New-Object System.Text.StringBuilder ($len + 2)
    [void][W3]::SendMessageW($txt.H, 0x000D, [IntPtr]::new($len + 1), $sb)
    Write-Output "--- результат ---"
    Write-Output $sb.ToString()
}
if (Test-Path $master) {
    Write-Output "--- последняя строка master.csv ---"
    Get-Content $master -Encoding UTF8 | Select-Object -Last 1
}

[void][W3]::PostMessageW($hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
Start-Sleep -Milliseconds 1200
if (-not $proc.HasExited) { Write-Output "окно всё ещё открыто, pid=$($proc.Id)" }
if (-not $ok) { exit 1 }