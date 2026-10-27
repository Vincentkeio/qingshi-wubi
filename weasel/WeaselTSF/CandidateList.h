#pragma once
#include <WeaselUI.h>
#include "ctffunc.h"

class WeaselTSF;

class CCandidateList : public ITfIntegratableCandidateListUIElement,
                       public ITfCandidateListUIElementBehavior {
 public:
  CCandidateList(com_ptr<WeaselTSF> pTextService);
  ~CCandidateList();

  // IUnknown
  STDMETHODIMP QueryInterface(REFIID riid, _Outptr_ void** ppvObj);
  STDMETHODIMP_(ULONG) AddRef(void);
  STDMETHODIMP_(ULONG) Release(void);

  // ITfUIElement
  STDMETHODIMP GetDescription(BSTR* pbstr);
  STDMETHODIMP GetGUID(GUID* pguid);
  STDMETHODIMP Show(BOOL showCandidateWindow);
  STDMETHODIMP IsShown(BOOL* pIsShow);

  // ITfCandidateListUIElement
  STDMETHODIMP GetUpdatedFlags(DWORD* pdwFlags);
  STDMETHODIMP GetDocumentMgr(ITfDocumentMgr** ppdim);
  STDMETHODIMP GetCount(UINT* pCandidateCount);
  STDMETHODIMP GetSelection(UINT* pSelectedCandidateIndex);
  STDMETHODIMP GetString(UINT uIndex, BSTR* pbstr);
  STDMETHODIMP GetPageIndex(UINT* pIndex, UINT uSize, UINT* puPageCnt);
  STDMETHODIMP SetPageIndex(UINT* pIndex, UINT uPageCnt);
  STDMETHODIMP GetCurrentPage(UINT* puPage);

  // ITfCandidateListUIElementBehavior methods
  STDMETHODIMP SetSelection(UINT nIndex);
  STDMETHODIMP Finalize(void);
  STDMETHODIMP Abort(void);

  // ITfIntegratableCandidateListUIElement methods
  STDMETHODIMP SetIntegrationStyle(GUID guidIntegrationStyle);
  STDMETHODIMP GetSelectionStyle(
      _Out_ TfIntegratableCandidateListSelectionStyle* ptfSelectionStyle);
  STDMETHODIMP OnKeyDown(_In_ WPARAM wParam,
                         _In_ LPARAM lParam,
                         _Out_ BOOL* pIsEaten);
  STDMETHODIMP ShowCandidateNumbers(_Out_ BOOL* pIsShow);
  STDMETHODIMP FinalizeExactCompositionString();

  /* Update */
  void UpdateUI(const weasel::Context& ctx, const weasel::Status& status);
  // 只重绘本地候选窗，不回调宿主的 ITfCandidateListUIElement。
  // 固顶后的即时刷新用它 —— _UpdateUIElement 会重入宿主的 COM 对象，
  // 在右键/中键回调里调它会直接把宿主带崩。
  void UpdateLocalOnly(const weasel::Context& ctx,
                       const weasel::Status& status);
  void UpdateStyle(const weasel::UIStyle& sty);
  void UpdateInputPosition(RECT const& rc);
  void Destroy();
  void DestroyAll();
  void StartUI();
  void EndUI();

  com_ptr<ITfContext> GetContextDocument();
  bool GetIsReposition() {
    if (_ui)
      return _ui->GetIsReposition();
    else
      return false;
  }

  weasel::UIStyle& style();
  weasel::Context& ctx() { return _ui->ctx(); }
  // 纯本地重排：把 word 挪到第一位，只重排布局 + 重绘。
  // 不走 _UpdateUI / _UpdateUIElement，不碰宿主 COM，不会带崩宿主。
  void ReorderLocal(const std::wstring& word);
  // 把 word 挪到第 target 位（0 基），同样只重绘不回调宿主
  void MoveLocal(const std::wstring& word, size_t target);
  // 恢复到引擎原始顺序（取消固顶用）
  void RestoreLocal();
  // 本地重排后，界面上的第 i 个候选对应引擎里的第几个。
  // 空格 / 数字键必须按它换算，否则显示和实际选中的不一致。
  bool has_display_order() const { return !m_display_order.empty(); }
  size_t display_order_size() const { return m_display_order.size(); }
  size_t display_to_original(size_t i) const {
    return i < m_display_order.size() ? m_display_order[i] : i;
  }
  // 调序后延迟刷新：投递消息给候选窗，等回到消息循环再取新候选。
  void RequestShadowRefresh();
  void DoShadowRefresh();
  HWND hwnd() const { return _ui ? _ui->hwnd() : nullptr; }

 private:
  // void _UpdateOwner();
  HWND _GetActiveWnd();
  HRESULT _UpdateUIElement();
  // 由输入法自己创建并显示候选窗（宿主不画，或宿主明确不允许 TIP 画）
  void _EnableLocalUI(const wchar_t* reason);
  // 宿主来读取候选数据 = 宿主确实在自己画，不要再叠一层本地窗口
  void _MarkHostConsumed();

  // for CCandidateList::EndUI(), after ending composition ||
  // WeaselTSF::_EndUI()
  void _DisposeUIWindow();
  // for CCandidateList::Destroy(), when inputing app exit
  void _DisposeUIWindowAll();
  void _MakeUIWindow();

  std::unique_ptr<weasel::UI> _ui;
  DWORD _cRef;
  com_ptr<WeaselTSF> _tsf;
  DWORD uiid;
  TfIntegratableCandidateListSelectionStyle _selectionStyle =
      STYLE_ACTIVE_SELECTION;

  BOOL _pbShow;
  bool _uiStarted = false;
  // 下面三个标志描述"这一轮合成里宿主到底画不画候选"：
  //   _hostDeclined   BeginUIElement 返回 pbShow == FALSE，宿主声称自己画
  //   _hostConsumed   宿主真的来读了候选数据（GetCount/GetString/...）
  //   _localUI        候选窗由输入法自己创建并显示（宿主不画或允许 TIP 画）
  bool _hostDeclined = false;
  bool _hostConsumed = false;
  bool _localUI = false;
  // UILess 线程（游戏常走这条路）：宿主会来读候选数据，由宿主自己绘制。
  bool _uiLess = false;
  DWORD _updateSeq = 0;
  weasel::UIStyle _style;
  // 显示位置 → 引擎原始索引；空表示没重排过
  std::vector<size_t> m_display_order;
  // 第一次本地重排前的候选快照，取消固顶时用来还原
  std::vector<weasel::Text> m_original_candies;
  bool _ui_warmed_up = false;

  com_ptr<ITfContext> _pContextDocument;
};
