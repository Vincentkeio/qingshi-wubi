#include "../include/QingshiPhraseStore.h"
#include "../include/QingshiCaretGeometry.h"
#include <cassert>
#include <iostream>

int main() {
  RECT normal{100, 100, 900, 700};
  assert(qingshi::UsableCaret({300, 250, 300, 275}, normal));
  assert(!qingshi::UsableCaret({0, 0, 0, 0}, normal));
  assert(!qingshi::UsableCaret({0, 0, 1, 20}, normal));
  assert(!qingshi::UsableCaret({100, 100, 101, 100}, normal));
  // Secondary monitors to the left must remain valid.
  assert(qingshi::UsableCaret({-1200, 200, -1200, 224}, {-1920, 0, 0, 1080}));
  // A real text field at the desktop origin is valid, unlike an empty placeholder.
  assert(qingshi::UsableCaret({0, 0, 0, 24}, {0, 0, 1000, 800}));
  // Current plain TSV is what the settings panel and right-click menu both write.
  auto entries = qingshi::ParsePhrases({L"# comment", L"目标\tfjfc\t9999",
                                       L"保留\tfjfc\t9998", L"目标\tdddd\t9997"});
  assert(entries.size() == 3);
  assert(qingshi::RemovePhrase(entries, L"目标", L"fjfc"));
  assert(entries.size() == 2);
  assert(entries[0].word == L"保留");
  assert(entries[1].word == L"目标" && entries[1].code == L"dddd");
  assert(!qingshi::RemovePhrase(entries, L"不存在", L"fjfc"));
  // Old YAML header must not hide the actual TSV rows after its closing delimiter.
  auto legacy = qingshi::ParsePhrases({L"\ufeff# Rime", L"---", L"name: custom_phrase", L"...",
                                      L"旧词\tfjfc\t9999\r", L"另词\tfjfc\t9000"});
  assert(legacy.size() == 2);
  assert(qingshi::RemovePhrase(legacy, L"旧词", L"fjfc"));
  assert(legacy.size() == 1 && legacy[0].word == L"另词");
  // Re-pinning must preserve unrelated entries rather than recreating an empty file.
  assert(qingshi::PinPhrase(entries, L"新词", L"fjfc", 1));
  assert(entries.size() == 3 && entries[0].word == L"新词");
  assert(qingshi::PinPhrase(entries, L"新词", L"fjfc", 2));
  assert(entries.size() == 3 && entries[0].word == L"保留");
  auto round_trip = qingshi::ParsePhrases(qingshi::PhraseLines(entries));
  assert(round_trip.size() == entries.size());
  assert(qingshi::NormalizeCode(L"FJ FC") == L"fjfc");
  assert(qingshi::NormalizeCode(L"中文").empty());
  std::vector<qingshi::Phrase> original{{L"原第一", L"aaaa"}, {L"原第二", L"aaaa"}, {L"原第三", L"aaaa"}};
  std::vector<qingshi::PinHistory> history;
  qingshi::RememberPosition(history, original, L"原第三", L"aaaa");
  qingshi::PinPhrase(original, L"原第三", L"aaaa", 1);
  qingshi::RememberPosition(history, original, L"原第三", L"aaaa");
  qingshi::PinPhrase(original, L"原第三", L"aaaa", 2);
  assert(history.size() == 1 && history[0].original_index == 2);
  history = qingshi::ParseHistory(qingshi::HistoryLines(history));
  assert(qingshi::RestorePosition(original, history, L"原第三", L"aaaa"));
  assert(history.empty() && original.size() == 3);
  assert(original[0].word == L"原第一" && original[1].word == L"原第二" && original[2].word == L"原第三");
  qingshi::RememberPosition(history, original, L"码表词", L"aaaa");
  qingshi::PinPhrase(original, L"码表词", L"aaaa", 1);
  assert(qingshi::RestorePosition(original, history, L"码表词", L"aaaa"));
  assert(original.size() == 3 && history.empty());
  std::cout << "Phrase parser, unpin, legacy input, code isolation and preservation passed.\n";
}
