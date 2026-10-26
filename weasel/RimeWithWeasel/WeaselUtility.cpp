#include "stdafx.h"
#include <filesystem>
#include <string>
#include <fstream>
#include <WeaselUtility.h>

fs::path WeaselUserDataPath() {
  WCHAR _path[MAX_PATH] = {0};
  // Installed builds use an isolated per-user directory, including other accounts.
  WCHAR module[MAX_PATH] = {0};
  GetModuleFileNameW(NULL, module, _countof(module));
  auto package_root = fs::path(module).parent_path().parent_path();
  if (fs::exists(package_root / L".qingshi-install.json")) {
    ExpandEnvironmentStringsW(L"%AppData%\\QingshiWubi", _path, _countof(_path));
    fs::path user_dir(_path);
    if (fs::create_directories(user_dir)) {
      std::ofstream marker(user_dir / L".qingshi-data.json");
      marker << "{\"app_id\":\"QingshiWubi\"}";
    }
    return user_dir;
  }
  const WCHAR KEY[] = L"Software\\Rime\\Weasel";
  HKEY hKey;
  LSTATUS ret = RegOpenKey(HKEY_CURRENT_USER, KEY, &hKey);
  if (ret == ERROR_SUCCESS) {
    DWORD len = sizeof(_path);
    DWORD type = 0;
    DWORD data = 0;
    ret =
        RegQueryValueEx(hKey, L"RimeUserDir", NULL, &type, (LPBYTE)_path, &len);
    RegCloseKey(hKey);
    if (ret == ERROR_SUCCESS && type == REG_SZ && _path[0]) {
      return fs::path(_path);
    }
  }
  // default location
  ExpandEnvironmentStringsW(L"%AppData%\\Rime", _path, _countof(_path));
  return fs::path(_path);
}

fs::path WeaselSharedDataPath() {
  wchar_t _path[MAX_PATH] = {0};
  GetModuleFileNameW(NULL, _path, _countof(_path));
  return fs::path(_path).remove_filename().append("data");
}

std::string GetCustomResource(const char* name, const char* type) {
  const HINSTANCE module = 0;  // main executable
  HRSRC hRes = FindResourceA(module, name, type);
  if (hRes) {
    HGLOBAL hData = LoadResource(module, hRes);
    if (hData) {
      const char* data = (const char*)::LockResource(hData);
      size_t size = ::SizeofResource(module, hRes);

      if (data && size) {
        if (data[size - 1] == '\0')  // null-terminated string
          size--;
        return std::string(data, size);
      }
    }
  }

  return std::string();
}
