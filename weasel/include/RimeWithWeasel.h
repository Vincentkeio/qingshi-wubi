#pragma once
#include <WeaselIPC.h>
#include <WeaselUI.h>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <vector>

#include <rime_api.h>

struct CaseInsensitiveCompare {
  bool operator()(const std::string& str1, const std::string& str2) const {
    std::string str1Lower, str2Lower;
    std::transform(str1.begin(), str1.end(), std::back_inserter(str1Lower),
                   [](char c) { return std::tolower(c); });
    std::transform(str2.begin(), str2.end(), std::back_inserter(str2Lower),
                   [](char c) { return std::tolower(c); });
    return str1Lower < str2Lower;
  }
};

typedef std::map<std::string, bool> AppOptions;
typedef std::map<std::string, AppOptions, CaseInsensitiveCompare>
    AppOptionsByAppName;

struct SessionStatus {
  SessionStatus() : style(weasel::UIStyle()), __synced(false), session_id(0) {
    RIME_STRUCT(RimeStatus, status);
  }
  weasel::UIStyle style;
  RimeStatus status;
  bool __synced;
  RimeSessionId session_id;
};
typedef std::map<DWORD, SessionStatus> SessionStatusMap;
typedef DWORD WeaselSessionId;

void LoadWeaselUIStyle(RimeConfig* config,
                       weasel::UIStyle& style,
                       bool initialize = true,
                       const std::string& color_scheme = std::string());
void LoadWeaselUIStyleWithPatch(RimeConfig* config, RimeConfig* user_patch,
                               weasel::UIStyle& style);

class RimeWithWeaselHandler : public weasel::RequestHandler {
 public:
  RimeWithWeaselHandler(weasel::UI* ui);
  virtual ~RimeWithWeaselHandler();
  virtual void Initialize();
  virtual void Finalize();
  virtual DWORD FindSession(WeaselSessionId ipc_id);
  virtual DWORD AddSession(LPWSTR buffer, EatLine eat = 0);
  virtual DWORD RemoveSession(WeaselSessionId ipc_id);
  virtual BOOL ProcessKeyEvent(weasel::KeyEvent keyEvent,
                               WeaselSessionId ipc_id,
                               EatLine eat);
  virtual void CommitComposition(WeaselSessionId ipc_id);
  virtual void ClearComposition(WeaselSessionId ipc_id);
  virtual void SelectCandidateOnCurrentPage(size_t index,
                                            WeaselSessionId ipc_id);
  virtual bool HighlightCandidateOnCurrentPage(size_t index,
                                               WeaselSessionId ipc_id,
                                               EatLine eat);
  virtual bool ChangePage(bool backward, WeaselSessionId ipc_id, EatLine eat);
  virtual void FocusIn(DWORD param, WeaselSessionId ipc_id);
  virtual void FocusOut(DWORD param, WeaselSessionId ipc_id);
  virtual void UpdateInputPosition(RECT const& rc, WeaselSessionId ipc_id);
  virtual void StartMaintenance();
  virtual void EndMaintenance();
  virtual void SetOption(WeaselSessionId ipc_id,
                         const std::string& opt,
                         bool val);
  virtual void UpdateColorTheme(BOOL darkMode);
  // 重读用户配置（不部署）：外观、按键、候选数、标点、主题、候选调序表。
  virtual bool ReloadConfig();
  // 候选调序：置顶 / 撤置顶 / 移到末位。改动立即落盘并刷新当前会话。
  virtual bool AdjustShadow(int action,
                            size_t index,
                            WeaselSessionId ipc_id,
                            EatLine eat = 0);

  void OnUpdateUI(std::function<void()> const& cb);

 private:
  void _Setup();
  bool _IsDeployerRunning();
  void _UpdateUI(WeaselSessionId ipc_id);
  void _LoadSchemaSpecificSettings(WeaselSessionId ipc_id,
                                   const std::string& schema_id);
  void _LoadAppInlinePreeditSet(WeaselSessionId ipc_id,
                                bool ignore_app_name = false);
  bool _ShowMessage(weasel::Context& ctx, weasel::Status& status);
  bool _Respond(WeaselSessionId ipc_id, EatLine eat);
  void _ReadClientInfo(WeaselSessionId ipc_id, LPWSTR buffer);
  void _GetCandidateInfo(weasel::CandidateInfo& cinfo, RimeContext& ctx);
  void _GetStatus(weasel::Status& stat,
                  WeaselSessionId ipc_id,
                  weasel::Context& ctx);
  void _GetContext(weasel::Context& ctx, RimeSessionId session_id);
  void _UpdateShowNotifications(RimeConfig* config, bool initialize = false);

  void _UpdateInlinePreeditStatus(WeaselSessionId ipc_id);

  // ── 四码无候选提示音 ────────────────────────────────────────────
  // 五笔打满 4 码却一个字都出不来，基本是打错了。响一声提醒，但不打断输入。
  // 开关在 HKCU\Software\Rime\Weasel\QingshiBeepOnNoCandidate，缺省视为开启。
  void _BeepIfNoCandidate(RimeSessionId session_id);
  static bool _NoCandidateBeepEnabled();
  std::string m_beeped_code;  // 已经响过的编码，同一个码不重复响

  // ── 四码唯一自动上屏 ────────────────────────────────────────────
  // 打满 4 码只剩一个候选时直接上屏，省掉一次空格。
  // 只认「正好 4 码 + 唯一候选」，简码（1-3 码）不动 —— 简码上屏会毁掉
  // 五笔「先出编码再决定」的习惯，也容易把简码词误上屏。
  // 开关在 HKCU\Software\Rime\Weasel\QingshiAutoCommitUnique，**缺省关闭**：
  // 自动上屏会改变输入节奏，要用户显式打开。
  bool _AutoCommitUniqueCode(RimeSessionId session_id);
  static bool _UniqueCodeAutoCommitEnabled();

  // ── 候选调序（shadow 层）─────────────────────────────────────────
  // 规则存在 %APPDATA%\QingshiWubi\shadow\<方案>.yaml，**不改原词库**，
  // 也不触发部署；候选装配完在最后应用，所以压得住词频重排。
  void _LoadShadow(const std::string& schema_id);
  bool _SaveShadow(const std::string& schema_id);
  // 返回「显示位置 → 原始索引」的映射；空表示没有规则命中。
  std::vector<int> _ApplyShadow(const std::string& schema_id,
                                const std::string& code,
                                RimeContext& ctx);
  // 从 RimeContext 里取当前输入串（五笔就是编码）。
  static std::string _CurrentCode(RimeContext& ctx);
  void _LoadShadowForSession(RimeSessionId session_id, const std::string& schema_id);
  // 界面上的序号是重排后的，送回引擎前要换回原始索引。
  size_t _ToOriginalIndex(WeaselSessionId ipc_id, size_t display_index);

  RimeSessionId to_session_id(WeaselSessionId ipc_id) {
    return m_session_status_map[ipc_id].session_id;
  }
  SessionStatus& get_session_status(WeaselSessionId ipc_id) {
    return m_session_status_map[ipc_id];
  }
  SessionStatus& new_session_status(WeaselSessionId ipc_id) {
    return m_session_status_map[ipc_id] = SessionStatus();
  }

  AppOptionsByAppName m_app_options;
  weasel::UI* m_ui;  // reference
  DWORD m_active_session;
  bool m_disabled;
  std::string m_last_schema_id;
  std::string m_last_app_name;
  weasel::UIStyle m_base_style;
  std::map<std::string, bool> m_show_notifications;
  std::map<std::string, bool> m_show_notifications_base;
  std::function<void()> _UpdateUICallback;

  static void OnNotify(void* context_object,
                       uintptr_t session_id,
                       const char* message_type,
                       const char* message_value);
  static std::string m_message_type;
  static std::string m_message_value;
  static std::string m_message_label;
  static std::string m_option_name;
  static std::mutex m_notifier_mutex;
  SessionStatusMap m_session_status_map;
  bool m_current_dark_mode;
  bool m_global_ascii_mode;
  int m_show_notifications_time;
  DWORD m_pid;

  // ── 候选调序 ────────────────────────────────────────────────
  // 编码 → 置顶词（按顺序）。一个方案一份。
  typedef std::map<std::string, std::vector<std::string>> ShadowRules;
  std::map<std::string, ShadowRules> m_shadow;      // schema_id → 规则
  std::set<std::string> m_shadow_loaded;            // 已从磁盘读过的方案
  // 最近一次交给 UI 的顺序：显示位置 → 原始索引。选择/高亮时换回去，
  // 否则用户按 1 选中的会是重排前的第一个候选。
  std::map<RimeSessionId, std::vector<int>> m_page_order;
  std::map<RimeSessionId, std::string> m_page_code;
  std::mutex m_shadow_mutex;
  std::mutex m_page_mutex;
};
