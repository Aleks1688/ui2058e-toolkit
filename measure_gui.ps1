#requires -Version 5.1
# UI2058E - окно замера: артикул/образец/тест -> чтение прибора -> запись в таблицу.

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:Base = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:Data = Join-Path $script:Base "data"
$script:OutDir = $script:Data
$script:Config = Join-Path $script:Data "config.json"

function Get-MasterCsv { Join-Path $script:OutDir "master.csv" }

function Save-Config {
    try {
        if (-not (Test-Path $script:Data)) { New-Item -ItemType Directory -Path $script:Data | Out-Null }
        @{ operator = $tbOperator.Text.Trim(); out_dir = $script:OutDir } |
            ConvertTo-Json | Set-Content -Path $script:Config -Encoding UTF8
    } catch {}
}

# Ищем настоящий python (не заглушку Microsoft Store из WindowsApps).
# Можно задать свой путь переменной окружения UI2058_PYTHON.
$script:Py = $null
$cands = @()
if ($env:UI2058_PYTHON) { $cands += $env:UI2058_PYTHON }
$cands += @(Get-Command python.exe -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
$cands += @(Get-Command py.exe -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
$cands += @("C:\ProgramData\Lenovo\AIAgent\MCPEnv\python-3.14.6-embed-amd64\python.exe")
foreach ($c in $cands) {
    if (-not $c) { continue }
    if ($c -like "*\WindowsApps\*") { continue }
    if (-not (Test-Path $c)) { continue }
    try {
        $ver = & $c -c "import sys; print(1 if sys.version_info[0] == 3 else 0)" 2>$null
        if ($LASTEXITCODE -eq 0 -and "$ver".Trim() -eq "1") { $script:Py = $c; break }
    } catch {}
}
if (-not $script:Py) {
    [System.Windows.Forms.MessageBox]::Show(
        "Не найден рабочий python.exe.`n`nПроверено:`n" + ($cands -join "`n") +
        "`n`nЕсли python установлен в другом месте, поправьте путь в measure_gui.ps1.", "UI2058 замер") | Out-Null
    return
}
$script:Measure = Join-Path $script:Base "ui2058_measure.py"
if (-not (Test-Path $script:Measure)) {
    [System.Windows.Forms.MessageBox]::Show("Не найден ui2058_measure.py рядом со скриптом.", "UI2058 замер") | Out-Null
    return
}

function Get-NextTest {
    param([string]$article, [string]$sample)
    $csv = Get-MasterCsv
    if (-not (Test-Path $csv)) { return 1 }
    try {
        $rows = @(Import-Csv -Path $csv -Encoding UTF8)
        $sel = @($rows | Where-Object { $_.'Артикул' -eq $article -and $_.'Образец' -eq $sample })
        if ($sel.Count -gt 0) {
            $mx = ($sel | ForEach-Object { [int]$_.'Тест №' } | Measure-Object -Maximum).Maximum
            return [int]$mx + 1
        }
        return 1
    } catch { return 1 }
}

# ---------- окно ----------
$form = New-Object System.Windows.Forms.Form
$form.Text = "UI2058E - замер и сохранение"
$form.ClientSize = New-Object System.Drawing.Size(624, 900)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedSingle"
$form.MaximizeBox = $false
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9.75)

function Add-Label($parent, $text, $x, $y) {
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $text
    $l.Location = New-Object System.Drawing.Point($x, $y)
    $l.AutoSize = $true
    $parent.Controls.Add($l)
}

function Add-Text($parent, $label, $x, $y, $w) {
    Add-Label $parent $label $x $y
    $t = New-Object System.Windows.Forms.TextBox
    $t.Location = New-Object System.Drawing.Point($x, ($y + 20))
    $t.Size = New-Object System.Drawing.Size($w, 26)
    $parent.Controls.Add($t)
    return $t
}

# --- группа "Изделие" ---
$gb1 = New-Object System.Windows.Forms.GroupBox
$gb1.Text = "Изделие"
$gb1.Location = New-Object System.Drawing.Point(12, 8)
$gb1.Size = New-Object System.Drawing.Size(600, 180)
$form.Controls.Add($gb1)

$tbArticle = Add-Text $gb1 "Артикул" 15 20 320
$tbSample  = Add-Text $gb1 "Образец" 350 20 100
$tbTest    = Add-Text $gb1 "Тест №" 465 20 55

$btnAuto = New-Object System.Windows.Forms.Button
$btnAuto.Text = "№ авто"
$btnAuto.Location = New-Object System.Drawing.Point(525, 40)
$btnAuto.Size = New-Object System.Drawing.Size(60, 26)
$gb1.Controls.Add($btnAuto)

$tbOperator = Add-Text $gb1 "Оператор" 15 86 270
$tbComment  = Add-Text $gb1 "Комментарий" 300 86 285

$lblPath = New-Object System.Windows.Forms.Label
$lblPath.Location = New-Object System.Drawing.Point(15, 146)
$lblPath.Size = New-Object System.Drawing.Size(570, 18)
$lblPath.AutoEllipsis = $true
$lblPath.ForeColor = [System.Drawing.Color]::Gray
$gb1.Controls.Add($lblPath)

$script:Tip = New-Object System.Windows.Forms.ToolTip
$script:Tip.SetToolTip($btnAuto, "Подставляет следующий номер теста для этой пары артикул+образец")

# --- группа "Замер" ---
$gb2 = New-Object System.Windows.Forms.GroupBox
$gb2.Text = "Замер"
$gb2.Location = New-Object System.Drawing.Point(12, 194)
$gb2.Size = New-Object System.Drawing.Size(600, 104)
$form.Controls.Add($gb2)

Add-Label $gb2 "Циклов:" 15 25
$numCycles = New-Object System.Windows.Forms.NumericUpDown
$numCycles.Location = New-Object System.Drawing.Point(80, 22)
$numCycles.Size = New-Object System.Drawing.Size(60, 26)
$numCycles.Minimum = 1
$numCycles.Maximum = 20
$numCycles.Value = 3
$gb2.Controls.Add($numCycles)

$chkWave = New-Object System.Windows.Forms.CheckBox
$chkWave.Text = "сохранять осциллограммы"
$chkWave.Location = New-Object System.Drawing.Point(170, 23)
$chkWave.AutoSize = $true
$gb2.Controls.Add($chkWave)

$btnRun = New-Object System.Windows.Forms.Button
$btnRun.Text = "СНЯТЬ ДАННЫЕ С ПРИБОРА"
$btnRun.Location = New-Object System.Drawing.Point(15, 56)
$btnRun.Size = New-Object System.Drawing.Size(570, 38)
$btnRun.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
$btnRun.BackColor = [System.Drawing.Color]::FromArgb(220, 240, 220)
$gb2.Controls.Add($btnRun)

# --- группа "Результат" ---
$gb3 = New-Object System.Windows.Forms.GroupBox
$gb3.Text = "Результат"
$gb3.Location = New-Object System.Drawing.Point(12, 304)
$gb3.Size = New-Object System.Drawing.Size(600, 520)
$form.Controls.Add($gb3)

$txtOut = New-Object System.Windows.Forms.TextBox
$txtOut.Location = New-Object System.Drawing.Point(10, 20)
$txtOut.Size = New-Object System.Drawing.Size(578, 488)
$txtOut.Multiline = $true
$txtOut.ReadOnly = $true
$txtOut.ScrollBars = "Vertical"
$txtOut.WordWrap = $false
$txtOut.Font = New-Object System.Drawing.Font("Consolas", 9.75)
$txtOut.BackColor = [System.Drawing.Color]::White
$gb3.Controls.Add($txtOut)

# --- низ ---
$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.Text = "Готово."
$lblStatus.Location = New-Object System.Drawing.Point(14, 830)
$lblStatus.AutoSize = $true
$form.Controls.Add($lblStatus)

$btnCopy = New-Object System.Windows.Forms.Button
$btnCopy.Text = "Копировать строку"
$btnCopy.Location = New-Object System.Drawing.Point(12, 856)
$btnCopy.Size = New-Object System.Drawing.Size(145, 34)
$form.Controls.Add($btnCopy)

$btnFolder = New-Object System.Windows.Forms.Button
$btnFolder.Text = "Папка замеров"
$btnFolder.Location = New-Object System.Drawing.Point(165, 856)
$btnFolder.Size = New-Object System.Drawing.Size(142, 34)
$form.Controls.Add($btnFolder)

$btnTable = New-Object System.Windows.Forms.Button
$btnTable.Text = "Общая таблица"
$btnTable.Location = New-Object System.Drawing.Point(315, 856)
$btnTable.Size = New-Object System.Drawing.Size(142, 34)
$form.Controls.Add($btnTable)

$btnLast = New-Object System.Windows.Forms.Button
$btnLast.Text = "Файл замера"
$btnLast.Location = New-Object System.Drawing.Point(465, 856)
$btnLast.Size = New-Object System.Drawing.Size(147, 34)
$form.Controls.Add($btnLast)

$script:LastRecord = ""

# ---------- логика ----------
$btnAuto.Add_Click({
    $tbTest.Text = [string](Get-NextTest $tbArticle.Text.Trim() $tbSample.Text.Trim())
})

$btnFolder.Add_Click({
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = "Куда сохранять замеры"
    $dlg.ShowNewFolderButton = $true
    if (Test-Path $script:OutDir) { $dlg.SelectedPath = $script:OutDir }
    if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $script:OutDir = $dlg.SelectedPath
        $lblPath.Text = "Замеры: " + $script:OutDir
        Save-Config
        $lblStatus.Text = "Папка замеров: " + $script:OutDir
        $lblStatus.ForeColor = [System.Drawing.Color]::ForestGreen
    }
})

$script:MenuOpen = New-Object System.Windows.Forms.ContextMenuStrip
$miOpen = New-Object System.Windows.Forms.ToolStripMenuItem "Открыть папку замеров"
$miOpen.Add_Click({
    if (Test-Path $script:OutDir) { Start-Process explorer.exe $script:OutDir }
    else { [System.Windows.Forms.MessageBox]::Show("Папка не найдена: $($script:OutDir)", "UI2058 замер") | Out-Null }
})
[void]$script:MenuOpen.Items.Add($miOpen)
$btnFolder.ContextMenuStrip = $script:MenuOpen
$script:Tip.SetToolTip($btnFolder, "Куда сохранять замеры. Правый клик - открыть текущую папку")

$btnTable.Add_Click({
    $x = Join-Path $script:OutDir "master.xlsx"
    $csv = Get-MasterCsv
    if (Test-Path $x) { Start-Process $x }
    elseif (Test-Path $csv) { Start-Process $csv }
    else { [System.Windows.Forms.MessageBox]::Show("В этой папке пока нет замеров.`n`n$($script:OutDir)", "UI2058 замер") | Out-Null }
})

$btnLast.Add_Click({
    if ($script:LastRecord -and (Test-Path $script:LastRecord)) { Start-Process $script:LastRecord }
    else { [System.Windows.Forms.MessageBox]::Show("Ещё не было замера.", "UI2058 замер") | Out-Null }
})

$btnCopy.Add_Click({
    $csv = Get-MasterCsv
    if (-not (Test-Path $csv)) {
        [System.Windows.Forms.MessageBox]::Show("В этой папке пока нет замеров.`n`n$($script:OutDir)", "UI2058 замер") | Out-Null
        return
    }
    try {
        $rows = @(Import-Csv -Path $csv -Encoding UTF8)
        if ($rows.Count -eq 0) { throw "таблица пуста" }
        $last = $rows[$rows.Count - 1]
        $cells = @($last.PSObject.Properties | ForEach-Object { [string]$_.Value })
        ($cells -join "`t") | Set-Clipboard
        $lblStatus.Text = "Строка скопирована - вставьте в Excel (Ctrl+V)."
        $lblStatus.ForeColor = [System.Drawing.Color]::ForestGreen
    } catch {
        [System.Windows.Forms.MessageBox]::Show("Не удалось скопировать: $_", "UI2058 замер") | Out-Null
    }
})

$form.Add_KeyDown({
    if ($_.Control -and $_.KeyCode -eq "Enter") { $btnRun.PerformClick() }
})

$btnRun.Add_Click({
    $article = $tbArticle.Text.Trim()
    $sample = $tbSample.Text.Trim()
    $test = $tbTest.Text.Trim()
    if (-not $article) { [System.Windows.Forms.MessageBox]::Show("Введите артикул.", "UI2058 замер") | Out-Null; $tbArticle.Focus(); return }
    if (-not $sample) { [System.Windows.Forms.MessageBox]::Show("Введите номер образца.", "UI2058 замер") | Out-Null; $tbSample.Focus(); return }
    if (-not $test) { $test = [string](Get-NextTest $article $sample); $tbTest.Text = $test }

    $btnRun.Enabled = $false
    $lblStatus.Text = "Снимаю данные... (не закрывайте окно)"
    $lblStatus.ForeColor = [System.Drawing.Color]::DarkOrange
    [System.Windows.Forms.Application]::DoEvents()

    $tmp = Join-Path $env:TEMP ("ui2058_" + [guid]::NewGuid().ToString("N") + ".json")
    $a = @($script:Measure, "--article", $article, "--sample", $sample,
           "--test", $test, "--operator", $tbOperator.Text.Trim(),
           "--comment", $tbComment.Text.Trim(), "--cycles", [string][int]$numCycles.Value,
           "--out-dir", $script:OutDir, "--json-out", $tmp)
    if ($chkWave.Checked) { $a += "--wave" }

    $procOut = ""
    try { $procOut = (& $script:Py @a 2>&1 | Out-String) }
    catch { $procOut = $_.Exception.Message }

    $res = $null
    if (Test-Path $tmp) {
        try { $res = Get-Content -Raw -Encoding UTF8 $tmp | ConvertFrom-Json } catch { $res = $null }
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }

    if ($null -eq $res) {
        $lblStatus.Text = "Ошибка."
        $lblStatus.ForeColor = [System.Drawing.Color]::Firebrick
        [System.Windows.Forms.MessageBox]::Show("Скрипт не вернул результат.`n`n$procOut", "UI2058 замер") | Out-Null
        $btnRun.Enabled = $true
        return
    }
    if (-not $res.ok) {
        $lblStatus.Text = "Ошибка: " + $res.error
        $lblStatus.ForeColor = [System.Drawing.Color]::Firebrick
        [System.Windows.Forms.MessageBox]::Show($res.error, "UI2058 замер") | Out-Null
        $btnRun.Enabled = $true
        return
    }

    $v = $res.values
    $hu = $res.harmonics_u
    $hi = $res.harmonics_i
    $o = $res.output
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine("Артикул: $($res.article)    Образец: $($res.sample)    Тест №: $($res.test)")
    [void]$sb.AppendLine("Прибор: $($res.version) ($($res.port))    циклов усреднено: $($res.cycles)")
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("Вход драйвера (RMS):")
    [void]$sb.AppendLine(("Urms    {0,10:F3} В" -f [double]$v.Urms_V))
    [void]$sb.AppendLine(("Irms    {0,10:F4} А" -f [double]$v.Irms_A))
    [void]$sb.AppendLine(("P       {0,10:F3} Вт" -f [double]$v.P_W))
    [void]$sb.AppendLine(("PF      {0,10:F4}" -f [double]$v.PF))
    [void]$sb.AppendLine(("Freq    {0,10:F3} Гц" -f [double]$v.Freq_Hz))
    [void]$sb.AppendLine(("Irmsw   {0,10:F4} А" -f [double]$v.Irmsw_A))
    [void]$sb.AppendLine(("CFv     {0,10:F3}" -f [double]$v.CFv))
    [void]$sb.AppendLine(("CFi     {0,10:F3}" -f [double]$v.CFi))
    if ($null -ne $o) {
        [void]$sb.AppendLine("")
        [void]$sb.AppendLine("Выход драйвера (RMS):")
        [void]$sb.AppendLine(("Ulamp   {0,10:F2} В" -f [double]$o.Ulamp_V))
        [void]$sb.AppendLine(("Ilamp   {0,10:F5} А" -f [double]$o.Ilamp_A))
        [void]$sb.AppendLine(("Pout    {0,10:F3} Вт" -f [double]$o.Pout_W))
        $effTxt = if ($null -ne $o.efficiency_pct) { "{0,10:F1} %" -f [double]$o.efficiency_pct } else { "     нет данных" }
        [void]$sb.AppendLine("КПД     " + $effTxt)
    }
    [void]$sb.AppendLine("")
    $tdu = if ($null -ne $res.thdu) { ("{0:F2}" -f [double]$res.thdu) + " %" } else { "нет данных" }
    $tdi = if ($null -ne $res.thdi) { ("{0:F2}" -f [double]$res.thdi) + " %" } else { "нет тока (нагрузка 0)" }
    [void]$sb.AppendLine("THDU: $tdu    THDI: $tdi")
    $uLine = ($hu.PSObject.Properties | Where-Object { $null -ne $_.Value } | ForEach-Object { "$($_.Name) $('{0:F2}' -f [double]$_.Value)" }) -join "  "
    $iLine = ($hi.PSObject.Properties | Where-Object { $null -ne $_.Value } | ForEach-Object { "$($_.Name) $('{0:F2}' -f [double]$_.Value)" }) -join "  "
    if (-not $uLine) { $uLine = "нет данных" }
    if (-not $iLine) { $iLine = "нет тока (нагрузка 0)" }
    [void]$sb.AppendLine("U гармоники: $uLine")
    [void]$sb.AppendLine("I гармоники: $iLine")
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine(("Разброс Urms за замер: {0:F3} В" -f [double]$res.spread_urms))
    [void]$sb.AppendLine("Запись: " + $res.record)
    [void]$sb.AppendLine("Таблица: " + $res.master_csv)

    $txtOut.Text = $sb.ToString()
    $script:LastRecord = $res.record
    $lblStatus.Text = "Сохранено: " + (Split-Path -Leaf $res.record)
    $lblStatus.ForeColor = [System.Drawing.Color]::ForestGreen
    $tbTest.Text = [string]([int]$res.test + 1)

    $btnRun.Enabled = $true
    [System.Windows.Forms.Application]::DoEvents()
})

$form.Add_Shown({
    $tbArticle.Focus() | Out-Null
    $tbTest.Text = "1"
})

if (Test-Path $script:Config) {
    try {
        $cfg = Get-Content -Raw -Encoding UTF8 $script:Config | ConvertFrom-Json
        if ($cfg.operator) { $tbOperator.Text = $cfg.operator }
        if ($cfg.out_dir) {
            if (Test-Path $cfg.out_dir) { $script:OutDir = $cfg.out_dir }
            else {
                $lblStatus.Text = "Папка замеров недоступна, сохраняю в data."
                $lblStatus.ForeColor = [System.Drawing.Color]::Firebrick
            }
        }
    } catch {}
}
$lblPath.Text = "Замеры: " + $script:OutDir

$form.Add_FormClosed({ Save-Config })

[void]$form.ShowDialog()