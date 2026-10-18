$ErrorActionPreference = 'Stop'
$installer = (Resolve-Path 'dist\微信聊天记录导出器-0.1.0-安装包.exe').Path
$tempBase = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
$target = [System.IO.Path]::GetFullPath((Join-Path $env:TEMP ('WeChatExporterSmoke-' + [guid]::NewGuid().ToString('N'))))
if (-not $target.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Smoke install target escaped the temporary directory.' }
try {
    $setup = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$target") -Wait -PassThru -WindowStyle Hidden
    if ($setup.ExitCode -ne 0) { throw 'Trial installer returned a nonzero exit code.' }
    $app = Join-Path $target 'WeChatChatExporter.exe'
    if (-not (Test-Path -LiteralPath $app)) { throw 'Installed application executable is missing.' }
    $program = Start-Process -FilePath $app -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5
    $program.Refresh()
    if ($program.HasExited) { throw 'Installed application exited during startup.' }
    Stop-Process -Id $program.Id -Force
    Wait-Process -Id $program.Id -ErrorAction SilentlyContinue
    $uninstaller = Join-Path $target 'unins000.exe'
    if (-not (Test-Path -LiteralPath $uninstaller)) { throw 'Uninstaller was not installed.' }
    $remove = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru -WindowStyle Hidden
    if ($remove.ExitCode -ne 0) { throw 'Trial uninstaller returned a nonzero exit code.' }
    if (Test-Path -LiteralPath $target) { throw 'Uninstaller left files in its temporary install folder.' }
    'installer_install_start_uninstall=ok'
} finally {
    if (Test-Path -LiteralPath $target) {
        if (-not $target.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Cleanup target escaped the temporary directory.' }
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
