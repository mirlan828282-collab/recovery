#define MyAppName "Recovery HDD"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Recovery HDD"
#define MyAppExeName "RecoveryHDD.exe"

[Setup]
AppId={{A1D0D7E4-9E1D-4C9A-A8A5-3D8D4A1E0001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Recovery HDD
DefaultGroupName=Recovery HDD
OutputDir=..\Output
OutputBaseFilename=RecoveryHDD_Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\RecoveryHDD\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Recovery HDD"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Recovery HDD"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить Recovery HDD"; Flags: postinstall nowait
