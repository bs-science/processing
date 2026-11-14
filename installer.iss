#define MyAppName "스펙트럼 분석기"
#define MyAppVersion "1.4.1"
#define MyAppPublisher "jw-astro09"
#define MyAppExeName "SpectrumAnalyzer.exe"

[Setup]
AppId={{8A51E194-6DC5-4C97-A7D9-71F14C7A4978}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\spectrum analyzer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE_AGREEMENT.txt
OutputDir=release_1.4.1
OutputBaseFilename=SpectrumAnalyzer-Setup-{#MyAppVersion}-x64
SetupIconFile=spectrum_analyzer_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면 바로가기 만들기"; Flags: checkedonce

[Files]
Source: "release_1.4.1\SpectrumAnalyzer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE_AGREEMENT.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} 실행"; Flags: nowait postinstall skipifsilent
