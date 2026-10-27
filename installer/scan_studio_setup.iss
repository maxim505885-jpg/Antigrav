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
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\Запустить_SCAN.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\desktop_app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\backend\scan2bim\*"; DestDir: "{app}\backend\scan2bim"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
Source: "..\contracts\*.json"; DestDir: "{app}\contracts"; Flags: ignoreversion
Source: "..\frontend\dist\*"; DestDir: "{app}\frontend\dist"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\.venv\*"; DestDir: "{app}\.venv"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,tests\*,*.pyc,*.pyo,Lib\site-packages\jedi\third_party\typeshed\*"
Source: "{#PythonBase}\*"; DestDir: "{app}\python313"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,tests\*,*.pyc,Doc\*,include\*,libs\*,Lib\site-packages\*,Lib\test\*,Lib\tests\*"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: shellexec postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigPath: string;
  ConfigLines: TArrayOfString;
  NewHome: string;
  NewExecutable: string;
  NewCommand: string;
  LineIndex: Integer;
  PythonHomeReplaced: Boolean;
  PythonExecutableReplaced: Boolean;
  PythonCommandReplaced: Boolean;
begin
  if CurStep = ssPostInstall then
  begin
    ConfigPath := ExpandConstant('{app}\.venv\pyvenv.cfg');
    NewHome := 'home = ' + ExpandConstant('{app}\python313');
    NewExecutable := 'executable = ' + ExpandConstant('{app}\python313\python.exe');
    NewCommand := 'command = "' + ExpandConstant('{app}\python313\python.exe') +
      '" -m venv "' + ExpandConstant('{app}\.venv') + '"';
    if not LoadStringsFromFile(ConfigPath, ConfigLines) then
      RaiseException('Could not read the bundled Python environment configuration.');
    PythonHomeReplaced := False;
    PythonExecutableReplaced := False;
    PythonCommandReplaced := False;
    for LineIndex := 0 to GetArrayLength(ConfigLines) - 1 do
    begin
      if Pos('home = ', ConfigLines[LineIndex]) = 1 then
      begin
        ConfigLines[LineIndex] := NewHome;
        PythonHomeReplaced := True;
      end;
      if Pos('executable = ', ConfigLines[LineIndex]) = 1 then
      begin
        ConfigLines[LineIndex] := NewExecutable;
        PythonExecutableReplaced := True;
      end;
      if Pos('command = ', ConfigLines[LineIndex]) = 1 then
      begin
        ConfigLines[LineIndex] := NewCommand;
        PythonCommandReplaced := True;
      end;
    end;
    if not PythonHomeReplaced then
      RaiseException('The bundled Python runtime path did not match the expected build runtime.');
    if not PythonExecutableReplaced or not PythonCommandReplaced then
      RaiseException('The bundled Python environment configuration is incomplete.');
    if not SaveStringsToUTF8FileWithoutBOM(ConfigPath, ConfigLines, False) then
      RaiseException('Could not configure the bundled Python runtime.');
  end;
end;
