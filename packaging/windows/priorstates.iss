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

[Icons]
; pythonw.exe (no console) -m priorstates gui, pinned to the install interpreter.
Name: "{group}\PriorStates";        Filename: "{code:GetPyExeW}"; Parameters: "-m priorstates gui"; WorkingDir: "{userdocs}"; Comment: "PriorStates desktop GUI"
Name: "{group}\PriorStates Cockpit (web)"; Filename: "{cmd}";     Parameters: "{code:CockpitParams}"; Comment: "Run the web cockpit"
Name: "{group}\Uninstall PriorStates"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PriorStates";  Filename: "{code:GetPyExeW}"; Parameters: "-m priorstates gui"; WorkingDir: "{userdocs}"; Tasks: desktopicon

[Run]
; Install the bundled wheel into the user's Python, then initialize data dirs.
Filename: "{code:GetPyExe}"; Parameters: "{code:PipInstallArgs}"; \
  StatusMsg: "Installing PriorStates into your Python..."; Flags: runhidden waituntilterminated
Filename: "{code:GetPyExe}"; Parameters: "{code:InitArgs}"; \
  StatusMsg: "Initializing PriorStates..."; Flags: runhidden waituntilterminated
; pywinpty gives the cockpit's embedded terminal a real TTY (so interactive CLIs
; like codex work). Windows-only; small prebuilt wheel.
Filename: "{code:GetPyExe}"; Parameters: "-m pip install --user pywinpty"; \
  StatusMsg: "Installing cockpit terminal support..."; Flags: runhidden waituntilterminated
; Optional: install the MCP runtime + register it into any Claude / Codex / Gemini
; so wired agents actually get the PriorStates tools.
Filename: "{code:GetPyExe}"; Parameters: "{code:McpInstallArgs}"; \
  StatusMsg: "Installing MCP support..."; Flags: runhidden waituntilterminated; Tasks: wireagents
Filename: "{code:GetPyExe}"; Parameters: "{code:AgentsArgs}"; \
  StatusMsg: "Connecting your AI agents over MCP..."; Flags: runhidden waituntilterminated; Tasks: wireagents
Filename: "{code:GetPyExeW}"; Parameters: "-m priorstates gui"; \
  Description: "Launch PriorStates now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{code:GetPyExe}"; Parameters: "{code:UninstallArgs}"; Flags: runhidden; RunOnceId: "PipUninstall"

[Code]
const
  { Python to fetch when none is present (per-user, no admin). }
  PyUrl = 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe';

var
  PyCmd: String;
  PyExe: String;    { absolute python.exe of the install interpreter }
  PyExeW: String;   { absolute pythonw.exe (no console); falls back to PyExe }
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

{ Resolve PyCmd ('py' / 'python' / an abs path) to the ABSOLUTE interpreter, so
  shortcuts launch the very Python we installed into -- not a floating `pyw -3`
  that drifts to a newer/Store Python the user adds later (which wouldn't have
  PriorStates or its `mcp` package, breaking the GUI and the MCP server). }
procedure ResolveAbsPython();
var
  probe, outp, exe, params: String;
  lines: TArrayOfString;
  rc, sp: Integer;
begin
  if PyExe <> '' then exit;
  probe := ExpandConstant('{tmp}\ps_probe.py');
  outp  := ExpandConstant('{tmp}\ps_pyexe.txt');
  { a file-based probe avoids any quoting of the python expression }
  SaveStringToFile(probe,
    'import sys' + #13#10 + 'open(r"' + outp + '","w").write(sys.executable)' + #13#10, False);
  sp := Pos(' ', PyCmd);
  if sp > 0 then
  begin
    exe := Copy(PyCmd, 1, sp - 1);
    params := Copy(PyCmd, sp + 1, Length(PyCmd)) + ' "' + probe + '"';
  end
  else
  begin
    exe := PyCmd;
    params := '"' + probe + '"';
  end;
  if Exec(exe, params, '', SW_HIDE, ewWaitUntilTerminated, rc) and (rc = 0)
     and LoadStringsFromFile(outp, lines) and (GetArrayLength(lines) > 0) then
    PyExe := Trim(lines[0]);
  if (PyExe = '') and FileExists(PyCmd) then
    PyExe := PyCmd;
  if PyExe <> '' then
  begin
    PyExeW := ExtractFilePath(PyExe) + 'pythonw.exe';
    if not FileExists(PyExeW) then PyExeW := PyExe;
  end;
end;

function GetPyExe(Param: String): String;
begin
  if PyExe = '' then
  begin
    if PyCmd = '' then PyCmd := DetectPy();
    ResolveAbsPython();
  end;
  if PyExe <> '' then Result := PyExe else Result := GetPy('');
end;

function GetPyExeW(Param: String): String;
begin
  GetPyExe('');
  if PyExeW <> '' then Result := PyExeW else Result := GetPyExe('');
end;

function CockpitParams(Param: String): String;
begin
  Result := '/k "' + GetPyExe('') + '" -m priorstates cockpit';
end;

{ All install steps run with the resolved ABSOLUTE python (GetPyExe), so pip
  installs into exactly the interpreter the shortcuts launch -- no '-3' selector. }
function PipInstallArgs(Param: String): String;
begin
  Result := '-m pip install --user --upgrade --force-reinstall "' +
            ExpandConstant('{app}\{#Wheel}') + '"';
end;

function InitArgs(Param: String): String;
begin
  Result := '-m priorstates init';
end;

function McpInstallArgs(Param: String): String;
begin
  Result := '-m pip install --user mcp';
end;

function AgentsArgs(Param: String): String;
begin
  Result := '-m priorstates agents install';
end;

function UninstallArgs(Param: String): String;
begin
  Result := '-m pip uninstall -y priorstates';
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
    exit;
  { Pin every shortcut to this exact interpreter (not a floating launcher). }
  ResolveAbsPython();
end;
