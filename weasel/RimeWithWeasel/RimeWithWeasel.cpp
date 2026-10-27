#include "stdafx.h"
#include <RimeWithWeasel.h>
#include <StringAlgorithm.hpp>
#include <WeaselConstants.h>
#include <WeaselStyleColor.h>
#include <WeaselUtility.h>

#include <filesystem>
#include <map>
#include <array>
#include <vector>
#include <regex>
#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <fstream>
#include <set>
#include <rime_api.h>

#define TRANSPARENT_COLOR 0x00000000

using namespace weasel;

static RimeApi* rime_api;

// ── 用户 custom 配置优先 ────────────────────────────────────────────────
// Rime 的 `config_open("weasel")` 读的是**部署产物**，用户改 `weasel.custom.yaml`
// 后不部署看不到新值。热更新（/reload）时把用户配置挂到 g_user_patch 上，
// 下面几个读取函数会先查 `patch/<key>`，查不到再回落到部署产物 ——
// 这样外观/按键/候选数/标点这类设置才能真正即时生效。
static RimeConfig* g_user_patch = nullptr;

static bool _LoadFreshUserPatch(RimeConfig* config) {
  std::ifstream stream(WeaselUserDataPath() / L"weasel.custom.yaml", std::ios::binary);
  if (!stream)
    return false;
  std::string yaml((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
  if (!rime_api->config_init(config))
    return false;
  if (!rime_api->config_load_string(config, yaml.c_str())) {
    rime_api->config_close(config);
    return false;
  }
  return true;
}

// 调序相关的排查日志。glog 的级别在这台机器上被配置压住了，
// 排查期间先用独立文件，能确定「执行到哪一步」就够。
void ShadowTrace(const char* fmt, ...) {
  static std::mutex trace_mutex;
  std::lock_guard<std::mutex> lock(trace_mutex);
  wchar_t dir[MAX_PATH] = {0};
  if (GetTempPathW(MAX_PATH, dir) == 0)
    return;
  std::ofstream out(std::wstring(dir) + L"qingshi-shadow.log",
                    std::ios::app | std::ios::binary);
  if (!out)
    return;
  char buf[1024] = {0};
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf) - 1, fmt, ap);
  va_end(ap);
  out << buf << "\r\n";
}

static bool _GetBoolPatched(RimeConfig* config, const char* key, Bool* out) {
  if (g_user_patch) {
    std::string patched = std::string("patch/") + key;
    if (rime_api->config_get_bool(g_user_patch, patched.c_str(), out))
      return true;
  }
  return rime_api->config_get_bool(config, key, out);
}

static bool _GetIntPatched(RimeConfig* config, const char* key, int* out) {
  if (g_user_patch) {
    std::string patched = std::string("patch/") + key;
    if (rime_api->config_get_int(g_user_patch, patched.c_str(), out))
      return true;
  }
  return rime_api->config_get_int(config, key, out);
}

static bool _GetStrPatched(RimeConfig* config,
                           const char* key,
                           char* buffer,
                           size_t size) {
  if (g_user_patch) {
    std::string patched = std::string("patch/") + key;
    if (rime_api->config_get_string(g_user_patch, patched.c_str(), buffer, size))
      return true;
  }
  return rime_api->config_get_string(config, key, buffer, size);
}

WeaselSessionId _GenerateNewWeaselSessionId(SessionStatusMap sm, DWORD pid) {
  if (sm.empty())
    return (WeaselSessionId)(pid + 1);
  return (WeaselSessionId)(sm.rbegin()->first + 1);
}

int expand_ibus_modifier(int m) {
  return (m & 0xff) | ((m & 0xff00) << 16);
}

RimeWithWeaselHandler::RimeWithWeaselHandler(UI* ui)
    : m_ui(ui),
      m_active_session(0),
      m_disabled(true),
      m_current_dark_mode(false),
      m_global_ascii_mode(false),
      m_show_notifications_time(1200),
      _UpdateUICallback(NULL) {
  LOG(INFO) << "constructing RimeWithWeaselHandler";
  m_ui->InServer() = true;
  rime_api = rime_get_api();
  assert(rime_api);
  m_pid = GetCurrentProcessId();
  uint16_t msbit = 0;
  for (auto i = 31; i >= 0; i--) {
    if (m_pid & (1 << i)) {
      msbit = i;
      break;
    }
  }
  m_pid = (m_pid << (31 - msbit));
  LOG(INFO) << "setting up Rime traits";
  _Setup();
  // 候选窗右键「固顶 / 取消固顶」直接落到 shadow 层：内存改规则 + 立刻重排，
  // 不写词库、不跑部署器 —— 以前这两个菜单项走的是「改 custom_phrase + 重新部署」，
  // 每次点都要等好几秒，就是用户说的「卡一下」。
  if (m_ui) {
    m_ui->SetShadowAction([this](size_t index, int action) {
      AdjustShadow(action, index, m_active_session);
    });
  }
  // 面板在 UI 里构造、回调在这里注册，用进程级全局最稳（见 WeaselUI.h 注释）。
  SetGlobalShadowAction([this](size_t index, int action) {
    AdjustShadow(action, index, m_active_session);
  });
  LOG(INFO) << "RimeWithWeaselHandler constructed";
}

RimeWithWeaselHandler::~RimeWithWeaselHandler() {
  m_show_notifications.clear();
  m_session_status_map.clear();
  m_app_options.clear();
}

bool add_session = false;
void _UpdateUIStyle(RimeConfig* config, UI* ui, bool initialize);
bool _UpdateUIStyleColor(RimeConfig* config,
                         UIStyle& style,
                         const std::string& color = std::string());
void _LoadAppOptions(RimeConfig* config, AppOptionsByAppName& app_options);

void _RefreshTrayIcon(const RimeSessionId session_id,
                      const std::function<void()> _UpdateUICallback) {
  // Dangerous, don't touch
  static char app_name[256] = {0};
  auto ret = rime_api->get_property(session_id, "client_app", app_name,
                                    sizeof(app_name) - 1);
  if (!ret || u8tow(app_name) == std::wstring(L"explorer.exe"))
    boost::thread th([=]() {
      ::Sleep(100);
      if (_UpdateUICallback)
        _UpdateUICallback();
    });
  else if (_UpdateUICallback)
    _UpdateUICallback();
}

void RimeWithWeaselHandler::_Setup() {
  RIME_STRUCT(RimeTraits, weasel_traits);
  std::string shared_dir = wtou8(WeaselSharedDataPath().wstring());
  std::string user_dir = wtou8(WeaselUserDataPath().wstring());
  weasel_traits.shared_data_dir = shared_dir.c_str();
  weasel_traits.user_data_dir = user_dir.c_str();
  weasel_traits.prebuilt_data_dir = weasel_traits.shared_data_dir;
  std::string distribution_name = wtou8(get_weasel_ime_name());
  weasel_traits.distribution_name = distribution_name.c_str();
  weasel_traits.distribution_code_name = WEASEL_CODE_NAME;
  weasel_traits.distribution_version = WEASEL_PRODUCT_VERSION;
  weasel_traits.app_name = "rime.weasel";
  std::string log_dir = WeaselLogPath().u8string();
  weasel_traits.log_dir = log_dir.c_str();
  rime_api->setup(&weasel_traits);
  rime_api->set_notification_handler(&RimeWithWeaselHandler::OnNotify, this);
}

void RimeWithWeaselHandler::Initialize() {
  m_disabled = _IsDeployerRunning();
  if (m_disabled) {
    return;
  }

  LOG(INFO) << "Initializing la rime.";
  LOG(INFO) << "calling rime_api->initialize";
  rime_api->initialize(NULL);
  LOG(INFO) << "starting Rime maintenance";
  if (rime_api->start_maintenance(/*full_check = */ False)) {
    m_disabled = true;
    LOG(INFO) << "waiting for Rime maintenance";
    rime_api->join_maintenance_thread();
  }

  RimeConfig config = {NULL};
  if (rime_api->config_open("weasel", &config)) {
    RimeConfig user_config = {NULL};
    const bool has_user = _LoadFreshUserPatch(&user_config);
    if (has_user)
      g_user_patch = &user_config;
    if (m_ui) {
      _UpdateUIStyle(&config, m_ui, true);
      _UpdateShowNotifications(&config, true);
      m_current_dark_mode = IsUserDarkMode();
      {
        // 配色字段与 preset_color_schemes 都由 weasel 主配置提供。
        // 自定义方案使用 color_format: argb，颜色值采用直观的 #RRGGBB 顺序。
        const int BUF_SIZE = 255;
        char buffer[BUF_SIZE + 1] = {0};
        const char* scheme_key = m_current_dark_mode
                                     ? "style/color_scheme_dark"
                                     : "style/color_scheme";
        if (_GetStrPatched(&config, scheme_key, buffer, BUF_SIZE)) {
          const std::string color_name(buffer);
          const bool applied =
              _UpdateUIStyleColor(&config, m_ui->style(), color_name);
          LOG(INFO) << "Qingshi color init: dark=" << m_current_dark_mode
                    << " scheme=" << color_name << " applied=" << applied
                    << " hilite="
                    << m_ui->style().hilited_candidate_back_color;
        } else {
          LOG(ERROR) << "Qingshi color init: cannot read " << scheme_key;
        }
      }
      m_base_style = m_ui->style();
      // Warm up UI resources with finalized style to avoid first-show latency.
      m_ui->Refresh();
      m_ui->Hide();
    }
    Bool global_ascii = false;
    if (rime_api->config_get_bool(&config, "global_ascii", &global_ascii))
      m_global_ascii_mode = !!global_ascii;
    if (!rime_api->config_get_int(&config, "show_notifications_time",
                                  &m_show_notifications_time))
      m_show_notifications_time = 1200;
    _LoadAppOptions(&config, m_app_options);
    if (has_user) {
      g_user_patch = nullptr;
      rime_api->config_close(&user_config);
    }
    rime_api->config_close(&config);
  }
  m_last_schema_id.clear();
}

void RimeWithWeaselHandler::Finalize() {
  m_active_session = 0;
  m_disabled = true;
  m_session_status_map.clear();
  LOG(INFO) << "Finalizing la rime.";
  rime_api->finalize();
}

DWORD RimeWithWeaselHandler::FindSession(WeaselSessionId ipc_id) {
  if (m_disabled)
    return 0;
  Bool found = rime_api->find_session(to_session_id(ipc_id));
  DLOG(INFO) << "Find session: session_id = " << to_session_id(ipc_id)
             << ", found = " << found;
  return found ? (ipc_id) : 0;
}

DWORD RimeWithWeaselHandler::AddSession(LPWSTR buffer, EatLine eat) {
  if (m_disabled) {
    DLOG(INFO) << "Trying to resume service.";
    EndMaintenance();
    if (m_disabled)
      return 0;
  }
  RimeSessionId session_id = (RimeSessionId)rime_api->create_session();
  if (m_global_ascii_mode) {
    for (const auto& pair : m_session_status_map) {
      if (pair.first) {
        rime_api->set_option(session_id, "ascii_mode",
                             !!pair.second.status.is_ascii_mode);
        break;
      }
    }
  }

  WeaselSessionId ipc_id =
      _GenerateNewWeaselSessionId(m_session_status_map, m_pid);
  DLOG(INFO) << "Add session: created session_id = " << session_id
             << ", ipc_id = " << ipc_id;
  SessionStatus& session_status = new_session_status(ipc_id);
  session_status.style = m_base_style;
  session_status.session_id = session_id;
  _ReadClientInfo(ipc_id, buffer);

  RIME_STRUCT(RimeStatus, status);
  if (rime_api->get_status(session_id, &status)) {
    std::string schema_id = status.schema_id;
    m_last_schema_id = schema_id;
    _LoadSchemaSpecificSettings(ipc_id, schema_id);
    _LoadAppInlinePreeditSet(ipc_id, true);
    _UpdateInlinePreeditStatus(ipc_id);
    _RefreshTrayIcon(session_id, _UpdateUICallback);
    session_status.status = status;
    session_status.__synced = false;
    rime_api->free_status(&status);
  }
  m_ui->style() = session_status.style;
  // show session's welcome message :-) if any
  if (eat) {
    _Respond(ipc_id, eat);
  }
  add_session = true;
  _UpdateUI(ipc_id);
  add_session = false;
  m_active_session = ipc_id;
  return ipc_id;
}

DWORD RimeWithWeaselHandler::RemoveSession(WeaselSessionId ipc_id) {
  if (m_ui)
    m_ui->Hide();
  if (m_disabled)
    return 0;
  DLOG(INFO) << "Remove session: session_id = " << to_session_id(ipc_id);
  // TODO: force committing? otherwise current composition would be lost
  rime_api->destroy_session(to_session_id(ipc_id));
  m_session_status_map.erase(ipc_id);
  m_active_session = 0;
  return 0;
}

void RimeWithWeaselHandler::UpdateColorTheme(BOOL darkMode) {
  RimeConfig config = {NULL};
  if (rime_api->config_open("weasel", &config)) {
    RimeConfig user_config = {NULL};
    const bool has_user = _LoadFreshUserPatch(&user_config);
    if (has_user)
      g_user_patch = &user_config;
    if (m_ui) {
      _UpdateUIStyle(&config, m_ui, true);
      m_current_dark_mode = darkMode;
      {
        const int BUF_SIZE = 255;
        char buffer[BUF_SIZE + 1] = {0};
        const char* scheme_key = darkMode ? "style/color_scheme_dark"
                                         : "style/color_scheme";
        if (_GetStrPatched(&config, scheme_key, buffer, BUF_SIZE)) {
          std::string color_name(buffer);
          _UpdateUIStyleColor(&config, m_ui->style(), color_name);
        }
      }
      m_base_style = m_ui->style();
    }
    if (has_user) {
      g_user_patch = nullptr;
      rime_api->config_close(&user_config);
    }
    rime_api->config_close(&config);
  }

  for (auto& pair : m_session_status_map) {
    RIME_STRUCT(RimeStatus, status);
    if (rime_api->get_status(to_session_id(pair.first), &status)) {
      _LoadSchemaSpecificSettings(pair.first, std::string(status.schema_id));
      _LoadAppInlinePreeditSet(pair.first, true);
      _UpdateInlinePreeditStatus(pair.first);
      pair.second.status = status;
      pair.second.__synced = false;
      rime_api->free_status(&status);
    }
  }
  m_ui->style() = get_session_status(m_active_session).style;
}

BOOL RimeWithWeaselHandler::ProcessKeyEvent(KeyEvent keyEvent,
                                            WeaselSessionId ipc_id,
                                            EatLine eat) {
  DLOG(INFO) << "Process key event: keycode = " << keyEvent.keycode
             << ", mask = " << keyEvent.mask << ", ipc_id = " << ipc_id;
  if (m_disabled)
    return FALSE;
  RimeSessionId session_id = to_session_id(ipc_id);

  // ── 候选调序生效时，选词键按「界面上看到的顺序」走 ──────────────────
  // 重排只改了交给客户端的候选数组，引擎内部的顺序没变：空格上屏的是内部
  // 第一个候选、数字键选的也是内部序号。不在这里换一次，用户按 1 拿到的是
  // 重排前的那一个 —— 显示和实际选中的不一致，比不排序更糟。
  if (!(keyEvent.mask & ibus::Modifier::RELEASE_MASK)) {
    std::vector<int> order;
    {
      std::lock_guard<std::mutex> lock(m_page_mutex);
      auto it = m_page_order.find(session_id);
      if (it != m_page_order.end() && it->second.size() > 1)
        order = it->second;
    }
    if (!order.empty()) {
      const uint32_t kc = keyEvent.keycode;
      const bool plain =
          !(keyEvent.mask & (ibus::Modifier::SHIFT_MASK |
                             ibus::Modifier::CONTROL_MASK |
                             (1 << 3)));  // 1<<3 = Alt
      size_t picked = static_cast<size_t>(-1);
      if (plain && kc >= '1' && kc <= '9') {
        const size_t idx = kc - '1';
        if (idx < order.size())
          picked = static_cast<size_t>(order[idx]);
      } else if (plain && kc == 0x20) {
        picked = static_cast<size_t>(order[0]);  // 空格 = 上屏界面上第一个
      }
      if (picked != static_cast<size_t>(-1)) {
        ShadowTrace("[key] select display->orig %zu", picked);
        rime_api->select_candidate_on_current_page(session_id, picked);
        _Respond(ipc_id, eat);
        _UpdateUI(ipc_id);
        m_active_session = ipc_id;
        return TRUE;
      }
    }
  }

  Bool handled = rime_api->process_key(session_id, keyEvent.keycode,
                                       expand_ibus_modifier(keyEvent.mask));
  // vim_mode when keydown only
  if (!handled && !(keyEvent.mask & ibus::Modifier::RELEASE_MASK)) {
    bool isVimBackInCommandMode =
        (keyEvent.keycode == ibus::Keycode::Escape) ||
        ((keyEvent.mask & (1 << 2)) &&
         (keyEvent.keycode == ibus::Keycode::XK_c ||
          keyEvent.keycode == ibus::Keycode::XK_C ||
          keyEvent.keycode == ibus::Keycode::XK_bracketleft));
    if (isVimBackInCommandMode &&
        rime_api->get_option(session_id, "vim_mode") &&
        !rime_api->get_option(session_id, "ascii_mode")) {
      rime_api->set_option(session_id, "ascii_mode", True);
    }
  }
  _Respond(ipc_id, eat);
  _UpdateUI(ipc_id);
  m_active_session = ipc_id;
  return (BOOL)handled;
}

void RimeWithWeaselHandler::CommitComposition(WeaselSessionId ipc_id) {
  DLOG(INFO) << "Commit composition: ipc_id = " << ipc_id;
  if (m_disabled)
    return;
  rime_api->commit_composition(to_session_id(ipc_id));
  _UpdateUI(ipc_id);
  m_active_session = ipc_id;
}

void RimeWithWeaselHandler::ClearComposition(WeaselSessionId ipc_id) {
  DLOG(INFO) << "Clear composition: ipc_id = " << ipc_id;
  if (m_disabled)
    return;
  rime_api->clear_composition(to_session_id(ipc_id));
  _UpdateUI(ipc_id);
  m_active_session = ipc_id;
}

void RimeWithWeaselHandler::SelectCandidateOnCurrentPage(
    size_t index,
    WeaselSessionId ipc_id) {
  DLOG(INFO) << "select candidate on current page, ipc_id = " << ipc_id
             << ", index = " << index;
  if (m_disabled)
    return;
  rime_api->select_candidate_on_current_page(to_session_id(ipc_id),
                                             _ToOriginalIndex(ipc_id, index));
}

bool RimeWithWeaselHandler::HighlightCandidateOnCurrentPage(
    size_t index,
    WeaselSessionId ipc_id,
    EatLine eat) {
  DLOG(INFO) << "highlight candidate on current page, ipc_id = " << ipc_id
             << ", index = " << index;
  bool res = rime_api->highlight_candidate_on_current_page(
      to_session_id(ipc_id), _ToOriginalIndex(ipc_id, index));
  _Respond(ipc_id, eat);
  _UpdateUI(ipc_id);
  return res;
}

bool RimeWithWeaselHandler::ChangePage(bool backward,
                                       WeaselSessionId ipc_id,
                                       EatLine eat) {
  DLOG(INFO) << "change page, ipc_id = " << ipc_id
             << (backward ? "backward" : "foreward");
  bool res = rime_api->change_page(to_session_id(ipc_id), backward);
  _Respond(ipc_id, eat);
  _UpdateUI(ipc_id);
  return res;
}

void RimeWithWeaselHandler::FocusIn(DWORD client_caps, WeaselSessionId ipc_id) {
  DLOG(INFO) << "Focus in: ipc_id = " << ipc_id
             << ", client_caps = " << client_caps;
  if (m_disabled)
    return;
  _UpdateUI(ipc_id);
  m_active_session = ipc_id;
}

void RimeWithWeaselHandler::FocusOut(DWORD param, WeaselSessionId ipc_id) {
  DLOG(INFO) << "Focus out: ipc_id = " << ipc_id;
  if (m_ui)
    m_ui->Hide();
  m_active_session = 0;
  if (!m_disabled && RIME_API_AVAILABLE(rime_api, cleanup_stale_sessions))
    rime_api->cleanup_stale_sessions();
}

void RimeWithWeaselHandler::UpdateInputPosition(RECT const& rc,
                                                WeaselSessionId ipc_id) {
  DLOG(INFO) << "Update input position: (" << rc.left << ", " << rc.top
             << "), ipc_id = " << ipc_id
             << ", m_active_session = " << m_active_session;
  if (m_ui)
    m_ui->UpdateInputPosition(rc);
  if (m_disabled)
    return;
  if (m_active_session != ipc_id) {
    _UpdateUI(ipc_id);
    m_active_session = ipc_id;
  }
}

std::string RimeWithWeaselHandler::m_message_type;
std::string RimeWithWeaselHandler::m_message_value;
std::string RimeWithWeaselHandler::m_message_label;
std::string RimeWithWeaselHandler::m_option_name;
std::mutex RimeWithWeaselHandler::m_notifier_mutex;

void RimeWithWeaselHandler::OnNotify(void* context_object,
                                     uintptr_t session_id,
                                     const char* message_type,
                                     const char* message_value) {
  // may be running in a thread when deploying rime
  RimeWithWeaselHandler* self =
      reinterpret_cast<RimeWithWeaselHandler*>(context_object);
  if (!self || !message_type || !message_value)
    return;
  std::lock_guard<std::mutex> lock(m_notifier_mutex);
  m_message_type = message_type;
  m_message_value = message_value;
  if (RIME_API_AVAILABLE(rime_api, get_state_label) &&
      !strcmp(message_type, "option")) {
    Bool state = message_value[0] != '!';
    const char* option_name = message_value + !state;
    m_option_name = option_name;
    const char* state_label =
        rime_api->get_state_label(session_id, option_name, state);
    if (state_label) {
      m_message_label = std::string(state_label);
    }
  }
}

void RimeWithWeaselHandler::_ReadClientInfo(WeaselSessionId ipc_id,
                                            LPWSTR buffer) {
  std::string app_name;
  // parse request text
  wbufferstream bs(buffer, WEASEL_IPC_BUFFER_LENGTH);
  std::wstring line;
  while (bs.good()) {
    std::getline(bs, line);
    if (!bs.good())
      break;
    // file ends
    if (line == L".")
      break;
    const std::wstring kClientAppKey = L"session.client_app=";
    if (starts_with(line, kClientAppKey)) {
      std::wstring lwr = line;
      to_lower(lwr);
      app_name = wtou8(lwr.substr(kClientAppKey.length()));
    }
  }
  SessionStatus& session_status = get_session_status(ipc_id);
  RimeSessionId session_id = session_status.session_id;
  // set app specific options
  if (!app_name.empty()) {
    rime_api->set_property(session_id, "client_app", app_name.c_str());

    auto it = m_app_options.find(app_name);
    if (it != m_app_options.end()) {
      AppOptions& options(m_app_options[it->first]);
      for (const auto& pair : options) {
        DLOG(INFO) << "set app option: " << pair.first << " = " << pair.second;
        rime_api->set_option(session_id, pair.first.c_str(), Bool(pair.second));
      }
    }
  }
  // inline preedit
  bool inline_preedit = session_status.style.inline_preedit;
  rime_api->set_option(session_id, "inline_preedit", Bool(inline_preedit));
  // show soft cursor on weasel panel but not inline
  rime_api->set_option(session_id, "soft_cursor", Bool(!inline_preedit));
}

void RimeWithWeaselHandler::_GetCandidateInfo(CandidateInfo& cinfo,
                                              RimeContext& ctx) {
  cinfo.candies.resize(ctx.menu.num_candidates);
  cinfo.comments.resize(ctx.menu.num_candidates);
  cinfo.labels.resize(ctx.menu.num_candidates);
  for (int i = 0; i < ctx.menu.num_candidates; ++i) {
    cinfo.candies[i].str = escape_string(u8tow(ctx.menu.candidates[i].text));
    if (ctx.menu.candidates[i].comment) {
      cinfo.comments[i].str =
          escape_string(u8tow(ctx.menu.candidates[i].comment));
    }
    if (RIME_STRUCT_HAS_MEMBER(ctx, ctx.select_labels) && ctx.select_labels) {
      cinfo.labels[i].str = escape_string(u8tow(ctx.select_labels[i]));
    } else if (ctx.menu.select_keys) {
      cinfo.labels[i].str =
          escape_string(std::wstring(1, ctx.menu.select_keys[i]));
    } else {
      cinfo.labels[i].str = std::to_wstring((i + 1) % 10);
    }
  }
  cinfo.highlighted = ctx.menu.highlighted_candidate_index;
  cinfo.currentPage = ctx.menu.page_no;
  cinfo.is_last_page = ctx.menu.is_last_page;
}

void RimeWithWeaselHandler::StartMaintenance() {
  m_session_status_map.clear();
  Finalize();
  _UpdateUI(0);
}

void RimeWithWeaselHandler::EndMaintenance() {
  if (m_disabled) {
    Initialize();
    _UpdateUI(0);
  }
  m_session_status_map.clear();
}

void RimeWithWeaselHandler::SetOption(WeaselSessionId ipc_id,
                                      const std::string& opt,
                                      bool val) {
  // from no-session client, not actual typing session
  if (!ipc_id) {
    if (m_global_ascii_mode && opt == "ascii_mode") {
      for (auto& pair : m_session_status_map)
        rime_api->set_option(to_session_id(pair.first), "ascii_mode", val);
    } else {
      rime_api->set_option(to_session_id(m_active_session), opt.c_str(), val);
    }
  } else {
    rime_api->set_option(to_session_id(ipc_id), opt.c_str(), val);
  }
  // refresh UI (and tray icon) so the option change takes effect immediately,
  // e.g. when toggling ascii_mode from the TSF language bar
  _UpdateUI(ipc_id ? ipc_id : m_active_session);
}

void RimeWithWeaselHandler::OnUpdateUI(std::function<void()> const& cb) {
  _UpdateUICallback = cb;
}

bool RimeWithWeaselHandler::_IsDeployerRunning() {
  HANDLE hMutex = CreateMutex(NULL, TRUE, L"WeaselDeployerMutex");
  bool deployer_detected = hMutex && GetLastError() == ERROR_ALREADY_EXISTS;
  if (hMutex) {
    CloseHandle(hMutex);
  }
  return deployer_detected;
}

void RimeWithWeaselHandler::_UpdateUI(WeaselSessionId ipc_id) {
  // if m_ui nullptr, _UpdateUI meaningless
  if (!m_ui)
    return;

  Status& weasel_status = m_ui->status();
  Context weasel_context;

  RimeSessionId session_id = to_session_id(ipc_id);

  if (ipc_id == 0)
    weasel_status.disabled = m_disabled;

  _GetStatus(weasel_status, ipc_id, weasel_context);

  SessionStatus& session_status = get_session_status(ipc_id);
  if (rime_api->get_option(session_id, "inline_preedit"))
    session_status.style.client_caps |= INLINE_PREEDIT_CAPABLE;
  else
    session_status.style.client_caps &= ~INLINE_PREEDIT_CAPABLE;

  if (!_ShowMessage(weasel_context, weasel_status)) {
    m_ui->Hide();
    m_ui->Update(weasel_context, weasel_status);
  }

  _RefreshTrayIcon(session_id, _UpdateUICallback);

  {
    std::lock_guard<std::mutex> lock(m_notifier_mutex);
    m_message_type.clear();
    m_message_value.clear();
    m_message_label.clear();
    m_option_name.clear();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 候选调序（shadow 层）
//
// 规则存在 <用户数据>\shadow\<方案>.yaml，形如：
//     version: 1
//     rules:
//       "d":
//         - "在"
//         - "大"
// 含义：打 d 时，「在」排第一、「大」排第二，其余候选保持原相对顺序。
//
// 三条设计约束（照抄清风的思路）：
//   ① 不改原词库 —— 只在候选装配完之后重排，删掉这个文件就恢复原状；
//   ② 不触发部署 —— 改完立刻重排并刷新，毫秒级；
//   ③ 每个编码独立 —— d 的规则不影响 de。
// ─────────────────────────────────────────────────────────────────────────────

namespace {

fs::path ShadowDir() {
  // 放在用户数据目录根部，文件名 shadow_<方案>.yaml。
  // 刻意不建子目录：librime 的 config id 用 `/` 分隔会解析失败，
  // 用平铺命名才能直接 config_open("shadow_wubi86")。
  return fs::path(WeaselUserDataPath());
}

fs::path ShadowFile(const std::string& schema_id) {
  return ShadowDir() / (L"shadow_" + u8tow(schema_id) + L".yaml");
}

// YAML 字符串转义：只处理双引号与反斜杠，中文原样写。
std::string QuoteYaml(const std::string& s) {
  std::string out = "\"";
  for (char c : s) {
    if (c == '"' || c == '\\')
      out.push_back('\\');
    out.push_back(c);
  }
  out.push_back('"');
  return out;
}

}  // namespace

void RimeWithWeaselHandler::_LoadShadow(const std::string& schema_id) {
  // 直接解析文件，不走 librime 的 config API：那个 API 的 config id 规则
  // （会在 user/shared/build 三处查找、还会自动套 custom patch）对一个
  // 我们自己维护的简单两列表格来说太重，也容易踩到「找不到文件却静默成功」。
  ShadowRules rules;
  const auto path = ShadowFile(schema_id);
  std::ifstream in(path, std::ios::binary);
  if (in) {
    const auto unquote = [](std::string s) {
      if (s.size() >= 2 && s.front() == '"' && s.back() == '"') {
        s = s.substr(1, s.size() - 2);
        std::string out;
        for (size_t i = 0; i < s.size(); ++i) {
          if (s[i] == '\\' && i + 1 < s.size()) {
            out.push_back(s[++i]);
          } else {
            out.push_back(s[i]);
          }
        }
        return out;
      }
      return s;
    };
    std::string line;
    std::string current_code;
    while (std::getline(in, line)) {
      if (!line.empty() && line.back() == '\r')
        line.pop_back();
      const size_t first = line.find_first_not_of(" \t");
      if (first == std::string::npos)
        continue;
      std::string s = line.substr(first);
      if (s.empty() || s[0] == '#')
        continue;
      if (s.rfind("- ", 0) == 0) {
        const std::string word = unquote(s.substr(2));
        if (!current_code.empty() && !word.empty())
          rules[current_code].push_back(word);
        continue;
      }
      const size_t colon = s.find(':');
      if (colon == std::string::npos)
        continue;
      const std::string key = unquote(s.substr(0, colon));
      if (key.empty() || key == "rules" || key == "version")
        continue;
      current_code = key;
    }
  }
  std::lock_guard<std::mutex> lock(m_shadow_mutex);
  const size_t n = rules.size();
  m_shadow[schema_id] = std::move(rules);
  m_shadow_loaded.insert(schema_id);
  LOG(ERROR) << "[shadow] loaded: " << schema_id << " rules=" << n
             << " path=" << path.u8string();
}

bool RimeWithWeaselHandler::_SaveShadow(const std::string& schema_id) {
  std::error_code ec;
  fs::create_directories(ShadowDir(), ec);
  const auto path = ShadowFile(schema_id);
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out)
    return false;
  out << "# 青石五笔 候选调序\n"
      << "# 由输入法在候选上「置顶」时自动写入；删掉对应编码即恢复默认顺序。\n"
      << "version: 1\n"
      << "rules:\n";
  {
    std::lock_guard<std::mutex> lock(m_shadow_mutex);
    auto sit = m_shadow.find(schema_id);
    if (sit != m_shadow.end()) {
      for (const auto& kv : sit->second) {
        if (kv.second.empty())
          continue;
        out << "  " << QuoteYaml(kv.first) << ":\n";
        for (const auto& word : kv.second)
          out << "    - " << QuoteYaml(word) << "\n";
      }
    }
  }
  out.flush();
  return out.good();
}

std::string RimeWithWeaselHandler::_CurrentCode(RimeContext& ctx) {
  // 五笔方案的 preedit 就是编码。一旦出现非 ASCII（说明已经转成汉字显示），
  // 就拿不到原始编码了，此时放弃调序 —— 宁可不动，也不要按错误的码去重排。
  std::string code;
  if (!ctx.composition.preedit)
    return code;
  for (int i = 0; i < ctx.composition.length; ++i) {
    const unsigned char c = static_cast<unsigned char>(ctx.composition.preedit[i]);
    if (c == '\0' || c == ' ')
      break;
    if (c >= 0x80)
      return std::string();
    code.push_back(static_cast<char>(c));
  }
  return code;
}

std::vector<int> RimeWithWeaselHandler::_ApplyShadow(const std::string& schema_id,
                                                     const std::string& code,
                                                     RimeContext& ctx) {
  std::vector<int> order;
  const int n = ctx.menu.num_candidates;
  ShadowTrace("[apply] enter schema=%s code=%s n=%d ptr=%p", schema_id.c_str(),
              code.c_str(), n, (void*)ctx.menu.candidates);
  if (n <= 0 || code.empty() || schema_id.empty() || !ctx.menu.candidates)
    return order;

  std::vector<std::string> wanted;
  {
    std::lock_guard<std::mutex> lock(m_shadow_mutex);
    auto sit = m_shadow.find(schema_id);
    if (sit == m_shadow.end())
      return order;
    auto rit = sit->second.find(code);
    if (rit == sit->second.end())
      return order;
    wanted = rit->second;
  }
  if (wanted.empty())
    return order;

  std::vector<int> picked;
  std::vector<bool> used(n, false);
  for (const auto& want : wanted) {
    for (int i = 0; i < n; ++i) {
      if (used[i] || !ctx.menu.candidates[i].text)
        continue;
      if (want == ctx.menu.candidates[i].text) {
        picked.push_back(i);
        used[i] = true;
        break;
      }
    }
  }
  if (picked.empty())
    return order;  // 规则里的词这一页没有，原样显示

  order.reserve(n);
  for (int i : picked)
    order.push_back(i);
  for (int i = 0; i < n; ++i)
    if (!used[i])
      order.push_back(i);

  std::vector<RimeCandidate> snapshot(ctx.menu.candidates,
                                     ctx.menu.candidates + n);
  for (int i = 0; i < n; ++i)
    ctx.menu.candidates[i] = snapshot[order[i]];

  LOG(ERROR) << "[shadow] applied: schema=" << schema_id << " code=" << code
            << " pinned=" << picked.size();
  ShadowTrace("[apply] reordered picked=%zu first=%s", picked.size(),
              ctx.menu.candidates[0].text ? ctx.menu.candidates[0].text : "?");
  return order;
}

void RimeWithWeaselHandler::_LoadShadowForSession(RimeSessionId session_id,
                                                  const std::string& schema_id) {
  (void)session_id;  // 目前按方案缓存，与会话无关
  if (schema_id.empty())
    return;
  bool need = false;
  {
    std::lock_guard<std::mutex> lock(m_shadow_mutex);
    need = m_shadow_loaded.find(schema_id) == m_shadow_loaded.end();
  }
  if (need)
    _LoadShadow(schema_id);
}

size_t RimeWithWeaselHandler::_ToOriginalIndex(WeaselSessionId ipc_id,
                                               size_t display_index) {
  const RimeSessionId session_id = to_session_id(ipc_id);
  std::lock_guard<std::mutex> lock(m_page_mutex);
  auto it = m_page_order.find(session_id);
  if (it != m_page_order.end() && display_index < it->second.size())
    return static_cast<size_t>(it->second[display_index]);
  return display_index;
}

bool RimeWithWeaselHandler::ReloadConfig() {
  if (m_disabled) {
    LOG(INFO) << "ReloadConfig skipped: handler disabled";
    return false;
  }
  RimeConfig config = {NULL};
  if (!rime_api->config_open("weasel", &config)) {
    LOG(ERROR) << "ReloadConfig: cannot open weasel config";
    return false;
  }
  // 用户 custom 配置挂上去：_RimeGet* 系列会优先读 patch/<key>。
  // 注意用 config_open("weasel.custom") 而不是 user_config_open("weasel")：
  // 后者只找 user_dir 里的 weasel.yaml（我们这里是 weasel.custom.yaml）。
  RimeConfig user_config = {NULL};
  const bool has_user = _LoadFreshUserPatch(&user_config);
  if (has_user)
    g_user_patch = &user_config;

  if (m_ui) {
    _UpdateUIStyle(&config, m_ui, true);
    _UpdateShowNotifications(&config, true);
    m_current_dark_mode = IsUserDarkMode();
    const int BUF_SIZE = 255;
    char buffer[BUF_SIZE + 1] = {0};
    const char* scheme_key =
        m_current_dark_mode ? "style/color_scheme_dark" : "style/color_scheme";
    if (_GetStrPatched(&config, scheme_key, buffer, BUF_SIZE)) {
      _UpdateUIStyleColor(&config, m_ui->style(), std::string(buffer));
    }
    m_base_style = m_ui->style();
    m_ui->ForceRefresh();
  }

  Bool global_ascii = false;
  if (rime_api->config_get_bool(&config, "global_ascii", &global_ascii))
    m_global_ascii_mode = !!global_ascii;
  if (!rime_api->config_get_int(&config, "show_notifications_time",
                                &m_show_notifications_time))
    m_show_notifications_time = 1200;
  m_app_options.clear();
  _LoadAppOptions(&config, m_app_options);
  if (has_user) {
    g_user_patch = nullptr;
    rime_api->config_close(&user_config);
  }
  rime_api->config_close(&config);

  // 方案级 UI 设置（配色、图标、inline_preedit）也要重读：
  // 清掉缓存标记，让下一次 _GetStatus 重新加载。
  m_last_schema_id.clear();
  // 候选调序表同样重读（用户可能直接编辑了 shadow 文件）。
  {
    std::lock_guard<std::mutex> lock(m_shadow_mutex);
    m_shadow_loaded.clear();
    m_shadow.clear();
  }
  m_page_order.clear();
  m_page_code.clear();

  for (auto& pair : m_session_status_map) {
    SessionStatus& status = pair.second;
    status.style = m_base_style;
    RIME_STRUCT(RimeStatus, current);
    if (status.session_id && rime_api->get_status(status.session_id, &current)) {
      if (current.schema_id && std::string(current.schema_id) != ".default")
        _LoadSchemaSpecificSettings(pair.first, current.schema_id);
      rime_api->free_status(&current);
    }
    // Candidate panels live in host processes. They must receive fresh style
    // data on their next response even when the schema did not change.
    status.__synced = false;
  }

  _UpdateUI(0);
  ShadowTrace("[reload] done back=0x%08X hilite=0x%08X font_point=%d sessions=%zu",
              static_cast<unsigned>(m_base_style.back_color),
              static_cast<unsigned>(m_base_style.hilited_candidate_back_color),
              m_base_style.font_point, m_session_status_map.size());
  LOG(ERROR) << "[reload] done (no deployment)";
  return true;
}

bool RimeWithWeaselHandler::AdjustShadow(int action,
                                         size_t index,
                                         WeaselSessionId ipc_id,
                                         EatLine eat) {
  // 从命令行（WeaselDeployer /pin）调进来时没有会话 id，退回最近活跃的那个。
  if (!ipc_id)
    ipc_id = m_active_session;
  RimeSessionId session_id = to_session_id(ipc_id);
  if (!session_id) {
    ShadowTrace("[shadow] adjust: no session (ipc_id=0)");
    return false;
  }

  // 界面上看到的序号是重排后的，先换回引擎里的原始索引。
  size_t original = index;
  {
    std::lock_guard<std::mutex> lock(m_page_mutex);
    auto order_it = m_page_order.find(session_id);
    if (order_it != m_page_order.end() && index < order_it->second.size())
      original = static_cast<size_t>(order_it->second[index]);
  }

  RIME_STRUCT(RimeStatus, status);
  std::string schema_id;
  if (rime_api->get_status(session_id, &status)) {
    if (status.schema_id)
      schema_id = status.schema_id;
    rime_api->free_status(&status);
  }
  if (schema_id.empty())
    return false;

  RIME_STRUCT(RimeContext, ctx);
  if (!rime_api->get_context(session_id, &ctx))
    return false;
  const std::string code = _CurrentCode(ctx);
  std::string text;
  if (original < static_cast<size_t>(ctx.menu.num_candidates) &&
      ctx.menu.candidates[original].text) {
    text = ctx.menu.candidates[original].text;
  }
  rime_api->free_context(&ctx);

  if (code.empty() || text.empty()) {
    LOG(ERROR) << "[shadow] adjust: no code/text, ignored";
    return false;
  }

  {
    std::lock_guard<std::mutex> lock(m_shadow_mutex);
    ShadowRules& rules = m_shadow[schema_id];
    auto& list = rules[code];
    list.erase(std::remove(list.begin(), list.end(), text), list.end());
    if (action >= 100) {
      // 「调整位置」：插到置顶区第 (action-100) 位，越界就追加到末尾
      size_t pos = static_cast<size_t>(action - 100);
      if (pos > 0)
        --pos;
      if (pos > list.size())
        pos = list.size();
      list.insert(list.begin() + pos, text);
    } else if (action == WEASEL_SHADOW_PIN) {
      list.insert(list.begin(), text);
    }
    ShadowTrace("[shadow] adjust action=%d code=%s word=%s list=%zu", action,
                code.c_str(), text.c_str(), list.size());
    if (list.empty())
      rules.erase(code);
    m_shadow_loaded.insert(schema_id);
  }
  _SaveShadow(schema_id);
  LOG(ERROR) << "[shadow] adjust: action=" << action << " code=" << code
            << " word=" << text;

  // 立刻按新规则重排并刷新，不需要重启、不需要部署。
  //
  // ★ 关键：候选窗在**应用进程**（TSF）里，服务端只持有数据。
  // 光调 _UpdateUI 只刷新服务端自己那个没人看的 UI，界面上不会有任何变化。
  // 必须通过 eat 把重排后的候选回给客户端，由它更新本地窗口。
  if (eat) {
    _Respond(ipc_id, eat);
  } else {
    _UpdateUI(ipc_id);
  }
  if (m_ui)
    m_ui->Show();
  return true;
}

void RimeWithWeaselHandler::_LoadSchemaSpecificSettings(
    WeaselSessionId ipc_id,
    const std::string& schema_id) {
  if (!m_ui)
    return;
  RimeConfig config;
  if (!rime_api->schema_open(schema_id.c_str(), &config))
    return;
  _UpdateShowNotifications(&config);
  m_ui->style() = m_base_style;
  _UpdateUIStyle(&config, m_ui, false);
  SessionStatus& session_status = get_session_status(ipc_id);
  session_status.style = m_ui->style();
  UIStyle& style = session_status.style;
  // load schema color style config
  const int BUF_SIZE = 255;
  char buffer[BUF_SIZE + 1] = {0};
  const auto update_color_scheme = [&]() {
    std::string color_name(buffer);
    RimeConfigIterator preset = {0};
    if (rime_api->config_begin_map(
            &preset, &config, ("preset_color_schemes/" + color_name).c_str())) {
      _UpdateUIStyleColor(&config, style, color_name);
      rime_api->config_end(&preset);
    } else {
      RimeConfig weaselconfig;
      if (rime_api->config_open("weasel", &weaselconfig)) {
        _UpdateUIStyleColor(&weaselconfig, style, color_name);
        rime_api->config_close(&weaselconfig);
      }
    }
  };
  const char* key =
      m_current_dark_mode ? "style/color_scheme_dark" : "style/color_scheme";
  if (rime_api->config_get_string(&config, key, buffer, BUF_SIZE))
    update_color_scheme();
  // load schema icon start
  {
    const auto load_icon = [](RimeConfig& config, const char* key1,
                              const char* key2) {
      const auto user_dir = WeaselUserDataPath();
      const auto shared_dir = WeaselSharedDataPath();
      const int BUF_SIZE = 255;
      char buffer[BUF_SIZE + 1] = {0};
      if (rime_api->config_get_string(&config, key1, buffer, BUF_SIZE) ||
          (key2 != NULL &&
           rime_api->config_get_string(&config, key2, buffer, BUF_SIZE))) {
        auto resource = u8tow(buffer);
        if (fs::is_regular_file(user_dir / resource))
          return (user_dir / resource).wstring();
        else if (fs::is_regular_file(shared_dir / resource))
          return (shared_dir / resource).wstring();
      }
      return std::wstring();
    };
    style.current_zhung_icon =
        load_icon(config, "schema/icon", "schema/zhung_icon");
    style.current_ascii_icon = load_icon(config, "schema/ascii_icon", NULL);
    style.current_full_icon = load_icon(config, "schema/full_icon", NULL);
    style.current_half_icon = load_icon(config, "schema/half_icon", NULL);
  }
  // load schema icon end
  rime_api->config_close(&config);
}

void RimeWithWeaselHandler::_LoadAppInlinePreeditSet(WeaselSessionId ipc_id,
                                                     bool ignore_app_name) {
  SessionStatus& session_status = get_session_status(ipc_id);
  RimeSessionId session_id = session_status.session_id;
  static char _app_name[50];
  rime_api->get_property(session_id, "client_app", _app_name,
                         sizeof(_app_name) - 1);
  std::string app_name(_app_name);
  if (!ignore_app_name && m_last_app_name == app_name)
    return;
  m_last_app_name = app_name;
  bool inline_preedit = session_status.style.inline_preedit;
  bool found = false;
  if (!app_name.empty()) {
    auto it = m_app_options.find(app_name);
    if (it != m_app_options.end()) {
      AppOptions& options(m_app_options[it->first]);
      for (const auto& pair : options) {
        if (pair.first == "inline_preedit") {
          rime_api->set_option(session_id, pair.first.c_str(),
                               Bool(pair.second));
          session_status.style.inline_preedit = Bool(pair.second);
          found = true;
          break;
        }
      }
    }
  }
  if (!found) {
    session_status.style.inline_preedit = m_base_style.inline_preedit;
    // load from schema.
    RIME_STRUCT(RimeStatus, status);
    if (rime_api->get_status(session_id, &status)) {
      std::string schema_id = status.schema_id;
      RimeConfig config;
      if (rime_api->schema_open(schema_id.c_str(), &config)) {
        Bool value = False;
        if (rime_api->config_get_bool(&config, "style/inline_preedit",
                                      &value)) {
          session_status.style.inline_preedit = value;
        }
        rime_api->config_close(&config);
      }
      rime_api->free_status(&status);
    }
  }
  if (session_status.style.inline_preedit != inline_preedit)
    _UpdateInlinePreeditStatus(ipc_id);
}

bool RimeWithWeaselHandler::_ShowMessage(Context& ctx, Status& status) {
  std::lock_guard<std::mutex> lock(m_notifier_mutex);
  if (m_message_type.empty() || m_message_value.empty())
    return m_ui->IsCountingDown();
  // show as auxiliary string
  std::wstring& tips(ctx.aux.str);
  bool show_icon = false;
  if (m_message_type == "deploy") {
    if (m_message_value == "start")
      if (GetThreadUILanguage() == MAKELANGID(LANG_ENGLISH, SUBLANG_ENGLISH_US))
        tips = L"Deploying RIME";
      else
        tips = L"正在部署 RIME";
    else if (m_message_value == "success")
      if (GetThreadUILanguage() == MAKELANGID(LANG_ENGLISH, SUBLANG_ENGLISH_US))
        tips = L"Deployed";
      else
        tips = L"部署完成";
    else if (m_message_value == "failure") {
      if (GetThreadUILanguage() ==
          MAKELANGID(LANG_CHINESE, SUBLANG_CHINESE_TRADITIONAL))
        tips = L"有錯誤，請查看日誌 %TEMP%\\rime.weasel\\rime.weasel.*.INFO";
      else if (GetThreadUILanguage() ==
               MAKELANGID(LANG_CHINESE, SUBLANG_CHINESE_SIMPLIFIED))
        tips = L"有错误，请查看日志 %TEMP%\\rime.weasel\\rime.weasel.*.INFO";
      else
        tips =
            L"There is an error, please check the logs "
            L"%TEMP%\\rime.weasel\\rime.weasel.*.INFO";
    }
  } else if (m_message_type == "schema") {
    tips = /*L"【" + */ status.schema_name /* + L"】"*/;
  } else if (m_message_type == "option") {
    status.type = SCHEMA;
    if (m_message_value == "!ascii_mode") {
      show_icon = true;
    } else if (m_message_value == "ascii_mode") {
      show_icon = true;
    } else
      tips = u8tow(m_message_label);

    if (m_message_value == "full_shape" || m_message_value == "!full_shape")
      status.type = FULL_SHAPE;
  }
  auto counter = m_ui->IsCountingDown();
  if (!show_icon && counter)
    return counter;
  auto foption = m_show_notifications.find(m_option_name);
  auto falways = m_show_notifications.find("always");
  if ((!add_session && (foption != m_show_notifications.end() ||
                        falways != m_show_notifications.end())) ||
      m_message_type == "deploy") {
    m_ui->Update(ctx, status);
    // For icon-only notifications, status/context may be unchanged and Update()
    // can early-return; force a refresh before showing timeout tip.
    m_ui->Refresh();
    if (m_show_notifications_time)
      m_ui->ShowWithTimeout(m_show_notifications_time);
    return true;
  } else {
    return m_ui->IsCountingDown();
  }
}
inline std::string _GetLabelText(const std::vector<Text>& labels,
                                 int id,
                                 const wchar_t* format) {
  wchar_t buffer[128];
  swprintf_s<128>(buffer, format, labels.at(id).str.c_str());
  return wtou8(std::wstring(buffer));
}

bool RimeWithWeaselHandler::_Respond(WeaselSessionId ipc_id, EatLine eat) {
  std::wstring body;
  body.reserve(4096);
  std::vector<const char*> actions;
  actions.reserve(8);

  SessionStatus& session_status = get_session_status(ipc_id);
  RimeSessionId session_id = session_status.session_id;
  RIME_STRUCT(RimeCommit, commit);
  if (rime_api->get_commit(session_id, &commit)) {
    actions.push_back("commit");
    std::wstring commit_text_w = escape_string(u8tow(commit.text));
    body.append(L"commit=").append(commit_text_w).append(L"\n");
    rime_api->free_commit(&commit);
  }

  bool is_composing = false;
  RIME_STRUCT(RimeStatus, status);
  static const std::wstring Bool_wstring[] = {L"0", L"1"};
  if (rime_api->get_status(session_id, &status)) {
    is_composing = !!status.is_composing;
    actions.push_back("status");
    body.append(L"status.ascii_mode=")
        .append(Bool_wstring[!!status.is_ascii_mode])
        .append(L"\n")
        .append(L"status.composing=")
        .append(Bool_wstring[!!status.is_composing])
        .append(L"\n")
        .append(L"status.disabled=")
        .append(Bool_wstring[!!status.is_disabled])
        .append(L"\n")
        .append(L"status.full_shape=")
        .append(Bool_wstring[!!status.is_full_shape])
        .append(L"\n")
        .append(L"status.schema_id=")
        .append(status.schema_id ? u8tow(status.schema_id) : std::wstring())
        .append(L"\n");
    if (m_global_ascii_mode &&
        (session_status.status.is_ascii_mode != status.is_ascii_mode)) {
      for (auto& pair : m_session_status_map) {
        if (pair.first != ipc_id)
          rime_api->set_option(to_session_id(pair.first), "ascii_mode",
                               !!status.is_ascii_mode);
      }
    }
    session_status.status = status;
    rime_api->free_status(&status);
  }

  RIME_STRUCT(RimeContext, ctx);
  if (rime_api->get_context(session_id, &ctx)) {
    bool has_candidates = ctx.menu.num_candidates > 0;
    CandidateInfo cinfo;
    if (has_candidates) {
      // [探针] 只观察不改动：确认 schema_id / 编码 / 规则加载是否到位
      std::string probe_schema;
      RIME_STRUCT(RimeStatus, probe_status);
      if (rime_api->get_status(session_id, &probe_status)) {
        if (probe_status.schema_id)
          probe_schema = probe_status.schema_id;
        rime_api->free_status(&probe_status);
      }
      const std::string probe_code = _CurrentCode(ctx);
      _LoadShadowForSession(session_id, probe_schema);
      const std::vector<int> order = _ApplyShadow(probe_schema, probe_code, ctx);
      {
        std::lock_guard<std::mutex> lock(m_page_mutex);
        m_page_order[session_id] = order;
        m_page_code[session_id] = probe_code;
      }
      {
        std::lock_guard<std::mutex> lock(m_shadow_mutex);
        auto it = m_shadow.find(probe_schema);
        ShadowTrace("[respond] schema=%s code=%s n=%d loaded=%d rules=%zu order=%zu",
                    probe_schema.c_str(), probe_code.c_str(),
                    ctx.menu.num_candidates,
                    (int)m_shadow_loaded.count(probe_schema),
                    it == m_shadow.end() ? 0 : it->second.size(),
                    order.size());
      }
      _GetCandidateInfo(cinfo, ctx);
    }
    if (is_composing) {
      const auto& preedit = ctx.composition.preedit;
      const auto& start = ctx.composition.sel_start;
      const auto& end = ctx.composition.sel_end;
      const auto& cursor = ctx.composition.cursor_pos;
      static const auto u8towstring = [](const char* u8str, int len = 0) {
        return std::to_wstring(utf8towcslen(u8str, len));
      };
      actions.push_back("ctx");
      switch (session_status.style.preedit_type) {
        case UIStyle::PREVIEW: {
          if (ctx.commit_text_preview) {
            const char* first_utf8 = ctx.commit_text_preview;
            const size_t first_len = std::strlen(first_utf8);
            const std::wstring first_w = escape_string(u8tow(first_utf8));
            const std::wstring tmp = u8towstring(first_utf8, (int)first_len);
            body.append(L"ctx.preedit=")
                .append(first_w)
                .append(L"\n")
                .append(L"ctx.preedit.cursor=")
                .append(u8towstring(first_utf8, 0))
                .append(L",")
                .append(tmp)
                .append(L",")
                .append(tmp)
                .append(L"\n");
            break;
          }
          // no preview, fall back to composition
        }
        case UIStyle::COMPOSITION: {
          body.append(L"ctx.preedit=")
              .append(escape_string(u8tow(preedit)))
              .append(L"\n");
          if (start <= end) {
            body.append(L"ctx.preedit.cursor=")
                .append(u8towstring(preedit, start))
                .append(L",")
                .append(u8towstring(preedit, end))
                .append(L",")
                .append(u8towstring(preedit, cursor))
                .append(L"\n");
          }
          break;
        }
        case UIStyle::PREVIEW_ALL: {
          body.append(L"ctx.preedit=")
              .append(escape_string(u8tow(preedit)))
              .append(L"  [");
          auto label_valid = session_status.style.label_font_point > 0;
          auto comment_valid = session_status.style.comment_font_point > 0;
          const std::wstring mark_text_w =
              session_status.style.mark_text.empty()
                  ? std::wstring(L"*")
                  : session_status.style.mark_text;
          for (auto i = 0; i < ctx.menu.num_candidates; i++) {
            std::wstring label_w;
            if (label_valid) {
              wchar_t buf_lbl[128];
              swprintf_s<128>(buf_lbl,
                              session_status.style.label_text_format.c_str(),
                              cinfo.labels.at(i).str.c_str());
              label_w = std::wstring(buf_lbl);
            }
            std::wstring comment_w =
                comment_valid ? cinfo.comments.at(i).str : std::wstring();
            std::wstring prefix_w = (i != ctx.menu.highlighted_candidate_index)
                                        ? std::wstring()
                                        : mark_text_w;
            body.append(L" ")
                .append(prefix_w)
                .append(escape_string(label_w))
                .append(escape_string(u8tow(ctx.menu.candidates[i].text)))
                .append(L" ")
                .append(escape_string(comment_w));
          }
          body.append(L" ]\n");
          if (start <= end) {
            body.append(L"ctx.preedit.cursor=")
                .append(u8towstring(preedit, start))
                .append(L",")
                .append(u8towstring(preedit, end))
                .append(L",")
                .append(u8towstring(preedit, cursor))
                .append(L"\n");
          }
          break;
        }
      }
    }
    if (has_candidates) {
      std::wstringstream ss;
      boost::archive::text_woarchive oa(ss);

      oa << cinfo;

      auto s = ss.str();
      body.append(L"ctx.cand=").append(std::move(s)).append(L"\n");
    }
    rime_api->free_context(&ctx);
  }

  // configuration information
  actions.push_back("config");
  body.append(L"config.inline_preedit=")
      .append(std::to_wstring((int)session_status.style.inline_preedit))
      .append(L"\n");

  // style
  if (!session_status.__synced) {
    std::wstringstream ss;
    boost::archive::text_woarchive oa(ss);
    oa << session_status.style;

    actions.push_back("style");
    body.append(L"style=").append(ss.str()).append(L"\n");
    session_status.__synced = true;
  }

  // summarize: send header first to avoid vector head-insert cost
  std::wstring header;
  if (actions.empty()) {
    header = L"action=noop\n";
  } else {
    std::string actionList;
    actionList.reserve(64);
    for (size_t i = 0; i < actions.size(); ++i) {
      if (i > 0)
        actionList += ',';
      actionList += actions[i];
    }
    header = std::wstring(L"action=") + u8tow(actionList) + L"\n";
  }
  if (!eat(header))
    return false;

  body.append(L".\n");
  if (!eat(body))
    return false;

  return true;
}

// Blend foreground and background ARGB colors taking alpha into account.
// Returns an ABGR COLORREF with premultiplied alpha blended result.
static inline COLORREF blend_colors(COLORREF fcolor, COLORREF bcolor) {
  // Extract ARGB channels from both colors.
  BYTE fA = (fcolor >> 24) & 0xFF;
  BYTE fB = (fcolor >> 16) & 0xFF;
  BYTE fG = (fcolor >> 8) & 0xFF;
  BYTE fR = fcolor & 0xFF;
  BYTE bA = (bcolor >> 24) & 0xFF;
  BYTE bB = (bcolor >> 16) & 0xFF;
  BYTE bG = (bcolor >> 8) & 0xFF;
  BYTE bR = bcolor & 0xFF;
  // Convert alpha to [0,1]
  float fAlpha = fA / 255.0f;
  float bAlpha = bA / 255.0f;
  // Result alpha
  float retAlpha = fAlpha + (1 - fAlpha) * bAlpha;
  if (retAlpha <= 1e-6f) {
    // Fully transparent result — return background unchanged as fallback.
    return bcolor;
  }
  auto mix = [&](float fc, float bc) -> BYTE {
    return static_cast<BYTE>((fc * fAlpha + bc * bAlpha * (1 - fAlpha)) /
                             retAlpha);
  };
  BYTE retR = mix(fR, bR);
  BYTE retG = mix(fG, bG);
  BYTE retB = mix(fB, bB);
  BYTE outA = static_cast<BYTE>(retAlpha * 255.0f);
  return (static_cast<COLORREF>(outA) << 24) | (retB << 16) | (retG << 8) |
         retR;
}
// parse color value, with fallback value
static Bool _RimeGetColor(RimeConfig* config,
                          const std::string& key,
                          int& value,
                          const ColorFormat& fmt,
                          const unsigned int& fallback) {
  char color[256] = {0};
  if (!_GetStrPatched(config, key.c_str(), color, 256)) {
    value = fallback;
    return False;
  }
  unsigned int parsed = 0;
  if (!ParseColorValue(std::string(color), fmt, &parsed)) {
    value = fallback;
    return False;
  }
  value = static_cast<int>(parsed);
  return True;
}

template <typename T, size_t N>
using Array = std::array<std::pair<const char*, T>, N>;

// parset bool type configuration to T type value trueValue / falseValue
template <typename T>
void _RimeGetBool(RimeConfig* config,
                  const char* key,
                  bool cond,
                  T& value,
                  const T& trueValue = true,
                  const T& falseValue = false) {
  Bool tempb = False;
  if (_GetBoolPatched(config, key, &tempb) || cond)
    value = (!!tempb) ? trueValue : falseValue;
}
// parse string option to T type value, with fallback
template <typename T, size_t N>
void _RimeParseStringOptWithFallback(RimeConfig* config,
                                     const char* key,
                                     T& value,
                                     const Array<T, N>& arr,
                                     const T& fallback) {
  char str_buff[256] = {0};
  if (_GetStrPatched(config, key, str_buff, 255)) {
    for (size_t i = 0; i < N; ++i) {
      if (strcmp(arr[i].first, str_buff) == 0) {
        value = arr[i].second;
        return;
      }
    }
  }
  value = fallback;
}

template <typename T>
void _RimeGetIntStr(RimeConfig* config,
                    const char* key,
                    T& value,
                    const char* fb_key = nullptr,
                    const void* fb_value = nullptr,
                    const std::function<void(T&)>& func = nullptr) {
  if constexpr (std::is_same<T, int>::value) {
    if (!_GetIntPatched(config, key, &value) && fb_key != 0)
      _GetIntPatched(config, fb_key, &value);
  } else if constexpr (std::is_same<T, std::wstring>::value) {
    const int BUF_SIZE = 2047;
    char buffer[BUF_SIZE + 1] = {0};
    if (_GetStrPatched(config, key, buffer, BUF_SIZE) ||
        (fb_key != 0 && _GetStrPatched(config, fb_key, buffer, BUF_SIZE))) {
      value = u8tow(buffer);
    } else if (fb_value) {
      value = *(T*)fb_value;
    }
  }
  if (func)
    func(value);
}

// Helper to iterate a Rime map and invoke callback with key/path
static void ForEachRimeMap(
    RimeConfig* config,
    const std::string& path,
    const std::function<void(const char* key, const char* child_path)>& cb) {
  RimeConfigIterator iter;
  if (!rime_api->config_begin_map(&iter, config, path.c_str()))
    return;
  while (rime_api->config_next(&iter)) {
    cb(iter.key, iter.path);
  }
  rime_api->config_end(&iter);
}

// Helper to iterate a Rime list and invoke callback with item path
static void ForEachRimeList(
    RimeConfig* config,
    const std::string& path,
    const std::function<void(const char* item_path)>& cb) {
  RimeConfigIterator iter;
  if (!rime_api->config_begin_list(&iter, config, path.c_str()))
    return;
  while (rime_api->config_next(&iter)) {
    cb(iter.path);
  }
  rime_api->config_end(&iter);
}

void RimeWithWeaselHandler::_UpdateShowNotifications(RimeConfig* config,
                                                     bool initialize) {
  Bool show_notifications = true;
  if (initialize)
    m_show_notifications_base.clear();
  m_show_notifications.clear();

  if (_GetBoolPatched(config, "show_notifications",
                      &show_notifications)) {
    // config read as bool, for global all on or off
    if (show_notifications)
      m_show_notifications["always"] = true;
    if (initialize)
      m_show_notifications_base = m_show_notifications;
  } else {
    // read as list using helper
    ForEachRimeList(config, "show_notifications", [&](const char* item_path) {
      char buffer[256] = {0};
      if (rime_api->config_get_string(config, item_path, buffer, 256))
        m_show_notifications[std::string(buffer)] = true;
    });
    if (initialize)
      m_show_notifications_base = m_show_notifications;
    if (m_show_notifications.empty()) {
      // not configured, or incorrect type
      if (initialize)
        m_show_notifications_base["always"] = true;
      m_show_notifications = m_show_notifications_base;
    }
  }
}

// Load style parameters from `config` into `style`. When `initialize` is true,
// unset values are replaced with defaults; otherwise existing values are kept.
// A non-empty `color_scheme` selects that scheme instead of the active one.
void LoadWeaselUIStyle(RimeConfig* config,
                       UIStyle& style,
                       bool initialize,
                       const std::string& color_scheme) {
  if (!rime_api)
    rime_api = rime_get_api();
  if (!rime_api || !config)
    return;
  const std::function<void(std::wstring&)> rmspace = [](std::wstring& str) {
    str = std::regex_replace(str, std::wregex(L"\\s*(,|:|^|$)\\s*"), L"$1");
  };
  const std::function<void(int&)> _abs = [](int& value) { value = abs(value); };
  // get font faces
  _RimeGetIntStr(config, "style/font_face", style.font_face, 0, 0, rmspace);
  std::wstring* const pFallbackFontFace = initialize ? &style.font_face : NULL;
  _RimeGetIntStr(config, "style/label_font_face", style.label_font_face, 0,
                 pFallbackFontFace, rmspace);
  _RimeGetIntStr(config, "style/comment_font_face", style.comment_font_face, 0,
                 pFallbackFontFace, rmspace);
  // able to set label font/comment font empty, force fallback to font face.
  if (style.label_font_face.empty())
    style.label_font_face = style.font_face;
  if (style.comment_font_face.empty())
    style.comment_font_face = style.font_face;
  // get font points
  _RimeGetIntStr(config, "style/font_point", style.font_point);
  if (style.font_point <= 0)
    style.font_point = 12;
  _RimeGetIntStr(config, "style/label_font_point", style.label_font_point,
                 "style/font_point", 0, _abs);
  _RimeGetIntStr(config, "style/comment_font_point", style.comment_font_point,
                 "style/font_point", 0, _abs);
  _RimeGetIntStr(config, "style/candidate_abbreviate_length",
                 style.candidate_abbreviate_length, 0, 0, _abs);
  _RimeGetBool(config, "style/inline_preedit", initialize,
               style.inline_preedit);
  _RimeGetBool(config, "style/vertical_auto_reverse", initialize,
               style.vertical_auto_reverse);
  static constexpr Array<UIStyle::PreeditType, 3> _preeditArr = {
      {{"composition", UIStyle::COMPOSITION},
       {"preview", UIStyle::PREVIEW},
       {"preview_all", UIStyle::PREVIEW_ALL}}};
  _RimeParseStringOptWithFallback(config, "style/preedit_type",
                                  style.preedit_type, _preeditArr,
                                  style.preedit_type);
  static constexpr Array<UIStyle::AntiAliasMode, 5> _aliasModeArr = {
      {{"force_dword", UIStyle::FORCE_DWORD},
       {"cleartype", UIStyle::CLEARTYPE},
       {"grayscale", UIStyle::GRAYSCALE},
       {"aliased", UIStyle::ALIASED},
       {"default", UIStyle::DEFAULT}}};
  _RimeParseStringOptWithFallback(config, "style/antialias_mode",
                                  style.antialias_mode, _aliasModeArr,
                                  style.antialias_mode);
  static constexpr Array<UIStyle::HoverType, 3> _hoverTypeArr = {
      {{"none", UIStyle::HoverType::NONE},
       {"semi_hilite", UIStyle::HoverType::SEMI_HILITE},
       {"hilite", UIStyle::HoverType::HILITE}}};
  _RimeParseStringOptWithFallback(config, "style/hover_type", style.hover_type,
                                  _hoverTypeArr, style.hover_type);
  static constexpr Array<UIStyle::LayoutAlignType, 3> _alignType = {
      {{"top", UIStyle::ALIGN_TOP},
       {"center", UIStyle::ALIGN_CENTER},
       {"bottom", UIStyle::ALIGN_BOTTOM}}};
  _RimeParseStringOptWithFallback(config, "style/layout/align_type",
                                  style.align_type, _alignType,
                                  style.align_type);
  _RimeGetBool(config, "style/display_tray_icon", initialize,
               style.display_tray_icon);
  _RimeGetBool(config, "style/ascii_tip_follow_cursor", initialize,
               style.ascii_tip_follow_cursor);
  _RimeGetBool(config, "style/horizontal", initialize, style.layout_type,
               UIStyle::LAYOUT_HORIZONTAL, UIStyle::LAYOUT_VERTICAL);
  _RimeGetBool(config, "style/paging_on_scroll", initialize,
               style.paging_on_scroll);
  _RimeGetBool(config, "style/click_to_capture", initialize,
               style.click_to_capture, true, false);
  bool fullscreen = false;
  _RimeGetBool(config, "style/fullscreen", false, fullscreen);
  bool vertical_text = false;
  _RimeGetBool(config, "style/vertical_text", false, vertical_text);
  if (vertical_text) {
    if (fullscreen) {
      style.layout_type = UIStyle::LAYOUT_VERTICAL_TEXT_FULLSCREEN;
    } else {
      style.layout_type = UIStyle::LAYOUT_VERTICAL_TEXT;
    }
  } else {
    if (fullscreen) {
      style.layout_type = (style.layout_type == UIStyle::LAYOUT_HORIZONTAL)
                              ? UIStyle::LAYOUT_HORIZONTAL_FULLSCREEN
                              : UIStyle::LAYOUT_VERTICAL_FULLSCREEN;
    }
  }
  _RimeGetBool(config, "style/vertical_text_left_to_right", false,
               style.vertical_text_left_to_right);
  _RimeGetBool(config, "style/vertical_text_with_wrap", false,
               style.vertical_text_with_wrap);
  _RimeGetBool(config, "style/vertical_right_to_left", initialize,
               style.vertical_right_to_left);
  static constexpr Array<bool, 2> _text_orientation = {
      {{"horizontal", false}, {"vertical", true}}};
  bool _text_orientation_bool = false;
  _RimeParseStringOptWithFallback(config, "style/text_orientation",
                                  _text_orientation_bool, _text_orientation,
                                  _text_orientation_bool);
  if (_text_orientation_bool) {
    if (fullscreen) {
      style.layout_type = UIStyle::LAYOUT_VERTICAL_TEXT_FULLSCREEN;
    } else {
      style.layout_type = UIStyle::LAYOUT_VERTICAL_TEXT;
    }
  }
  _RimeGetIntStr(config, "style/label_format", style.label_text_format);
  _RimeGetIntStr(config, "style/mark_text", style.mark_text);
  _RimeGetIntStr(config, "style/layout/baseline", style.baseline, 0, 0, _abs);
  _RimeGetIntStr(config, "style/layout/linespacing", style.linespacing, 0, 0,
                 _abs);
  _RimeGetIntStr(config, "style/layout/min_width", style.min_width, 0, 0, _abs);
  _RimeGetIntStr(config, "style/layout/max_width", style.max_width, 0, 0, _abs);
  _RimeGetIntStr(config, "style/layout/min_height", style.min_height, 0, 0,
                 _abs);
  _RimeGetIntStr(config, "style/layout/max_height", style.max_height, 0, 0,
                 _abs);
  // layout (alternative to style/horizontal)
  static constexpr Array<UIStyle::LayoutType, 6> _layoutArr = {
      {{"vertical", UIStyle::LAYOUT_VERTICAL},
       {"horizontal", UIStyle::LAYOUT_HORIZONTAL},
       {"vertical_text", UIStyle::LAYOUT_VERTICAL_TEXT},
       {"vertical+fullscreen", UIStyle::LAYOUT_VERTICAL_FULLSCREEN},
       {"horizontal+fullscreen", UIStyle::LAYOUT_HORIZONTAL_FULLSCREEN},
       {"vertical_text+fullscreen", UIStyle::LAYOUT_VERTICAL_TEXT_FULLSCREEN}}};
  _RimeParseStringOptWithFallback(config, "style/layout/type",
                                  style.layout_type, _layoutArr,
                                  style.layout_type);
  // Keep fullscreen vertical-text mode stable even when layout/type is also
  // set. Otherwise layout/type can override the earlier
  // fullscreen+vertical_text combination and cause unintended column wrapping
  // behavior.
  if (fullscreen && (vertical_text || _text_orientation_bool)) {
    style.layout_type = UIStyle::LAYOUT_VERTICAL_TEXT_FULLSCREEN;
  }
  // disable max_width when full screen
  if (style.layout_type == UIStyle::LAYOUT_HORIZONTAL_FULLSCREEN ||
      style.layout_type == UIStyle::LAYOUT_VERTICAL_FULLSCREEN) {
    style.max_width = 0;
    style.inline_preedit = false;
  }
  _RimeGetIntStr(config, "style/layout/border", style.border,
                 "style/layout/border_width", 0, _abs);
  _RimeGetIntStr(config, "style/layout/margin_x", style.margin_x);
  _RimeGetIntStr(config, "style/layout/margin_y", style.margin_y);
  _RimeGetIntStr(config, "style/layout/spacing", style.spacing, 0, 0, _abs);
  _RimeGetIntStr(config, "style/layout/candidate_spacing",
                 style.candidate_spacing, 0, 0, _abs);
  _RimeGetIntStr(config, "style/layout/hilite_spacing", style.hilite_spacing, 0,
                 0, _abs);
  _RimeGetIntStr(config, "style/layout/hilite_padding_x",
                 style.hilite_padding_x, "style/layout/hilite_padding", 0,
                 _abs);
  _RimeGetIntStr(config, "style/layout/hilite_padding_y",
                 style.hilite_padding_y, "style/layout/hilite_padding", 0,
                 _abs);
  _RimeGetIntStr(config, "style/layout/shadow_radius", style.shadow_radius, 0,
                 0, _abs);
  _RimeGetIntStr(config, "style/layout/shadow_offset_x", style.shadow_offset_x);
  _RimeGetIntStr(config, "style/layout/shadow_offset_y", style.shadow_offset_y);
  // round_corner as alias of hilited_corner_radius
  _RimeGetIntStr(config, "style/layout/hilited_corner_radius",
                 style.round_corner, "style/layout/round_corner", 0, _abs);
  // corner_radius not set, fallback to round_corner
  _RimeGetIntStr(config, "style/layout/corner_radius", style.round_corner_ex,
                 "style/layout/round_corner", 0, _abs);
  // fix padding and spacing settings
  if (style.layout_type != UIStyle::LAYOUT_VERTICAL_TEXT) {
    // hilite_padding vs spacing
    // if hilite_padding over spacing, increase spacing
    style.spacing = max(style.spacing, style.hilite_padding_y * 2);
    // hilite_padding vs candidate_spacing
    if (style.layout_type == UIStyle::LAYOUT_VERTICAL_FULLSCREEN ||
        style.layout_type == UIStyle::LAYOUT_VERTICAL) {
      // vertical, if hilite_padding_y over candidate spacing,
      // increase candidate spacing
      style.candidate_spacing =
          max(style.candidate_spacing, style.hilite_padding_y * 2);
    } else {
      // horizontal, if hilite_padding_x over candidate
      // spacing, increase candidate spacing
      style.candidate_spacing =
          max(style.candidate_spacing, style.hilite_padding_x * 2);
    }
    // hilite_padding_x vs hilite_spacing
    if (!style.inline_preedit)
      style.hilite_spacing = max(style.hilite_spacing, style.hilite_padding_x);
  } else  // LAYOUT_VERTICAL_TEXT
  {
    // hilite_padding_x vs spacing
    // if hilite_padding over spacing, increase spacing
    style.spacing = max(style.spacing, style.hilite_padding_x * 2);
    // hilite_padding vs candidate_spacing
    // if hilite_padding_x over candidate
    // spacing, increase candidate spacing
    style.candidate_spacing =
        max(style.candidate_spacing, style.hilite_padding_x * 2);
    // vertical_text_with_wrap and hilite_padding_y over candidate_spacing
    if (style.vertical_text_with_wrap)
      style.candidate_spacing =
          max(style.candidate_spacing, style.hilite_padding_y * 2);
    // hilite_padding_y vs hilite_spacing
    if (!style.inline_preedit)
      style.hilite_spacing = max(style.hilite_spacing, style.hilite_padding_y);
  }
  if (style.layout_type == UIStyle::LAYOUT_VERTICAL_TEXT_FULLSCREEN) {
    style.max_height = 0;
  }
  // fix padding and margin settings
  int scale = style.margin_x < 0 ? -1 : 1;
  style.margin_x = scale * max(style.hilite_padding_x, abs(style.margin_x));
  scale = style.margin_y < 0 ? -1 : 1;
  style.margin_y = scale * max(style.hilite_padding_y, abs(style.margin_y));
  // get enhanced_position
  _RimeGetBool(config, "style/enhanced_position", initialize,
               style.enhanced_position, true, false);
  // get color scheme
  const int BUF_SIZE = 255;
  char buffer[BUF_SIZE + 1] = {0};
  if ((initialize && _GetStrPatched(config, "style/color_scheme",
                                                 buffer, BUF_SIZE)) ||
      !color_scheme.empty())
    _UpdateUIStyleColor(config, style, color_scheme);
}

void LoadWeaselUIStyleWithPatch(RimeConfig* config, RimeConfig* user_patch,
                               UIStyle& style) {
  struct PatchScope {
    RimeConfig* previous;
    ~PatchScope() { g_user_patch = previous; }
  } scope{g_user_patch};
  g_user_patch = user_patch;
  LoadWeaselUIStyle(config, style, true);
}

static void _UpdateUIStyle(RimeConfig* config, UI* ui, bool initialize) {
  LoadWeaselUIStyle(config, ui->style(), initialize);
}
// load color configs to style, by "style/color_scheme" or specific scheme name
// "color" which is default empty
static bool _UpdateUIStyleColor(RimeConfig* config,
                                UIStyle& style,
                                const std::string& color) {
  if (!rime_api)
    rime_api = rime_get_api();
  if (!rime_api || !config)
    return false;
  const int BUF_SIZE = 255;
  char buffer[BUF_SIZE + 1] = {0};
  std::string color_mark = "style/color_scheme";
  // color scheme
  if (_GetStrPatched(config, color_mark.c_str(), buffer,
                                  BUF_SIZE) ||
      !color.empty()) {
    std::string prefix("preset_color_schemes/");
    prefix += (color.empty()) ? buffer : color;
    // define color format, default abgr if not set
    ColorFormat fmt = COLOR_ABGR;
    static constexpr Array<ColorFormat, 3> _colorFmt = {
        {{"argb", COLOR_ARGB}, {"rgba", COLOR_RGBA}, {"abgr", COLOR_ABGR}}};
    _RimeParseStringOptWithFallback(config, (prefix + "/color_format").c_str(),
                                    fmt, _colorFmt, COLOR_ABGR);
#define COLOR(key, value, fallback) \
  _RimeGetColor(config, (prefix + "/" + key), value, fmt, fallback)
    COLOR("back_color", style.back_color, 0xffffffff);
    COLOR("shadow_color", style.shadow_color, 0);
    COLOR("prevpage_color", style.prevpage_color, 0);
    COLOR("nextpage_color", style.nextpage_color, 0);
    COLOR("text_color", style.text_color, 0xff000000);
    COLOR("candidate_text_color", style.candidate_text_color, style.text_color);
    COLOR("candidate_back_color", style.candidate_back_color, 0);
    COLOR("border_color", style.border_color, style.text_color);
    COLOR("hilited_text_color", style.hilited_text_color, style.text_color);
    COLOR("hilited_back_color", style.hilited_back_color, style.back_color);
    COLOR("hilited_candidate_text_color", style.hilited_candidate_text_color,
          style.hilited_text_color);
    COLOR("hilited_candidate_back_color", style.hilited_candidate_back_color,
          style.hilited_back_color);
    COLOR("hilited_candidate_shadow_color",
          style.hilited_candidate_shadow_color, 0);
    COLOR("hilited_shadow_color", style.hilited_shadow_color, 0);
    COLOR("candidate_shadow_color", style.candidate_shadow_color, 0);
    COLOR("candidate_border_color", style.candidate_border_color, 0);
    COLOR("hilited_candidate_border_color",
          style.hilited_candidate_border_color, 0);
    COLOR("label_color", style.label_text_color,
          blend_colors(style.candidate_text_color, style.candidate_back_color));
    COLOR("hilited_label_color", style.hilited_label_text_color,
          blend_colors(style.hilited_candidate_text_color,
                       style.hilited_candidate_back_color));
    COLOR("comment_text_color", style.comment_text_color,
          style.label_text_color);
    COLOR("hilited_comment_text_color", style.hilited_comment_text_color,
          style.hilited_label_text_color);
    COLOR("hilited_mark_color", style.hilited_mark_color, 0);
#undef COLOR
    return true;
  }
  return false;
}
static void _LoadAppOptions(RimeConfig* config,
                            AppOptionsByAppName& app_options) {
  app_options.clear();
  ForEachRimeMap(
      config, "app_options", [&](const char* app_key, const char* app_path) {
        AppOptions& options(app_options[app_key]);
        ForEachRimeMap(
            config, app_path, [&](const char* opt_key, const char* opt_path) {
              Bool value = False;
              if (rime_api->config_get_bool(config, opt_path, &value)) {
                options[opt_key] = !!value;
              }
            });
      });
}

void RimeWithWeaselHandler::_GetStatus(Status& stat,
                                       WeaselSessionId ipc_id,
                                       Context& ctx) {
  SessionStatus& session_status = get_session_status(ipc_id);
  RimeSessionId session_id = session_status.session_id;
  RIME_STRUCT(RimeStatus, status);
  if (rime_api->get_status(session_id, &status)) {
    std::string schema_id = "";
    if (status.schema_id)
      schema_id = status.schema_id;
    stat.schema_name = u8tow(status.schema_name);
    stat.schema_id = u8tow(status.schema_id);
    stat.ascii_mode = !!status.is_ascii_mode;
    stat.composing = !!status.is_composing;
    stat.disabled = !!status.is_disabled;
    stat.full_shape = !!status.is_full_shape;
    if (schema_id != m_last_schema_id) {
      session_status.__synced = false;
      m_last_schema_id = schema_id;
      if (schema_id != ".default") {  // don't load for schema select menu
        bool inline_preedit = session_status.style.inline_preedit;
        _LoadSchemaSpecificSettings(ipc_id, schema_id);
        _LoadAppInlinePreeditSet(ipc_id, true);
        if (session_status.style.inline_preedit != inline_preedit)
          // in case of inline_preedit set in schema
          _UpdateInlinePreeditStatus(ipc_id);
        // refresh icon after schema changed
        _RefreshTrayIcon(session_id, _UpdateUICallback);
        m_ui->style() = session_status.style;
        if (m_show_notifications.find("schema") != m_show_notifications.end() &&
            m_show_notifications_time > 0) {
          ctx.aux.str = stat.schema_name;
          m_ui->Update(ctx, stat);
          m_ui->ShowWithTimeout(m_show_notifications_time);
        }
      }
    }
    rime_api->free_status(&status);
  }
}

void RimeWithWeaselHandler::_GetContext(Context& weasel_context,
                                        RimeSessionId session_id) {
  RIME_STRUCT(RimeContext, ctx);
  if (rime_api->get_context(session_id, &ctx)) {
    if (ctx.composition.length > 0) {
      weasel_context.preedit.str = u8tow(ctx.composition.preedit);
      if (ctx.composition.sel_start < ctx.composition.sel_end) {
        TextAttribute attr;
        attr.type = HIGHLIGHTED;
        attr.range.start =
            utf8towcslen(ctx.composition.preedit, ctx.composition.sel_start);
        attr.range.end =
            utf8towcslen(ctx.composition.preedit, ctx.composition.sel_end);

        weasel_context.preedit.attributes.push_back(attr);
      }
    }
    if (ctx.menu.num_candidates) {
      // 候选调序：先按 shadow 规则重排，再把结果交给 UI。
      // 必须在 _GetCandidateInfo 之前做 —— 那个函数按数组顺序生成候选与标签。
      RIME_STRUCT(RimeStatus, st);
      std::string schema_id;
      if (rime_api->get_status(session_id, &st)) {
        if (st.schema_id)
          schema_id = st.schema_id;
        rime_api->free_status(&st);
      }
      _LoadShadowForSession(session_id, schema_id);
      const std::string code = _CurrentCode(ctx);
      std::vector<int> order = _ApplyShadow(schema_id, code, ctx);
      {
        std::lock_guard<std::mutex> lock(m_page_mutex);
        m_page_code[session_id] = code;
        m_page_order[session_id] = std::move(order);
      }
      CandidateInfo& cinfo(weasel_context.cinfo);
      _GetCandidateInfo(cinfo, ctx);
    }
    rime_api->free_context(&ctx);
  }
}

void RimeWithWeaselHandler::_UpdateInlinePreeditStatus(WeaselSessionId ipc_id) {
  if (!m_ui)
    return;
  SessionStatus& session_status = get_session_status(ipc_id);
  RimeSessionId session_id = session_status.session_id;
  // set inline_preedit option
  bool inline_preedit = session_status.style.inline_preedit;
  rime_api->set_option(session_id, "inline_preedit", Bool(inline_preedit));
  // show soft cursor on weasel panel but not inline
  rime_api->set_option(session_id, "soft_cursor", Bool(!inline_preedit));
}
