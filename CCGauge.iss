; CCGauge.iss — Inno Setup 安装脚本
;
; 版本号不在此硬编码：由 build.bat 读取 app/__init__.py（唯一版本源）后经
;   iscc /DMyAppVersion=<ver> CCGauge.iss
; 注入。若单独编译而未注入，则回落为 0.0.0-dev（明确标记为非正式版本，避免
; 出现与源码不一致的假版本号）。
;
; 产物：dist\CCGauge-v<ver>-setup.exe
; 特性：可选桌面快捷方式（默认不勾选）、开始菜单项、安装后启动、运行中检测。

#define MyAppName "CCGauge"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "CCGauge Team"
#define MyAppExeName "CCGauge.exe"

[Setup]
; AppId 唯一标识此应用，升级/卸载时据此识别，务必保持不变
AppId={{B8A3C9D2-4E5F-6A7B-8C9D-0E1F2A3B4C5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=.\dist
OutputBaseFilename={#MyAppName}-v{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=.\assets\CCGauge.ico
; 单文件应用装在用户目录即可，不强制管理员
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 与 app/main.py 的命名互斥体一致：应用运行中时提示关闭
AppMutex=CCGauge_SingleInstance_Mutex

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Languages\English.isl"

[Tasks]
; 桌面快捷方式：默认不勾选，由用户在安装向导中决定
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 单文件 exe（图标已嵌入，无需额外复制 assets）
Source: ".\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 开始菜单入口
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
; 桌面快捷方式（仅在用户勾选 desktopicon 任务时创建）
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 安装完成后可选启动
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
