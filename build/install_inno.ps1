$setupDir = Join-Path $env:TEMP 'inno-setup-6.7.3'
New-Item -ItemType Directory -Force -Path $setupDir | Out-Null
$installer = Join-Path $setupDir 'innosetup-6.7.3.exe'
Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $installer
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid') { throw 'Inno Setup installer signature validation failed.' }
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\InnoSetup6'
$process = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/CURRENTUSER', '/NORESTART', "/DIR=$installDir") -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) { throw 'Inno Setup installation failed.' }
Get-Item (Join-Path $installDir 'ISCC.exe') | Select-Object FullName, Length
$signature.SignerCertificate.Subject
