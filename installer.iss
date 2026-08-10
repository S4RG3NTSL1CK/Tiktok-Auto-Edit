; Built on windows-latest CI via: iscc /DMyAppVersion=1.2.3 installer.iss
#define MyAppName "Tiktok Auto Edit"
#define MyAppPublisher "S4RG3NTSL1CK"
#define MyAppURL "https://github.com/S4RG3NTSL1CK/Tiktok-Auto-Edit"
#define MyAppExeName "TiktokAutoEdit.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
; Fixed AppId so future versions upgrade in place instead of side-installing.
AppId={{C44934A1-5BC6-468D-97AF-6A049C028667}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\TiktokAutoEdit
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=TiktokAutoEdit-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; force (not the softer "yes"): the app can be a large bundle now (numpy/
; scipy/opencv), so a soft close-request has more room to race the file
; copy than it used to. force via Restart Manager instead of hoping our own
; self.close() finishes in time.
CloseApplications=force
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\TiktokAutoEdit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; No skipifsilent: the in-app auto-updater always installs with /VERYSILENT,
; and it relies on this step to relaunch the app afterward.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall
