#include <rime_api.h>
#include <windows.h>
#include "../include/QingshiPhraseStore.h"
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace fs = std::filesystem;
std::string utf8(const std::wstring& text) {
  int size = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
  std::string output(size, 0);
  WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), size, nullptr, nullptr);
  return output;
}
std::wstring wide(const std::string& text) {
  int size = MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0);
  std::wstring output(size, 0);
  MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), size);
  return output;
}
std::vector<std::string> candidates(RimeApi* api, RimeSessionId session, const char* code = "dddd") {
  api->clear_composition(session);
  api->simulate_key_sequence(session, code);
  RIME_STRUCT(RimeContext, context);
  assert(api->get_context(session, &context));
  std::vector<std::string> result;
  for (int i = 0; i < context.menu.num_candidates; ++i)
    result.push_back(context.menu.candidates[i].text);
  api->free_context(&context);
  api->clear_composition(session);
  return result;
}
void write(const fs::path& file, const std::vector<qingshi::Phrase>& entries) {
  std::ofstream stream(file, std::ios::binary | std::ios::trunc);
  for (const auto& line : qingshi::PhraseLines(entries))
    stream << utf8(line) << '\n';
  stream.flush();
  assert(stream.good());
}

int wmain(int argc, wchar_t** argv) {
  assert(argc == 3);
  std::string shared = utf8(argv[1]), user = utf8(argv[2]);
  RimeApi* api = rime_get_api();
  RIME_STRUCT(RimeTraits, traits);
  traits.shared_data_dir = shared.c_str();
  traits.user_data_dir = user.c_str();
  traits.app_name = "rime.qingshi_regression";
  api->setup(&traits);
  api->initialize(&traits);
  if (api->start_maintenance(True))
    api->join_maintenance_thread();
  auto session = api->create_session();
  assert(api->select_schema(session, "wubi86"));
  // Check actual Rime mode behavior, including both Shift keys and initial modes.
  for (int shift : {0xffe1, 0xffe2}) {
    for (bool initial_english : {false, true}) {
      api->set_option(session, "ascii_mode", initial_english);
      api->process_key(session, shift, 1);
      api->process_key(session, 'A', (1 << 30) | 1); // TSF direct-letter notification
      api->process_key(session, 'B', (1 << 30) | 1);
      api->process_key(session, shift, 1 << 30);
      assert(bool(api->get_option(session, "ascii_mode")) == initial_english);
      RIME_STRUCT(RimeCommit, commit);
      assert(!api->get_commit(session, &commit)); // no duplicate uppercase letters
      api->process_key(session, shift, 1);
      api->process_key(session, shift, 1 << 30);
      assert(bool(api->get_option(session, "ascii_mode")) != initial_english); // standalone still toggles
    }
  }
  api->set_option(session, "ascii_mode", false);
  // Selecting later candidates repeatedly must never train a new ranking.
  for (const char* schema : {"wubi86", "wubi98", "wubi06"}) {
    assert(api->select_schema(session, schema));
    api->set_option(session, "ascii_mode", false);
    auto fixed = candidates(api, session, "a");
    assert(fixed.size() >= 2);
    for (int repetition = 0; repetition < 40; ++repetition) {
      api->simulate_key_sequence(session, "a");
      assert(api->select_candidate_on_current_page(session, 1));
      RIME_STRUCT(RimeCommit, selected);
      assert(api->get_commit(session, &selected));
      assert(std::string(selected.text) == fixed[1]);
      api->free_commit(&selected);
      assert(candidates(api, session, "a") == fixed);
    }
  }
  assert(api->select_schema(session, "wubi86"));
  auto baseline = candidates(api, session);
  assert(baseline.size() >= 3);
  auto word = wide(baseline[2]);
  std::vector<qingshi::Phrase> phrases;
  std::vector<qingshi::PinHistory> history;
  qingshi::RememberPosition(history, phrases, word, L"dddd");
  qingshi::PinPhrase(phrases, word, L"dddd", 1);
  auto phrase_file = fs::path(argv[2]) / L"custom_phrase.txt";
  write(phrase_file, phrases);
  api->destroy_session(session);
  api->finalize();
  api->initialize(&traits);
  session = api->create_session();
  assert(api->select_schema(session, "wubi86"));
  auto pinned = candidates(api, session);
  assert(!pinned.empty() && pinned.front() == baseline[2]);
  assert(qingshi::RestorePosition(phrases, history, word, L"dddd"));
  write(phrase_file, phrases);
  api->destroy_session(session);
  api->finalize();
  api->initialize(&traits);
  session = api->create_session();
  assert(api->select_schema(session, "wubi86"));
  auto restored = candidates(api, session);
  assert(restored == baseline);
  api->destroy_session(session);
  api->finalize();
  std::cout << "PASS: All three schemas keep candidate order after 40 repeated selections each; Shift chords preserve mode, no duplicate commit; unpin restores original sequence.\n";
}
