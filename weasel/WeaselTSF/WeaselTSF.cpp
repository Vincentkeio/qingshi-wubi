#include "stdafx.h"

#include <WeaselIPCData.h>
#include <thread>
#include <shellapi.h>
#include <tlhelp32.h>
#include "WeaselTSF.h"
#include "CandidateList.h"
#include "LanguageBar.h"
#include "Compartment.h"
#include "QingshiDiag.h"
#include "ResponseParser.h"

static void error_message(const WCHAR* msg) {
  static DWORD next_tick = 0;
  DWORD now = GetTickCount();
  if (now > next_tick) {
    next_tick = now + 10000;  // (ms)
    MessageBox(NULL, msg, get_weasel_ime_name().c_str(), MB_ICONERROR | MB_OK);
  }
}

WeaselTSF::WeaselTSF() {
  _cRef = 1;

  _dwThreadMgrEventSinkCookie = TF_INVALID_COOKIE;

  _dwTextEditSinkCookie = TF_INVALID_COOKIE;
  _dwTextLayoutSinkCookie = TF_INVALID_COOKIE;
  _dwThreadFocusSinkCookie = TF_INVALID_COOKIE;
  _fTestKeyDownPending = FALSE;
  _fTestKeyUpPending = FALSE;

  _fCUASWorkaroundTested = _fCUASWorkaroundEnabled = FALSE;

  _cand = new CCandidateList(this);

  DllAddRef();
}

WeaselTSF::~WeaselTSF() {
  DllRelease();
}

STDMETHODIMP WeaselTSF::QueryInterface(REFIID riid, void** ppvObject) {
  if (ppvObject == NULL)
    return E_INVALIDARG;

  *ppvObject = NULL;

  if (IsEqualIID(riid, IID_IUnknown) ||
      IsEqualIID(riid, IID_ITfTextInputProcessor))
    *ppvObject = (ITfTextInputProcessor*)this;
  else if (IsEqualIID(riid, IID_ITfTextInputProcessorEx))
    *ppvObject = (ITfTextInputProcessorEx*)this;
  else if (IsEqualIID(riid, IID_ITfThreadMgrEventSink))
    *ppvObject = (ITfThreadMgrEventSink*)this;
  else if (IsEqualIID(riid, IID_ITfTextEditSink))
    *ppvObject = (ITfTextEditSink*)this;
  else if (IsEqualIID(riid, IID_ITfTextLayoutSink))
    *ppvObject = (ITfTextLayoutSink*)this;
  else if (IsEqualIID(riid, IID_ITfKeyEventSink))
    *ppvObject = (ITfKeyEventSink*)this;
  else if (IsEqualIID(riid, IID_ITfCompositionSink))
    *ppvObject = (ITfCompositionSink*)this;
  else if (IsEqualIID(riid, IID_ITfEditSession))
    *ppvObject = (ITfEditSession*)this;
  else if (IsEqualIID(riid, IID_ITfThreadFocusSink))
    *ppvObject = (ITfThreadFocusSink*)this;
  else if (IsEqualIID(riid, IID_ITfDisplayAttributeProvider))
    *ppvObject = (ITfDisplayAttributeProvider*)this;

  if (*ppvObject) {
    AddRef();
    return S_OK;
  }
  return E_NOINTERFACE;
}

STDMETHODIMP_(ULONG) WeaselTSF::AddRef() {
  return ++_cRef;
}

STDMETHODIMP_(ULONG) WeaselTSF::Release() {
  LONG cr = --_cRef;

  assert(_cRef >= 0);

  if (_cRef == 0)
    delete this;

  return cr;
}

STDMETHODIMP WeaselTSF::Activate(ITfThreadMgr* pThreadMgr,
                                 TfClientId tfClientId) {
  return ActivateEx(pThreadMgr, tfClientId, 0U);
}

STDMETHODIMP WeaselTSF::Deactivate() {
  m_client.EndSession();

  _InitTextEditSink(com_ptr<ITfDocumentMgr>());

  _UninitThreadMgrEventSink();

  _UninitKeyEventSink();
  _UninitPreservedKey();

  _UninitLanguageBar();

  _UninitCompartment();

  _UninitThreadMgrEventSink();

  _pThreadMgr = NULL;

  _tfClientId = TF_CLIENTID_NULL;

  _cand->DestroyAll();

  return S_OK;
}

STDMETHODIMP WeaselTSF::ActivateEx(ITfThreadMgr* pThreadMgr,
                                   TfClientId tfClientId,
                                   DWORD dwFlags) {
  LoadWeaselLogLevelFromRegistry();
  com_ptr<ITfDocumentMgr> pDocMgrFocus;
  _activateFlags = dwFlags;

  _pThreadMgr = pThreadMgr;
  _tfClientId = tfClientId;

  qingshi::diag::Log(L"ActivateEx flags=%s",
                     qingshi::diag::DescribeThreadFlags(dwFlags).c_str());

  if (!_InitThreadMgrEventSink())
    goto ExitError;

  if ((_pThreadMgr->GetFocus(&pDocMgrFocus) == S_OK) &&
      (pDocMgrFocus != NULL)) {
    _InitTextEditSink(pDocMgrFocus);
  }

  if (!_InitKeyEventSink())
    goto ExitError;

  // if (!_InitDisplayAttributeGuidAtom())
  //	goto ExitError;
  //	some app might init failed because it not provide DisplayAttributeInfo,
  // like some opengl stuff
  _InitDisplayAttributeGuidAtom();

  if (!_InitPreservedKey())
    goto ExitError;

  // 语言栏、compartment、线程焦点订阅都属于"锦上添花"。全屏游戏里语言栏
  // 往往创建失败，旧代码一旦失败就 Deactivate() 并返回 E_FAIL，TSF 会认定
  // 这个 TIP 激活失败，整个游戏里就一个字都打不出来。这里改成失败也继续。
  if (!_InitLanguageBar())
    qingshi::diag::Log(L"ActivateEx: language bar unavailable (continuing)");

  if (!_IsKeyboardOpen())
    _SetKeyboardOpen(TRUE);

  if (!_InitCompartment())
    qingshi::diag::Log(L"ActivateEx: compartment sink unavailable (continuing)");
  if (!_InitThreadFocusSink())
    qingshi::diag::Log(L"ActivateEx: thread focus sink unavailable (continuing)");

  _EnsureServerConnected();

  qingshi::diag::Log(L"ActivateEx: activated");
  return S_OK;

ExitError:
  qingshi::diag::Log(L"ActivateEx: FAILED, deactivating");
  Deactivate();
  return E_FAIL;
}

LRESULT CALLBACK WeaselTSF::_RefreshWndProc(HWND hwnd,
                                            UINT msg,
                                            WPARAM wParam,
                                            LPARAM lParam) {
  if (msg == WM_NCCREATE) {
    auto* cs = reinterpret_cast<CREATESTRUCTW*>(lParam);
    ::SetWindowLongPtrW(hwnd, GWLP_USERDATA,
                        reinterpret_cast<LONG_PTR>(cs->lpCreateParams));
    return TRUE;
  }
  if (msg == WM_APP + 1) {
    auto* self = reinterpret_cast<WeaselTSF*>(
        ::GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (self)
      self->_RefreshCandidates();
    return 0;
  }
  return ::DefWindowProcW(hwnd, msg, wParam, lParam);
}

void WeaselTSF::_EnsureRefreshWindow() {
  if (m_refresh_hwnd && ::IsWindow(m_refresh_hwnd))
    return;
  static bool cls_ready = false;
  if (!cls_ready) {
    WNDCLASSEXW wc = {sizeof(wc)};
    wc.lpfnWndProc = &WeaselTSF::_RefreshWndProc;
    wc.hInstance = g_hInst;
    wc.lpszClassName = L"QingshiShadowRefresh";
    ::RegisterClassExW(&wc);
    cls_ready = true;
  }
  m_refresh_hwnd =
      ::CreateWindowExW(0, L"QingshiShadowRefresh", L"", 0, 0, 0, 0, 0,
                        HWND_MESSAGE, nullptr, g_hInst, this);
}

void WeaselTSF::_RefreshCandidates() {
  if (!m_client.Echo())
    return;
  // 主动要一次应答：服务端此时已经按新规则重排过，会返回当前 composition
  // 的最新候选。这样 channel 里只有这一轮的数据，不会和按键响应串包。
  m_client.ProcessKeyEvent(0);

  weasel::Context ctx;
  weasel::Status status = _status;
  weasel::ResponseParser parser(NULL, &ctx, &status, NULL, &_cand->style());
  if (!m_client.GetResponseData(std::ref(parser)))
    return;

  // ★ 拿到的上下文可能没有候选（会话对不上 / composition 已结束）。
  // 这时候绝不能 _UpdateUI —— 那会把正在显示的候选窗直接藏掉，
  // 用户看到的就是「点一下固顶，候选框没了」。
  if (ctx.cinfo.candies.empty())
    return;

  _status = status;
  // 只重绘本地窗口：不调 _UpdateUI（它会走 _UpdateUIElement 回调宿主 COM 对象，
  // 在固顶这种「非按键」上下文里重入宿主，正是之前宿主崩溃的根源）。
  _cand->UpdateLocalOnly(ctx, status);
}

bool WeaselTSF::_AdjustShadow(int action, size_t index) {
  if (!_EnsureServerConnected())
    return false;

  // ① 先本地重排候选窗 —— 纯内存 + 只重绘，不碰宿主 COM，点完立刻看到顺序变。
  if (_cand) {
    const auto& candies = _cand->ctx().cinfo.candies;
    if (index < candies.size()) {
      const std::wstring word = candies[index].str;
      if (action == 0) {
        _cand->ReorderLocal(word);                       // 置顶
      } else if (action == 1) {
        _cand->RestoreLocal();                           // 取消固顶 = 还原原始顺序
      } else if (action >= 100) {
        _cand->MoveLocal(word, static_cast<size_t>(action - 100 - 1));  // 调到第 N 位
      }
    }
  }

  // ② 再让服务端把规则写进 shadow_<方案>.yaml，下次输入同一编码直接生效。
  m_client.AdjustShadow(action, index);
  return true;
}

STDMETHODIMP WeaselTSF::OnSetThreadFocus() {
  std::wstring _ToggleImeOnOpenClose{};
  RegGetStringValue(HKEY_CURRENT_USER, L"Software\\Rime\\weasel",
                    L"ToggleImeOnOpenClose", _ToggleImeOnOpenClose);
  _isToOpenClose = (_ToggleImeOnOpenClose == L"yes");
  if (m_client.Echo()) {
    m_client.ProcessKeyEvent(0);
    weasel::ResponseParser parser(NULL, NULL, &_status, NULL, &_cand->style());
    bool ok = m_client.GetResponseData(std::ref(parser));
    if (ok)
      _UpdateLanguageBar(_status);
  }
  return S_OK;
}
STDMETHODIMP WeaselTSF::OnKillThreadFocus() {
  _AbortComposition();
  return S_OK;
}
BOOL WeaselTSF::_InitThreadFocusSink() {
  com_ptr<ITfSource> pSource;
  if (FAILED(_pThreadMgr->QueryInterface(&pSource)))
    return FALSE;
  if (FAILED(pSource->AdviseSink(IID_ITfThreadFocusSink,
                                 (ITfThreadFocusSink*)this,
                                 &_dwThreadFocusSinkCookie)))
    return FALSE;
  return TRUE;
}
void WeaselTSF::_UninitThreadFocusSink() {
  com_ptr<ITfSource> pSource;
  if (FAILED(_pThreadMgr->QueryInterface(&pSource)))
    return;
  if (FAILED(pSource->UnadviseSink(_dwThreadFocusSinkCookie)))
    return;
}

STDMETHODIMP WeaselTSF::OnActivated(REFCLSID clsid,
                                    REFGUID guidProfile,
                                    BOOL isActivated) {
  if (!IsEqualCLSID(clsid, c_clsidTextService)) {
    return S_OK;
  }

  if (isActivated) {
    _ShowLanguageBar(TRUE);
    _UpdateLanguageBar(_status);
  } else {
    _DeleteCandidateList();
    _ShowLanguageBar(FALSE);
  }
  return S_OK;
}

void WeaselTSF::_Reconnect() {
  m_client.Disconnect();
  m_client.Connect(NULL);
  m_client.StartSession();
  weasel::ResponseParser parser(NULL, NULL, &_status, NULL, &_cand->style());
  bool ok = m_client.GetResponseData(std::ref(parser));
  if (ok) {
    _UpdateLanguageBar(_status);
  }
}

bool WeaselTSF::_EnsureServerConnected() {
  if (m_client.Echo())
    return true;

  // 卸载时启动脚本会被先删掉，卸载完成后 WeaselRoot 也会被删。
  // 这种情况下没有任何可恢复的路径，必须立刻放行按键：否则下面那段
  // 同步重试会为**每一次按键**阻塞 4 秒，整台机器表现为卡死，
  // 而且等多久都不会成功。
  const std::wstring dir = _GetRootDir();
  if (dir.empty())
    return false;
  const std::wstring launcher = dir + L"\\start_service.bat";
  if (::GetFileAttributesW(launcher.c_str()) == INVALID_FILE_ATTRIBUTES)
    return false;

  // 上一次连接尝试刚失败过：给一个冷却窗口，避免连续按键把调用方的
  // UI 线程反复卡住（服务真挂了的时候，按键应当尽快放行给应用）。
  const ULONGLONG now = ::GetTickCount64();
  if (now < _nextConnectAttempt)
    return false;

  const auto count_server_process = []() -> int {
    int count = 0;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE)
      return -1;
    PROCESSENTRY32 pe{};
    pe.dwSize = sizeof(pe);
    if (Process32First(snap, &pe)) {
      do {
        if (_wcsicmp(pe.szExeFile, L"WeaselServer.exe") == 0)
          ++count;
      } while (Process32Next(snap, &pe));
    }
    CloseHandle(snap);
    return count;
  };

  // Never infer this from GetLastError after unrelated API calls. The old code
  // sampled it after Echo/process enumeration, so a stale error could prevent
  // startup. OpenMutex only observes the deployer's existing exclusive lock.
  HANDLE deployer_mutex =
      OpenMutexW(SYNCHRONIZE, FALSE, L"WeaselDeployerExclusiveMutex");
  bool deployer_running = deployer_mutex != nullptr;
  if (deployer_mutex)
    CloseHandle(deployer_mutex);

  int server_count = count_server_process();
  if (!deployer_running && server_count == 0) {
    ::ShellExecuteW(NULL, L"open", launcher.c_str(), NULL, dir.c_str(),
                    SW_HIDE);
  }

  // A process can exist before its IPC loop is ready (Rime is still loading),
  // so don't treat "WeaselServer.exe exists" as "connected". Keep retrying
  // until a live session answers; this keeps the triggering keystroke in TSF
  // instead of forwarding several letters to the application during startup.
  constexpr int kConnectAttempts = 80;  // up to 4 seconds, only on failure
  for (int i = 0; i < kConnectAttempts; ++i) {
    // 重建会话比较重（Disconnect + Connect + StartSession + 取响应），
    // 每 200ms 试一次就够，不必每 50ms 都重连。
    if (!deployer_running && (i % 4) == 0) {
      _Reconnect();
      if (m_client.Echo())
        return true;
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    deployer_mutex = OpenMutexW(SYNCHRONIZE, FALSE,
                                L"WeaselDeployerExclusiveMutex");
    deployer_running = deployer_mutex != nullptr;
    if (deployer_mutex)
      CloseHandle(deployer_mutex);
  }

  if (m_client.Echo())
    return true;

  _nextConnectAttempt = ::GetTickCount64() + 3000;
  return false;
}
