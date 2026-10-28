#pragma once

// 青石五笔产品版本号（只用于「检查新版本」比对，与小狼毫上游版本无关）。
// 发版时必须同步修改：
//   rime-dev/gui/wubi_settings.py 的 APP_VER
//   rime-dev/gui/installer_backend.py 的 VERSION
//   rime-dev/release-manifest.json 的 version
#define QINGSHI_VERSION "1.0.14"

// 官网首页（检查到更新时提供的第二个下载入口）
#define QINGSHI_WEBSITE_URL L"https://qingshi.funnyai.wiki/"
