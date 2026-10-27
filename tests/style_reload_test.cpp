#include <windows.h>
#include <RimeWithWeasel.h>
#include <cassert>
#include <iostream>

int main() {
  RimeApi* api = rime_get_api();
  RimeConfig compiled{}, patch{};
  assert(api->config_init(&compiled));
  assert(api->config_init(&patch));
  const char* old_style =
      "style:\n  color_scheme: qingshi_blue\n  font_point: 13\n"
      "preset_color_schemes:\n  qingshi_blue:\n    color_format: argb\n"
      "    back_color: 0xffffff\n    hilited_candidate_back_color: 0x2868d7\n"
      "  qingshi_ink:\n    color_format: argb\n    back_color: 0xffffff\n"
      "    hilited_candidate_back_color: 0x2868d7\n";
  const char* new_style =
      "patch:\n  style:\n    color_scheme: qingshi_ink\n    font_point: 18\n"
      "  preset_color_schemes:\n    qingshi_ink:\n      color_format: argb\n"
      "      back_color: 0xf7f7f5\n      hilited_candidate_back_color: 0x4a4a46\n";
  assert(api->config_load_string(&compiled, old_style));
  assert(api->config_load_string(&patch, new_style));
  weasel::UIStyle style;
  LoadWeaselUIStyleWithPatch(&compiled, &patch, style);
  assert(style.font_point == 18);
  assert(static_cast<unsigned int>(style.back_color) == 0xfff5f7f7);
  assert(static_cast<unsigned int>(style.hilited_candidate_back_color) == 0xff464a4a);
  // The scoped overlay must not leak into the next unpatched read.
  LoadWeaselUIStyle(&compiled, style, true);
  assert(style.font_point == 13);
  assert(static_cast<unsigned int>(style.hilited_candidate_back_color) == 0xffd76828);
  api->config_close(&patch);
  api->config_close(&compiled);
  std::cout << "PASS: saved ink colors and font override stale compiled blue; overlay does not leak.\n";
}
