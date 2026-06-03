; Inno Setup script for a double-click PriorStates installer (.exe).
;
; Build on Windows with Inno Setup 6 (https://jrsoftware.org/isdl.php):
;     packaging\windows\build-installer.ps1        ; builds the wheel, then runs this
; or directly:
;     iscc /DMyAppVersion=0.1.0 /DWheel=priorstates-0.1.0-py3-none-any.whl packaging\windows\priorstates.iss
;
; This is a per-user install (no admin). It bundles the wheel and pip-installs it
; into the user's existing Python (>= 3.10 must be on PATH), then adds Start Menu
; and Desktop shortcuts that launch the desktop GUI. Node.js is optional (cockpit).

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef Wheel
  #define Wheel "priorstates-" + MyAppVersion + "-py3-none-any.whl"
#endif

[Setup]
AppId={{B4F2A1C0-7E3D-4A6B-9C21-PRIORSTATES0001}
AppName=PriorStates
AppVersion={#MyAppVersion}
AppPublisher=PriorStates contributors
AppComments=Shared memory & research journal for your AI agents
DefaultDirName={autopf}\PriorStates
DefaultGroupName=PriorStates
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\build\windows
OutputBaseFilename=PriorStates-{#MyAppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\..\build\windows\{#Wheel}"; DestDir: "{app}"; Flags: ignoreversion
Source: "launcher\PriorStates.vbs";        DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PriorStates";        Filename: "{sys}\wscript.exe"; Parameters: """{app}\PriorStates.vbs"""; Comment: "PriorStates desktop GUI"
Name: "{group}\PriorStates Cockpit (web)"; Filename: "{cmd}";     Parameters: "/k py -3 -m priorstates cockpit || python -m priorstates cockpit"; Comment: "Run the web cockpit"
Name: "{group}\Uninstall PriorStates"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PriorStates";  Filename: "{sys}\wscript.exe"; Parameters: """{app}\PriorStates.vbs"""; Tasks: desktopicon

[Run]
; Install the bundled wheel into the user's Python, then initialize data dirs.
Filename: "{code:GetPy}"; Parameters: "{code:PipInstallArgs}"; \
  StatusMsg: "Installing PriorStates into your Python..."; Flags: runhidden waituntilterminated
Filename: "{code:GetPy}"; Parameters: "{code:InitArgs}"; \
  StatusMsg: "Initializing PriorStates..."; Flags: runhidden waituntilterminated
Filename: "{sys}\wscript.exe"; Parameters: """{app}\PriorStates.vbs"""; \
  Description: "Launch PriorStates now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{code:GetPy}"; Parameters: "{code:UninstallArgs}"; Flags: runhidden; RunOnceId: "PipUninstall"

[Code]
var
  PyCmd: String;

{ Find a usable Python (>=3.10) on PATH. Prefers the 'py' launcher. '' if none. }
function DetectPy(): String;
var
  rc: Integer;
begin
  Result := '';
  if Exec('py', '-3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)"',
          '', SW_HIDE, ewWaitUntilTerminated, rc) and (rc = 0) then
    Result := 'py'
  else if Exec('python', '-c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)"',
          '', SW_HIDE, ewWaitUntilTerminated, rc) and (rc = 0) then
    Result := 'python';
end;

function GetPy(Param: String): String;
begin
  if PyCmd = '' then PyCmd := 'py';
  Result := PyCmd;
end;

{ The 'py' launcher needs a '-3' selector; bare 'python' must not get one. }
function PyPrefix(): String;
begin
  if GetPy('') = 'py' then Result := '-3 ' else Result := '';
end;

function PipInstallArgs(Param: String): String;
begin
  Result := PyPrefix + '-m pip install --user --upgrade --force-reinstall "' +
            ExpandConstant('{app}\{#Wheel}') + '"';
end;

function InitArgs(Param: String): String;
begin
  Result := PyPrefix + '-m priorstates init';
end;

function UninstallArgs(Param: String): String;
begin
  Result := PyPrefix + '-m pip uninstall -y priorstates';
end;

function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  PyCmd := DetectPy();
  if PyCmd = '' then
  begin
    if MsgBox('PriorStates needs Python 3.10 or newer on your PATH, which was not found.'#13#10#13#10 +
              'Install it from https://python.org (tick "Add python.exe to PATH"), then run this installer again.'#13#10#13#10 +
              'Open the download page now?', mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://www.python.org/downloads/', '', '', SW_SHOW, ewNoWait, ErrorCode);
    Result := False;
    exit;
  end;
  Result := True;
end;
