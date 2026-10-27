#pragma once

// 青石五笔 TSF 诊断日志（仅元数据）。
//
// 只记录：窗口句柄、进程映像名、HRESULT、pbShow、UIElement ID、候选计数、
//         编码/候选的**长度**、屏幕矩形、窗口可见状态。
// 不记录：用户输入的编码、候选文字、文档内容。
//
// 开启：HKCU\Software\Rime\Weasel 下新建 DWORD 值 QingshiDiag = 1
//       运行中修改会在 2 秒内生效，不必重启宿主进程。
// 位置：%APPDATA%\QingshiWubi\qingshi-tsf-diag.log（超过 512KB 自动重建）

#include <windows.h>

#include <cstdarg>
#include <cstdio>
#include <string>

namespace qingshi {
namespace diag {

inline bool Enabled() {
  static ULONGLONG next_check = 0;
  static bool enabled = false;
  const ULONGLONG now = ::GetTickCount64();
  if (now >= next_check) {
    next_check = now + 2000;
    DWORD value = 0;
    DWORD size = sizeof(value);
    enabled = ::RegGetValueW(HKEY_CURRENT_USER, L"Software\\Rime\\Weasel",
                             L"QingshiDiag", RRF_RT_REG_DWORD, nullptr, &value,
                             &size) == ERROR_SUCCESS &&
              value != 0;
  }
  return enabled;
}

inline std::wstring LogPath() {
  wchar_t appdata[MAX_PATH] = {};
  const DWORD n = ::GetEnvironmentVariableW(L"APPDATA", appdata, MAX_PATH);
  if (n == 0 || n >= MAX_PATH)
    return std::wstring();
  std::wstring folder = std::wstring(appdata) + L"\\QingshiWubi";
  ::CreateDirectoryW(folder.c_str(), nullptr);
  return folder + L"\\qingshi-tsf-diag.log";
}

inline void Write(const wchar_t* text) {
  if (!text || !*text)
    return;
  const std::wstring path = LogPath();
  if (path.empty())
    return;

  WIN32_FILE_ATTRIBUTE_DATA attr{};
  if (::GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &attr) &&
      attr.nFileSizeHigh == 0 && attr.nFileSizeLow > 512u * 1024u)
    ::DeleteFileW(path.c_str());

  const int bytes = ::WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0,
                                          nullptr, nullptr);
  if (bytes <= 1)
    return;
  std::string utf8(static_cast<size_t>(bytes), '\0');
  ::WideCharToMultiByte(CP_UTF8, 0, text, -1, &utf8[0], bytes, nullptr,
                        nullptr);
  utf8.pop_back();

  FILE* file = nullptr;
  if (_wfopen_s(&file, path.c_str(), L"ab") != 0 || file == nullptr)
    return;
  ::fwrite(utf8.data(), 1, utf8.size(), file);
  ::fputc('\n', file);
  ::fclose(file);
}

inline void Log(const wchar_t* format, ...) {
  if (!Enabled() || !format)
    return;
  SYSTEMTIME st{};
  ::GetLocalTime(&st);
  wchar_t body[768] = {};
  va_list args;
  va_start(args, format);
  _vsnwprintf_s(body, ARRAYSIZE(body), _TRUNCATE, format, args);
  va_end(args);
  wchar_t line[1024] = {};
  _snwprintf_s(line, ARRAYSIZE(line), _TRUNCATE,
               L"%04d-%02d-%02d %02d:%02d:%02d.%03d [pid %lu tid %lu] %s",
               st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond,
               st.wMilliseconds, ::GetCurrentProcessId(), ::GetCurrentThreadId(),
               body);
  Write(line);
}

// 窗口所属进程的映像名（不含路径）。失败返回 "?"。
inline std::wstring ProcessImageOf(HWND window) {
  if (!window)
    return L"-";
  DWORD pid = 0;
  if (!::GetWindowThreadProcessId(window, &pid) || pid == 0)
    return L"?";
  HANDLE process =
      ::OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
  if (!process)
    return L"?";
  wchar_t image[MAX_PATH] = {};
  DWORD length = MAX_PATH;
  const BOOL ok = ::QueryFullProcessImageNameW(process, 0, image, &length);
  ::CloseHandle(process);
  if (!ok)
    return L"?";
  const wchar_t* name = wcsrchr(image, L'\\');
  return name ? std::wstring(name + 1) : std::wstring(image);
}

// "0x00120A3C(explorer.exe)"
inline std::wstring DescribeWindow(HWND window) {
  if (!window)
    return L"0x0(-)";
  wchar_t buffer[128] = {};
  _snwprintf_s(buffer, ARRAYSIZE(buffer), _TRUNCATE, L"0x%p(%s)",
               reinterpret_cast<void*>(window),
               ProcessImageOf(window).c_str());
  return std::wstring(buffer);
}

// 宿主线程的激活标志，用来判断是否处于 UILess（UIElementEnabledOnly）模式。
inline std::wstring DescribeThreadFlags(DWORD flags) {
  wchar_t buffer[256] = {};
  _snwprintf_s(buffer, ARRAYSIZE(buffer), _TRUNCATE,
               L"0x%08lX%s%s%s%s", flags,
               (flags & TF_TMF_UIELEMENTENABLEDONLY) ? L"|UIELEMENTONLY" : L"",
               (flags & TF_TMF_IMMERSIVEMODE) ? L"|IMMERSIVE" : L"",
               (flags & TF_TMF_CONSOLE) ? L"|CONSOLE" : L"",
               (flags & TF_TMF_ACTIVATED) ? L"|ACTIVATED" : L"");
  return std::wstring(buffer);
}

}  // namespace diag
}  // namespace qingshi
