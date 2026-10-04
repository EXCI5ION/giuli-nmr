#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "GIULI"
#define MyAppExeName "GIULI.exe"
#define MySourceDir "..\..\dist\GIULI"

[Setup]
AppId={{C80DDE29-F4E4-48E1-9B64-7FA29469CDE5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=GIULI
AppPublisherURL=https://github.com/EXCI5ION/giuli-nmr
AppSupportURL=https://github.com/EXCI5ION/giuli-nmr/issues
AppUpdatesURL=https://github.com/EXCI5ION/giuli-nmr/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist-installer
OutputBaseFilename=GIULI-{#MyAppVersion}-windows-x64
SetupIconFile=..\..\src\nmr_processor\resources\giuli-icon.ico
LicenseFile=..\..\LICENSE
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern dynamic
CloseApplications=yes
RestartApplications=no
MinVersion=10.0.17763

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos adicionales:"; Flags: unchecked

[InstallDelete]
Type: files; Name: "{app}\_internal\icuuc.dll"
Type: files; Name: "{app}\_internal\icudt*.dll"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\CITATION.cff"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar {#MyAppName}"; Flags: nowait postinstall skipifsilent
