// 青石五笔 IMM32 兼容层（weasel.ime）
//
// 为采用旧式 IMM32 输入接口的宿主提供原生 .ime 入口。
// Windows 也可能通过 IMM/TSF 桥接；是否需要此层应以宿主诊断为准。
//
// 这一层刻意做得很薄：候选窗本来就在 WeaselServer.exe 里画，这里只做三件事
//   1) 把按键翻译成 Rime 的 KeyEvent，通过现有 IPC 发给服务；
//   2) 把上屏文字以 GCS_RESULTSTR 交给应用；
//   3) 上报插入点，让服务端的候选窗出现在光标附近。
//
// 安全原则：只有在服务确实吃下这个按键时才返回 TRUE。任何环节出问题都退化成
// “按键照常交给应用”，绝不会比没有这个输入法更糟。

#include <windows.h>
#include <imm.h>
#include <immdev.h>
#include <msctf.h>
#include <shellapi.h>

#include <atomic>
#include <chrono>
#include <functional>
#include <iomanip>
#include <map>
#include <sstream>
#include <string>

#include "KeyEvent.h"
#include "ResponseParser.h"
#include "WeaselIPC.h"
#include "ImmResult.h"
#include "../WeaselTSF/QingshiDiag.h"

#pragma comment(lib, "imm32.lib")

namespace {

HINSTANCE g_instance = nullptr;
CRITICAL_SECTION g_lock;
bool g_lock_ready = false;
std::map<HIMC, struct ImeContext*> g_contexts;

struct ImeContext {
  weasel::Client client;
  bool connected = false;
  bool session = false;
  std::wstring commit;
  bool composing = false;
};

LRESULT CALLBACK ImeUiProc(HWND window, UINT message, WPARAM wparam,
                           LPARAM lparam) {
  // Rendering lives in WeaselServer. Do not send IME messages back through
  // DefWindowProc: that forwards them to this very UI window again.
  if ((message >= WM_IME_STARTCOMPOSITION && message <= WM_IME_COMPOSITION) ||
      (message >= WM_IME_SETCONTEXT && message <= WM_IME_KEYUP))
    return 0;
  return ::DefWindowProcW(window, message, wparam, lparam);
}

bool RegisterUiClass() {
  WNDCLASSEXW existing{sizeof(existing)};
  if (::GetClassInfoExW(g_instance, L"QingshiImeUi", &existing))
    return true;
  WNDCLASSEXW wc{sizeof(wc)};
  wc.style = CS_IME;
  wc.lpfnWndProc = ImeUiProc;
  wc.cbWndExtra = 2 * sizeof(LONG_PTR);
  wc.hInstance = g_instance;
  wc.lpszClassName = L"QingshiImeUi";
  return ::RegisterClassExW(&wc) != 0;
}

bool LaunchServer() {
  std::wstring root;
  if (RegGetStringValue(HKEY_LOCAL_MACHINE, L"Software\\Rime\\Weasel",
                        L"WeaselRoot", root) != ERROR_SUCCESS ||
      root.empty())
    return false;
  std::wstring launcher = root + L"\\start_service.bat";
  if (::GetFileAttributesW(launcher.c_str()) == INVALID_FILE_ATTRIBUTES)
    return false;
  return reinterpret_cast<INT_PTR>(::ShellExecuteW(nullptr, L"open",
                                                  launcher.c_str(), nullptr,
                                                  root.c_str(), SW_HIDE)) > 32;
}

ImeContext* Find(HIMC himc) {
  if (!g_lock_ready || !himc)
    return nullptr;
  ::EnterCriticalSection(&g_lock);
  auto it = g_contexts.find(himc);
  ImeContext* ctx = it == g_contexts.end() ? nullptr : it->second;
  ::LeaveCriticalSection(&g_lock);
  return ctx;
}

ImeContext* Ensure(HIMC himc) {
  ImeContext* ctx = Find(himc);
  if (!ctx || !himc)
    return ctx;
  if (ctx->connected && !ctx->client.Echo()) {
    ctx->client.Disconnect();
    ctx->connected = ctx->session = false;
  }
  if (!ctx->connected) {
    ctx->connected = ctx->client.Connect(&LaunchServer);
    if (ctx->connected) {
      ctx->client.StartSession();
      ctx->session = ctx->client.Echo();
      ctx->connected = ctx->session;
      if (!ctx->session)
        ctx->client.Disconnect();
      qingshi::diag::Log(L"IME: connected to server");
    } else {
      qingshi::diag::Log(L"IME: server connect failed");
    }
  }
  return ctx;
}

void ReportCaret(ImeContext* ctx) {
  RECT rc{};
  GUITHREADINFO info{sizeof(info)};
  if (::GetGUIThreadInfo(::GetCurrentThreadId(), &info) && info.hwndCaret) {
    POINT top_left{info.rcCaret.left, info.rcCaret.top};
    POINT bottom_right{info.rcCaret.right, info.rcCaret.bottom};
    ::ClientToScreen(info.hwndCaret, &top_left);
    ::ClientToScreen(info.hwndCaret, &bottom_right);
    rc = {top_left.x, top_left.y, bottom_right.x, bottom_right.y};
  }
  if (rc.right == rc.left && rc.bottom == rc.top) {
    HWND foreground = ::GetForegroundWindow();
    RECT window{};
    if (foreground && ::GetWindowRect(foreground, &window)) {
      rc.left = window.left + 40;
      rc.top = window.top + 80;
      rc.right = rc.left;
      rc.bottom = rc.top + 24;
    }
  }
  if (rc.bottom > rc.top)
    ctx->client.UpdateInputPosition(rc);
}

}  // namespace

// ---------------------------------------------------------------------------
// IME 导出函数
// ---------------------------------------------------------------------------

extern "C" BOOL WINAPI ImeInquire(LPIMEINFO info,
                                  LPWSTR ui_class,
                                  DWORD system_info_flags) {
  if (!info || !ui_class || !RegisterUiClass())
    return FALSE;
  *info = {};
  wcsncpy_s(ui_class, IME_UI_CLASS_NAME_SIZE, L"QingshiImeUi", _TRUNCATE);
  info->dwPrivateDataSize = 0;
  // UNICODE：应用收到的是宽字符；AT_CARET：组合串画在插入点。
  // 不声明 SPECIAL_UI，走系统标准的组合串流程，兼容性最好。
  info->fdwProperty = IME_PROP_UNICODE | IME_PROP_AT_CARET;
  info->fdwConversionCaps = IME_CMODE_NATIVE | IME_CMODE_FULLSHAPE;
  info->fdwSentenceCaps = IME_SMODE_NONE;
  info->fdwUICaps = UI_CAP_2700;
  info->fdwSCSCaps = 0;
  info->fdwSelectCaps = SELECT_CAP_CONVERSION | SELECT_CAP_SENTENCE;
  qingshi::diag::Log(L"IME: ImeInquire");
  return TRUE;
}

extern "C" BOOL WINAPI ImeConfigure(HKL hkl,
                                    HWND window,
                                    DWORD mode,
                                    LPVOID data) {
  return FALSE;
}

extern "C" DWORD WINAPI ImeConversionList(HIMC himc,
                                          LPCWSTR source,
                                          LPCANDIDATELIST destination,
                                          DWORD length,
                                          UINT flags) {
  return 0;
}

extern "C" BOOL WINAPI ImeRegisterWord(LPCWSTR reading,
                                       DWORD style,
                                       LPCWSTR text) {
  return FALSE;
}

extern "C" BOOL WINAPI ImeUnregisterWord(LPCWSTR reading,
                                         DWORD style,
                                         LPCWSTR text) {
  return FALSE;
}

extern "C" UINT WINAPI ImeGetRegisterWordStyle(UINT count, LPSTYLEBUF buffer) {
  return 0;
}

extern "C" UINT WINAPI ImeEnumRegisterWord(REGISTERWORDENUMPROC callback,
                                           LPCWSTR reading,
                                           DWORD style,
                                           LPCWSTR text,
                                           LPVOID data) {
  return 0;
}

extern "C" BOOL WINAPI ImeSelect(HIMC himc, BOOL select) {
  if (!g_lock_ready || !himc)
    return FALSE;
  if (select) {
    auto* input = ::ImmLockIMC(himc);
    if (!input)
      return FALSE;
    if (!(input->fdwInit & INIT_CONVERSION)) {
      input->fdwConversion = IME_CMODE_NATIVE;
      input->fdwInit |= INIT_CONVERSION;
    }
    if (!Find(himc))
      input->fOpen = TRUE;
    ::ImmUnlockIMC(himc);
  }
  ::EnterCriticalSection(&g_lock);
  auto it = g_contexts.find(himc);
  if (select) {
    if (it == g_contexts.end()) {
      auto* ctx = new ImeContext();
      g_contexts[himc] = ctx;
      it = g_contexts.find(himc);
    }
  } else if (it != g_contexts.end()) {
    ImeContext* ctx = it->second;
    g_contexts.erase(it);
    ::LeaveCriticalSection(&g_lock);
    if (ctx->session)
      ctx->client.EndSession();
    delete ctx;
    qingshi::diag::Log(L"IME: ImeSelect(FALSE)");
    return TRUE;
  }
  ::LeaveCriticalSection(&g_lock);
  qingshi::diag::Log(L"IME: ImeSelect(%d)", select ? 1 : 0);
  return TRUE;
}

extern "C" BOOL WINAPI ImeSetActiveContext(HIMC himc, BOOL active) {
  ImeContext* ctx = Find(himc);
  if (!ctx)
    return FALSE;
  if (active)
    Ensure(himc);
  if (active && ctx->session)
    ctx->client.FocusIn();
  else
    ctx->client.FocusOut();
  return TRUE;
}

extern "C" BOOL WINAPI ImeProcessKey(HIMC himc,
                                     UINT vkey,
                                     LPARAM lparam,
                                     const LPBYTE key_state) {
  if (!key_state || !::ImmGetOpenStatus(himc))
    return FALSE;
  ImeContext* ctx = Ensure(himc);
  if (!ctx || !ctx->connected)
    return FALSE;

  weasel::KeyEvent key_event;
  if (!ConvertKeyEvent(vkey, KeyInfo(lparam), key_state, key_event))
    return FALSE;

  ctx->commit.clear();
  const bool eaten = ctx->client.ProcessKeyEvent(key_event);

  weasel::Context context;
  weasel::Status status;
  weasel::UIStyle style;
  weasel::ResponseParser parser(&ctx->commit, &context, &status, nullptr,
                                &style);
  // Even declined keys have response data (mode changes, status and commits).
  if (!ctx->client.GetResponseData(std::ref(parser))) {
    ctx->connected = ctx->session = false;
    ctx->client.Disconnect();
    return FALSE;
  }
  ctx->composing = status.composing;
  ReportCaret(ctx);
  qingshi::diag::Log(
      L"IME key vk=0x%02X commit=%zu composing=%d cand=%zu", vkey,
      ctx->commit.size(), status.composing ? 1 : 0,
      context.cinfo.candies.size());
  return eaten ? TRUE : FALSE;
}

extern "C" UINT WINAPI ImeToAsciiEx(UINT vkey,
                                    UINT scan_code,
                                    const LPBYTE key_state,
                                    LPTRANSMSGLIST trans_buf,
                                    UINT state,
                                    HIMC himc) {
  ImeContext* ctx = Find(himc);
  if (!ctx || ctx->commit.empty())
    return 0;

  if (!trans_buf)
    return 0;
  // ImmSetCompositionString calls the IME's ImeSetCompositionString export;
  // it does not populate GCS_RESULTSTR for us. Write IMM's result block here.
  const UINT count = qingshi::imm::CommitResult(himc, ctx->commit, trans_buf);
  if (count) {
    qingshi::diag::Log(L"IME: commit %zu UTF-16 units messages=%u",
                       ctx->commit.size(), count);
    ctx->commit.clear();
  }
  return count;
}

extern "C" BOOL WINAPI NotifyIME(HIMC himc,
                                 DWORD action,
                                 DWORD index,
                                 DWORD value) {
  ImeContext* ctx = Find(himc);
  if (!ctx)
    return FALSE;
  switch (action) {
    case NI_COMPOSITIONSTR:
      if (index == CPS_CANCEL) {
        ctx->commit.clear();
        ctx->client.ClearComposition();
        ctx->composing = false;
        return TRUE;
      }
      if (index == CPS_COMPLETE && ctx->session) {
        ctx->client.CommitComposition();
        weasel::Context context;
        weasel::Status status;
        weasel::ResponseParser parser(&ctx->commit, &context, &status);
        if (!ctx->client.GetResponseData(std::ref(parser)))
          return FALSE;
        ctx->composing = status.composing;
        if (ctx->commit.empty())
          return TRUE;
        if (!qingshi::imm::CommitResult(himc, ctx->commit, nullptr))
          return FALSE;
        ctx->commit.clear();
        return ::ImmGenerateMessage(himc);
      }
      return FALSE;
    case NI_OPENCANDIDATE:
    case NI_CLOSECANDIDATE:
      return TRUE;
    default:
      return FALSE;
  }
}

extern "C" LRESULT WINAPI ImeEscape(HIMC himc, UINT sub_function, LPVOID data) {
  return 0;
}

// Required IMM entry points. External composition replacement is unsupported;
// returning FALSE lets the application use its normal fallback.
extern "C" BOOL WINAPI ImeSetCompositionString(HIMC, DWORD, LPVOID, DWORD,
                                                LPVOID, DWORD) {
  return FALSE;
}

extern "C" BOOL WINAPI ImeDestroy(UINT) {
  std::map<HIMC, ImeContext*> contexts;
  if (g_lock_ready) {
    ::EnterCriticalSection(&g_lock);
    contexts.swap(g_contexts);
    ::LeaveCriticalSection(&g_lock);
  }
  // ImeDestroy is called outside DllMain, so IPC teardown is safe here.
  for (const auto& entry : contexts)
    delete entry.second;
  ::UnregisterClassW(L"QingshiImeUi", g_instance);
  return TRUE;
}

// ---------------------------------------------------------------------------
// DLL 入口
// ---------------------------------------------------------------------------

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
  switch (reason) {
    case DLL_PROCESS_ATTACH:
      g_instance = instance;
      ::InitializeCriticalSection(&g_lock);
      g_lock_ready = true;
      ::DisableThreadLibraryCalls(instance);
      break;
    case DLL_PROCESS_DETACH:
      if (g_lock_ready) {
        // Never wait on another process from the loader lock. ImeSelect(FALSE)
        // releases normal sessions; process teardown reclaims remaining memory.
        ::DeleteCriticalSection(&g_lock);
        g_lock_ready = false;
      }
      break;
  }
  return TRUE;
}
