#include "stdafx.h"
#include "WeaselServerApp.h"
#include <QingshiVersion.h>
#include <filesystem>
#include <thread>

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
      const std::wstring text = L"发现新版本 v" + version + L"（当前 v" + current +
                                L"）。\n\n是否打开官方发布页？";
      if (MessageBoxW(nullptr, text.c_str(), L"青石五笔有更新",
                      MB_YESNO | MB_ICONINFORMATION | MB_SETFOREGROUND) == IDYES) {
        WeaselServerApp::open(fs::path(url));
      }
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
  std::filesystem::path dir = install_dir();
  m_server.AddMenuHandler(ID_WEASELTRAY_QUIT,
                          [this] { return m_server.Stop() == 0; });
  m_server.AddMenuHandler(ID_WEASELTRAY_DEPLOY,
                          std::bind(execute, dir / L"WeaselDeployer.exe",
                                    std::wstring(L"/deploy")));
  m_server.AddMenuHandler(
      ID_WEASELTRAY_SETTINGS, [dir] {
        // Packaged builds keep the settings launcher beside the runtime folder.
        auto settings = dir.parent_path() / L"Qingshi.exe";
        if (fs::exists(settings))
          return WeaselServerApp::execute(settings, std::wstring());
        for (auto target : {L"D:\\空间\\青石五笔输入法\\启动设置.bat",
                            L"D:\\空间\\青石五笔输入法\\rime-dev\\gui\\启动设置.bat"}) {
          if (fs::exists(fs::path(target)))
            return WeaselServerApp::open(fs::path(target));
        }
        return WeaselServerApp::explore(WeaselUserDataPath());
      });
  m_server.AddMenuHandler(
      ID_WEASELTRAY_DICT_MANAGEMENT,
      std::bind(execute, dir / L"WeaselDeployer.exe", std::wstring(L"/dict")));
  m_server.AddMenuHandler(
      ID_WEASELTRAY_SYNC,
      std::bind(execute, dir / L"WeaselDeployer.exe", std::wstring(L"/sync")));
  // 帮助与讨论指向青石自己的入口，不再导向 rime.im（避免用户在那里下载到小狼毫）
  m_server.AddMenuHandler(
      ID_WEASELTRAY_WIKI,
      std::bind(open, L"https://qingshi.funnyai.wiki/guide.html"));
  m_server.AddMenuHandler(ID_WEASELTRAY_HOMEPAGE,
                          std::bind(open, L"https://qingshi.funnyai.wiki/"));
  m_server.AddMenuHandler(
      ID_WEASELTRAY_FORUM,
      std::bind(open, L"https://github.com/Vincentkeio/qingshi-wubi/issues"));
  m_server.AddMenuHandler(ID_WEASELTRAY_CHECKUPDATE, check_update);
  m_server.AddMenuHandler(ID_WEASELTRAY_INSTALLDIR, std::bind(explore, dir));
  m_server.AddMenuHandler(ID_WEASELTRAY_USERCONFIG,
                          std::bind(explore, WeaselUserDataPath()));
  m_server.AddMenuHandler(ID_WEASELTRAY_LOGDIR,
                          std::bind(explore, WeaselLogPath()));
}
