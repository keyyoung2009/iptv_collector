"""
IPTV Pro - 多功能直播源管理系统
功能包含：智能验证、分类过滤、质量检测、多格式支持等
"""

import os
import re
import json
import time
import hashlib
import requests
from pathlib import Path
from typing import List, Dict, Set, Optional
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor

# 配置文件（可抽离为单独JSON）
CONFIG = {
    "sources": {
        "github_keywords": ["IPTV", "直播源", "直播地址"],
        "custom_urls": [
            "https://raw.githubusercontent.com/iptv-org/iptv/master/index.m3u",
            "https://mirror.ghproxy.com/https://raw.githubusercontent.com/zhanghong1983/IPTV/main/IPTV.m3u"
        ],
        "proxy": os.getenv("PROXY_URL"),  # 代理设置
        "max_workers": 5  # 并发线程数
    },
    "filters": {
        "min_duration": 30,  # 最低播放时长要求（秒）
        "allowed_categories": ["央视", "卫视", "电影", "体育"],
        "block_keywords": ["成人", "测试", "失效"]
    },
    "output": {
        "formats": ["m3u", "txt", "json"],
        "group_categories": True,
        "generate_report": True
    }
}

class ChannelValidator:
    """频道有效性验证模块"""
    
    @staticmethod
    def check_url_reachable(url: str) -> bool:
        try:
            resp = requests.head(url, timeout=10, 
                              proxies={"http": CONFIG["sources"]["proxy"]} if CONFIG["sources"]["proxy"] else None)
            return resp.status_code in [200, 302]
        except:
            return False

    @staticmethod
    def detect_stream_type(url: str) -> str:
        if ".m3u8" in url:
            return "HLS"
        if ".flv" in url:
            return "FLV"
        if ".mpd" in url:
            return "DASH"
        return "TS"

class AdvancedM3UParser:
    """增强型M3U解析器"""
    
    def __init__(self):
        self.extinf_pattern = re.compile(
            r'#EXTINF:-?[0-9]*\s*(?:tvg-id="([^"]*)")?\s*(?:tvg-name="([^"]*)")?\s*(?:tvg-logo="([^"]*)")?\s*group-title="([^"]*)",(.*)'
        )

    def parse(self, content: str) -> List[Dict]:
        channels = []
        lines = content.split('\n')
        channel_info = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                match = self.extinf_pattern.match(line)
                if match:
                    channel_info = {
                        "tvg_id": match.group(1) or "",
                        "tvg_name": match.group(2) or "",
                        "tvg_logo": match.group(3) or "",
                        "group": match.group(4),
                        "title": match.group(5),
                        "url": ""
                    }
            elif line and not line.startswith("#"):
                channel_info["url"] = line
                channel_info["hash"] = hashlib.md5(line.encode()).hexdigest()
                channels.append(channel_info)
                channel_info = {}
                
        return channels

class SourceCollector:
    """多源采集引擎"""
    
    def __init__(self, github_token: str):
        self.github_token = github_token
        self.session = requests.Session()
        if CONFIG["sources"]["proxy"]:
            self.session.proxies.update({"http": CONFIG["sources"]["proxy"], "https": CONFIG["sources"]["proxy"]})

    def fetch_github_sources(self) -> List[str]:
        """获取GitHub最新仓库资源"""
        repos = set()
        for keyword in CONFIG["sources"]["github_keywords"]:
            response = self.session.get(
                "https://api.github.com/search/repositories",
                params={"q": f"{keyword} in:name,description fork:true", "sort": "updated"},
                headers={"Authorization": f"token {self.github_token}"}
            )
            repos.update([repo["html_url"] for repo in response.json()["items"][:3]])
        return self._extract_raw_urls(repos)

    def _extract_raw_urls(self, repos: List[str]) -> List[str]:
        """从仓库提取原始文件地址"""
        raw_urls = []
        for repo in repos:
            try:
                response = self.session.get(f"{repo}/contents/", headers={"Accept": "application/vnd.github.v3+json"})
                for item in response.json():
                    if item["name"].lower().endswith((".m3u", ".m3u8", ".txt")):
                        raw_urls.append(urljoin(repo, f"raw/main/{item['name']}"))
            except:
                continue
        return raw_urls

class QualityAnalyzer:
    """流媒体质量分析模块"""
    
    @staticmethod
    def analyze_stream(url: str) -> dict:
        try:
            start = time.time()
            resp = requests.get(url, stream=True, timeout=15)
            duration = time.time() - start
            return {
                "status": resp.status_code,
                "response_time": round(duration, 2),
                "content_type": resp.headers.get("Content-Type"),
                "content_length": resp.headers.get("Content-Length")
            }
        except Exception as e:
            return {"error": str(e)}

class EnhancedFileGenerator:
    """增强型文件生成器"""
    
    @staticmethod
    def generate_outputs(channels: List[Dict]):
        # 生成分类报告
        if CONFIG["output"]["generate_report"]:
            report = {}
            for chan in channels:
                group = chan["group"] or "未分类"
                report[group] = report.get(group, 0) + 1
            with open("report.json", "w") as f:
                json.dump(report, f, indent=2)

        # 多格式输出
        if "m3u" in CONFIG["output"]["formats"]:
            EnhancedFileGenerator._generate_m3u(channels)
        if "txt" in CONFIG["output"]["formats"]:
            EnhancedFileGenerator._generate_txt(channels)
        if "json" in CONFIG["output"]["formats"]:
            EnhancedFileGenerator._generate_json(channels)

    @staticmethod
    def _generate_m3u(channels: List[Dict]):
        with open("live.m3u", "w", encoding="utf-8") as f:
            f.write("#EXTM3U x-tvg-url=\"https://example.com/epg.xml\"\n")
            current_group = ""
            for chan in sorted(channels, key=lambda x: x["group"]):
                if CONFIG["output"]["group_categories"] and chan["group"] != current_group:
                    f.write(f'\n#EXTGRP:{chan["group"]}\n')
                    current_group = chan["group"]
                f.write(f'#EXTINF:-1 tvg-id="{chan["tvg_id"]}" tvg-name="{chan["tvg_name"]}" tvg-logo="{chan["tvg_logo"]}" group-title="{chan["group"]}",{chan["title"]}\n')
                f.write(f'{chan["url"]}\n')

    @staticmethod
    def _generate_txt(channels: List[Dict]):
        with open("live.txt", "w", encoding="utf-8") as f:
            for chan in channels:
                f.write(f'{chan["tvg_name"]},{chan["url"]}\n')

    @staticmethod
    def _generate_json(channels: List[Dict]):
        with open("live.json", "w", encoding="utf-8") as f:
            json.dump({"channels": channels}, f, ensure_ascii=False, indent=2)

class IPTVManager:
    """核心管理系统"""
    
    def __init__(self):
        self.collector = SourceCollector(os.getenv("GH_TOKEN"))
        self.parser = AdvancedM3UParser()
        self.validator = ChannelValidator()
        self.seen_hashes = set()

    def process(self):
        # 收集所有来源
        sources = set(CONFIG["sources"]["custom_urls"] + self.collector.fetch_github_sources())
        
        # 并发处理
        with ThreadPoolExecutor(max_workers=CONFIG["sources"]["max_workers"]) as executor:
            channels = list(executor.map(self._process_source, sources))

        # 过滤和验证
        valid_channels = [chan for sublist in channels for chan in sublist if self._is_valid_channel(chan)]
        
        # 质量检测
        with ThreadPoolExecutor(max_workers=3) as executor:
            quality_reports = list(executor.map(QualityAnalyzer.analyze_stream, [chan["url"] for chan in valid_channels]))

        # 生成输出
        EnhancedFileGenerator.generate_outputs(valid_channels)

    def _process_source(self, url: str) -> List[Dict]:
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return self.parser.parse(response.text)
        except Exception as e:
            print(f"Error processing {url}: {str(e)}")
        return []

    def _is_valid_channel(self, chan: Dict) -> bool:
        # 哈希去重
        if chan["hash"] in self.seen_hashes:
            return False
        self.seen_hashes.add(chan["hash"])
        
        # 分类过滤
        if not any(cat in chan["group"] for cat in CONFIG["filters"]["allowed_categories"]):
            return False
            
        # 黑名单过滤
        if any(kw in chan["title"] for kw in CONFIG["filters"]["block_keywords"]):
            return False
            
        # 有效性验证
        return self.validator.check_url_reachable(chan["url"])

if __name__ == "__main__":
    IPTVManager().process()
