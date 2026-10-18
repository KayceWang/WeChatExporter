#define AppName "微信聊天记录导出器"
#define AppVersion "0.1.0"
#define AppExe "WeChatChatExporter.exe"
#ifndef AppSource
  #define AppSource "..\dist\WeChatChatExporter"
#endif

[Setup]
AppId={{F7A5BAF3-AB6B-4DA6-8DCE-1C81973B09CA}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Local
DefaultDirName={localappdata}\Programs\WeChatChatExporter
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=微信聊天记录导出器-0.1.0-安装包
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

