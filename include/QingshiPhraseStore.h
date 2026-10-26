#pragma once

#include <algorithm>
#include <string>
#include <vector>

namespace qingshi {
struct Phrase {
  std::wstring word;
  std::wstring code;
};

struct PinHistory {
  std::wstring word;
  std::wstring code;
  int original_index;  // -1 means this word originally came only from the base dictionary.
};

inline std::vector<PinHistory> ParseHistory(const std::vector<std::wstring>& lines) {
  std::vector<PinHistory> result;
  for (const auto& line : lines) {
    if (line.empty() || line.front() == L'#')
      continue;
    auto tab = line.find(L'\t');
    auto tab2 = tab == std::wstring::npos ? tab : line.find(L'\t', tab + 1);
    if (tab == std::wstring::npos || tab2 == std::wstring::npos)
      continue;
    try {
      result.push_back({line.substr(0, tab), line.substr(tab + 1, tab2 - tab - 1),
                         std::stoi(line.substr(tab2 + 1))});
    } catch (...) {
      // A malformed history row must not block normal phrase handling.
    }
  }
  return result;
}

inline std::vector<std::wstring> HistoryLines(const std::vector<PinHistory>& history) {
  std::vector<std::wstring> lines{L"# 青石五笔 · 固顶前的位置"};
  for (const auto& item : history)
    lines.push_back(item.word + L"\t" + item.code + L"\t" + std::to_wstring(item.original_index));
  return lines;
}

inline void RememberPosition(std::vector<PinHistory>& history, const std::vector<Phrase>& entries,
                               const std::wstring& word, const std::wstring& code) {
  for (const auto& item : history)
    if (item.word == word && item.code == code)
      return;  // Repeated pinning must keep the first pre-pin position.
  int original = -1;
  for (size_t i = 0; i < entries.size(); ++i)
    if (entries[i].word == word && entries[i].code == code) {
      original = static_cast<int>(i);
      break;
    }
  history.push_back({word, code, original});
}

inline std::wstring NormalizeCode(const std::wstring& input) {
  std::wstring code;
  for (auto ch : input) {
    if (ch == L' ' || ch == L'\'' || ch == L'\t')
      continue;
    if (ch >= L'A' && ch <= L'Z')
      ch += L'a' - L'A';
    if (ch < L'a' || ch > L'z')
      return {};
    code += ch;
  }
  return code;
}

// StableDb consumes plain TSV. Also accept the older optional YAML header,
// without using its delimiters to decide whether subsequent TSV rows count.
inline std::vector<Phrase> ParsePhrases(const std::vector<std::wstring>& lines) {
  std::vector<Phrase> entries;
  for (auto line : lines) {
    if (!line.empty() && line.front() == 0xfeff)
      line.erase(line.begin());
    if (!line.empty() && line.back() == L'\r')
      line.pop_back();
    auto first = line.find_first_not_of(L" \t");
    if (first == std::wstring::npos || line[first] == L'#')
      continue;
    auto tab = line.find(L'\t');
    if (tab == std::wstring::npos || tab == 0)
      continue;
    auto tab2 = line.find(L'\t', tab + 1);
    auto code = NormalizeCode(line.substr(tab + 1, tab2 == std::wstring::npos ? tab2 : tab2 - tab - 1));
    if (!code.empty())
      entries.push_back({line.substr(0, tab), code});
  }
  return entries;
}

inline bool RemovePhrase(std::vector<Phrase>& entries, const std::wstring& word,
                          const std::wstring& code) {
  auto old_size = entries.size();
  entries.erase(std::remove_if(entries.begin(), entries.end(), [&](const Phrase& entry) {
    return entry.word == word && entry.code == code;
  }), entries.end());
  return entries.size() != old_size;
}

inline bool PinPhrase(std::vector<Phrase>& entries, const std::wstring& word,
                       const std::wstring& code, int position) {
  if (word.empty() || code.empty())
    return false;
  RemovePhrase(entries, word, code);
  auto insertion = entries.end();
  int count = 0;
  for (auto it = entries.begin(); it != entries.end(); ++it) {
    if (it->code != code)
      continue;
    insertion = it + 1;
    if (++count == (std::max)(1, position)) {
      insertion = it;
      break;
    }
  }
  entries.insert(insertion, {word, code});
  return true;
}

inline bool RestorePosition(std::vector<Phrase>& entries, std::vector<PinHistory>& history,
                              const std::wstring& word, const std::wstring& code) {
  bool changed = RemovePhrase(entries, word, code);
  for (auto it = history.begin(); it != history.end(); ++it) {
    if (it->word != word || it->code != code)
      continue;
    if (it->original_index >= 0) {
      auto index = (std::min)(static_cast<size_t>(it->original_index), entries.size());
      entries.insert(entries.begin() + index, {word, code});
    }
    history.erase(it);
    return true;
  }
  return changed;  // Old pins without history fall back to the base dictionary order.
}

inline std::vector<std::wstring> PhraseLines(const std::vector<Phrase>& entries) {
  std::vector<std::wstring> result = {L"# 青石五笔 · 自定义词条 / 固顶词条",
                                      L"# 每行：词条<TAB>编码<TAB>权重"};
  for (size_t i = 0; i < entries.size(); ++i) {
    result.push_back(entries[i].word + L"\t" + entries[i].code + L"\t" +
                     std::to_wstring((std::max)(1, 9999 - static_cast<int>(i))));
  }
  return result;
}
}  // namespace qingshi
