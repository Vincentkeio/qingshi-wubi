#pragma once

#include <windows.h>
#include <imm.h>
#include <immdev.h>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

namespace qingshi {
namespace imm {

// Offsets are bytes, string lengths are UTF-16 code units. IMM owns the
// surrounding HIMCC; callers copy this complete block into hCompStr.
inline std::vector<BYTE> ResultBlock(const std::wstring& text) {
  const size_t header = sizeof(COMPOSITIONSTRING) + 2 * sizeof(DWORD);
  if (text.size() > ((std::numeric_limits<DWORD>::max)() - header) /
                        sizeof(wchar_t))
    return {};
  const DWORD size = static_cast<DWORD>(header + text.size() * sizeof(wchar_t));
  std::vector<BYTE> block(size, 0);
  COMPOSITIONSTRING composition{};
  composition.dwSize = size;
  composition.dwResultStrLen = static_cast<DWORD>(text.size());
  composition.dwResultStrOffset = static_cast<DWORD>(header);
  composition.dwResultClauseLen = 2 * sizeof(DWORD);
  composition.dwResultClauseOffset = sizeof(COMPOSITIONSTRING);
  const DWORD clauses[] = {0, static_cast<DWORD>(text.size())};
  std::memcpy(block.data(), &composition, sizeof(composition));
  std::memcpy(block.data() + composition.dwResultClauseOffset, clauses,
              sizeof(clauses));
  std::memcpy(block.data() + composition.dwResultStrOffset, text.data(),
              text.size() * sizeof(wchar_t));
  return block;
}

inline bool StoreBlock(HIMCC& destination, const std::vector<BYTE>& block) {
  if (block.empty())
    return false;
  HIMCC resized = destination
      ? ::ImmReSizeIMCC(destination, static_cast<DWORD>(block.size()))
      : ::ImmCreateIMCC(static_cast<DWORD>(block.size()));
  if (!resized)
    return false;
  destination = resized;
  void* memory = ::ImmLockIMCC(destination);
  if (!memory)
    return false;
  std::memcpy(memory, block.data(), block.size());
  ::ImmUnlockIMCC(destination);
  return true;
}

// A result-only composition is deliberate: the existing server draws preedit
// and candidates. Windows still needs a complete start/result/end sequence.
inline UINT CommitResult(HIMC himc, const std::wstring& text,
                         LPTRANSMSGLIST output) {
  if (text.empty())
    return 0;
  const TRANSMSG messages[] = {
      {WM_IME_STARTCOMPOSITION, 0, 0},
      {WM_IME_COMPOSITION, 0, GCS_RESULTSTR | GCS_RESULTCLAUSE},
      {WM_IME_ENDCOMPOSITION, 0, 0}};
  constexpr UINT count = ARRAYSIZE(messages);
  LPINPUTCONTEXT context = ::ImmLockIMC(himc);
  if (!context)
    return 0;
  bool ok = StoreBlock(context->hCompStr, ResultBlock(text));
  if (ok && output && output->uMsgCount >= count) {
    std::memcpy(output->TransMsg, messages, sizeof(messages));
  } else if (ok) {
    // IMM uses hMsgBuf when the return count exceeds the caller's capacity.
    // For NotifyIME there is no caller buffer; ImmGenerateMessage drains it.
    std::vector<BYTE> bytes(sizeof(messages));
    std::memcpy(bytes.data(), messages, sizeof(messages));
    ok = StoreBlock(context->hMsgBuf, bytes);
    if (ok)
      context->dwNumMsgBuf = count;
  }
  ::ImmUnlockIMC(himc);
  return ok ? count : 0;
}

}  // namespace imm
}  // namespace qingshi
