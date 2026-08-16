; Standard installer: PDF and image tools only. It deliberately excludes LibreOffice.

#define AppName "OpenMerger"
#define AppVersion "1.0.0"
#define AppPublisher "OpenMerger"
#define AppExeName "OpenMerger.exe"

[Setup]
AppId={{A1DB97F7-5F4D-4A3B-B8D2-05B243C00A16}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\OpenMerger
DefaultGroupName=OpenMerger
OutputDir=..\installer-output
OutputBaseFilename=OpenMerger-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\OpenMerger.exe

[Files]
Source: "..\dist\OpenMerger\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\OpenMerger"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\OpenMerger"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch OpenMerger"; Flags: nowait postinstall skipifsilent
