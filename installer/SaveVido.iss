#define AppName "SaveVido"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppPublisher "AZAN KHAN"
#define AppExeName "SaveVido.exe"

[Setup]
AppId={{A0E9A9D8-9C3E-4DB8-8D65-3B4D14C1A501}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName=SaveVido {#AppVersion} — AZAN KHAN
AppComments=Created by AZAN KHAN
AppPublisher={#AppPublisher}
SetupIconFile=..\static\savevido.ico
Uninstallable=yes
CloseApplications=yes
DefaultDirName={localappdata}\Programs\SaveVido
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=SaveVido-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardSmallImageFile=savevido-installer-logo.bmp
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "..\dist\SaveVido\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SaveVido"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\SaveVido"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch SaveVido"; Flags: postinstall nowait skipifsilent
