#pragma once

#include <string>

namespace qingshi {

// 检查青石五笔的最新正式版本。
//
// 规则与设置面板（rime-dev/gui/update_checker.py）完全一致：
//   * 数据源：GitHub 官方仓库 releases/latest 的 API
//   * 只认 tag 形如 vX.Y.Z、且不是 draft / prerelease
//   * 发布页必须是青石官方仓库的 tag 页
//   * 只做检查，永不下载、永不执行任何文件
//
// 注意：未认证的 GitHub API 每小时 60 次、按出口 IP 算，被限流时返回 403，
// 此时会提示「暂时无法检查更新」，属正常现象（一小时后自动恢复）。
struct UpdateInfo {
  enum Status {
    kUpToDate,  // 已是最新正式版本
    kNewer,     // 有新版本
    kFailed,    // 检查失败（网络或数据异常）
  };

  Status status = kFailed;
  std::string version;      // 最新正式版本号，如 "1.0.11"
  std::string release_url;  // 官方发布页
  std::string detail;       // 失败原因，仅写日志
};

UpdateInfo CheckLatestRelease(const std::string& current_version);

}  // namespace qingshi
