#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IPTV 播放列表生成器.

功能:
    1. 从多个公开 M3U 源下载候选频道;
    2. 统一频道名称、去重、归类;
    3. 并发实测每条线路(HLS 清单 + 首个分片), 只保留可播放线路;
    4. 输出单线路、多线路以及分类播放列表。

时间: 2026-11-17
作者: stonearro
"""

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning

try:
    from zhconv import convert as zh_convert
except ImportError:  # 本地未安装时退化为原文, CI 会按 requirements.txt 安装
    def zh_convert(text, _locale="zh-cn"):
        """未安装 zhconv 时的占位实现."""
        return text

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
socket.setdefaulttimeout(15)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 源优先级: 数字越小越优先
SOURCES = [
    {
        "name": "Guovin",
        "url": "https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u",
        "region": "cn",
        "priority": 1,
    },
    {
        "name": "vbskycn",
        "url": "https://raw.githubusercontent.com/vbskycn/iptv/master/tv/iptv4.m3u",
        "region": "cn",
        "priority": 2,
    },
    {
        "name": "suxuang",
        "url": "https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv4.m3u",
        "region": "cn",
        "priority": 3,
    },
    {
        "name": "iptv-org-cn",
        "url": "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
        "region": "cn",
        "priority": 5,
    },
    {
        "name": "iptv-org-hk",
        "url": "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/hk.m3u",
        "region": "hk",
        "priority": 6,
    },
    {
        "name": "iptv-org-mo",
        "url": "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/mo.m3u",
        "region": "mo",
        "priority": 6,
    },
    {
        "name": "iptv-org-tw",
        "url": "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/tw.m3u",
        "region": "tw",
        "priority": 6,
    },
]

GROUP_ORDER = ["央视", "卫视", "地方", "港澳台", "影视", "体育", "少儿", "纪录", "音乐", "其他"]
MIN_CHANNELS = 80  # 低于该数量视为源站异常, 保留上一次结果

CCTV_NAMES = {
    1: "CCTV-1 综合",
    2: "CCTV-2 财经",
    3: "CCTV-3 综艺",
    4: "CCTV-4 中文国际",
    5: "CCTV-5 体育",
    6: "CCTV-6 电影",
    7: "CCTV-7 国防军事",
    8: "CCTV-8 电视剧",
    9: "CCTV-9 纪录",
    10: "CCTV-10 科教",
    11: "CCTV-11 戏曲",
    12: "CCTV-12 社会与法",
    13: "CCTV-13 新闻",
    14: "CCTV-14 少儿",
    15: "CCTV-15 音乐",
    16: "CCTV-16 奥林匹克",
    17: "CCTV-17 农业农村",
}

CCTV_PAY = {
    "风云足球": "CCTV-风云足球",
    "风云音乐": "CCTV-风云音乐",
    "风云剧场": "CCTV-风云剧场",
    "第一剧场": "CCTV-第一剧场",
    "怀旧剧场": "CCTV-怀旧剧场",
    "文化精品": "CCTV-文化精品",
    "女性时尚": "CCTV-女性时尚",
    "卫生健康": "CCTV-卫生健康",
    "央视台球": "CCTV-央视台球",
    "央视高网": "CCTV-央视高网",
    "兵器科技": "CCTV-兵器科技",
    "世界地理": "CCTV-世界地理",
    "电视指南": "CCTV-电视指南",
    "老故事": "CCTV-老故事",
    "发现之旅": "CCTV-发现之旅",
    "中学生": "CCTV-中学生",
    "Billiards": "CCTV-央视台球",
    "Golf & Tennis": "CCTV-央视高网",
    "Health": "CCTV-卫生健康",
    "Nostalgia Theater": "CCTV-怀旧剧场",
    "Storm Football": "CCTV-风云足球",
    "Storm Music": "CCTV-风云音乐",
    "Storm Theater": "CCTV-风云剧场",
    "The First Theater": "CCTV-第一剧场",
    "Weapon & Technology": "CCTV-兵器科技",
    "Women's Fashion": "CCTV-女性时尚",
    "World Geography": "CCTV-世界地理",
    "Culture of Quality": "CCTV-文化精品",
}

HK_TW_KEYWORDS = re.compile(
    r"TVB|翡翠|明珠台|无线新闻|无线星河|凤凰|澳门|澳视|莲花卫视|香港|港台|Viu|HOY|RTHK|"
    r"台湾|台视|中视|华视|民视|公视|东森|三立|中天|年代|非凡|大爱|"
    r"龙华|靖天|寰宇|TVBS|人间卫视|澳亚"
)

LOCAL_KEYWORDS = re.compile(
    r"北京|天津|河北|山西|内蒙古|辽宁|吉林|黑龙江|上海|江苏|浙江|安徽|"
    r"福建|江西|山东|河南|湖北|湖南|广东|广西|海南|重庆|四川|贵州|云南|"
    r"西藏|陕西|甘肃|青海|宁夏|新疆|杭州|南京|广州|深圳|成都|武汉|西安|"
    r"苏州|宁波|青岛|厦门|大连|沈阳|济南|郑州|长沙|合肥|福州|昆明|南宁"
)

NAME_ALIASES = [
    (r"(?i)^BRTV\s*北京卫视$", "北京卫视"),
    (r"(?i)^黑龙卫视$|^黑龙江卫$|^黑龙江视$", "黑龙江卫视"),
    (r"(?i)^(?:TVB)?翡翠台$", "翡翠台"),
    (r"(?i)^(?:TVB)?翡翠台\s*4K$", "翡翠台 4K"),
    (r"(?i)^翡翠台北美版$", "翡翠台北美版"),
    (r"(?i)^(?:TVB)?明珠台$", "明珠台"),
    (r"(?i)^(?:TVB)?无线新闻台?$", "无线新闻台"),
    (r"(?i)^(?:TVB)?无线星河台?$", "无线星河"),
    (r"(?i)^TVB星河$", "无线星河"),
    (r"(?i)^TVB\s*Plus$", "TVB Plus"),
    (r"(?i)^TVB\s*J1$", "TVB J1"),
    (r"(?i)^TVB生活台$", "TVB生活台"),
    (r"(?i)^TVB娱乐新闻台?$", "TVB娱乐新闻台"),
    (r"(?i)^凤凰中文台?$", "凤凰中文"),
    (r"(?i)^凤凰资讯台?$", "凤凰资讯"),
    (r"(?i)^凤凰香港台?$", "凤凰香港"),
    (r"(?i)^凤凰卫视台?$", "凤凰卫视"),
    (r"(?i)^凤凰电影$", "凤凰电影"),
    (r"(?i)^Viu\s*TV\s*Six$", "ViuTV6"),
    (r"(?i)^Viu6$", "ViuTV6"),
    (r"(?i)^Viutv$", "ViuTV"),
    (r"(?i)^HOY\s*TV$", "HOY TV"),
    (r"(?i)^HOY\s*Infotainment$", "HOY资讯台"),
    (r"(?i)^HOY资讯台$", "HOY资讯台"),
    (r"(?i)^HOY78$", "HOY 78"),
    (r"(?i)^港台电视\s*(3[1-6])$", r"港台电视\1"),
    (r"(?i)^RTHK\s*(?:TV)?\s*(3[1-6]).*$", r"港台电视\1"),
    (r"(?i)^TVBS\s*News.*$", "TVBS新闻台"),
    (r"(?i)^TVBS\s*Asia$", "TVBS亚洲"),
    (r"(?i)^VIUTV1$", "ViuTV"),
    (r"(?i)^民视新闻台?$", "民视新闻台"),
]

EXTINF_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
QUALITY_TAG_RE = re.compile(
    r"[\(（\[【]\s*(?:2160p|1080[pi]|720p|576[pi]|540p|480p|360p|4k|8k|uhd|fhd|hd|sd|"
    r"not\s*24/7|geo-blocked|backup|备用|无台标|测试|高清|超清|标清)\s*[\)）\]】]",
    re.I,
)
SOURCE_TAG_RE = re.compile(
    r"[「【\[]\s*(?:移动|电信|联通|广电|咪咕|备用|备|港澳|海外|ipv4|ipv6)\s*[」】\]]",
    re.I,
)
TRAILING_QUALITY_RE = re.compile(
    r"(?i)(?:\s*[-_·]?\s*(?:backup|备用|高清|超清|标清|蓝光|原画|"
    r"2160p|1080[pi]|720p|576[pi]|540p|480p|360p|fhd|uhd|hd|sd))+$"
)
BAD_NAME_RE = re.compile(
    r"更新时间|公告|声明|说明|关于|测试|广告|福利|扫码|加群|Q群|微信|公众号|"
    r"推广|赞助|请关注|防盗|预警|节目单|咪咕直播|轮播|春晚|支持作者|点击|关注|"
    r"爱奇艺|咪咕视频|优酷|腾讯视频|哔哩哔哩|抖音|快手",
    re.I,
)
BAD_GROUP_RE = re.compile(r"更新时间|公告|测试|备用频道|春晚|轮播", re.I)
VOD_GROUP_RE = re.compile(
    r"虎牙影视|斗鱼影视|点播电影|电视剧频道|经典剧场|埋堆堆|解说频道|咪咕赛事|游戏赛事",
    re.I,
)
MOVIE_GROUP_RE = re.compile(r"电影", re.I)
MOVIE_KEEP_RE = re.compile(r"CHC|淘剧场|淘电影|淘娱乐|NewTV|影视|影院|电影台|剧场|频道", re.I)
KIDS_GROUP_RE = re.compile(r"儿童|动画|卡通", re.I)
KIDS_KEEP_RE = re.compile(r"少儿|卡通|动画|动漫|儿童|EBS", re.I)
DOC_GROUP_RE = re.compile(r"纪录|纪实|记录", re.I)
DOC_VOD_RE = re.compile(r"第[一二三四五六七八九十0-9]+季|合集|人与自然|地理中国|中国村庄|航拍中国")
BAD_URL_RE = re.compile(r"\.(?:mp4|mkv|avi|webm|flv|mp3|mpd)(?:\?|$)", re.I)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
WHITELIST_RE = re.compile(r"(?i)^(?:CCTV|CGTN|TVB|TVBS|Viu|HOY|RTHK|iHOY)")
PSEUDO_NAME_RE = re.compile(r"^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}")

_thread_local = threading.local()
_print_lock = threading.Lock()


@dataclass
class Source:
    """一个 M3U 数据源."""

    name: str
    url: str
    region: str
    priority: int


@dataclass
class Line:
    """一条候选线路."""

    url: str
    source: str
    priority: int
    display_name: str = ""
    group: str = ""
    region: str = "cn"
    logo: str = ""
    tvg_id: str = ""
    user_agent: str = ""
    referer: str = ""
    latency: float = 0.0
    status: str = "pending"
    detail: str = ""

    @property
    def host(self) -> str:
        """返回 URL 主机名, 用于多线路时尽量选择不同主机."""
        try:
            return (urlsplit(self.url).hostname or "").lower()
        except ValueError:
            return ""


@dataclass
class Channel:
    """归一化后的频道."""

    name: str
    group: str
    lines: list = field(default_factory=list)


def log(message: str) -> None:
    """线程安全地打印日志."""
    with _print_lock:
        print(message, flush=True)


def get_session() -> requests.Session:
    """获取线程内复用的 HTTP Session."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _thread_local.session = session
    return session


def fetch_text(url: str, timeout: int = 40) -> str:
    """下载源文件, 失败重试两次."""
    last_error = None
    for attempt in range(3):
        try:
            response = get_session().get(
                url,
                headers={"User-Agent": DEFAULT_UA, "Accept": "*/*"},
                timeout=(8, timeout),
                verify=False,
            )
            response.raise_for_status()
            return response.content.decode("utf-8-sig", "replace")
        except Exception as exc:  # noqa: BLE001 - 网络异常种类多, 统一降级处理
            last_error = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"下载失败: {url} ({last_error})")


def _split_unquoted(text: str, delimiter: str = ",") -> list:
    """按引号外的分隔符切分字符串."""
    parts, current, quoted = [], [], False
    for char in text:
        if char == '"':
            quoted = not quoted
            current.append(char)
        elif char == delimiter and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def parse_extinf(line: str) -> tuple:
    """解析 #EXTINF 行, 返回 (属性字典, 显示名称).

    兼容两种写法:
        #EXTINF:-1 tvg-id="x" group-title="y",频道名
        #EXTINF:-1,tvg-id="x" group-title="y",频道名   (部分源使用)
    """
    body = line[len("#EXTINF:"):]
    parts = _split_unquoted(body)
    if len(parts) < 2:
        return {}, ""

    attrs_text = parts[0]
    name = ",".join(parts[1:]).strip()
    if re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*", parts[0]) and '="' in parts[1]:
        if len(parts) >= 3:
            attrs_text = ",".join(parts[1:-1])
            name = parts[-1].strip()
        else:
            attrs_text = parts[1]
            name = ""
    attrs = dict(EXTINF_ATTR_RE.findall(attrs_text))
    return attrs, name


def _clean_option_value(option: str, key: str) -> str:
    """清理 #EXTVLCOPT 值, 兼容源站重复嵌套 "key=#EXTVLCOPT:key=..." 的写法."""
    value = option.split("=", 1)[1].strip() if "=" in option else ""
    prefix = f"#EXTVLCOPT:{key}="
    while value.lower().startswith(prefix.lower()):
        value = value[len(prefix):].strip()
    return value


def parse_m3u(text: str, source: Source) -> list:
    """解析 M3U 文本, 返回候选线路列表."""
    lines = []
    attrs, name = {}, ""
    section = ""
    user_agent = referer = ""

    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attrs, name = parse_extinf(line)
            user_agent = referer = ""
        elif line.startswith("#EXTVLCOPT"):
            option = line.split(":", 1)[-1].strip()
            if option.lower().startswith("http-user-agent="):
                user_agent = _clean_option_value(option, "http-user-agent")
            elif option.lower().startswith(("http-referrer=", "http-referer=")):
                referer = _clean_option_value(option, "http-referrer")
        elif line.startswith("#EXTGRP:"):
            section = line.split(":", 1)[1].strip()
        elif line.startswith("#"):
            # 非标准指令行在部分源里被当作分组标题, 如 "#4K频道"
            if not line.startswith(("#EXTM3U", "#EXT-X", "#KODIPROP", "#PLAYLIST")):
                header = line.lstrip("#").strip()
                if header and len(header) <= 30:
                    section = header
        else:
            if not name:
                name = (attrs.get("tvg-name") or "").strip()
            if not name:
                continue
            group = (attrs.get("group-title") or section or "").strip()
            lines.append(
                Line(
                    url=line.replace("&amp;", "&"),
                    source=source.name,
                    priority=source.priority,
                    display_name=name,
                    group=group,
                    region=source.region,
                    logo=(attrs.get("tvg-logo") or "").replace("&amp;", "&").strip(),
                    tvg_id=(attrs.get("tvg-id") or "").strip(),
                    user_agent=user_agent,
                    referer=referer,
                )
            )
            name, attrs = "", {}
            user_agent = referer = ""
    return lines


def normalize_text(raw: str) -> str:
    """清理频道名中的画质、来源、备用等标记, 并统一为简体."""
    name = unicodedata.normalize("NFKC", raw or "")
    name = zh_convert(name, "zh-cn")
    name = name.replace("\u3000", " ")
    name = re.sub(r"^.*?\s+I\s+", "", name)
    name = QUALITY_TAG_RE.sub("", name)
    name = SOURCE_TAG_RE.sub("", name)
    name = TRAILING_QUALITY_RE.sub("", name)

    # "CTS News (华视新闻资讯)" 这类英文前缀 + 中文括号名, 取括号内名称
    match = re.fullmatch(r"[A-Za-z0-9 .,+&'\-/]+[\(（]([\w\u4e00-\u9fff .+-]+)[\)）]", name)
    if match:
        name = match.group(1).strip()

    name = re.sub(r"(?i)(\d)k(?=$|[\s\)）\]】])", lambda m: m.group(1) + "K", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip(" -_·|")


def canonical_cctv(name: str) -> str:
    """归一化 CCTV / CGTN 频道名, 非央视返回空字符串."""
    upper = name.upper()
    if upper.startswith("CCTV+") or upper.startswith("CCTV PLUS"):
        match = re.match(r"(?i)^CCTV\+\s*([0-9]+)\s*(.*)$", name)
        return f"CCTV+ {match.group(1)}" if match else "CCTV+"

    if upper.startswith("CGTN"):
        if "纪录" in name or "记录" in name:
            return "CGTN 纪录"
        if "法语" in name:
            return "CGTN 法语"
        if "西语" in name:
            return "CGTN 西语"
        if "阿语" in name or "阿拉伯" in name:
            return "CGTN 阿语"
        if "俄语" in name:
            return "CGTN 俄语"
        return "CGTN"

    if re.match(r"(?i)^CCTV[\s-]*4K", name):
        return "CCTV-4K 超高清"
    if re.match(r"(?i)^CCTV[\s-]*8K", name):
        return "CCTV-8K 超高清"

    match = re.match(r"(?i)^CCTV[\s-]*(5\+|[0-9]{1,2})\s*(.*)$", name)
    if match:
        number, suffix = match.group(1), match.group(2).strip(" -·")
        if number == "5+":
            return "CCTV-5+ 体育赛事"
        value = int(number)
        if value == 4 and "美洲" in suffix:
            return "CCTV-4 美洲"
        if value == 4 and "欧洲" in suffix:
            return "CCTV-4 欧洲"
        if value in CCTV_NAMES:
            return CCTV_NAMES[value]
        return f"CCTV-{value}" + (f" {suffix}" if suffix else "")

    if upper.startswith("CCTV"):
        for keyword, canonical in CCTV_PAY.items():
            if keyword.lower() in name.lower():
                return canonical
    return ""


def canonical_name(raw: str) -> str:
    """把各源的不同写法归一为统一频道名."""
    name = normalize_text(raw)
    if not name:
        return ""

    cctv = canonical_cctv(name)
    if cctv:
        return cctv

    for pattern, replacement in NAME_ALIASES:
        if re.match(pattern, name):
            return re.sub(pattern, replacement, name)

    # 卫视: 统一空格, 上海卫视并入东方卫视, 保留 4K 作为独立频道
    match = re.match(r"^(.{2,12}?)卫视\s*(4K|8K)?$", name)
    if match:
        base = match.group(1)
        quality = f" {match.group(2).upper()}" if match.group(2) else ""
        if base == "上海":
            base = "东方"
        elif base == "福建海峡":
            base = "海峡"
        return f"{base}卫视{quality}"

    return name


def classify(name: str, source_group: str, region: str) -> tuple:
    """返回 (分类, 是否收录)."""
    group = source_group or ""

    if name.startswith(("CCTV", "CGTN")):
        return "央视", True
    if region in ("hk", "mo", "tw") or HK_TW_KEYWORDS.search(name):
        return "港澳台", True
    if "卫视" in name:
        return "卫视", True
    if re.search(r"电影|影院|剧场", name):
        return "影视", True
    if re.search(r"纪录|纪实", name):
        return "纪录", True
    if re.search(r"体育|赛事", group):
        return "体育", True
    if re.search(r"电影|影视|剧场|电视剧|影院", group):
        return "影视", True
    if re.search(r"动画|少儿|儿童|卡通", group):
        return "少儿", True
    if DOC_GROUP_RE.search(group):
        if len(name) <= 6 and not re.search(
            r"纪录|纪实|地理|科教|探索|发现|人文|自然|中国|TV", name
        ):
            return "地方", True
        return "纪录", True
    if "音乐" in group:
        return "音乐", True
    if re.search(r"地方|频道", group) and (
        LOCAL_KEYWORDS.search(group) or "地方" in group
    ):
        return "地方", True
    if LOCAL_KEYWORDS.search(name) and "卫视" not in name:
        return "地方", True
    if re.search(r"港澳|港·澳|港台", group):
        return "港澳台", True
    if re.search(r"国际", group):
        return "其他", False
    return "其他", True


def build_channels(lines: list) -> dict:
    """过滤、归一化并按频道聚合线路."""
    channels = {}
    skipped = {
        "伪频道": 0,
        "非HTTP": 0,
        "非中文": 0,
        "非电视": 0,
        "分组排除": 0,
        "轮播内容": 0,
        "重复URL": 0,
    }
    seen_urls = set()

    for line in lines:
        url = line.url.strip()
        if not url.lower().startswith(("http://", "https://")):
            skipped["非HTTP"] += 1
            continue
        if BAD_URL_RE.search(url):
            skipped["伪频道"] += 1
            continue

        # 频道名优先取 #EXTINF 的显示名; 部分源只有 tvg-name
        raw_name = (line.display_name or "").strip()
        if not raw_name:
            skipped["伪频道"] += 1
            continue
        if BAD_NAME_RE.search(raw_name):
            skipped["伪频道"] += 1
            continue
        if PSEUDO_NAME_RE.match(raw_name):
            skipped["伪频道"] += 1
            continue
        if re.search(r"广播$", raw_name):
            skipped["非电视"] += 1
            continue
        if not CJK_RE.search(raw_name) and not WHITELIST_RE.match(raw_name):
            skipped["非中文"] += 1
            continue
        if line.source.startswith("iptv-org") and "@" in line.tvg_id:
            country = line.tvg_id.split("@", 1)[0].rsplit(".", 1)[-1].lower()
            if country and country not in ("cn", "hk", "mo", "tw"):
                skipped["非中文"] += 1
                continue

        group = line.group or ""
        if BAD_GROUP_RE.search(group):
            skipped["分组排除"] += 1
            continue
        if VOD_GROUP_RE.search(group):
            skipped["轮播内容"] += 1
            continue
        if MOVIE_GROUP_RE.search(group) and not MOVIE_KEEP_RE.search(raw_name):
            skipped["轮播内容"] += 1
            continue
        if KIDS_GROUP_RE.search(group) and not KIDS_KEEP_RE.search(raw_name):
            skipped["轮播内容"] += 1
            continue
        if DOC_GROUP_RE.search(group) and DOC_VOD_RE.search(raw_name):
            skipped["轮播内容"] += 1
            continue

        name = canonical_name(raw_name)
        if not name or BAD_NAME_RE.search(name):
            skipped["伪频道"] += 1
            continue

        category, keep = classify(name, group, line.region)
        if not keep:
            skipped["分组排除"] += 1
            continue

        key = (url, line.user_agent, line.referer)
        if key in seen_urls:
            skipped["重复URL"] += 1
            continue
        seen_urls.add(key)

        channel = channels.setdefault(name, Channel(name=name, group=category))
        channel.lines.append(line)

    # 分类以第一次出现的归类为准, 但央视/港澳台优先覆盖
    for channel in channels.values():
        category, _ = classify(channel.name, "", "cn")
        if category in ("央视", "港澳台"):
            channel.group = category

    return {"channels": channels, "skipped": skipped}


def probe_stream(line: Line, timeout: tuple) -> Line:
    """实测一条线路是否可播放."""
    started = time.monotonic()
    header_options = []
    if line.user_agent or line.referer:
        header_options.append((line.user_agent or DEFAULT_UA, line.referer))
    header_options.append((DEFAULT_UA, ""))
    origin = _origin(line.url)
    if origin:
        header_options.append((DEFAULT_UA, origin))

    best_error = ""
    for user_agent, referer in header_options:
        try:
            status, detail = probe_once(line.url, user_agent, referer, timeout)
        except Exception as exc:  # noqa: BLE001 - 单个线路异常不应中断整体任务
            status, detail = "fail", f"{type(exc).__name__}"
        if status == "ok":
            line.status = "ok"
            line.detail = detail
            line.latency = time.monotonic() - started
            # 记录实际生效的请求头, 避免把未生效的源站 UA/Referer 写进播放列表
            line.user_agent = "" if user_agent == DEFAULT_UA else user_agent
            line.referer = referer or ""
            return line
        if status == "manifest_only":
            line.status = "manifest_only"
            best_error = detail or best_error
            continue
        best_error = detail or best_error
        # 只有鉴权类失败才值得换 UA / Referer 重试, 超时和 404 直接放弃
        if not re.match(r"HTTP (401|403|406)", detail or ""):
            break
    line.latency = time.monotonic() - started
    line.detail = best_error
    if line.status != "manifest_only":
        line.status = "fail"
    return line


def _origin(url: str) -> str:
    """返回 URL 的 scheme://host/ 作为 Referer 候选."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}/"


def recheck_line(line: Line, timeout: tuple) -> Line:
    """对首轮通过的线路再做一次确认, 降低瞬时可用导致的误判."""
    try:
        status, detail = probe_once(
            line.url, line.user_agent or DEFAULT_UA, line.referer, timeout
        )
    except Exception as exc:  # noqa: BLE001 - 复检异常按失败处理
        status, detail = "fail", f"{type(exc).__name__}"
    if status != "ok":
        line.status = "fail"
        line.detail = f"复检失败: {detail}"
    return line


def probe_once(url: str, user_agent: str, referer: str, timeout: tuple) -> tuple:
    """执行一次探测, 返回 (状态, 说明)."""
    headers = {"User-Agent": user_agent, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    session = get_session()
    response = session.get(
        url, headers=headers, timeout=timeout, stream=True, allow_redirects=True, verify=False
    )
    try:
        if response.status_code >= 400:
            return "fail", f"HTTP {response.status_code}"
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/html" in content_type:
            return "fail", "HTML 页面"

        path = urlsplit(url).path.lower()
        binary = content_type.startswith(("video/", "audio/")) or path.endswith(
            (".ts", ".m4s", ".flv")
        )
        head = _read_head(response, 8192 if binary else 512 * 1024)
        if not head:
            return "fail", "空响应"
        if b"#EXTM3U" in head[:4096]:
            text = head.decode("utf-8", "replace")
            return _probe_hls(text, url, headers, timeout)
        if content_type.startswith(("video/", "audio/")) or _looks_like_ts(head):
            return "ok", "直连视频流"
        return "fail", f"未知类型 {content_type or 'unknown'}"
    finally:
        response.close()


def _read_head(response: requests.Response, limit: int) -> bytes:
    """读取响应前若干字节, 用于识别清单或视频流."""
    data = b""
    for chunk in response.iter_content(8192):
        data += chunk
        if len(data) >= limit:
            break
    return data


def _looks_like_ts(data: bytes) -> bool:
    """判断数据是否为 MPEG-TS."""
    return len(data) >= 376 and (data[0] == 0x47 or data[188] == 0x47)


def _probe_hls(text: str, base_url: str, headers: dict, timeout: tuple) -> tuple:
    """检查 HLS 清单及首个媒体分片, 主清单最多尝试 3 档码率."""
    variants = _parse_variants(text, base_url)
    if variants:
        manifest_only = False
        for bandwidth, variant_url in variants[:3]:
            try:
                response = get_session().get(
                    variant_url,
                    headers=headers,
                    timeout=timeout,
                    stream=True,
                    allow_redirects=True,
                    verify=False,
                )
                try:
                    if response.status_code >= 400:
                        continue
                    variant_text = _read_head(response, 256 * 1024).decode("utf-8", "replace")
                finally:
                    response.close()
                if "#EXTM3U" not in variant_text:
                    continue
                media_url = _pick_media_uri(variant_text, variant_url)
                if not media_url:
                    continue
                status, detail = _check_segment(media_url, headers, timeout)
                if status == "ok":
                    return "ok", f"HLS 分片正常 ({bandwidth // 1000}kbps)"
                manifest_only = True
            except Exception:  # noqa: BLE001 - 尝试下一档码率
                continue
        return ("manifest_only" if manifest_only else "fail"), "分片不可用"

    media_url = _pick_media_uri(text, base_url)
    if not media_url:
        return "fail", "无媒体分片"
    return _check_segment(media_url, headers, timeout)


def _check_segment(url: str, headers: dict, timeout: tuple) -> tuple:
    """请求首个媒体分片, 确认返回的是有效媒体数据."""
    try:
        response = get_session().get(
            url,
            headers=headers,
            timeout=timeout,
            stream=True,
            allow_redirects=True,
            verify=False,
        )
    except Exception as exc:  # noqa: BLE001 - 分片异常按不可用处理
        return "manifest_only", f"{type(exc).__name__}"
    try:
        if response.status_code >= 400:
            return "manifest_only", f"分片 HTTP {response.status_code}"
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/html" in content_type:
            return "manifest_only", "分片返回 HTML"
        data = _read_head(response, 4096)
        if len(data) >= 512:
            return "ok", "HLS 分片正常"
        return "manifest_only", "分片过小"
    finally:
        response.close()


def _parse_variants(text: str, base_url: str) -> list:
    """解析主清单中的码率变体, 按带宽从高到低排序."""
    lines = [item.strip() for item in text.splitlines() if item.strip()]
    variants = []
    for index, item in enumerate(lines):
        if not item.startswith("#EXT-X-STREAM-INF"):
            continue
        bandwidth = re.search(r"BANDWIDTH=(\d+)", item)
        for candidate in lines[index + 1:]:
            if not candidate.startswith("#"):
                variants.append(
                    (
                        int(bandwidth.group(1)) if bandwidth else 1,
                        urljoin(base_url, candidate),
                    )
                )
                break
    variants.sort(key=lambda pair: pair[0], reverse=True)
    return variants


def _pick_media_uri(text: str, base_url: str) -> str:
    """从媒体清单中取出第一个分片地址."""
    lines = [item.strip() for item in text.splitlines() if item.strip()]
    for index, item in enumerate(lines):
        if item.startswith("#EXTINF"):
            for candidate in lines[index + 1:]:
                if not candidate.startswith("#"):
                    return urljoin(base_url, candidate)
    for item in lines:
        if not item.startswith("#"):
            return urljoin(base_url, item)
    return ""


def pick_lines(channel: Channel, limit: int) -> list:
    """选择线路: 优先低延迟, 多线路时尽量分散到不同主机."""
    candidates = [line for line in channel.lines if line.status == "ok"]
    if not candidates:
        return []
    candidates.sort(
        key=lambda line: (
            line.latency,
            0 if line.url.lower().startswith("https://") else 1,
            line.priority,
        )
    )
    selected = []
    hosts = set()
    for line in candidates:
        if len(selected) >= limit:
            break
        if line.host not in hosts:
            selected.append(line)
            hosts.add(line.host)
    for line in candidates:
        if len(selected) >= limit:
            break
        if line not in selected:
            selected.append(line)
    selected.sort(key=lambda line: (line.latency, line.priority))
    return selected


def sort_key(channel: Channel) -> tuple:
    """按分类顺序、CCTV 编号、卫视常用顺序排序."""
    try:
        group_index = GROUP_ORDER.index(channel.group)
    except ValueError:
        group_index = len(GROUP_ORDER)
    name = channel.name
    if name.startswith("CCTV-"):
        match = re.match(r"CCTV-(\d+)", name)
        number = int(match.group(1)) if match else 99
        return group_index, number, name
    if name.startswith("CCTV"):
        return group_index, 50, name
    satellite_order = [
        "北京卫视", "东方卫视", "湖南卫视", "浙江卫视", "江苏卫视", "广东卫视",
        "深圳卫视", "安徽卫视", "山东卫视", "湖北卫视", "天津卫视", "四川卫视",
        "河南卫视", "福建东南卫视", "东南卫视", "江西卫视", "河北卫视", "辽宁卫视",
    ]
    if name in satellite_order:
        return group_index, satellite_order.index(name), name
    return group_index, 100, name


def _m3u_attr(value: str) -> str:
    """转义 M3U 属性值中的双引号和换行."""
    return (value or "").replace('"', "'").replace("\n", " ").replace("\r", " ").strip()


def write_m3u(path: str, channels: list, multi: bool = False) -> int:
    """写入 M3U 文件, 返回频道数."""
    lines = [
        '#EXTM3U x-tvg-url="https://live.fanmingming.cn/e.xml"',
        "# 由 GitHub Actions 自动生成, 请勿手动编辑",
        f"# 更新时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    count = 0
    for channel in channels:
        selected = pick_lines(channel, 3 if multi else 1)
        if not selected:
            continue
        logo = next((line.logo for line in selected if line.logo), "")
        tvg_id = ""
        if channel.name.startswith("CCTV-"):
            match = re.match(r"CCTV-(5\+|\d+|4K|8K)", channel.name)
            if match:
                tvg_id = "CCTV" + match.group(1)
        if not tvg_id:
            tvg_id = next(
                (
                    line.tvg_id
                    for line in selected
                    if line.tvg_id
                    and re.match(r"^[\w.+-]+$", line.tvg_id)
                    and not line.tvg_id.isdigit()
                ),
                "",
            )
        if not tvg_id:
            tvg_id = channel.name.replace(" ", "")
        display_name = _m3u_attr(channel.name)
        for index, line in enumerate(selected):
            display = display_name if index == 0 else f"{display_name} (线路{index + 1})"
            attrs = f'tvg-name="{display_name}" group-title="{channel.group}"'
            if tvg_id and re.match(r"^[\w.+-]+$", tvg_id):
                attrs = f'tvg-id="{_m3u_attr(tvg_id)}" ' + attrs
            if logo.startswith(("http://", "https://")):
                attrs += f' tvg-logo="{_m3u_attr(logo)}"'
            lines.append(f"#EXTINF:-1 {attrs},{display}")
            if line.user_agent:
                lines.append(f"#EXTVLCOPT:http-user-agent={line.user_agent}")
            if line.referer:
                lines.append(f"#EXTVLCOPT:http-referrer={line.referer}")
            lines.append(line.url)
        count += 1
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return count


def main() -> int:
    """命令行入口."""
    parser = argparse.ArgumentParser(description="生成实测可用的 IPTV 播放列表")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument("--workers", type=int, default=32, help="并发探测数")
    parser.add_argument("--timeout", type=float, default=8.0, help="单次请求超时秒数")
    parser.add_argument("--limit", type=int, default=0, help="仅探测前 N 条, 调试用")
    parser.add_argument("--no-verify", action="store_true", help="跳过实测, 调试用")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    timeout = (min(5.0, args.timeout), args.timeout)
    all_lines = []

    for config in SOURCES:
        source = Source(**config)
        try:
            text = fetch_text(source.url)
        except RuntimeError as exc:
            log(f"[源失败] {source.name}: {exc}")
            continue
        parsed = parse_m3u(text, source)
        log(f"[源完成] {source.name}: {len(parsed)} 条")
        all_lines.extend(parsed)

    # 解析阶段没有保留显示名, 这里从原始条目补充
    log(f"[聚合] 候选线路 {len(all_lines)} 条")

    result = build_channels(all_lines)
    channels = result["channels"]
    candidates = [line for channel in channels.values() for line in channel.lines]
    log(f"[清洗] 频道 {len(channels)} 个, 待测线路 {len(candidates)} 条")

    if args.limit:
        candidates = candidates[: args.limit]

    if args.no_verify:
        for line in candidates:
            line.status = "ok"
            line.latency = 0.0
    else:
        done = 0
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(probe_stream, line, timeout) for line in candidates]
            for future in as_completed(futures):
                future.result()
                done += 1
                if done % 50 == 0 or done == len(candidates):
                    ok = sum(1 for line in candidates if line.status == "ok")
                    log(
                        f"[探测] {done}/{len(candidates)} 可用 {ok} "
                        f"用时 {time.monotonic() - started:.0f}s"
                    )

        # 二次复检: 首轮通过的线路再确认一次, 过滤瞬时可用和鉴权失效
        ok_lines = [line for line in candidates if line.status == "ok"]
        log(f"[复检] 待复检 {len(ok_lines)} 条")
        done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(recheck_line, line, timeout) for line in ok_lines]
            for future in as_completed(futures):
                future.result()
                done += 1
                if done % 50 == 0 or done == len(ok_lines):
                    ok = sum(1 for line in ok_lines if line.status == "ok")
                    log(f"[复检] {done}/{len(ok_lines)} 通过 {ok}")

    usable = [channel for channel in channels.values() if any(
        line.status == "ok" for line in channel.lines
    )]
    usable.sort(key=sort_key)

    existing_playlist = os.path.join(args.output_dir, "all.m3u")
    if not args.no_verify and len(usable) < MIN_CHANNELS and os.path.exists(existing_playlist):
        log(
            f"[警告] 本次仅 {len(usable)} 个可用频道, 低于保护阈值 {MIN_CHANNELS}, "
            "保留上一次播放列表"
        )
        return 0

    total_channels = write_m3u(os.path.join(args.output_dir, "all.m3u"), usable, multi=False)
    write_m3u(os.path.join(args.output_dir, "multi.m3u"), usable, multi=True)

    group_files = {
        "cctv": "央视",
        "satellite": "卫视",
        "local": "地方",
        "hkmo_tw": "港澳台",
        "movie": "影视",
        "sports": "体育",
        "kids": "少儿",
        "documentary": "纪录",
        "music": "音乐",
        "other": "其他",
    }
    group_stats = {}
    for filename, group in group_files.items():
        subset = [channel for channel in usable if channel.group == group]
        write_m3u(os.path.join(args.output_dir, f"{filename}.m3u"), subset, multi=False)
        group_stats[group] = len(subset)

    source_stats = {}
    for line in all_lines:
        entry = source_stats.setdefault(line.source, {"候选": 0, "可用": 0})
        entry["候选"] += 1
        if line.status == "ok":
            entry["可用"] += 1

    stats = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "channels": total_channels,
        "lines": sum(len(pick_lines(channel, 3)) for channel in usable),
        "groups": group_stats,
        "sources": source_stats,
        "skipped": result["skipped"],
    }
    with open(
        os.path.join(args.output_dir, "stats.json"), "w", encoding="utf-8", newline="\n"
    ) as handle:
        json.dump(stats, handle, ensure_ascii=False, indent=2)

    log(
        f"[完成] 频道 {len(usable)} 个, 线路 "
        f"{sum(len(pick_lines(channel, 3)) for channel in usable)} 条"
    )
    log(f"[跳过] {result['skipped']}")
    log(f"[分组] {group_stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
