; Compile only through scripts/build_installer.ps1. AppVersion comes from app/version.py.
#if VER != EncodeVer(6, 7, 3)
  #error Installer build requires Inno Setup 6.7.3
#endif
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef AppNumericVersion
  #error AppNumericVersion is required
#endif
#ifndef BundleDir
  #error BundleDir is required
#endif

[Setup]
AppId={{C2D78D77-6F6E-4B63-9E60-871E7B955961}
AppName=HeetKit
AppVersion={#AppVersion}
AppPublisher=heeetz
AppPublisherURL=https://github.com/heeetz/heetkit-bot
AppSupportURL=https://github.com/heeetz/heetkit-bot/issues
VersionInfoVersion={#AppNumericVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductTextVersion={#AppVersion}
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
; English is preselected regardless of the Windows language; upgrades default to the
; previous Setup language. The choice is handed to the app (see CurStepChanged).
ShowLanguageDialog=yes
LanguageDetectionMethod=none
UsePreviousLanguage=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
en.InfoBeforeLabel=HeetKit license and dependency notices. Installed copies remain available in the application folder.
en.InfoBeforeClickLabel=Read the notices, then click Next to continue.
uk.InfoBeforeLabel=Ліцензія HeetKit і повідомлення про залежності. Їхні копії залишаються в папці програми.
uk.InfoBeforeClickLabel=Прочитайте повідомлення й натисніть «Далі».
ru.InfoBeforeLabel=Лицензия HeetKit и уведомления о зависимостях. Их копии остаются в папке программы.
ru.InfoBeforeClickLabel=Прочитайте уведомления и нажмите «Далее».

[CustomMessages]
en.DesktopShortcut=Create a &desktop shortcut
en.LaunchHeetKit=Launch HeetKit
en.LicenseShortcut=License and notices
en.PrerequisiteTitle=Microsoft runtime prerequisites
en.PrerequisiteSubtitle=HeetKit uses .NET Framework and Edge WebView2 Evergreen Runtime.
en.DownloadWebView=Download WebView2 from Microsoft
en.DownloadNet=Download .NET Framework from Microsoft
en.NeedNet=Install Microsoft .NET Framework 4.6.2 or newer from %1.
en.NeedWebView=Install Microsoft Edge WebView2 Evergreen Runtime using the Evergreen Bootstrapper (online) or x64 Standalone Installer (offline) from %1.
en.RetryAfterPrerequisites=Complete Microsoft installation (and restart Windows if requested), then retry HeetKit Setup. No application files or profile data have been changed.
en.OpenPageManually=Open this Microsoft download page in your browser:
en.DirectoryOverlapsProfiles=Choose an application directory separate from HeetKit and TwitchBot user profiles.
en.DirectoryOverlapsProfile=Choose an application directory separate from the configured user profile.
en.DirectoryMustMatch=Upgrades and reinstalls must use the existing application directory. To move HeetKit, uninstall first; your profile is retained.
en.NoDowngrade=A newer HeetKit version is already installed. Downgrades are not supported. Your profile has not been changed.
uk.DesktopShortcut=Створити ярлик на &робочому столі
uk.LaunchHeetKit=Запустити HeetKit
uk.LicenseShortcut=Ліцензія й повідомлення
uk.PrerequisiteTitle=Потрібні компоненти Microsoft
uk.PrerequisiteSubtitle=HeetKit використовує .NET Framework і Edge WebView2 Evergreen Runtime.
uk.DownloadWebView=Завантажити WebView2 з сайту Microsoft
uk.DownloadNet=Завантажити .NET Framework з сайту Microsoft
uk.NeedNet=Установіть Microsoft .NET Framework 4.6.2 або новіший: %1.
uk.NeedWebView=Установіть Microsoft Edge WebView2 Evergreen Runtime через Evergreen Bootstrapper (онлайн) або x64 Standalone Installer (офлайн): %1.
uk.RetryAfterPrerequisites=Завершіть установлення Microsoft (і перезапустіть Windows, якщо попросить), потім знову запустіть установлення HeetKit. Файли програми й дані профілю не змінено.
uk.OpenPageManually=Відкрийте цю сторінку Microsoft у браузері:
uk.DirectoryOverlapsProfiles=Виберіть папку програми окремо від профілів HeetKit і TwitchBot.
uk.DirectoryOverlapsProfile=Виберіть папку програми окремо від налаштованого профілю.
uk.DirectoryMustMatch=Оновлення й перевстановлення мають використовувати наявну папку програми. Щоб перемістити HeetKit, спершу видаліть його; профіль збережеться.
uk.NoDowngrade=Уже встановлено новішу версію HeetKit. Повернення до старішої версії не підтримується. Профіль не змінено.
ru.DesktopShortcut=Создать ярлык на &рабочем столе
ru.LaunchHeetKit=Запустить HeetKit
ru.LicenseShortcut=Лицензия и уведомления
ru.PrerequisiteTitle=Нужные компоненты Microsoft
ru.PrerequisiteSubtitle=HeetKit использует .NET Framework и Edge WebView2 Evergreen Runtime.
ru.DownloadWebView=Скачать WebView2 с сайта Microsoft
ru.DownloadNet=Скачать .NET Framework с сайта Microsoft
ru.NeedNet=Установите Microsoft .NET Framework 4.6.2 или новее: %1.
ru.NeedWebView=Установите Microsoft Edge WebView2 Evergreen Runtime через Evergreen Bootstrapper (онлайн) или x64 Standalone Installer (офлайн): %1.
ru.RetryAfterPrerequisites=Завершите установку Microsoft (и перезапустите Windows, если попросит), затем снова запустите установку HeetKit. Файлы программы и данные профиля не изменены.
ru.OpenPageManually=Откройте эту страницу Microsoft в браузере:
ru.DirectoryOverlapsProfiles=Выберите папку программы отдельно от профилей HeetKit и TwitchBot.
ru.DirectoryOverlapsProfile=Выберите папку программы отдельно от настроенного профиля.
ru.DirectoryMustMatch=Обновление и переустановка должны использовать существующую папку программы. Чтобы переместить HeetKit, сначала удалите его; профиль сохранится.
ru.NoDowngrade=Уже установлена более новая версия HeetKit. Возврат к старой версии не поддерживается. Профиль не изменен.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "INSTALLER.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\third_party_licenses\inno-setup\LICENSE.txt"; DestDir: "{app}\_internal\licenses"; DestName: "Inno-Setup-LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\HeetKit\HeetKit"; Filename: "{app}\HeetKit.exe"; WorkingDir: "{app}"; AppUserModelID: "HeetKit.Desktop"
Name: "{userprograms}\HeetKit\{cm:LicenseShortcut}"; Filename: "{app}\_internal"; WorkingDir: "{app}"
Name: "{userdesktop}\HeetKit"; Filename: "{app}\HeetKit.exe"; WorkingDir: "{app}"; AppUserModelID: "HeetKit.Desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\HeetKit.exe"; Description: "{cm:LaunchHeetKit}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
const
  WebViewKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  NetKey = 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full';
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{C2D78D77-6F6E-4B63-9E60-871E7B955961}_is1';
  WebViewURL = 'https://developer.microsoft.com/microsoft-edge/webview2/#download-section';
  NetURL = 'https://dotnet.microsoft.com/download/dotnet-framework';
  LanguageKey = 'Software\HeetKit';
  LanguageValue = 'InitialUiLanguage';
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
    Result := FmtMessage(CustomMessage('NeedNet'), [NetURL]) + #13#10;
  if not HasWebView then
    Result := Result + FmtMessage(CustomMessage('NeedWebView'), [WebViewURL]) + #13#10;
  if Result <> '' then
    Result := Result + CustomMessage('RetryAfterPrerequisites');
end;

procedure OpenPrerequisite(Sender: TObject);
var
  ErrorCode: Integer;
  URL: String;
begin
  if Sender = WebViewButton then URL := WebViewURL else URL := NetURL;
  if not ShellExec('open', URL, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode) then
    MsgBox(CustomMessage('OpenPageManually') + #13#10 + URL, mbInformation, MB_OK);
end;

procedure InitializeWizard;
begin
  RegQueryStringValue(HKCU64, UninstallKey, 'InstallLocation', PreviousDirectory);
  PrerequisitePage := CreateCustomPage(wpInfoBefore, CustomMessage('PrerequisiteTitle'),
    CustomMessage('PrerequisiteSubtitle'));
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
  WebViewButton.Caption := CustomMessage('DownloadWebView');
  WebViewButton.OnClick := @OpenPrerequisite;
  NetButton := TNewButton.Create(PrerequisitePage);
  NetButton.Parent := PrerequisitePage.Surface;
  NetButton.Top := ScaleY(200);
  NetButton.Width := ScaleX(270);
  NetButton.Caption := CustomMessage('DownloadNet');
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
    Result := CustomMessage('DirectoryOverlapsProfiles');
  if (SelectedProfile <> '') and PathsOverlap(Directory, SelectedProfile) then
    Result := CustomMessage('DirectoryOverlapsProfile');
  if (PreviousDirectory <> '') and
     (CompareText(RemoveBackslashUnlessRoot(Directory), RemoveBackslashUnlessRoot(PreviousDirectory)) <> 0) then
    Result := CustomMessage('DirectoryMustMatch');
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
     StrToVersion('{#AppNumericVersion}', Candidate) and
     (ComparePackedVersion(Installed, Candidate) > 0) then
    Result := CustomMessage('NoDowngrade');
end;

function HasExplicitLanguage: Boolean;
begin
  Result := Pos('/LANG=', Uppercase(GetCmdTail)) > 0;
end;

{ Hand the chosen language to the app. The app reads it once, only while no interface
  language is saved in its settings. A silent update without /LANG= keeps an existing value. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  Existing: String;
begin
  if CurStep <> ssPostInstall then exit;
  if WizardSilent and not HasExplicitLanguage and
     RegQueryStringValue(HKCU, LanguageKey, LanguageValue, Existing) then exit;
  RegWriteStringValue(HKCU, LanguageKey, LanguageValue, ActiveLanguage);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usPostUninstall then exit;
  RegDeleteValue(HKCU, LanguageKey, LanguageValue);
  RegDeleteKeyIfEmpty(HKCU, LanguageKey);
end;
