#pragma once
#include <windows.h>

namespace qingshi {
inline bool UsableCaret(const RECT& caret, const RECT& client) {
  // Zero-width caret rectangles are valid; zero-height placeholders are not.
  if (caret.bottom <= caret.top || caret.bottom - caret.top > 512 ||
      caret.right < caret.left || client.right <= client.left || client.bottom <= client.top)
    return false;
  return caret.left >= client.left - 2 && caret.left <= client.right + 2 &&
         caret.top >= client.top - 2 && caret.top < client.bottom + 2 &&
         caret.bottom <= client.bottom + 32;
}
}
