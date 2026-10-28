#pragma once

#include <windows.h>
#include <shellapi.h>
#include <filesystem>
#include <string>

namespace qingshi {

inline bool OpenSettings() {
  namespace fs = std::filesystem;
  // Reuse an already open settings window without starting another interpreter.
  HWND existing = FindWindowW(nullptr, L"青石五笔输入法 · 设置");
  if (existing) {
    ShowWindow(existing, IsIconic(existing) ? SW_RESTORE : SW_SHOW);
    SetForegroundWindow(existing);
    return true;
  }
  wchar_t root[MAX_PATH]{};
  DWORD bytes = sizeof(root);
  HKEY key = nullptr;
  wchar_t runtime[MAX_PATH]{};
  DWORD runtime_bytes = sizeof(runtime);
  LONG runtime_result = ERROR_FILE_NOT_FOUND;
  LONG result = RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"Software\\QingshiWubi", 0,
                              KEY_READ | KEY_WOW64_64KEY, &key);
  if (result == ERROR_SUCCESS) {
    result = RegGetValueW(key, nullptr, L"InstallDir", RRF_RT_REG_SZ, nullptr, root, &bytes);
    runtime_result = RegGetValueW(key, nullptr, L"RuntimeDir", RRF_RT_REG_SZ, nullptr, runtime, &runtime_bytes);
    RegCloseKey(key);
  }
  if (runtime_result == ERROR_SUCCESS) {
    const auto fast = fs::path(runtime) / L"settings/QingshiSettings.exe";
    if (fs::is_regular_file(fast))
      return reinterpret_cast<INT_PTR>(ShellExecuteW(nullptr, L"open", fast.c_str(),
          nullptr, fast.parent_path().c_str(), SW_SHOWNORMAL)) > 32;
  }
  if (result == ERROR_SUCCESS) {
    const auto app = fs::path(root) / L"Qingshi.exe";
    if (fs::is_regular_file(app))
      return reinterpret_cast<INT_PTR>(ShellExecuteW(nullptr, L"open", app.c_str(),
          L"--settings", root, SW_SHOWNORMAL)) > 32;
  }

  wchar_t module[MAX_PATH]{};
  GetModuleFileNameW(nullptr, module, MAX_PATH);
  const auto directory = fs::path(module).parent_path();
  const auto app = directory.parent_path() / L"Qingshi.exe";
  if (fs::is_regular_file(app))
    return reinterpret_cast<INT_PTR>(ShellExecuteW(nullptr, L"open", app.c_str(),
        L"--settings", app.parent_path().c_str(), SW_SHOWNORMAL)) > 32;

  // Source-tree development can use pythonw directly, without ever spawning cmd.
  const auto script = directory.parent_path().parent_path() / L"gui" / L"wubi_settings.py";
  wchar_t profile[MAX_PATH]{};
  if (fs::is_regular_file(script) && GetEnvironmentVariableW(L"USERPROFILE", profile, MAX_PATH)) {
    const auto python = fs::path(profile) / L".workbuddy-ai/binaries/python/envs/default/Scripts/pythonw.exe";
    if (fs::is_regular_file(python)) {
      const auto args = L"\"" + script.wstring() + L"\"";
      return reinterpret_cast<INT_PTR>(ShellExecuteW(nullptr, L"open", python.c_str(),
          args.c_str(), script.parent_path().c_str(), SW_SHOWNORMAL)) > 32;
    }
  }
  return false;
}

}  // namespace qingshi
