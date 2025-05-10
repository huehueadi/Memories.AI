; --- ZENCIA Installer Script ---

[Setup]
AppName=ZENCIA
AppVersion=2.0.1
AppPublisher=ZENCIA
AppPublisherURL=https://zencia.ai   
AppSupportURL=https://zencia.ai
AppUpdatesURL=https://zencia.ai
DefaultDirName=C:\ZENCIA
DefaultGroupName=ZENCIA
PrivilegesRequired=admin
AllowNoIcons=yes
UsePreviousAppDir=yes
CreateAppDir=yes
OutputDir=.\Output
OutputBaseFilename=ZENCIA
Compression=lzma
SolidCompression=yes
DiskSpanning=yes
SetupIconFile="C:\Users\udayr\Downloads\zencia.ico"
WizardStyle=modern
LicenseFile=license.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop Shortcut"; GroupDescription: "Shortcuts"; Flags: unchecked

[Dirs]
Name: "{app}"; Permissions: users-full
Name: "{app}\internal"; Permissions: users-full

[Files]
; Add your EXE 
Source: "C:\Users\udayr\Downloads\Zencia.exe"; DestDir: "{app}";
; Include the internals folder with all Python modules
Source: "C:\Users\udayr\Downloads\_internal\*"; DestDir: "{app}\_internal"; Flags: recursesubdirs createallsubdirs  
; Add Ollama setup file (replace with your actual path to the Ollama installer)
Source: "C:\Users\udayr\Downloads\OllamaSetup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not IsOllamaInstalled



[Icons]
Name: "{group}\ZENCIA"; Filename: "{app}\Zencia.exe"; IconFilename: "{app}\zencia.ico"
Name: "{autodesktop}\ZENCIA"; Filename: "{app}\Zencia.exe"; IconFilename: "{app}\zencia.ico"; Tasks: desktopicon

[Run]
Filename: "{tmp}\OllamaSetup.exe"; Parameters: "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"; StatusMsg: "Installing AI..."; Check: not IsOllamaInstalled
Filename: "{app}\Zencia.exe"; Description: "Launch Zencia"; Flags: postinstall nowait skipifsilent

[Code]
function IsOllamaInstalled: Boolean;
begin
  Result := DirExists(ExpandConstant('{localappdata}\Programs\Ollama')) or
            FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
            
  if not Result then
    Result := RegKeyExists(HKLM, 'SOFTWARE\Ollama') or
              RegKeyExists(HKCU, 'SOFTWARE\Ollama');
end;
