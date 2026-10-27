#include "../weasel/WeaselIME/ImmResult.h"
#include <cassert>
#include <iostream>
#include <cstdlib>

static void CheckResult(HIMC himc, const std::wstring& expected) {
  auto context = ImmLockIMC(himc);
  assert(context);
  auto result = static_cast<COMPOSITIONSTRING*>(ImmLockIMCC(context->hCompStr));
  assert(result);
  assert(result->dwSize <= ImmGetIMCCSize(context->hCompStr));
  assert(result->dwResultStrLen == expected.size());
  assert(result->dwCompStrLen == 0);
  auto text = reinterpret_cast<const wchar_t*>(
      reinterpret_cast<const BYTE*>(result) + result->dwResultStrOffset);
  assert(std::wstring(text, result->dwResultStrLen) == expected);
  auto clauses = reinterpret_cast<const DWORD*>(
      reinterpret_cast<const BYTE*>(result) + result->dwResultClauseOffset);
  assert(result->dwResultClauseLen == 2 * sizeof(DWORD));
  assert(clauses[0] == 0 && clauses[1] == expected.size());
  ImmUnlockIMCC(context->hCompStr);
  ImmUnlockIMC(himc);
}

int wmain(int argc, wchar_t** argv) {
  _set_abort_behavior(0, _CALL_REPORTFAULT);
  assert(argc == 2);
  auto dll = LoadLibraryW(argv[1]);
  assert(dll);
  const char* exports[] = {"ImeInquire", "ImeSelect", "ImeProcessKey",
      "ImeToAsciiEx", "NotifyIME", "ImeSetCompositionString", "ImeDestroy"};
  for (auto name : exports)
    assert(GetProcAddress(dll, name));
  using Inquire = BOOL(WINAPI*)(LPIMEINFO, LPWSTR, DWORD);
  auto inquire = reinterpret_cast<Inquire>(GetProcAddress(dll, "ImeInquire"));
  IMEINFO info{};
  wchar_t class_name[IME_UI_CLASS_NAME_SIZE]{};
  assert(inquire(&info, class_name, 0));
  WNDCLASSEXW wc{sizeof(wc)};
  assert(GetClassInfoExW(dll, class_name, &wc));
  assert(wc.style & CS_IME);
  assert(wc.cbWndExtra >= 2 * sizeof(LONG_PTR));
  assert(!inquire(nullptr, class_name, 0));
  assert(inquire(&info, class_name, 0)); // repeated inquiry must succeed

  auto himc = ImmCreateContext();
  assert(himc);
  HWND edit = CreateWindowExW(0, L"EDIT", L"", WS_POPUP, 0, 0, 200, 30,
                               nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
  assert(edit);
  ImmAssociateContext(edit, himc);
  auto initialized_context = ImmLockIMC(himc);
  if (!initialized_context)
    std::cerr << "ImmLockIMC unavailable: " << GetLastError() << '\n';
  assert(initialized_context);
  ImmUnlockIMC(himc);
  using Select = BOOL(WINAPI*)(HIMC, BOOL);
  auto select = reinterpret_cast<Select>(GetProcAddress(dll, "ImeSelect"));
  assert(select(himc, TRUE));
  assert(ImmGetOpenStatus(himc));
  struct Output {
    UINT capacity;
    TRANSMSG messages[3];
    DWORD sentinel;
  } output{};
  output.capacity = 3;
  output.sentinel = 0x12345678;
  auto list = reinterpret_cast<LPTRANSMSGLIST>(&output);
  const std::wstring text = L"青石\U00020000";
  assert(qingshi::imm::CommitResult(himc, text, list) == 3);
  assert(output.sentinel == 0x12345678);
  assert(output.capacity == 3);
  assert(output.messages[0].message == WM_IME_STARTCOMPOSITION);
  assert(output.messages[1].message == WM_IME_COMPOSITION);
  assert(output.messages[1].lParam & GCS_RESULTSTR);
  assert(output.messages[2].message == WM_IME_ENDCOMPOSITION);
  CheckResult(himc, text);

  output.capacity = 1;
  output.messages[0].message = 0x9876;
  assert(qingshi::imm::CommitResult(himc, L"你好", list) == 3);
  assert(output.messages[0].message == 0x9876); // no overrun of caller capacity
  CheckResult(himc, L"你好");
  auto context = ImmLockIMC(himc);
  assert(context->dwNumMsgBuf == 3);
  auto messages = static_cast<TRANSMSG*>(ImmLockIMCC(context->hMsgBuf));
  assert(messages && messages[1].lParam & GCS_RESULTSTR);
  assert(messages[2].message == WM_IME_ENDCOMPOSITION);
  ImmUnlockIMCC(context->hMsgBuf);
  ImmUnlockIMC(himc);
  assert(qingshi::imm::CommitResult(himc, L"", list) == 0);
  assert(qingshi::imm::CommitResult(nullptr, L"x", list) == 0);
  assert(select(himc, FALSE));
  ImmAssociateContext(edit, nullptr);
  ImmDestroyContext(himc);
  DestroyWindow(edit);
  // The test owns this registration; production IMM unload manages its class.
  UnregisterClassW(class_name, dll);
  FreeLibrary(dll);
  std::cout << "IMM result, capacity, UTF-16 and DLL entry-point tests passed\n";
}
