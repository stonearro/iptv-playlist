# IPTV 直播源（每日自动更新）

![更新 IPTV 播放列表](https://github.com/stonearro/iptv-playlist/actions/workflows/update.yml/badge.svg)

通过 GitHub Actions 每天自动聚合、清洗并实测公开 IPTV 直播源，生成可直接导入播放器的 M3U 播放列表。

**一个链接放进播放器，就能看到频道列表**，不需要逐个添加电视台地址。

## 国内可用地址（推荐）

以下地址均已实测能返回完整列表，按速度排序。**任意一个都可以直接放进播放器**；某个打不开时换下一个。

**最快单线路地址**

```text
https://ghproxy.imciel.com/https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/all.m3u
```

| 线路 | 单线路地址 | 实测速度 |
| --- | --- | --- |
| GitHub 加速 ① | `https://ghproxy.imciel.com/https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/all.m3u` | 约 1.8 秒 |
| GitHub 加速 ② | `https://gh-proxy.com/https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/all.m3u` | 约 2.1 秒 |
| GitHub 加速 ③ | `https://gh-proxy.org/https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/all.m3u` | 约 2.6 秒 |
| jsDelivr 国内 CDN | `https://quantil.jsdelivr.net/gh/stonearro/iptv-playlist@main/output/all.m3u` | 约 3.1 秒 |
| jsDelivr 全球 | `https://cdn.jsdelivr.net/gh/stonearro/iptv-playlist@main/output/all.m3u` | 约 3.6 秒 |

**多线路版**：把上面地址中的 `all.m3u` 换成 `multi.m3u`。

**GitHub 原始地址（部分网络可能打不开，仅作备用）**

```text
https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/all.m3u
```

> 加速站点是第三方公共服务，可能限速、缓存或临时失效；如果全部打不开，可稍后重试或使用 GitHub 原始地址。

## 全部频道与分类（GitHub 原始地址）

推荐先使用「单线路版」；如果某个频道打不开，再换「多线路版」。

| 版本 | 地址 |
| --- | --- |
| 全部频道 · 单线路 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/all.m3u` |
| 全部频道 · 多线路（最多 3 条容错） | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/multi.m3u` |
| 央视 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/cctv.m3u` |
| 卫视 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/satellite.m3u` |
| 地方台 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/local.m3u` |
| 港澳台 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/hkmo_tw.m3u` |
| 影视 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/movie.m3u` |
| 体育 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/sports.m3u` |
| 少儿 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/kids.m3u` |
| 纪录 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/documentary.m3u` |
| 音乐 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/music.m3u` |
| 其他 | `https://raw.githubusercontent.com/stonearro/iptv-playlist/main/output/other.m3u` |

## 使用方法

1. 复制上面的播放列表地址。
2. 在播放器中打开「网络串流 / 添加播放列表 / M3U URL」。
3. 粘贴地址并保存，即可看到频道列表。

常见播放器：

- **VLC**：媒体 → 打开网络串流 → 粘贴地址
- **Kodi**：PVR IPTV Simple Client → M3U Play List URL
- **TiviMate / DIYP / 电视端播放器**：添加播放列表 → 输入 URL

## 更新机制

- 每天北京时间 **04:00** 左右由 GitHub Actions 自动运行（GitHub 定时任务可能延迟几分钟到几十分钟）。
- 也可以在仓库的 **Actions → 更新 IPTV 播放列表 → Run workflow** 手动触发。
- 每次运行会重新下载源、去重、实测，并只保留通过检测的线路。
- 实测包括：HLS 清单可访问 + 首个媒体分片可读取；失效线路会被剔除。
- 若本次可用频道异常偏少（低于 80 个），会保留上一次播放列表，避免源站临时故障导致列表被清空。
- 运行统计见 [output/stats.json](output/stats.json)。

## 数据来源

公开社区项目（按优先级）：

- [Guovin/iptv-api](https://github.com/Guovin/iptv-api)
- [vbskycn/iptv](https://github.com/vbskycn/iptv)
- [suxuang/myIPTV](https://github.com/suxuang/myIPTV)
- [iptv-org/iptv](https://github.com/iptv-org/iptv)

本项目只聚合这些项目中公开的直播地址，不存储、不转播任何视频内容。

## 自定义

- 修改 `scripts/build_playlist.py` 中的 `SOURCES` 可增删数据源。
- 修改 `.github/workflows/update.yml` 中的 `cron` 可调整更新时间（UTC 时间）。
- 修改 `GROUP_ORDER`、`NAME_ALIASES` 可调整分类和频道名归一化规则。
- 本地运行：

```bash
pip install -r requirements.txt
python scripts/build_playlist.py --output-dir output
```

调试时可加 `--limit 100` 只测前 100 条，或 `--no-verify` 跳过实测。

## 说明与限制

- 所有直播源均来自公开网络，可用性、清晰度、地域限制由源站决定，本项目不保证长期可用。
- GitHub Actions 运行在海外机房，部分仅中国大陆可访问的源可能被误判为不可用。
- 港澳台及部分频道可能存在地区版权限制，无法播放属于正常现象。
- 本项目参考了 [chuiziyao/wushuang-iptv](https://github.com/chuiziyao/wushuang-iptv) 的抓源与验证思路，但面向公网 HTTP(S) 直播源，不涉及组播抓包。

## 免责声明

本项目仅供个人学习、技术研究和自用测试，不提供、不托管、不转播任何音视频内容。所有频道地址的版权归原权利人所有。请勿将本项目用于商业用途、公开传播或任何侵犯著作权的行为。如有侵权，请联系删除。
