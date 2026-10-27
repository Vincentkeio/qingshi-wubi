#include "stdafx.h"
#include "WeaselIPC.h"
#include "WeaselTSF.h"
#include <KeyEvent.h>
#include "CandidateList.h"
#include "QingshiDiag.h"

static weasel::KeyEvent prevKeyEvent;
static BOOL prevfEaten = FALSE;
static int keyCountToSimulate = 0;

// 按键为什么被放行给应用 —— 每秒最多记一条，用来定位"某些程序里打不了字"。
static void DiagKeyPassthrough(const wchar_t* reason) {
  static ULONGLONG next_allowed = 0;
  const ULONGLONG now = ::GetTickCount64();
  if (now < next_allowed)
    return;
  next_allowed = now + 1000;
  qingshi::diag::Log(L"key passthrough: %s", reason);
}

// 青石：Shift + 字母 直接输出（不进编码）。开关存在注册表，默认开启。
static bool QingshiShiftLetterDirect() {
  DWORD value = 1;
  DWORD size = sizeof(value);
  HKEY key = nullptr;
  if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\Rime\\Weasel", 0,
                    KEY_READ, &key) == ERROR_SUCCESS) {
    RegQueryValueExW(key, L"QingshiShiftLetterDirect", nullptr, nullptr,
                     reinterpret_cast<LPBYTE>(&value), &size);
    RegCloseKey(key);
  }
  return value != 0;
}

void WeaselTSF::_ProcessKeyEvent(WPARAM wParam, LPARAM lParam, BOOL* pfEaten) {
  // when _IsKeyboardDisabled don't eat the key,
  // when keyboard closable and keyboard closed, don't eat the key
  if ((_isToOpenClose && !_IsKeyboardOpen()) || _IsKeyboardDisabled()) {
    DiagKeyPassthrough(_isToOpenClose && !_IsKeyboardOpen() ? L"keyboard-closed"
                                                            : L"keyboard-disabled");
    *pfEaten = FALSE;
    return;
  }

  // if server connection is Not OK, don't eat it.
  if (!_EnsureServerConnected()) {
    DiagKeyPassthrough(L"no-server");
    *pfEaten = FALSE;
    return;
  }

  // Shift + 字母：不交给输入法，让应用自己输出大写字母
  // 用 GetAsyncKeyState 读实时键态，GetKeyState 在 TSF 回调里可能滞后，
  // 会把 Shift 已松开的情况误判成按住，导致字母一直不进输入法。
  if (!_status.composing && wParam >= 'A' && wParam <= 'Z' &&
      (::GetAsyncKeyState(VK_SHIFT) & 0x8000) &&
      !(::GetAsyncKeyState(VK_CONTROL) & 0x8000) &&
      !(::GetAsyncKeyState(VK_MENU) & 0x8000) && QingshiShiftLetterDirect()) {
    // Rime already saw Shift-down. Let it observe a non-modifier release so
    // AsciiComposer knows this was a chord, not a standalone Shift tap. A
    // release event never inserts a character; the application still receives
    // the real letter normally, and the eventual Shift-up won't change modes.
    m_client.ProcessKeyEvent(weasel::KeyEvent(
        static_cast<UINT>(wParam), ibus::SHIFT_MASK | ibus::RELEASE_MASK));
    *pfEaten = FALSE;
    return;
  }
  weasel::KeyEvent ke;
  GetKeyboardState(_lpbKeyState);
  if (!ConvertKeyEvent(static_cast<UINT>(wParam), lParam, _lpbKeyState, ke)) {
    /* Unknown key event */
    *pfEaten = FALSE;
  } else {
    // ── 候选调序快捷键 ────────────────────────────────────────────
    // Ctrl+数字   = 把该候选置顶到本编码第一位
    // Ctrl+Shift+数字 = 撤掉本编码的全部置顶
    // 规则写到 shadow_<方案>.yaml，服务端立刻重排并刷新，不部署、不重启。
    if (_status.composing && !(ke.mask & ibus::RELEASE_MASK) &&
        (ke.mask & ibus::CONTROL_MASK) && ke.keycode >= '1' &&
        ke.keycode <= '9') {
      const int action = (ke.mask & ibus::SHIFT_MASK) ? WEASEL_SHADOW_UNPIN
                                                      : WEASEL_SHADOW_PIN;
      const size_t idx = static_cast<size_t>(ke.keycode - '1');
      if (m_client.AdjustShadow(action, idx)) {
        *pfEaten = TRUE;
        return;
      }
    }

    // cheet key code when vertical auto reverse happened, swap up and down
    if (_cand->GetIsReposition()) {
      if (ke.keycode == ibus::Up)
        ke.keycode = ibus::Down;
      else if (ke.keycode == ibus::Down)
        ke.keycode = ibus::Up;
    }
    // 候选窗被本地重排过：空格 / 数字键按「界面上的顺序」选词。
    // 不换算的话显示是第一位的「仰泳」，按空格上屏的却是引擎里的第一个「你」。
    if (_cand && _cand->has_display_order() && _status.composing &&
        !(ke.mask & ibus::RELEASE_MASK) &&
        !(ke.mask & (ibus::SHIFT_MASK | ibus::CONTROL_MASK | (1 << 3)))) {
      size_t display_index = static_cast<size_t>(-1);
      if (ke.keycode == 0x20) {
        display_index = 0;   // 空格 = 上屏界面上第一个
      } else if (ke.keycode >= '1' && ke.keycode <= '9') {
        const size_t d = static_cast<size_t>(ke.keycode - '1');
        if (d < _cand->display_order_size())
          display_index = d;
      } else if (ke.keycode == 0x3B /* ; */ || ke.keycode == 0x27 /* ' */) {
        // 方案里 alternative_select_keys: "1;'" —— 分号选第 2 位、单引号选第 3 位。
        // 这两个键不走 process_key 的数字选词路径，必须在这里换算，否则
        // 显示重排了、按 ; 拿到的还是引擎里的第 2 个。
        const size_t d = (ke.keycode == 0x3B) ? 1 : 2;
        if (d < _cand->display_order_size())
          display_index = d;
      }
      if (display_index != static_cast<size_t>(-1)) {
        const size_t orig = _cand->display_to_original(display_index);
        m_client.SelectCandidateOnCurrentPage(orig);
        *pfEaten = TRUE;
        return;
      }
    }

    if (!keyCountToSimulate)
      *pfEaten = (BOOL)m_client.ProcessKeyEvent(ke);
    if (!*pfEaten && !keyCountToSimulate)
      DiagKeyPassthrough(L"rime-declined");

    if (ke.keycode == ibus::Caps_Lock) {
      if (prevKeyEvent.keycode == ibus::Caps_Lock && prevfEaten == TRUE &&
          (ke.mask & ibus::RELEASE_MASK) && (!keyCountToSimulate)) {
        if ((GetKeyState(VK_CAPITAL) & 0x01)) {
          if (_committed || (!*pfEaten && _status.composing)) {
            keyCountToSimulate = 2;
            INPUT inputs[2];
            inputs[0].type = INPUT_KEYBOARD;
            inputs[0].ki = {VK_CAPITAL, 0, 0, 0, 0};
            inputs[1].type = INPUT_KEYBOARD;
            inputs[1].ki = {VK_CAPITAL, 0, KEYEVENTF_KEYUP, 0, 0};
            ::SendInput(sizeof(inputs) / sizeof(INPUT), inputs, sizeof(INPUT));
          }
        }
        *pfEaten = TRUE;
      }
      if (keyCountToSimulate)
        keyCountToSimulate--;
    }

    prevfEaten = *pfEaten;
    prevKeyEvent = ke;
  }
}

STDMETHODIMP WeaselTSF::OnSetFocus(BOOL fForeground) {
  if (fForeground)
    m_client.FocusIn();
  else {
    m_client.FocusOut();
    _AbortComposition();
  }

  return S_OK;
}

/* Some apps sends strange OnTestKeyDown/OnKeyDown combinations:
 *  Some sends OnKeyDown() only. (QQ2012)
 *  Some sends multiple OnTestKeyDown() for a single key event. (MS WORD 2010
 * x64)
 *
 * We assume every key event will eventually cause a OnKeyDown() call.
 * We use _fTestKeyDownPending to omit multiple OnTestKeyDown() calls,
 *  and for OnKeyDown() to check if the key has already been sent to the server.
 */

STDMETHODIMP WeaselTSF::OnTestKeyDown(ITfContext* pContext,
                                      WPARAM wParam,
                                      LPARAM lParam,
                                      BOOL* pfEaten) {
  _fTestKeyUpPending = FALSE;
  if (_fTestKeyDownPending) {
    *pfEaten = TRUE;
    return S_OK;
  }
  _ProcessKeyEvent(wParam, lParam, pfEaten);
  _UpdateComposition(pContext);
  if (*pfEaten)
    _fTestKeyDownPending = TRUE;
  return S_OK;
}

STDMETHODIMP WeaselTSF::OnKeyDown(ITfContext* pContext,
                                  WPARAM wParam,
                                  LPARAM lParam,
                                  BOOL* pfEaten) {
  _fTestKeyUpPending = FALSE;
  if (_fTestKeyDownPending) {
    _fTestKeyDownPending = FALSE;
    *pfEaten = TRUE;
  } else {
    _ProcessKeyEvent(wParam, lParam, pfEaten);
    _UpdateComposition(pContext);
  }
  return S_OK;
}

STDMETHODIMP WeaselTSF::OnTestKeyUp(ITfContext* pContext,
                                    WPARAM wParam,
                                    LPARAM lParam,
                                    BOOL* pfEaten) {
  _fTestKeyDownPending = FALSE;
  if (_fTestKeyUpPending) {
    *pfEaten = TRUE;
    return S_OK;
  }
  _ProcessKeyEvent(wParam, lParam, pfEaten);
  _UpdateComposition(pContext);
  if (*pfEaten)
    _fTestKeyUpPending = TRUE;
  return S_OK;
}

STDMETHODIMP WeaselTSF::OnKeyUp(ITfContext* pContext,
                                WPARAM wParam,
                                LPARAM lParam,
                                BOOL* pfEaten) {
  _fTestKeyDownPending = FALSE;
  if (_fTestKeyUpPending) {
    _fTestKeyUpPending = FALSE;
    *pfEaten = TRUE;
  } else {
    _ProcessKeyEvent(wParam, lParam, pfEaten);
    if (!_async_edit)
      _UpdateComposition(pContext);
  }
  return S_OK;
}

STDMETHODIMP WeaselTSF::OnPreservedKey(ITfContext* pContext,
                                       REFGUID rguid,
                                       BOOL* pfEaten) {
  *pfEaten = FALSE;
  return S_OK;
}

BOOL WeaselTSF::_InitKeyEventSink() {
  com_ptr<ITfKeystrokeMgr> pKeystrokeMgr;
  HRESULT hr;

  if (_pThreadMgr->QueryInterface(&pKeystrokeMgr) != S_OK)
    return FALSE;

  hr = pKeystrokeMgr->AdviseKeyEventSink(_tfClientId, (ITfKeyEventSink*)this,
                                         TRUE);

  return (hr == S_OK);
}

void WeaselTSF::_UninitKeyEventSink() {
  com_ptr<ITfKeystrokeMgr> pKeystrokeMgr;

  if (_pThreadMgr->QueryInterface(&pKeystrokeMgr) != S_OK)
    return;

  pKeystrokeMgr->UnadviseKeyEventSink(_tfClientId);
}

BOOL WeaselTSF::_InitPreservedKey() {
  return TRUE;
#if 0
	com_ptr<ITfKeystrokeMgr> pKeystrokeMgr;
	if (_pThreadMgr->QueryInterface(pKeystrokeMgr.GetAddressOf()) != S_OK)
	{
		return FALSE;
	}
	TF_PRESERVEDKEY preservedKeyImeMode;

	/* Define SHIFT ONLY for now */
	preservedKeyImeMode.uVKey = VK_SHIFT;
	preservedKeyImeMode.uModifiers = TF_MOD_ON_KEYUP;

	auto hr = pKeystrokeMgr->PreserveKey(
		_tfClientId,
		GUID_IME_MODE_PRESERVED_KEY,
		&preservedKeyImeMode, L"", 0);
	
	return SUCCEEDED(hr);
#endif
}

void WeaselTSF::_UninitPreservedKey() {}
