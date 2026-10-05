; Compile only through scripts/build_installer.ps1. AppVersion comes from app/version.py.
#if VER != EncodeVer(6, 7, 3)
  #error Installer build requires Inno Setup 6.7.3
#endif
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef BundleDir
  #error BundleDir is required
#endif

[Setup]
AppId={{C2D78D77-6F6E-4B63-9E60-871E7B955961}
AppName=HeetKit
AppVersion={#AppVersion}
AppPublisher=heeetz
AppPublisherURL=https://github.com/heeetz/twitch-bot
AppSupportURL=https://github.com/heeetz/twitch-bot/issues
VersionInfoVersion={#AppVersion}
VersionInfoDescription=HeetKit Setup
VersionInfoCompany=heeetz
VersionInfoCopyright=Copyright (C) 2026 heeetz
DefaultDirName={localappdata}\Programs\HeetKit
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
DisableDirPage=no
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
UninstallDisplayIcon={app}\HeetKit.exe
SetupIconFile={#BundleDir}\_internal\app\resources\icon.ico
InfoBeforeFile={#NoticePage}
OutputDir={#OutputDir}
OutputBaseFilename=HeetKit-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no

[Messages]
InfoBeforeLabel=HeetKit license and dependency notices. Installed copies remain available in the application folder.
InfoBeforeClickLabel=Read the notices, then click Next to continue.

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "INSTALLER.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\third_party_licenses\inno-setup\LICENSE.txt"; DestDir: "{app}\_internal\licenses"; DestName: "Inno-Setup-LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\HeetKit\HeetKit"; Filename: "{app}\HeetKit.exe"; WorkingDir: "{app}"; AppUserModelID: "HeetKit.Desktop"
Name: "{userprograms}\HeetKit\License and notices"; Filename: "{app}\_internal"; WorkingDir: "{app}"
Name: "{userdesktop}\HeetKit"; Filename: "{app}\HeetKit.exe"; WorkingDir: "{app}"; AppUserModelID: "HeetKit.Desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\HeetKit.exe"; Description: "Launch HeetKit"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
const
  WebViewKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  NetKey = 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full';
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{C2D78D77-6F6E-4B63-9E60-871E7B955961}_is1';
  WebViewURL = 'https://developer.microsoft.com/microsoft-edge/webview2/#download-section';
  NetURL = 'https://dotnet.microsoft.com/download/dotnet-framework';
var
  PrerequisitePage: TWizardPage;
  PrerequisiteStatus: TNewStaticText;
  WebViewButton, NetButton: TNewButton;
  PreviousDirectory: String;

function HasWebViewAt(Root: Integer): Boolean;
var
  Value: String;
  Version: Int64;
begin
  Result := RegQueryStringValue(Root, WebViewKey, 'pv', Value) and
    StrToVersion(Value, Version) and (Version > 0);
end;

function HasWebView: Boolean;
begin
  Result := HasWebViewAt(HKCU32) or HasWebViewAt(HKLM32);
end;

function MissingPrerequisites: String;
var
  Release: Cardinal;
begin
  Result := '';
  if not RegQueryDWordValue(HKLM64, NetKey, 'Release', Release) or (Release < 394802) then
    Result := 'Install Microsoft .NET Framework 4.6.2 or newer from ' + NetURL + '.' + #13#10;
  if not HasWebView then
    Result := Result + 'Install Microsoft Edge WebView2 Evergreen Runtime using the Evergreen Bootstrapper (online) or x64 Standalone Installer (offline) from ' + WebViewURL + '.' + #13#10;
  if Result <> '' then
    Result := Result + 'Complete Microsoft installation (and restart Windows if requested), then retry HeetKit Setup. No application files or profile data have been changed.';
end;

procedure OpenPrerequisite(Sender: TObject);
var
  ErrorCode: Integer;
  URL: String;
begin
  if Sender = WebViewButton then URL := WebViewURL else URL := NetURL;
  if not ShellExec('open', URL, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode) then
    MsgBox('Open this Microsoft download page in your browser:' + #13#10 + URL, mbInformation, MB_OK);
end;

procedure InitializeWizard;
begin
  RegQueryStringValue(HKCU64, UninstallKey, 'InstallLocation', PreviousDirectory);
  PrerequisitePage := CreateCustomPage(wpInfoBefore, 'Microsoft runtime prerequisites',
    'HeetKit uses .NET Framework and Edge WebView2 Evergreen Runtime.');
  PrerequisiteStatus := TNewStaticText.Create(PrerequisitePage);
  PrerequisiteStatus.Parent := PrerequisitePage.Surface;
  PrerequisiteStatus.Width := PrerequisitePage.SurfaceWidth;
  PrerequisiteStatus.Height := ScaleY(150);
  PrerequisiteStatus.AutoSize := False;
  PrerequisiteStatus.WordWrap := True;
  WebViewButton := TNewButton.Create(PrerequisitePage);
  WebViewButton.Parent := PrerequisitePage.Surface;
  WebViewButton.Top := ScaleY(160);
  WebViewButton.Width := ScaleX(270);
  WebViewButton.Caption := 'Download WebView2 from Microsoft';
  WebViewButton.OnClick := @OpenPrerequisite;
  NetButton := TNewButton.Create(PrerequisitePage);
  NetButton.Parent := PrerequisitePage.Surface;
  NetButton.Top := ScaleY(200);
  NetButton.Width := ScaleX(270);
  NetButton.Caption := 'Download .NET Framework from Microsoft';
  NetButton.OnClick := @OpenPrerequisite;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = PrerequisitePage.ID) and (MissingPrerequisites = '');
end;

procedure CurPageChanged(PageID: Integer);
begin
  if PageID = PrerequisitePage.ID then
    PrerequisiteStatus.Caption := MissingPrerequisites;
end;

function PathsOverlap(Left, Right: String): Boolean;
begin
  Left := AddBackslash(Lowercase(ExpandFileName(Left)));
  Right := AddBackslash(Lowercase(ExpandFileName(Right)));
  Result := (Pos(Left, Right) = 1) or (Pos(Right, Left) = 1);
end;

function ValidateDirectory: String;
var
  Directory, SelectedProfile: String;
begin
  Result := '';
  Directory := WizardDirValue;
  SelectedProfile := GetEnv('HEETKIT_DATA_DIR');
  if SelectedProfile = '' then SelectedProfile := GetEnv('TWITCH_BOT_DATA_DIR');
  if PathsOverlap(Directory, ExpandConstant('{localappdata}\HeetKit')) or
     PathsOverlap(Directory, ExpandConstant('{localappdata}\TwitchBot')) then
    Result := 'Choose an application directory separate from HeetKit and TwitchBot user profiles.';
  if (SelectedProfile <> '') and PathsOverlap(Directory, SelectedProfile) then
    Result := 'Choose an application directory separate from the configured user profile.';
  if (PreviousDirectory <> '') and
     (CompareText(RemoveBackslashUnlessRoot(Directory), RemoveBackslashUnlessRoot(PreviousDirectory)) <> 0) then
    Result := 'Upgrades and reinstalls must use the existing application directory. To move HeetKit, uninstall first; your profile is retained.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Problem: String;
begin
  { Silent installs enforce these checks in PrepareToInstall, without dialogs. }
  if WizardSilent then begin
    Result := True;
    exit;
  end;
  Problem := '';
  if CurPageID = PrerequisitePage.ID then Problem := MissingPrerequisites;
  if CurPageID = wpSelectDir then Problem := ValidateDirectory;
  Result := Problem = '';
  if not Result then MsgBox(Problem, mbError, MB_OK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Installed, Candidate: Int64;
begin
  Result := MissingPrerequisites;
  if Result <> '' then exit;
  Result := ValidateDirectory;
  if Result <> '' then exit;
  if GetPackedVersion(ExpandConstant('{app}\HeetKit.exe'), Installed) and
     StrToVersion('{#AppVersion}', Candidate) and
     (ComparePackedVersion(Installed, Candidate) > 0) then
    Result := 'A newer HeetKit version is already installed. Downgrades are not supported. Your profile has not been changed.';
end;
