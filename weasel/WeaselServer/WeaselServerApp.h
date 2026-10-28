#pragma once

#include "resource.h"
#include <resource.h>
#include <WeaselIPC.h>
#include <WeaselUI.h>
#include <RimeWithWeasel.h>
#include <WeaselUtility.h>
#include <filesystem>
#include <functional>
#include <memory>

#include "WeaselTrayIcon.h"

namespace fs = std::filesystem;

class WeaselServerApp {
 public:
  static bool execute(const fs::path& cmd, const std::wstring& args) {
    const int show = cmd.filename().wstring() == L"WeaselDeployer.exe"
                         ? SW_HIDE
                         : SW_SHOWNORMAL;
    return (uintptr_t)ShellExecuteW(NULL, NULL, cmd.c_str(), args.c_str(), NULL,
                                    show) > 32;
  }

  static bool explore(const fs::path& path) {
    std::wstring quoted_path(L"\"" + path.wstring() + L"\"");
    return (uintptr_t)ShellExecuteW(NULL, L"explore", quoted_path.c_str(), NULL,
                                    NULL, SW_SHOWNORMAL) > 32;
  }

  static bool open(const fs::path& path) {
    return (uintptr_t)ShellExecuteW(NULL, L"open", path.c_str(), NULL, NULL,
                                    SW_SHOWNORMAL) > 32;
  }

  // 检查青石五笔自己的新版本（GitHub 官方发布），规则与设置面板一致。
  // 不涉及小狼毫 / rime.im 的更新源，也不会下载或执行任何文件。
  static bool check_update();

  static fs::path install_dir() {
    WCHAR exe_path[MAX_PATH] = {0};
    GetModuleFileNameW(GetModuleHandle(NULL), exe_path, _countof(exe_path));
    return fs::path(exe_path).parent_path();
  }

 public:
  WeaselServerApp();
  ~WeaselServerApp();
  int Run();

 protected:
  void SetupMenuHandlers();

  weasel::Server m_server;
  weasel::UI m_ui;
  WeaselTrayIcon tray_icon;
  std::unique_ptr<RimeWithWeaselHandler> m_handler;
};
