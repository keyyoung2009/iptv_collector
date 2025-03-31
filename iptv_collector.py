import re
import requests
from pathlib import Path
from typing import Set, List, Dict
from urllib.parse import urlparse

class M3UProcessor:
    def __init__(self):
        self.channel_pattern = re.compile(r'#EXTINF:-1\s+tvg-name="([^"]+)".*group-title="([^"]+)".*,(.*)\n(http.*)')

    def parse(self, content: str) -> List[Dict]:
        return [{
            'name': match.strip(),
            'category': match‌:ml-citation{ref="1" data="citationList"}.strip(),
            'title': match‌:ml-citation{ref="2" data="citationList"}.strip(),
            'url': match‌:ml-citation{ref="3" data="citationList"}.strip()
        } for match in self.channel_pattern.findall(content)]

class GitHubCrawler:
    def __init__(self, token: str):
        self.headers = {'Authorization': f'token {token}'}
    
    def search_repos(self, keywords: str = "IPTV live") -> List[str]:
        response = requests.get(
            "https://api.github.com/search/repositories",
            params={'q': f'{keywords} in:name,description fork:true', 'sort': 'updated'},
            headers=self.headers
        )
        return [item['html_url'] for item in response.json()['items'][:5]]

class FileGenerator:
    @staticmethod
    def save_m3u(channels: List[Dict], filename: str = "live.m3u"):
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            for chan in channels:
                f.write(f'#EXTINF:-1 tvg-name="{chan["name"]}" group-title="{chan["category"]}",{chan["title"]}\n{chan["url"]}\n')

    @staticmethod
    def save_txt(channels: List[Dict], filename: str = "live.txt"):
        with open(filename, 'w', encoding='utf-8') as f:
            for chan in channels:
                f.write(f'{chan["name"]},{chan["url"]}\n')

def main():
    # 配置参数
    GITHUB_TOKEN = os.getenv('GH_TOKEN')
    CUSTOM_URLS = [
        'https://git.gra.phite.ro/alantang/itv/raw/branch/main/tv.m3u',
        'https://git.gra.phite.ro/alantang/tvbs/raw/branch/main/output/result.txt'
    ]

    # 初始化处理器
    crawler = GitHubCrawler(GITHUB_TOKEN)
    processor = M3UProcessor()
    
    # 收集数据源
    sources = set(crawler.search_repos()[0:3] + CUSTOM_URLS)
    
    # 处理所有源
    all_channels = []
    seen_urls = set()
    for url in sources:
        try:
            content = requests.get(url).text
            if any(url.endswith(ext) for ext in ('.m3u', '.m3u8', '.txt')):
                channels = processor.parse(content)
                for chan in channels:
                    if chan['url'] not in seen_urls:
                        seen_urls.add(chan['url'])
                        all_channels.append(chan)
        except Exception as e:
            print(f"Error processing {url}: {str(e)}")

    # 生成文件
    FileGenerator.save_m3u(all_channels)
    FileGenerator.save_txt(all_channels)

if __name__ == "__main__":
    main()
