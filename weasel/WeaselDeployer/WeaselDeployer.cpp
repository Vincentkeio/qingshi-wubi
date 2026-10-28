// WeaselDeployer.cpp : Defines the entry point for the application.
//
#include "stdafx.h"
#include <WeaselUtility.h>
#include <WeaselIPC.h>
#include <fstream>
#include <vector>
#include "WeaselDeployer.h"
#include "Configurator.h"
#include <ShellScalingApi.h>

CAppModule _Module;

static int Run(int argc, wchar_t* argv[]);

static bool IsOption(const std::wstring& value, const wchar_t* option) {
  return _wcsicmp(value.c_str(), option) == 0;
}

static int ShowHelp() {
  WCHAR msg[2048] = {0};
  if (LoadString(GetModuleHandle(NULL), IDS_STR_HELP, msg,
                 sizeof(msg) / sizeof(TCHAR))) {
    std::wstring help(msg);
    help.append(
        L"\n\n/dict list - List user dictionaries\n"
        L"/dict backup <dict> - Backup a user dictionary\n"
        L"/dict restore <file> - Restore a user dictionary snapshot\n"
        L"/dict export <dict> <file> - Export a user dictionary\n"
        L"/dict import <dict> <file> - Import a user dictionary");
    MessageBox(NULL, help.c_str(), L"青石五笔配置工具",
               MB_ICONINFORMATION | MB_OK);
  } else {
    MessageBox(NULL,
               L"Usage: WeaselDeployer.exe [options]\n"
               L"/? or /help\t\t- Show this help message\n"
               L"/deploy\t\t- Update Workspace\n"
               L"/reload\t\t- Reload user config without deploying\n"
               L"/dict\t\t- Manage dictionary\n"
               L"/dict list\t\t- List user dictionaries\n"
               L"/dict backup <dict>\t- Backup a user dictionary\n"
               L"/dict restore <file>\t- Restore a user dictionary snapshot\n"
               L"/dict export <dict> <file>\t- Export a user dictionary\n"
               L"/dict import <dict> <file>\t- Import a user dictionary\n"
               L"/sync\t\t- Sync user data\n"
               L"/install\t\t- Install Qingshi Wubi (Initial deployment)",
               L"青石五笔配置工具", MB_ICONINFORMATION | MB_OK);
  }
  return 0;
}

static bool IsDictionaryCli(int argc, wchar_t* argv[]) {
  return argc > 2 && IsOption(argv[1], L"/dict");
}

static void AttachDictionaryConsole() {
  // GUI launches have no console at all. Explicit dictionary CLI commands may
  // reuse the caller's terminal; preserve redirected output handles for scripts.
  const HANDLE out = GetStdHandle(STD_OUTPUT_HANDLE);
  const HANDLE err = GetStdHandle(STD_ERROR_HANDLE);
  if (GetConsoleWindow() || !AttachConsole(ATTACH_PARENT_PROCESS))
    return;
  FILE* stream = nullptr;
  if (!out || out == INVALID_HANDLE_VALUE)
    _wfreopen_s(&stream, L"CONOUT$", L"w", stdout);
  if (!err || err == INVALID_HANDLE_VALUE)
    _wfreopen_s(&stream, L"CONOUT$", L"w", stderr);
}

int wmain(int argc, wchar_t* argv[]) {
  if (IsDictionaryCli(argc, argv))
    AttachDictionaryConsole();

  HINSTANCE hInstance = GetModuleHandle(NULL);
  LoadWeaselLogLevelFromRegistry();
  SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE);
  LANGID langId = get_language_id();
  SetThreadUILanguage(langId);
  SetThreadLocale(langId);

  HRESULT hRes = ::CoInitialize(NULL);
  // If you are running on NT 4.0 or higher you can use the following call
  // instead to make the EXE free threaded. This means that calls come in on a
  // random RPC thread.
  // HRESULT hRes = ::CoInitializeEx(NULL, COINIT_MULTITHREADED);
  ATLASSERT(SUCCEEDED(hRes));

  // this resolves ATL window thunking problem when Microsoft Layer for Unicode
  // (MSLU) is used
  ::DefWindowProc(NULL, 0, 0, 0L);

  AtlInitCommonControls(
      ICC_BAR_CLASSES);  // add flags to support other controls

  hRes = _Module.Init(NULL, hInstance);
  ATLASSERT(SUCCEEDED(hRes));

  CreateDirectory(WeaselUserDataPath().c_str(), NULL);

  int ret = 0;
  HANDLE hMutex = CreateMutex(NULL, TRUE, L"WeaselDeployerExclusiveMutex");
  if (!hMutex) {
    ret = 1;
  } else if (GetLastError() == ERROR_ALREADY_EXISTS) {
    ret = 1;
  } else {
    ret = Run(argc, argv);
  }

  if (hMutex) {
    CloseHandle(hMutex);
  }
  _Module.Term();
  ::CoUninitialize();

  return ret;
}

static int Run(int argc, wchar_t* argv[]) {
  std::vector<std::wstring> args;
  for (int i = 1; i < argc; ++i) {
    args.emplace_back(argv[i]);
  }

  if (args.size() == 1 &&
      (IsOption(args.front(), L"/?") || IsOption(args.front(), L"/help"))) {
    return ShowHelp();
  }

  // /reload：只让正在运行的服务重读用户配置（外观、按键、候选数、标点、
  // 主题、候选调序表），**不跑部署、不初始化 rime**。
  // 设置面板保存后走这条，毫秒级生效；改码表/词库才需要 /deploy。
  if (args.size() == 1 && IsOption(args.front(), L"/reload")) {
    weasel::Client client;
    if (!client.Connect()) {
      return 2;  // 服务没在跑
    }
    const bool ok = client.ReloadConfig();
    client.Disconnect();
    return ok ? 0 : 3;
  }

  // /pin <n>：把当前页第 n 个候选置顶（调试与自动化测试用）。
  // 走 shadow 层，不部署、不重启。
  if (args.size() == 2 && IsOption(args.front(), L"/pin")) {
    weasel::Client client;
    if (!client.Connect())
      return 2;
    const bool ok = client.AdjustShadow(0 /* WEASEL_SHADOW_PIN */,
                                        static_cast<size_t>(_wtoi(args[1].c_str())));
    client.Disconnect();
    return ok ? 0 : 3;
  }

  Configurator configurator;
  configurator.Initialize();

  if (args.empty()) {
    return configurator.Run(false);
  }

  if (IsOption(args.front(), L"/deploy") && args.size() == 1) {
    return configurator.UpdateWorkspace();
  }

  if (IsOption(args.front(), L"/dict")) {
    return configurator.DictManagement(
        std::vector<std::wstring>(args.begin() + 1, args.end()));
  }

  if (IsOption(args.front(), L"/sync") && args.size() == 1) {
    return configurator.SyncUserData();
  }

  bool installing = IsOption(args.front(), L"/install") && args.size() == 1;
  return configurator.Run(installing);
}
