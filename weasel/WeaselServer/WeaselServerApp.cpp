#include "stdafx.h"
#include "WeaselServerApp.h"
#include <QingshiVersion.h>
#include <TrayMenu.h>
#include <QingshiSettings.h>
#include <commctrl.h>
#include <filesystem>
#include <thread>

#pragma comment(lib, "comctl32.lib")

#include "QingshiUpdate.h"

WeaselServerApp::WeaselServerApp()
    : m_handler(std::make_unique<RimeWithWeaselHandler>(&m_ui)),
      tray_icon(m_ui) {
  // m_handler.reset(new RimeWithWeaselHandler(&m_ui));
  LOG(INFO) << "WeaselServerApp constructed";
  m_server.SetRequestHandler(m_handler.get());
  SetupMenuHandlers();
}

WeaselServerApp::~WeaselServerApp() {}

int WeaselServerApp::Run() {
  LOG(INFO) << "starting IPC server window";
  if (!m_server.Start()) {
    LOG(ERROR) << "failed to start IPC server window";
    return -1;
  }
  LOG(INFO) << "IPC server window started";

  // 青石五笔不再使用 WinSparkle / rime.im 的更新源：检查新版本走 QingshiUpdate。
  LOG(INFO) << "creating candidate UI";
  if (!m_ui.Create(m_server.GetHWnd())) {
    LOG(ERROR) << "failed to create candidate UI";
    return -1;
  }
  LOG(INFO) << "candidate UI created";

  LOG(INFO) << "initializing Rime handler";
  m_handler->Initialize();
  LOG(INFO) << "Rime handler initialized";
  m_handler->OnUpdateUI([this]() { tray_icon.RequestRefresh(); });

  LOG(INFO) << "creating tray icon";
  if (!tray_icon.Create(m_server.GetHWnd()))
    LOG(ERROR) << "failed to create tray icon";
  else
    LOG(INFO) << "tray icon created";
  m_server.SetTrayRefreshCallback([this]() { tray_icon.ApplyRefresh(); });
  tray_icon.RequestRefresh();

  LOG(INFO) << "entering IPC message loop";
  int ret = m_server.Run();
  LOG(INFO) << "IPC message loop returned: " << ret;

  tray_icon.DisableRefresh();
  m_handler->Finalize();
  m_ui.Destroy();
  tray_icon.RemoveIcon();

  return ret;
}

namespace {

constexpr int kDownloadFromWebsite = 100;
constexpr int kDownloadFromGitHub = 101;

// 发现新版本时给两个下载入口：官网 + GitHub 发布页。
// 优先用任务对话框（能写清楚两个按钮各去哪），拿不到 comctl32 v6 时退回 MessageBox。
void AskWhereToDownload(const std::wstring& version,
                        const std::wstring& current,
                        const std::wstring& release_url) {
  const std::wstring instruction =
      L"发现新版本 v" + version + L"（当前 v" + current + L"）";

  TASKDIALOGCONFIG config{};
  config.cbSize = sizeof(config);
  config.dwFlags = TDF_USE_COMMAND_LINKS | TDF_ALLOW_DIALOG_CANCELLATION;
  config.dwCommonButtons = TDCBF_CANCEL_BUTTON;
  config.pszWindowTitle = L"青石五笔有更新";
  config.pszMainIcon = TD_INFORMATION_ICON;
  config.pszMainInstruction = instruction.c_str();
  config.pszContent =
      L"选择从哪里下载安装包。升级后请重新打开正在使用的程序。";
  const TASKDIALOG_BUTTON buttons[] = {
      {kDownloadFromWebsite, L"从官网下载\nqingshi.funnyai.wiki"},
      {kDownloadFromGitHub,
       L"从 GitHub 下载\ngithub.com/Vincentkeio/qingshi-wubi"},
  };
  config.pButtons = buttons;
  config.cButtons = ARRAYSIZE(buttons);

  int pressed = 0;
  if (SUCCEEDED(TaskDialogIndirect(&config, &pressed, nullptr, nullptr))) {
    if (pressed == kDownloadFromWebsite)
      WeaselServerApp::open(fs::path(QINGSHI_WEBSITE_URL));
    else if (pressed == kDownloadFromGitHub)
      WeaselServerApp::open(fs::path(release_url));
    return;
  }

  // 兜底：任务对话框不可用时用三个按钮，文案里写清每个按钮去哪
  const std::wstring text =
      instruction + L"。\n\n是：打开官网下载页\n否：打开 GitHub 发布页\n取消：稍后再说";
  const int answer = MessageBoxW(nullptr, text.c_str(), L"青石五笔有更新",
                                 MB_YESNOCANCEL | MB_ICONINFORMATION |
                                     MB_SETFOREGROUND);
  if (answer == IDYES)
    WeaselServerApp::open(fs::path(QINGSHI_WEBSITE_URL));
  else if (answer == IDNO)
    WeaselServerApp::open(fs::path(release_url));
}

// 真正的检查与提示，跑在后台线程里，避免网络卡住托盘菜单和输入法消息循环
void ShowUpdateResult() {
  const qingshi::UpdateInfo info = qingshi::CheckLatestRelease(QINGSHI_VERSION);
  const std::wstring current = string_to_wstring(QINGSHI_VERSION, CP_UTF8);

  switch (info.status) {
    case qingshi::UpdateInfo::kNewer: {
      const std::wstring version = string_to_wstring(info.version, CP_UTF8);
      const std::wstring url = string_to_wstring(info.release_url, CP_UTF8);
      LOG(INFO) << "update available: v" << info.version << " ("
                << info.release_url << ")";
      AskWhereToDownload(version, current, url);
      break;
    }
    case qingshi::UpdateInfo::kUpToDate: {
      LOG(INFO) << "already up to date: v" << QINGSHI_VERSION;
      const std::wstring text = L"当前已是最新正式版本（v" + current + L"）。";
      MessageBoxW(nullptr, text.c_str(), L"检查新版本",
                  MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND);
      break;
    }
    default: {
      LOG(WARNING) << "update check failed: " << info.detail;
      MessageBoxW(nullptr, L"暂时无法检查更新，请稍后重试。", L"检查新版本",
                  MB_OK | MB_ICONWARNING | MB_SETFOREGROUND);
      break;
    }
  }
}

}  // namespace

bool WeaselServerApp::check_update() {
  // 检查源是青石自己的 GitHub 正式发布，不涉及小狼毫 / rime.im。
  std::thread(ShowUpdateResult).detach();
  return true;
}

void WeaselServerApp::SetupMenuHandlers() {
  m_server.AddMenuHandler(TrayMenu::kShowServerMenu, [this] {
    tray_icon.ShowMenu();
    return true;
  });
  m_server.AddMenuHandler(
      ID_WEASELTRAY_SETTINGS, [] {
        const bool opened = qingshi::OpenSettings();
        if (!opened)
          MessageBoxW(nullptr, L"未找到设置中心，请重新安装青石五笔。", L"青石五笔",
                      MB_OK | MB_ICONERROR);
        return opened;
      });
  m_server.AddMenuHandler(
      ID_WEASELTRAY_ABOUT, [] {
        // 关于：版本、来源、许可，外加两个入口。不弹网页，先用消息框说清楚。
        const std::wstring current = string_to_wstring(QINGSHI_VERSION, CP_UTF8);
        std::wstring text =
            L"青石五笔 v" + current +
            L"\n\n基于 Rime 内核的五笔输入法。\n"
            L"码表：86 / 98 / 新世纪，默认 86。\n"
            L"许可：GNU GPL v3。第三方许可见安装目录。\n\n"
            L"官网：https://qingshi.funnyai.wiki/\n"
            L"源码：https://github.com/Vincentkeio/qingshi-wubi";
        MessageBoxW(nullptr, text.c_str(), L"关于青石五笔",
                    MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND);
        return true;
      });
  m_server.AddMenuHandler(ID_WEASELTRAY_CHECKUPDATE, check_update);
}
