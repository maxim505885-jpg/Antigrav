; Inno Setup Script for SCAN — Intelligent Point Cloud Studio
; Windows 11 Local-First Scan-to-CAD/BIM Studio

#define MyAppName "SCAN — Intelligent Point Cloud Studio"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Antigravity Engineering"
#define MyAppURL "https://github.com/maxim505885-jpg/Antigrav"
#define MyAppExeName "Запустить_SCAN.bat"
#define PythonBase GetEnv("LOCALAPPDATA") + "\Programs\Python\Python313"

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
Source: "..\Запустить_SCAN.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\desktop_app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\backend\*"; DestDir: "{app}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*;*.pyc"
Source: "..\frontend\dist\*"; DestDir: "{app}\frontend\dist"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\.venv\*"; DestDir: "{app}\.venv"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*;*.pyc;*.pyo"
Source: "{#PythonBase}\*"; DestDir: "{app}\python313"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*;*.pyc;Doc\*;include\*;libs\*"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: shellexec postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigPath: string;
  ConfigText: string;
  OldHome: string;
begin
  if CurStep = ssPostInstall then
  begin
    ConfigPath := ExpandConstant('{app}\.venv\pyvenv.cfg');
    OldHome := 'home = {#PythonBase}';
    if not LoadStringFromFile(ConfigPath, ConfigText) then
      RaiseException('Could not read the bundled Python environment configuration.');
    if StringChangeEx(ConfigText, OldHome, 'home = ' + ExpandConstant('{app}\python313'), True) = 0 then
      RaiseException('The bundled Python runtime path did not match the expected build runtime.');
    if not SaveStringToFile(ConfigPath, ConfigText, False) then
      RaiseException('Could not configure the bundled Python runtime.');
  end;
end;
