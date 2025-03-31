"""
IPTV Ultimate - 全功能直播管理系统
包含：EPG聚合、智能匹配、多协议支持、高级过滤
"""

import sys
import re
import json
import time
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from urllib.parse import urlparse, urljoin

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# 配置中心
CONFIG = {
    "sources": {
        "iptv": {
            "github_keywords": ["IPTV", "直播源", "直播地址"],
            "custom_urls": [
                "https://git.gra.phite.ro/alantang/tvbs/raw/branch/main/output/result.m3u",
                "https://gh.tryxd.cn/https://raw.githubusercontent.com/alantang1977/auto-iptv/main/live_ipv4.txt",
                "https://git.gra.phite.ro/alantang/itv/raw/branch/main/tv.m3u"
            ],
            "max_workers": 8
        },
        "epg": {
            "providers": [
                "https://epg.112114.xyz/pp.xml",
                "https://epg.112114.xyz/ds.xml",
                "https://raw.githubusercontent.com/Kodi-vStream/iptv/master/epg.xml"
            ],
            "cache_ttl": 86400  # EPG缓存时间（秒）
        }
    },
    "matching": {
        "fuzzy_match": True,
        "priority": ["tvg-id", "tvg-name", "channel-name"],
        "lang_preference": ["zh", "en"]
    },
    "output": {
        "formats": ["m3u", "json", "html"],
        "epg_strategy": "merge",  # 合并策略：merge/replace
        "epg_pretty": True
    }
}

class EPGManager:
    """EPG聚合管理系统"""
    
    def __init__(self):
        self.epg_data = {}
        self.last_update = 0
        self.cache_dir = Path("epg_cache")
        self.cache_dir.mkdir(exist_ok=True)

    def _download_epg(self, url: str) -> Optional[ET.ElementTree]:
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return ET.fromstring(resp.content)
        except Exception as e:
            print(f"EPG下载失败 {url}: {str(e)}")
            return None

    def _parse_epg(self, root: ET.ElementTree) -> Dict:
        ns = {'tv': 'http://xmltv.org/xmltv.dtd'}
        epg = {}
        
        for channel in root.findall('.//tv:channel', ns):
            chan_id = channel.get('id')
            epg[chan_id] = {
                'display_names': [e.text for e in channel.findall('tv:display-name', ns)],
                'icons': [e.get('src') for e in channel.findall('tv:icon', ns)]
            }

        for programme in root.findall('.//tv:programme', ns):
            chan_id = programme.get('channel')
            start = datetime.strptime(programme.get('start'), '%Y%m%d%H%M%S %z')
            end = datetime.strptime(programme.get('stop'), '%Y%m%d%H%M%S %z')
            
            epg.setdefault(chan_id, {}).setdefault('programmes', []).append({
                'start': start.isoformat(),
                'end': end.isoformat(),
                'title': programme.findtext('tv:title', '', ns),
                'desc': programme.findtext('tv:desc', '', ns),
                'category': programme.findtext('tv:category', '', ns)
            })
            
        return epg

    def update_epg(self):
        """更新EPG数据"""
        if time.time() - self.last_update < CONFIG["epg"]["cache_ttl"]:
            return
            
        merged_epg = {}
        for provider in CONFIG["epg"]["providers"]:
            cache_file = self.cache_dir / f"{hashlib.md5(provider.encode()).hexdigest()}.xml"
            
            if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CONFIG["epg"]["cache_ttl"]:
                root = ET.parse(cache_file)
            else:
                root = self._download_epg(provider)
                if root:
                    ET.ElementTree(root).write(cache_file)
            
            if root:
                provider_epg = self._parse_epg(root)
                if CONFIG["output"]["epg_strategy"] == "merge":
                    merged_epg.update(provider_epg)
                else:
                    merged_epg = provider_epg

        self.epg_data = merged_epg
        self.last_update = time.time()

    def match_channel(self, channel: Dict) -> Optional[Dict]:
        """频道EPG匹配"""
        identifiers = [
            channel.get('tvg-id'),
            channel.get('tvg-name'),
            channel.get('name'),
            *channel.get('aliases', [])
        ]
        
        # 精确匹配
        for id_type in CONFIG["matching"]["priority"]:
            if id_type in channel and channel[id_type] in self.epg_data:
                return self.epg_data[channel[id_type]]
        
        # 模糊匹配
        if CONFIG["matching"]["fuzzy_match"]:
            for chan_id, epg in self.epg_data.items():
                for name in epg['display_names']:
                    if any(identifier for identifier in identifiers if self._similar(identifier, name)):
                        return epg
        return None

    @staticmethod
    def _similar(a: str, b: str) -> bool:
        """相似度匹配算法"""
        a = re.sub(r'\W+', '', a.lower())
        b = re.sub(r'\W+', '', b.lower())
        return a in b or b in a or a.startswith(b) or b.startswith(a)

class EnhancedChannel:
    """增强型频道模型"""
    
    def __init__(self, raw_data: Dict):
        self.id = hashlib.md5(raw_data['url'].encode()).hexdigest()
        self.tvg_id = raw_data.get('tvg-id', '')
        self.name = raw_data.get('name', '')
        self.group = raw_data.get('group', '未分组')
        self.url = raw_data['url']
        self.epg = None
        self.metadata = {
            'source': raw_data.get('source', 'unknown'),
            'quality': raw_data.get('quality', 0),
            'last_checked': datetime.now().isoformat()
        }

class IPTVSystem:
    """核心系统"""
    
    def __init__(self):
        self.epg_manager = EPGManager()
        self.channels = {}
        
    def process(self):
        # 阶段1：数据采集
        iptv_sources = self._collect_iptv_sources()
        epg_sources = self._collect_epg_sources()
        
        # 阶段2：数据处理
        with ThreadPoolExecutor(max_workers=CONFIG["iptv"]["max_workers"]) as executor:
            futures = [executor.submit(self._process_source, url) for url in iptv_sources]
            for future in as_completed(futures):
                if channels := future.result():
                    self._add_channels(channels)

        # 阶段3：EPG匹配
        self.epg_manager.update_epg()
        self._match_epg()
        
        # 阶段4：生成输出
        self._generate_outputs()
        
    def _collect_iptv_sources(self) -> List[str]:
        """收集直播源地址"""
        # 实现GitHub仓库爬取逻辑（同之前版本）
        return CONFIG["iptv"]["custom_urls"] + github_sources
    
    def _process_source(self, url: str) -> List[EnhancedChannel]:
        """处理单个直播源"""
        try:
            resp = requests.get(url, timeout=10)
            if resp.ok:
                return [EnhancedChannel(chan) for chan in M3UParser().parse(resp.text)]
        except Exception as e:
            print(f"源处理失败 {url}: {str(e)}")
        return []
    
    def _add_channels(self, new_channels: List[EnhancedChannel]):
        """添加新频道（自动去重）"""
        for chan in new_channels:
            if chan.id not in self.channels or chan.metadata['quality'] > self.channels[chan.id].metadata['quality']:
                self.channels[chan.id] = chan
                
    def _match_epg(self):
        """执行EPG匹配"""
        for chan in self.channels.values():
            chan.epg = self.epg_manager.match_channel({
                'tvg-id': chan.tvg_id,
                'name': chan.name,
                'aliases': [chan.name.split(' '), chan.name.replace(' ', '')]
            })
    
    def _generate_outputs(self):
        """生成输出文件"""
        # M3U输出
        if 'm3u' in CONFIG["output"]["formats"]:
            with open('live.m3u', 'w', encoding='utf-8') as f:
                f.write(f'#EXTM3U x-tvg-url="epg.xml" url-tvg="{"|".join(CONFIG["epg"]["providers"])}"\n')
                for chan in self.channels.values():
                    epg_info = f'tvg-id="{chan.tvg_id}" ' if chan.tvg_id else ''
                    f.write(f'#EXTINF:-1 {epg_info}group-title="{chan.group}",{chan.name}\n{chan.url}\n')
        
        # JSON输出
        if 'json' in CONFIG["output"]["formats"]:
            output_data = [self._serialize_channel(chan) for chan in self.channels.values()]
            with open('live.json', 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
                
        # HTML可视化
        if 'html' in CONFIG["output"]["formats"]:
            self._generate_html_report()
            
        # EPG文件
        self._generate_epg_file()

    def _serialize_channel(self, chan: EnhancedChannel) -> Dict:
        return {
            'id': chan.id,
            'name': chan.name,
            'group': chan.group,
            'url': chan.url,
            'epg': chan.epg,
            'metadata': chan.metadata
        }
    
    def _generate_html_report(self):
        """生成可视化HTML报告"""
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>IPTV Live Report</title>
            <style>
                /* 添加CSS样式 */
            </style>
        </head>
        <body>
            <h1>频道总数: {{count}}</h1>
            <div class="channels">
                {% for chan in channels %}
                <div class="channel">
                    <h3>{{chan.name}}</h3>
                    <p>分类: {{chan.group}}</p>
                    {% if chan.epg %}
                    <div class="epg">
                        {% for prog in chan.epg.programmes|slice(3) %}
                        <div class="programme">
                            {{prog.start}} - {{prog.title}}
                        </div>
                        {% endfor %}
                    </div>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </body>
        </html>
        """
        # 使用模板引擎渲染（实际实现需添加模板处理）
        
    def _generate_epg_file(self):
        """生成合并后的EPG文件"""
        # 实现XML生成逻辑（符合XMLTV标准）

if __name__ == "__main__":
    IPTVSystem().process()
