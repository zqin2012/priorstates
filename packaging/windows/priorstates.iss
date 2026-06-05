; Inno Setup script for a double-click PriorStates installer (.exe).
;
; Build on Windows with Inno Setup 6 (https://jrsoftware.org/isdl.php):
;     packaging\windows\build-installer.ps1        ; builds the wheel, then runs this
; or directly:
;     iscc /DMyAppVersion=0.1.0 /DWheel=priorstates-0.1.0-py3-none-any.whl packaging\windows\priorstates.iss
;
; This is a per-user install (no admin). It bundles the wheel and pip-installs it
; into a Python 3.10+ interpreter. If no suitable Python is found, the installer
; downloads and silently installs Python 3.12 (per-user) first, then continues --
; a fresh Windows machine needs nothing pre-installed. It then adds Start Menu and
; Desktop shortcuts that launch the desktop GUI. No Node.js needed (the whole
; product, cockpit included, is pure Python).
;
; Requires Inno Setup 6.1+ (for the built-in download support).

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
Name: "wireagents"; Description: "&Connect PriorStates to my AI agents (Claude / Codex / Gemini) over MCP"; GroupDescription: "Agent setup:"

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
; Optional: install the MCP runtime + register it into any Claude / Codex / Gemini
; so wired agents actually get the PriorStates tools.
Filename: "{code:GetPy}"; Parameters: "{code:McpInstallArgs}"; \
  StatusMsg: "Installing MCP support..."; Flags: runhidden waituntilterminated; Tasks: wireagents
Filename: "{code:GetPy}"; Parameters: "{code:AgentsArgs}"; \
  StatusMsg: "Connecting your AI agents over MCP..."; Flags: runhidden waituntilterminated; Tasks: wireagents
Filename: "{sys}\wscript.exe"; Parameters: """{app}\PriorStates.vbs"""; \
  Description: "Launch PriorStates now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{code:GetPy}"; Parameters: "{code:UninstallArgs}"; Flags: runhidden; RunOnceId: "PipUninstall"

[Code]
const
  { Python to fetch when none is present (per-user, no admin). }
  PyUrl = 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe';

var
  PyCmd: String;
  DownloadPage: TDownloadWizardPage;

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

{ Locate a per-user python.exe we just installed: %LOCALAPPDATA%\Programs\Python\Python3*\python.exe }
function FindUserPython(): String;
var
  FR: TFindRec;
  base, candidate: String;
begin
  Result := '';
  base := ExpandConstant('{localappdata}\Programs\Python\');
  if FindFirst(base + 'Python3*', FR) then
  try
    repeat
      if (FR.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
      begin
        candidate := base + FR.Name + '\python.exe';
        if FileExists(candidate) then
        begin
          Result := candidate;
          exit;
        end;
      end;
    until not FindNext(FR);
  finally
    FindClose(FR);
  end;
end;

function GetPy(Param: String): String;
begin
  if PyCmd = '' then PyCmd := 'py';
  Result := PyCmd;
end;

{ The 'py' launcher needs a '-3' selector; bare 'python' / an absolute path must not. }
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

function McpInstallArgs(Param: String): String;
begin
  Result := PyPrefix + '-m pip install --user mcp';
end;

function AgentsArgs(Param: String): String;
begin
  Result := PyPrefix + '-m priorstates agents install';
end;

function UninstallArgs(Param: String): String;
begin
  Result := PyPrefix + '-m pip uninstall -y priorstates';
end;

procedure InitializeWizard();
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing),
                                     SetupMessage(msgPreparingDesc), nil);
end;

{ Detect Python; if absent, download + silently install it (per-user). Returns
  True with PyCmd set to a runnable interpreter, or False with an error reason. }
function EnsurePython(var Reason: String): Boolean;
var
  rc: Integer;
  installer: String;
begin
  PyCmd := DetectPy();
  if PyCmd <> '' then
  begin
    Result := True;
    exit;
  end;

  { No Python -> fetch the official installer and run it quietly. }
  DownloadPage.Clear;
  DownloadPage.Add(PyUrl, 'python-setup.exe', '');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
    except
      Reason := 'Could not download Python: ' + GetExceptionMessage;
      Result := False;
      exit;
    end;
  finally
    DownloadPage.Hide;
  end;

  installer := ExpandConstant('{tmp}\python-setup.exe');
  if not Exec(installer,
              '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1' +
              ' AssociateFiles=0 Shortcuts=0 SimpleInstall=1',
              '', SW_SHOW, ewWaitUntilTerminated, rc) then
  begin
    Reason := 'The Python installer failed to start.';
    Result := False;
    exit;
  end;

  { Use the freshly installed interpreter by absolute path (PATH isn't refreshed
    inside this running installer process). }
  PyCmd := FindUserPython();
  if PyCmd = '' then
    PyCmd := DetectPy();
  if PyCmd = '' then
  begin
    Reason := 'Python was installed but could not be located. Please reboot and ' +
              'run this installer again.';
    Result := False;
    exit;
  end;
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not EnsurePython(Result) then
    { Non-empty Result aborts the install and is shown to the user. }
    ;
end;
