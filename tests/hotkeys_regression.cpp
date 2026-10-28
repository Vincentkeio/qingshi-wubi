#include <windows.h>
#include <rime_api.h>
#include <cassert>
#include <iostream>
#include <string>

std::string utf8(const wchar_t* value) {
  int n = WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
  std::string result(n, '\0');
  WideCharToMultiByte(CP_UTF8, 0, value, -1, result.data(), n, nullptr, nullptr);
  result.pop_back();
  return result;
}
int page(RimeApi* api, RimeSessionId session) {
  RIME_STRUCT(RimeContext, context);
  assert(api->get_context(session, &context));
  int value = context.menu.page_no;
  api->free_context(&context);
  return value;
}
int count(RimeApi* api, RimeSessionId session) {
  RIME_STRUCT(RimeContext, context);
  assert(api->get_context(session, &context));
  int value = context.menu.num_candidates;
  api->free_context(&context);
  return value;
}
int wmain(int argc, wchar_t** argv) {
  assert(argc == 3 || argc == 4);
  std::string shared = utf8(argv[1]), user = utf8(argv[2]);
  RimeApi* api = rime_get_api();
  RIME_STRUCT(RimeTraits, traits);
  traits.shared_data_dir = shared.c_str();
  traits.user_data_dir = user.c_str();
  traits.app_name = "rime.qingshi_hotkeys_test";
  api->setup(&traits);
  api->initialize(&traits);
  if (api->start_maintenance(True)) api->join_maintenance_thread();
  auto session = api->create_session();
  for (const char* schema : {"wubi86", "wubi98", "wubi06"}) {
    assert(api->select_schema(session, schema));
    api->set_option(session, "ascii_mode", false);
    if (argc == 4) {
      api->process_key(session, 0xffe1, 1);
      api->process_key(session, 0xffe1, 1 << 30);
      assert(api->get_option(session, "ascii_mode"));
      api->process_key(session, 0xffe1, 1);
      api->process_key(session, 0xffe1, 1 << 30);
      assert(!api->get_option(session, "ascii_mode"));
      api->simulate_key_sequence(session, "{F8}");
      assert(!api->get_option(session, "ascii_mode"));
      std::cout << "PASS " << schema << ": restored defaults and Shift toggle\n";
      continue;
    }
    api->process_key(session, 0xffe1, 1);
    api->process_key(session, 0xffe1, 1 << 30);
    assert(!api->get_option(session, "ascii_mode"));
    api->simulate_key_sequence(session, "{F8}");
    assert(api->get_option(session, "ascii_mode"));
    api->simulate_key_sequence(session, "{F8}");
    assert(!api->get_option(session, "ascii_mode"));
    api->simulate_key_sequence(session, "{Control+Alt+e}");
    assert(api->get_option(session, "ascii_mode"));
    api->simulate_key_sequence(session, "{Control+Alt+e}");
    assert(!api->get_option(session, "ascii_mode"));
    for (auto pair : {std::pair<const char*,const char*>{"traditional","{Control+Alt+t}"},
                       {"full_shape","{Control+Alt+w}"}, {"ascii_punct","{Control+Alt+p}"},
                       {"extended_charset","{Control+Alt+g}"}}) {
      api->set_option(session, pair.first, false);
      api->simulate_key_sequence(session, pair.second);
      assert(api->get_option(session, pair.first));
      api->simulate_key_sequence(session, pair.second);
      assert(!api->get_option(session, pair.first));
    }
    api->simulate_key_sequence(session, "{Control+Shift+F}");
    assert(!api->get_option(session, "traditional"));
    api->simulate_key_sequence(session, "{Shift+space}");
    assert(!api->get_option(session, "full_shape"));
    api->clear_composition(session);
    api->simulate_key_sequence(session, "w");
    assert(count(api, session) >= 3 && page(api, session) == 0);
    api->simulate_key_sequence(session, "{bracketright}");
    assert(page(api, session) == 1);
    api->simulate_key_sequence(session, "{bracketleft}");
    assert(page(api, session) == 0);
    api->clear_composition(session);
    api->simulate_key_sequence(session, "{F4}");
    assert(count(api, session) == 0);
    api->simulate_key_sequence(session, "{F9}");
    assert(count(api, session) > 0);
    api->simulate_key_sequence(session, "{Escape}");
    std::cout << "PASS " << schema << ": custom modes, paging, schema menu, old keys unbound\n";
  }
  api->destroy_session(session);
  api->finalize();
  return 0;
}
