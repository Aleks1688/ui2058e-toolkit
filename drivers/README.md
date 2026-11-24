# Драйвер FTDI

Прибор подключается через USB-UART адаптер **FTDI FT231X**
(`VID_0403 / PID_6015`). Нужен драйвер **FTDI CDM (VCP)** — обычный
виртуальный COM-порт.

## Быстрая установка

1. Поместите пакет `ftdi_cdm.zip` в эту папку (он уже здесь в репозитории).
2. Запустите PowerShell **от администратора**:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_ftdi.ps1
```

3. Проверьте в диспетчере устройств:
   - «Контроллеры USB» → **USB Serial Converter**;
   - «Порты (COM и LPT)» → **USB Serial Port (COMx)**, без восклицательного знака.

Если драйвер «залип» после обновления, запустите с ключом `-Rebind`.

## Вручную

Распакуйте архив и установите по очереди:

- `ftdibus.inf` → правой кнопкой → «Установить»;
- `ftdiport.inf` → правой кнопкой → «Установить».

Или через `pnputil`:

```bat
pnputil /add-driver <путь>\ftdibus.inf  /install
pnputil /add-driver <путь>\ftdiport.inf /install
pnputil /scan-devices
```

## Типовые проблемы

| Симптом | Причина | Решение |
|---------|---------|---------|
| Восклицательный знак, «код 39», STATUS_DRIVER_BLOCKED | старый драйвер 2.12.00.x заблокирован изоляцией ядра Windows 11 | поставить CDM 2.12.36.x (в архиве) |
| Устройство видно, но со стрелкой вниз («код 22», Disabled) | Windows отключила устройство | диспетчер устройств → «Включить устройство»; затем перезапустить программу |
| Порт «COM28», а работает COM7 | устаревшая подпись после смены номера | ориентироваться на `HKLM\HARDWARE\DEVICEMAP\SERIALCOMM` |
| «Access denied» при открытии порта | порт держит `UI2058.exe` | закрыть фирменную программу |

Подробнее — [../docs/windows-setup.md](../docs/windows-setup.md).

## Источник

Официальный установщик FTDI: <https://ftdichip.com/drivers/vcp-drivers/>
(раздел CDM, Windows). В `ftdi_cdm.zip` лежит версия 2.12.36.20 (WHQL).