#include "stdafx.h"

#include "WeaselTSF.h"
#include "CandidateList.h"
#include "QingshiDiag.h"
#include <KeyEvent.h>
#include <math.h>

using namespace std;
using namespace weasel;

CCandidateList::CCandidateList(com_ptr<WeaselTSF> pTextService)
    : _ui(make_unique<UI>()), _tsf(pTextService), _pbShow(TRUE) {
  _cRef = 1;
  // 候选窗跑在 TSF 进程里，而候选调序的数据在服务端 —— 中间必须走 IPC。
  // 之前直接在服务端注册回调，TSF 进程里那份全局永远是空的，
  // 于是右键「固顶」一路退回「改词库 + 全量部署」。
  _ui->SetShadowAction([this](size_t index, int action) {
    if (_tsf)
      _tsf->_AdjustShadow(action, index);   // 只发 IPC，不在这里重绘
  });
  weasel::g_shadow_refresh = [this] { DoShadowRefresh(); };
}

void CCandidateList::RequestShadowRefresh() {
  HWND h = hwnd();
  if (h)
    ::PostMessageW(h, WEASEL_WM_SHADOW_REFRESH, 0, 0);
}

void CCandidateList::DoShadowRefresh() {
  if (_tsf)
    _tsf->_RefreshCandidates();
}

CCandidateList::~CCandidateList() {
  // 全局回调指向 this，对象没了必须清掉，否则下一次刷新会踩空指针。
  weasel::g_shadow_refresh = nullptr;
  weasel::g_shadow_action = nullptr;
}

STDMETHODIMP CCandidateList::QueryInterface(REFIID riid, void** ppvObj) {
  if (ppvObj == nullptr) {
    return E_INVALIDARG;
  }

  *ppvObj = nullptr;

  if (IsEqualIID(riid, IID_ITfUIElement) ||
      IsEqualIID(riid, IID_ITfCandidateListUIElement) ||
      IsEqualIID(riid, IID_ITfCandidateListUIElementBehavior)) {
    *ppvObj = (ITfCandidateListUIElementBehavior*)this;
  } else if (IsEqualIID(riid, IID_IUnknown) ||
             IsEqualIID(riid,
                        __uuidof(ITfIntegratableCandidateListUIElement))) {
    *ppvObj = (ITfIntegratableCandidateListUIElement*)this;
  }

  if (*ppvObj) {
    AddRef();
    return S_OK;
  }

  return E_NOINTERFACE;
}

STDMETHODIMP_(ULONG) CCandidateList::AddRef(void) {
  return ++_cRef;
}

STDMETHODIMP_(ULONG) CCandidateList::Release(void) {
  LONG cr = --_cRef;

  assert(_cRef >= 0);

  if (_cRef == 0) {
    delete this;
  }

  return cr;
}

STDMETHODIMP CCandidateList::GetDescription(BSTR* pbstr) {
  static auto str = SysAllocString(L"Candidate List");
  if (pbstr) {
    *pbstr = str;
  }
  return S_OK;
}

STDMETHODIMP CCandidateList::GetGUID(GUID* pguid) {
  /// 36c3c795-7159-45aa-ab12-30229a51dbd3
  *pguid = {0x36c3c795,
            0x7159,
            0x45aa,
            {0xab, 0x12, 0x30, 0x22, 0x9a, 0x51, 0xdb, 0xd3}};
  return S_OK;
}

STDMETHODIMP CCandidateList::Show(BOOL showCandidateWindow) {
  if (showCandidateWindow)
    _ui->Show();
  else
    _ui->Hide();
  return S_OK;
}

STDMETHODIMP CCandidateList::IsShown(BOOL* pIsShow) {
  *pIsShow = _ui->IsShown();
  return S_OK;
}

STDMETHODIMP CCandidateList::GetUpdatedFlags(DWORD* pdwFlags) {
  if (!pdwFlags)
    return E_INVALIDARG;

  *pdwFlags = TF_CLUIE_DOCUMENTMGR | TF_CLUIE_COUNT | TF_CLUIE_SELECTION |
              TF_CLUIE_STRING | TF_CLUIE_CURRENTPAGE;
  return S_OK;
}

STDMETHODIMP CCandidateList::GetDocumentMgr(ITfDocumentMgr** ppdim) {
  *ppdim = nullptr;
  auto pThreadMgr = _tsf->_GetThreadMgr();
  if (pThreadMgr == nullptr) {
    return E_FAIL;
  }
  if (FAILED(pThreadMgr->GetFocus(ppdim)) || (*ppdim == nullptr)) {
    return E_FAIL;
  }
  return S_OK;
}

STDMETHODIMP CCandidateList::GetCount(UINT* pCandidateCount) {
  _MarkHostConsumed();
  *pCandidateCount = static_cast<UINT>(_ui->ctx().cinfo.candies.size());
  return S_OK;
}

STDMETHODIMP CCandidateList::GetSelection(UINT* pSelectedCandidateIndex) {
  _MarkHostConsumed();
  *pSelectedCandidateIndex = _ui->ctx().cinfo.highlighted;
  return S_OK;
}

STDMETHODIMP CCandidateList::GetString(UINT uIndex, BSTR* pbstr) {
  _MarkHostConsumed();
  *pbstr = nullptr;
  auto& cinfo = _ui->ctx().cinfo;
  if (uIndex >= cinfo.candies.size())
    return E_INVALIDARG;

  auto& str = cinfo.candies[uIndex].str;
  *pbstr = SysAllocStringLen(str.c_str(), static_cast<UINT>(str.size()) + 1);

  return S_OK;
}

STDMETHODIMP CCandidateList::GetPageIndex(UINT* pIndex,
                                          UINT uSize,
                                          UINT* puPageCnt) {
  _MarkHostConsumed();
  if (!puPageCnt)
    return E_INVALIDARG;
  *puPageCnt = 1;
  if (pIndex) {
    if (uSize < *puPageCnt) {
      return E_INVALIDARG;
    }
    *pIndex = 0;
  }
  return S_OK;
}

STDMETHODIMP CCandidateList::SetPageIndex(UINT* pIndex, UINT uPageCnt) {
  if (!pIndex)
    return E_INVALIDARG;
  return S_OK;
}

STDMETHODIMP CCandidateList::GetCurrentPage(UINT* puPage) {
  _MarkHostConsumed();
  *puPage = 0;
  return S_OK;
}

STDMETHODIMP CCandidateList::SetSelection(UINT nIndex) {
  _ui->ctx().cinfo.highlighted = nIndex;
  return S_OK;
}

STDMETHODIMP CCandidateList::Finalize(void) {
  Destroy();
  return S_OK;
}

STDMETHODIMP CCandidateList::Abort(void) {
  _tsf->_AbortComposition(true);
  Destroy();
  return S_OK;
}

STDMETHODIMP CCandidateList::SetIntegrationStyle(GUID guidIntegrationStyle) {
  return S_OK;
}

STDMETHODIMP CCandidateList::GetSelectionStyle(
    TfIntegratableCandidateListSelectionStyle* ptfSelectionStyle) {
  *ptfSelectionStyle = _selectionStyle;
  return S_OK;
}

STDMETHODIMP CCandidateList::OnKeyDown(WPARAM wParam,
                                       LPARAM lParam,
                                       BOOL* pIsEaten) {
  *pIsEaten = TRUE;
  return S_OK;
}

STDMETHODIMP CCandidateList::ShowCandidateNumbers(BOOL* pIsShow) {
  *pIsShow = TRUE;
  return S_OK;
}

STDMETHODIMP CCandidateList::FinalizeExactCompositionString() {
  _tsf->_AbortComposition(false);
  return E_NOTIMPL;
}

void CCandidateList::ReorderLocal(const std::wstring& word) {
  if (!_ui || word.empty())
    return;
  auto& candies = _ui->ctx().cinfo.candies;
  if (candies.size() < 2)
    return;
  auto it = std::find_if(candies.begin(), candies.end(),
                         [&](const weasel::Text& t) { return t.str == word; });
  if (it == candies.end() || it == candies.begin())
    return;   // 没这个词，或已经在第一位

  const size_t from = static_cast<size_t>(it - candies.begin());

  // 第一次重排时建立映射（显示位置 → 引擎原始索引）
  // 第一次改动前存一份原始顺序，取消固顶时还原
  if (m_original_candies.size() != candies.size())
    m_original_candies = candies;

  if (m_display_order.size() != candies.size()) {
    m_display_order.resize(candies.size());
    for (size_t i = 0; i < candies.size(); ++i)
      m_display_order[i] = i;
  }

  weasel::Text picked = *it;
  candies.erase(candies.begin() + from);
  candies.insert(candies.begin(), picked);

  // 映射同步：把 from 对应的原始索引挪到最前
  const size_t orig = m_display_order[from];
  m_display_order.erase(m_display_order.begin() + from);
  m_display_order.insert(m_display_order.begin(), orig);

  // 只重排布局并重绘：panel.Refresh 不销毁窗口、不回调宿主。
  _ui->Refresh();
}

void CCandidateList::RestoreLocal() {
  if (!_ui || m_original_candies.empty())
    return;
  auto& candies = _ui->ctx().cinfo.candies;
  if (candies.size() != m_original_candies.size())
    return;
  candies = m_original_candies;
  m_display_order.clear();
  _ui->Refresh();
}

void CCandidateList::MoveLocal(const std::wstring& word, size_t target) {
  if (!_ui || word.empty())
    return;
  auto& candies = _ui->ctx().cinfo.candies;
  if (candies.size() < 2)
    return;
  auto it = std::find_if(candies.begin(), candies.end(),
                         [&](const weasel::Text& t) { return t.str == word; });
  if (it == candies.end())
    return;
  const size_t from = static_cast<size_t>(it - candies.begin());
  if (target >= candies.size())
    target = candies.size() - 1;
  if (from == target)
    return;

  // 第一次改动前存一份原始顺序，取消固顶时还原
  if (m_original_candies.size() != candies.size())
    m_original_candies = candies;

  if (m_display_order.size() != candies.size()) {
    m_display_order.resize(candies.size());
    for (size_t i = 0; i < candies.size(); ++i)
      m_display_order[i] = i;
  }

  weasel::Text picked = candies[from];
  candies.erase(candies.begin() + from);
  candies.insert(candies.begin() + target, picked);

  const size_t orig = m_display_order[from];
  m_display_order.erase(m_display_order.begin() + from);
  m_display_order.insert(m_display_order.begin() + target, orig);

  _ui->Refresh();
}

void CCandidateList::UpdateLocalOnly(const Context& ctx,
                                     const Status& status) {
  const bool style_changed = (_ui->style() != _style);
  if (style_changed)
    _ui->style() = _style;
  _ui->Update(ctx, status);
  if (style_changed)
    _ui->Refresh();
  const bool allowShow = _localUI || _pbShow;
  if (status.composing)
    Show(allowShow);
  else
    Show(FALSE);
}

void CCandidateList::UpdateUI(const Context& ctx, const Status& status) {
  // 新的候选列表意味着顺序重新来自引擎，本地重排的映射与快照都作废。
  m_display_order.clear();
  m_original_candies.clear();
  // 服务端每次应答都带全量 UIStyle（见 RimeWithWeasel 的 oa << style）。
  // 但候选窗是宿主进程里长期复用的同一个窗口对象，_ui->style() 才是真正
  // 驱动绘制的那份副本，以前只在「建窗」和「启用本地窗」时赋值一次，
  // 于是设置里换了配色，已经打开的旧候选框还是旧主题。
  // 这里每次按键都同步一次：WeaselPanel::Refresh 检测到 m_ostyle != m_style
  // 就会重init字体、重建布局并重绘 —— 热更新即可生效，不用重启服务。
  const bool style_changed = (_ui->style() != _style);
  if (style_changed) {
    _ui->style() = _style;
    // 排查用：确认客户端确实收到了新样式（只记颜色和字号，不含任何输入内容）。
    qingshi::diag::Log(L"style synced back=0x%08X hilite=0x%08X font_point=%d",
                       static_cast<unsigned>(_style.back_color),
                       static_cast<unsigned>(_style.hilited_candidate_back_color),
                       _style.font_point);
  }
  if (_ui->style().inline_preedit) {
    _ui->style().client_caps |= weasel::INLINE_PREEDIT_CAPABLE;
  } else {
    _ui->style().client_caps &= ~weasel::INLINE_PREEDIT_CAPABLE;
  }

  /// In UWP, candidate window will only be shown
  /// if it is owned by active view window
  //_UpdateOwner();
  _ui->Update(ctx, status);
  // Update 在「上下文和状态都没变」时会直接返回，样式变化必须再补一次重绘，
  // 否则改完配色继续打同一个编码，画面还是旧的。
  if (style_changed)
    _ui->Refresh();

  ++_updateSeq;
  // 宿主若在自己画候选，会在 UpdateUIElement 里同步回调 GetCount/GetString。
  // 这一步必须在"是否兜底本地窗口"的判断之前完成。
  if (_uiStarted)
    _UpdateUIElement();

  // 宿主说过"我自己画"（pbShow == FALSE），但更新之后一次都没来读候选数据：
  // 说明它并没有真的画，编码就会变成"没有候选框"。此时退回本地候选窗。
  // 只在确实有候选时才下结论，避免预编辑阶段误判后叠出双份候选。
  if (_uiStarted && _hostDeclined && !_hostConsumed && !_localUI &&
      !ctx.cinfo.candies.empty()) {
    _EnableLocalUI(L"host-declined-but-never-read");
  }

  const bool allowShow = _localUI || _pbShow;
  if (status.composing && allowShow && _ui->hwnd() == nullptr) {
    // 窗口可能在上一次 Destroy 时被释放，而状态仍认为 UI 已开始。
    // 这里自愈，避免"编码在走但再也没有候选窗"。
    _ui->style() = _style;
    _MakeUIWindow();
  }

  if (status.composing)
    Show(allowShow);
  else
    Show(FALSE);

  if (_updateSeq <= 3 || (_updateSeq % 16) == 0) {
    RECT panel_rect{};
    HWND panel = _ui->hwnd();
    if (panel)
      ::GetWindowRect(panel, &panel_rect);
    qingshi::diag::Log(
        L"UpdateUI seq=%lu composing=%d cand=%zu preedit_len=%zu aux_len=%zu "
        L"pbShow=%d declined=%d consumed=%d local=%d allow=%d "
        L"panel=%s visible=%d rect=(%ld,%ld,%ld,%ld)",
        _updateSeq, status.composing ? 1 : 0, ctx.cinfo.candies.size(),
        ctx.preedit.str.size(), ctx.aux.str.size(), _pbShow ? 1 : 0,
        _hostDeclined ? 1 : 0, _hostConsumed ? 1 : 0, _localUI ? 1 : 0,
        allowShow ? 1 : 0,
        panel ? qingshi::diag::DescribeWindow(panel).c_str() : L"0x0(-)",
        panel && ::IsWindowVisible(panel) ? 1 : 0, panel_rect.left,
        panel_rect.top, panel_rect.right, panel_rect.bottom);
  }
}

void CCandidateList::UpdateStyle(const UIStyle& sty) {
  _ui->style() = sty;
}

void CCandidateList::UpdateInputPosition(RECT const& rc) {
  _ui->UpdateInputPosition(rc);
  qingshi::diag::Log(L"UpdateInputPosition caret=(%ld,%ld,%ld,%ld) panel=%s",
                     rc.left, rc.top, rc.right, rc.bottom,
                     _ui->hwnd()
                         ? qingshi::diag::DescribeWindow(_ui->hwnd()).c_str()
                         : L"0x0(-)");
}

void CCandidateList::Destroy() {
  // EndUI();
  Show(FALSE);
  _DisposeUIWindow();
}

void CCandidateList::DestroyAll() {
  // EndUI();
  Show(FALSE);
  _DisposeUIWindowAll();
}
UIStyle& CCandidateList::style() {
  // return _ui->style();
  return _style;
}

HWND CCandidateList::_GetActiveWnd() {
  com_ptr<ITfDocumentMgr> pDocumentMgr;
  com_ptr<ITfContext> pContext;
  com_ptr<ITfContextView> pContextView;
  com_ptr<ITfThreadMgr> pThreadMgr = _tsf->_GetThreadMgr();

  HWND w = NULL;

  // Reset current context
  _pContextDocument = nullptr;

  if (pThreadMgr != nullptr && SUCCEEDED(pThreadMgr->GetFocus(&pDocumentMgr)) &&
      SUCCEEDED(pDocumentMgr->GetTop(&pContext)) &&
      SUCCEEDED(pContext->GetActiveView(&pContextView))) {
    // Set current context
    _pContextDocument = pContext;
    pContextView->GetWnd(&w);
  }

  if (w == NULL)
    w = ::GetFocus();
  return w;
}

HRESULT CCandidateList::_UpdateUIElement() {
  HRESULT hr = S_OK;

  com_ptr<ITfUIElementMgr> pUIElementMgr;
  com_ptr<ITfThreadMgr> pThreadMgr = _tsf->_GetThreadMgr();
  if (nullptr == pThreadMgr) {
    return S_OK;
  }
  hr = pThreadMgr->QueryInterface(IID_ITfUIElementMgr, (void**)&pUIElementMgr);

  if (hr == S_OK) {
    pUIElementMgr->UpdateUIElement(uiid);
  }

  return S_OK;
}

void CCandidateList::_MarkHostConsumed() {
  if (!_hostConsumed) {
    _hostConsumed = true;
    qingshi::diag::Log(L"host read candidate data (seq=%lu) -> host draws UI",
                       _updateSeq);
  }
}

void CCandidateList::_EnableLocalUI(const wchar_t* reason) {
  if (!_localUI)
    qingshi::diag::Log(L"candidate panel enabled: %s", reason);
  _localUI = true;
  _ui->style() = _style;
  _MakeUIWindow();
  if (!_ui_warmed_up && _ui->hwnd() != nullptr) {
    // Warm up render resources before first visible paint in TSF path.
    _ui->Refresh();
    _ui->Hide();
    _ui_warmed_up = true;
  }
}

void CCandidateList::StartUI() {
  if (_uiStarted)
    return;

  com_ptr<ITfThreadMgr> pThreadMgr = _tsf->_GetThreadMgr();
  if (!pThreadMgr) {
    qingshi::diag::Log(L"StartUI: no thread manager");
    return;
  }

  if (!_ui->uiCallback())
    _ui->SetUICallBack([this](size_t* const sel, size_t* const hov,
                              bool* const next, bool* const scroll_next) {
      _tsf->HandleUICallback(sel, hov, next, scroll_next);
    });

  _pbShow = TRUE;
  _hostDeclined = false;
  _hostConsumed = false;
  _localUI = false;
  _updateSeq = 0;

  const HWND view = _GetActiveWnd();
  DWORD thread_flags = 0;
  {
    com_ptr<ITfThreadMgrEx> thread_mgr_ex;
    if (SUCCEEDED(pThreadMgr->QueryInterface(&thread_mgr_ex)) &&
        thread_mgr_ex != nullptr) {
      thread_mgr_ex->GetActiveFlags(&thread_flags);
    }
  }

  com_ptr<ITfUIElementMgr> pUIElementMgr;
  const HRESULT qi = pThreadMgr->QueryInterface(&pUIElementMgr);
  if (FAILED(qi) || pUIElementMgr == nullptr) {
    // 没有 UIElement 管理器就没有"宿主代画"这条路径，直接自绘。
    qingshi::diag::Log(
        L"StartUI view=%s flags=%s: no ITfUIElementMgr (hr=0x%08lX)",
        qingshi::diag::DescribeWindow(view).c_str(),
        qingshi::diag::DescribeThreadFlags(thread_flags).c_str(), qi);
    _EnableLocalUI(L"no-uielement-manager");
    return;
  }

  const HRESULT begin = pUIElementMgr->BeginUIElement(this, &_pbShow, &uiid);
  _uiLess = (thread_flags & TF_TMF_UIELEMENTENABLEDONLY) != 0;
  qingshi::diag::Log(
      L"StartUI view=%s flags=%s BeginUIElement hr=0x%08lX pbShow=%d uiid=%lu",
      qingshi::diag::DescribeWindow(view).c_str(),
      qingshi::diag::DescribeThreadFlags(thread_flags).c_str(), begin,
      _pbShow ? 1 : 0, uiid);

  if (FAILED(begin)) {
    // 宿主直接拒绝这个 UIElement，只能自绘，否则整段编码没有任何候选。
    _EnableLocalUI(L"begin-uielement-failed");
    return;
  }

  _uiStarted = true;
  _hostDeclined = !_pbShow;
  if (_pbShow) {
    _EnableLocalUI(L"host-allows-tip-ui");
  }
  // pbShow == FALSE：宿主声称自己画。先不建窗，等 UpdateUIElement 之后
  // 看它是否真的来读候选数据（见 UpdateUI），避免和宿主叠出两份候选。
}

void CCandidateList::EndUI() {
  if (_uiStarted) {
    com_ptr<ITfThreadMgr> pThreadMgr = _tsf->_GetThreadMgr();
    if (pThreadMgr) {
      com_ptr<ITfUIElementMgr> emgr;
      if (SUCCEEDED(pThreadMgr->QueryInterface(&emgr)) && emgr != nullptr)
        emgr->EndUIElement(uiid);
    }
  }
  if (_uiStarted || _localUI) {
    qingshi::diag::Log(L"EndUI started=%d local=%d declined=%d consumed=%d",
                       _uiStarted ? 1 : 0, _localUI ? 1 : 0,
                       _hostDeclined ? 1 : 0, _hostConsumed ? 1 : 0);
  }
  _uiStarted = false;
  _hostDeclined = false;
  _hostConsumed = false;
  _localUI = false;
  _uiLess = false;
  _updateSeq = 0;
  _DisposeUIWindow();
}

com_ptr<ITfContext> CCandidateList::GetContextDocument() {
  return _pContextDocument;
}

void CCandidateList::_DisposeUIWindow() {
  if (_ui == nullptr) {
    return;
  }

  _ui->Destroy();
}

void CCandidateList::_DisposeUIWindowAll() {
  if (_ui == nullptr) {
    return;
  }

  // call _ui->Destroy(true) to clean resources
  _ui->Destroy(true);
  _ui_warmed_up = false;
}

void CCandidateList::_MakeUIWindow() {
  HWND p = _GetActiveWnd();
  _ui->Create(p);
}

void WeaselTSF::_UpdateUI(const Context& ctx, const Status& status) {
  _cand->UpdateUI(ctx, status);
}

void WeaselTSF::_StartUI() {
  _cand->StartUI();
}

void WeaselTSF::_EndUI() {
  _cand->EndUI();
}

void WeaselTSF::_ShowUI() {
  _cand->Show(TRUE);
}

void WeaselTSF::_HideUI() {
  _cand->Show(FALSE);
}

com_ptr<ITfContext> WeaselTSF::_GetUIContextDocument() {
  return _cand->GetContextDocument();
}

void WeaselTSF::_DeleteCandidateList() {
  _cand->Destroy();
}

void WeaselTSF::_SelectCandidateOnCurrentPage(size_t index) {
  m_client.SelectCandidateOnCurrentPage(index);
  // simulate a VK_SELECT presskey to get data back and DoEditSession
  // the simulated keycode must be the one make TranslateKeycode Non-Zero return
  // fix me: are there any better ways?
  INPUT inputs[2];
  inputs[0].type = INPUT_KEYBOARD;
  inputs[0].ki = {VK_SELECT, 0, 0, 0, 0};
  inputs[1].type = INPUT_KEYBOARD;
  inputs[1].ki = {VK_SELECT, 0, KEYEVENTF_KEYUP, 0, 0};
  ::SendInput(sizeof(inputs) / sizeof(INPUT), inputs, sizeof(INPUT));
}

void WeaselTSF::_HandleMousePageEvent(bool* const nextPage,
                                      bool* const scrollNextPage) {
  // from scrolling event
  if (scrollNextPage) {
    if (_cand->style().paging_on_scroll)
      m_client.ChangePage(!(*scrollNextPage));
    else {
      UINT current_select = 0, cand_count = 0;
      _cand->GetSelection(&current_select);
      _cand->GetCount(&cand_count);
      bool is_reposition = _cand->GetIsReposition();
      int offset = *scrollNextPage ? 1 : -1;
      offset = offset * (is_reposition ? -1 : 1);
      int index = (int)current_select + offset;
      if (index >= 0 && index < (int)cand_count)
        m_client.HighlightCandidateOnCurrentPage((size_t)index);
      else {
        KeyEvent ke{0, 0};
        ke.keycode = (index < 0) ? ibus::Up : ibus::Down;
        m_client.ProcessKeyEvent(ke);
      }
    }
  } else {  // from click event
    m_client.ChangePage(!(*nextPage));
  }
  _UpdateComposition(_pEditSessionContext);
}

void WeaselTSF::_HandleMouseHoverEvent(const size_t index) {
  UINT current_select = 0;
  _cand->GetSelection(&current_select);

  if (index != current_select) {
    m_client.HighlightCandidateOnCurrentPage(index);
    _UpdateComposition(_pEditSessionContext);
  }
}

void WeaselTSF::HandleUICallback(size_t* const sel,
                                 size_t* const hov,
                                 bool* const next,
                                 bool* const scroll_next) {
  if (sel)
    _SelectCandidateOnCurrentPage(*sel);
  else if (hov)
    _HandleMouseHoverEvent(*hov);
  else if (next || scroll_next)
    _HandleMousePageEvent(next, scroll_next);
}
