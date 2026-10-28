// 青石五笔 · 检查新版本（托盘菜单与命令行 /update 共用）
//
// 与设置面板 rime-dev/gui/update_checker.py 保持同一套规则：
// 读 GitHub 官方仓库的 releases/latest，比对 tag 版本，返回官方发布页。
// 本文件不依赖工程内其它模块，方便单独编译测试。

#include "QingshiUpdate.h"

#include <windows.h>
#include <winhttp.h>

#include <cctype>
#include <cstdlib>
#include <utility>

#pragma comment(lib, "winhttp.lib")

namespace qingshi {
namespace {

// ---- 与面板 update_checker.py 一致的常量 ----
constexpr wchar_t kHost[] = L"api.github.com";
constexpr wchar_t kPath[] = L"/repos/Vincentkeio/qingshi-wubi/releases/latest";
constexpr wchar_t kUserAgent[] = L"QingshiWubi-weasel-update-checker";
constexpr wchar_t kAccept[] = L"application/vnd.github+json";
constexpr char kReleasePrefix[] =
    "https://github.com/Vincentkeio/qingshi-wubi/releases/tag/";
constexpr size_t kMaxBytes = 1024 * 1024;

// WinHTTP 句柄的 RAII 包装
struct Handle {
  HINTERNET value = nullptr;

  Handle() = default;
  explicit Handle(HINTERNET handle) : value(handle) {}
  ~Handle() {
    if (value)
      WinHttpCloseHandle(value);
  }
  Handle(const Handle&) = delete;
  Handle& operator=(const Handle&) = delete;

  explicit operator bool() const { return value != nullptr; }
};

bool HttpGet(std::string* body, std::string* error) {
  // 与面板一样走系统（IE）代理设置
  Handle session(WinHttpOpen(kUserAgent, WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                             WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0));
  if (!session) {
    *error = "WinHttpOpen failed";
    return false;
  }
  // 面板的 urllib 超时是 12 秒，这里按阶段拆分
  WinHttpSetTimeouts(session.value, 5000, 5000, 5000, 12000);

  Handle connection(
      WinHttpConnect(session.value, kHost, INTERNET_DEFAULT_HTTPS_PORT, 0));
  if (!connection) {
    *error = "WinHttpConnect failed";
    return false;
  }

  Handle request(WinHttpOpenRequest(connection.value, L"GET", kPath, nullptr,
                                    WINHTTP_NO_REFERER,
                                    WINHTTP_DEFAULT_ACCEPT_TYPES,
                                    WINHTTP_FLAG_SECURE));
  if (!request) {
    *error = "WinHttpOpenRequest failed";
    return false;
  }

  const std::wstring headers = std::wstring(L"Accept: ") + kAccept + L"\r\n";
  if (!WinHttpSendRequest(request.value, headers.c_str(), static_cast<DWORD>(-1),
                          WINHTTP_NO_REQUEST_DATA, 0, 0, 0) ||
      !WinHttpReceiveResponse(request.value, nullptr)) {
    *error = "request failed, win32=" + std::to_string(GetLastError());
    return false;
  }

  DWORD status = 0;
  DWORD status_size = sizeof(status);
  WinHttpQueryHeaders(request.value,
                      WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                      WINHTTP_HEADER_NAME_BY_INDEX, &status, &status_size,
                      WINHTTP_NO_HEADER_INDEX);
  if (status != 200) {
    *error = "http status " + std::to_string(status);
    return false;
  }

  std::string data;
  for (;;) {
    DWORD available = 0;
    if (!WinHttpQueryDataAvailable(request.value, &available)) {
      *error = "WinHttpQueryDataAvailable failed";
      return false;
    }
    if (available == 0)
      break;
    std::string chunk(available, '\0');
    DWORD read = 0;
    if (!WinHttpReadData(request.value, chunk.data(), available, &read)) {
      *error = "WinHttpReadData failed";
      return false;
    }
    data.append(chunk.data(), read);
    if (data.size() > kMaxBytes) {
      *error = "响应超出大小限制";
      return false;
    }
  }

  *body = std::move(data);
  return true;
}

// 取 JSON 里第一个 "key": "value" 的字符串值（GitHub 返回的字段里没有转义引号）
std::string JsonString(const std::string& json, const char* key) {
  const std::string needle = std::string("\"") + key + "\"";
  size_t pos = json.find(needle);
  if (pos == std::string::npos)
    return {};
  pos = json.find(':', pos + needle.size());
  if (pos == std::string::npos)
    return {};
  pos = json.find('"', pos + 1);
  if (pos == std::string::npos)
    return {};
  std::string value;
  for (size_t i = pos + 1; i < json.size(); ++i) {
    const char ch = json[i];
    if (ch == '\\' && i + 1 < json.size()) {
      value.push_back(json[++i]);
      continue;
    }
    if (ch == '"')
      return value;
    value.push_back(ch);
  }
  return {};
}

bool JsonBool(const std::string& json, const char* key, bool fallback) {
  const std::string needle = std::string("\"") + key + "\"";
  size_t pos = json.find(needle);
  if (pos == std::string::npos)
    return fallback;
  pos = json.find(':', pos + needle.size());
  if (pos == std::string::npos)
    return fallback;
  ++pos;
  while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos])))
    ++pos;
  if (json.compare(pos, 4, "true") == 0)
    return true;
  if (json.compare(pos, 5, "false") == 0)
    return false;
  return fallback;
}

// 在响应里找出与官方 tag 页完全一致的 html_url（面板就是这么校验的）
std::string FindOfficialReleaseUrl(const std::string& json,
                                   const std::string& tag) {
  const std::string expected = std::string(kReleasePrefix) + tag;
  const std::string needle = "\"html_url\"";
  size_t pos = 0;
  while ((pos = json.find(needle, pos)) != std::string::npos) {
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos)
      break;
    pos = json.find('"', pos + 1);
    if (pos == std::string::npos)
      break;
    std::string value;
    size_t i = pos + 1;
    for (; i < json.size(); ++i) {
      if (json[i] == '"')
        break;
      value.push_back(json[i]);
    }
    if (value == expected)
      return value;
    pos = i;
  }
  return {};
}

// 只接受 X.Y.Z（可带前导 v），与面板的正则 fullmatch 一致
bool ParseVersion(const std::string& text, int out[3]) {
  std::string s = text;
  if (!s.empty() && (s[0] == 'v' || s[0] == 'V'))
    s.erase(0, 1);
  size_t i = 0;
  for (int part = 0; part < 3; ++part) {
    const size_t start = i;
    while (i < s.size() && std::isdigit(static_cast<unsigned char>(s[i])))
      ++i;
    if (i == start)
      return false;
    out[part] = std::atoi(s.substr(start, i - start).c_str());
    if (part < 2) {
      if (i >= s.size() || s[i] != '.')
        return false;
      ++i;
    }
  }
  return i == s.size();
}

bool VersionGreater(const int left[3], const int right[3]) {
  for (int i = 0; i < 3; ++i) {
    if (left[i] != right[i])
      return left[i] > right[i];
  }
  return false;
}

}  // namespace

UpdateInfo CheckLatestRelease(const std::string& current_version) {
  UpdateInfo info;

  int current[3] = {0, 0, 0};
  if (!ParseVersion(current_version, current)) {
    info.detail = "无法识别的本地版本号: " + current_version;
    return info;
  }

  std::string body;
  std::string error;
  if (!HttpGet(&body, &error)) {
    info.detail = "请求 GitHub 失败: " + error;
    return info;
  }

  const std::string tag = JsonString(body, "tag_name");
  if (tag.empty()) {
    info.detail = "响应缺少 tag_name";
    return info;
  }

  int latest[3] = {0, 0, 0};
  if (!ParseVersion(tag, latest)) {
    info.detail = "无法识别的 tag: " + tag;
    return info;
  }
  info.version = (tag[0] == 'v' || tag[0] == 'V') ? tag.substr(1) : tag;

  const std::string url = FindOfficialReleaseUrl(body, tag);
  if (url.empty()) {
    info.detail = "更新来源不是青石官方发布页";
    return info;
  }
  info.release_url = url;

  const bool draft = JsonBool(body, "draft", false);
  const bool prerelease = JsonBool(body, "prerelease", false);
  if (draft || prerelease) {
    info.detail = "最新发布是草稿或预发布，按最新正式版处理";
    info.status = UpdateInfo::kUpToDate;
    return info;
  }

  info.status =
      VersionGreater(latest, current) ? UpdateInfo::kNewer : UpdateInfo::kUpToDate;
  return info;
}

}  // namespace qingshi
