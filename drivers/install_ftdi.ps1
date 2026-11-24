#requires -Version 5.1
<#
    Установка драйвера FTDI CDM из пакета ftdi_cdm.zip (рядом со скриптом).

    Запускать от имени администратора:
        powershell -ExecutionPolicy Bypass -File .\install_ftdi.ps1

    Параметры:
        -Zip <путь>     другой архив (по умолчанию .\ftdi_cdm.zip)
        -Rebind         дополнительно удалить устройство FTDI из системы
                        и выполнить повторное сканирование (если драйвер
                        "залип" после смены версии)
#>
param(
    [string]$Zip = (Join-Path $PSScriptRoot "ftdi_cdm.zip"),
    [switch]$Rebind
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Нужны права администратора. Запустите PowerShell от имени администратора." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $Zip)) {
    Write-Host "Не найден пакет: $Zip" -ForegroundColor Red
    Write-Host "Скачайте CDM-драйвер с сайта FTDI и положите архив рядом со скриптом." -ForegroundColor Yellow
    exit 1
}

$work = Join-Path $env:TEMP ("ftdi_cdm_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
Write-Host "Распаковка в $work ..."
Expand-Archive -Path $Zip -DestinationPath $work -Force

$infBus = Get-ChildItem -Path $work -Recurse -Filter "ftdibus.inf" | Select-Object -First 1
$infPort = Get-ChildItem -Path $work -Recurse -Filter "ftdiport.inf" | Select-Object -First 1
if (-not $infBus -or -not $infPort) {
    # в некоторых сборках имена другие
    $infBus = Get-ChildItem -Path $work -Recurse -Filter "usbbus.inf" | Select-Object -First 1
    $infPort = Get-ChildItem -Path $work -Recurse -Filter "usbport.inf" | Select-Object -First 1
}
if (-not $infBus -or -not $infPort) {
    Write-Host "В архиве не найдены inf-файлы драйвера." -ForegroundColor Red
    exit 1
}

Write-Host "Установка $($infBus.FullName)"
& pnputil.exe /add-driver $infBus.FullName /install
Write-Host "Установка $($infPort.FullName)"
& pnputil.exe /add-driver $infPort.FullName /install

if ($Rebind) {
    $devs = @(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like "USB\VID_0403&PID_6015*" })
    foreach ($d in $devs) {
        Write-Host "Удаляю экземпляр $($d.InstanceId) для повторного связывания"
        & pnputil.exe /remove-device $d.InstanceId
    }
}

& pnputil.exe /scan-devices
Start-Sleep -Seconds 4

Write-Host ""
Write-Host "Состояние устройства:"
$d = @(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like "USB\VID_0403&PID_6015*" })
if ($d.Count -eq 0) {
    Write-Host "  устройство не найдено (проверьте кабель)" -ForegroundColor Yellow
} else {
    $d | Select-Object Status, Class, FriendlyName, InstanceId | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
}

Write-Host "COM-порты:"
Get-PnpDevice -PresentOnly -Class Ports |
    Select-Object Status, FriendlyName | Format-Table -AutoSize | Out-String -Width 200 | Write-Host

Write-Host "Готово. Если порт не появился - перезагрузите ПК." -ForegroundColor Green