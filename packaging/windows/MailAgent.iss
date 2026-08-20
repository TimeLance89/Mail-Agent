#define MyAppName "MAIL-AGENT"
#define MyAppVersion "0.17.2"
#define MyAppPublisher "MAIL-AGENT"
#define MyAppExeName "Mail-Agent.exe"

[Setup]
AppId={{9F1BC4CB-E23F-4B5F-BCCA-DB7B53E45072}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Mail-Agent
DefaultGroupName=MAIL-AGENT
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=Mail-Agent-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\..\dist\Mail-Agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "restart-mail-agent.cmd"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\MAIL-AGENT"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\MAIL-AGENT"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Verknüpfungen:"; Flags: unchecked

[Run]
Filename: "{tmp}\restart-mail-agent.cmd"; Parameters: """{app}\{#MyAppExeName}"" ""{#MyAppVersion}"" ""open-browser"""; Description: "MAIL-AGENT jetzt starten"; Flags: runhidden postinstall skipifsilent
Filename: "{tmp}\restart-mail-agent.cmd"; Parameters: """{app}\{#MyAppExeName}"" ""{#MyAppVersion}"" ""no-browser"""; Flags: runhidden skipifnotsilent