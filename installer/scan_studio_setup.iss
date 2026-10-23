; Inno Setup Script for SCAN — Intelligent Point Cloud Studio
; Windows 11 Local-First Scan-to-CAD/BIM Studio

#define MyAppName "SCAN — Intelligent Point Cloud Studio"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Antigravity Engineering"
#define MyAppURL "https://github.com/maxim505885-jpg/Antigrav"
#define MyAppExeName "Запустить_SCAN.bat"

[Setup]
AppId={{5E973B90-E57A-4543-8473-A3FE9DF3289E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\ScanStudio
DisableProgramGroupPage=yes
OutputBaseFilename=SCAN_Studio_Windows11_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\Запустить_ScanToBIM.bat"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
Source: "..\intelligent-scan-to-bim\*"; DestDir: "{app}\intelligent-scan-to-bim"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: shellexec postinstall skipifsilent
