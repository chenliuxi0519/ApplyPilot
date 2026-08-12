import ipaddress
import re
import socket
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlsplit

import httpx

from app.modules.columns import get_datetime_utc

OFFICIAL_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "nus.edu.sg",
    "ntu.edu.sg",
    "hkust.edu.hk",
    "hku.hk",
    "cuhk.edu.hk",
    "imperial.ac.uk",
    "ucl.ac.uk",
    "ed.ac.uk",
    "manchester.ac.uk",
    "kcl.ac.uk",
    "warwick.ac.uk",
    "southampton.ac.uk",
)

REQUEST_TIMEOUT_SECONDS = 20.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_REDIRECTS = 5

# 不带 UA 的请求会被多数学校官网拒绝。
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en,zh;q=0.9",
}

_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_RE = re.compile(r"\n\s*\n+")


class FetchError(RuntimeError):
    """页面读不到。"""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    text: str
    captured_at: str


def is_official_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in OFFICIAL_DOMAIN_SUFFIXES
    )


def _reject_non_public_address(host: str) -> None:
    """避免把内网地址伪装成官方域名来读取。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise FetchError(f"无法解析域名：{host}") from error

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise FetchError(f"{host} 解析到非公网地址，已拒绝读取")


def html_to_text(html: str) -> str:
    without_scripts = _SCRIPT_RE.sub(" ", html)
    text = _TAG_RE.sub("\n", without_scripts)
    # WordPress 之类的站点会把引号输出成 &#8217;，不解码会混进原文引用。
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return _BLANK_RE.sub("\n\n", text).strip()


def fetch_official_page(url: str) -> FetchedPage:
    if not url.startswith("https://"):
        raise FetchError(f"只读取 https 页面：{url}")
    if not is_official_url(url):
        raise FetchError(f"{url} 不在官方域名白名单内，已拒绝读取")

    host = urlsplit(url).hostname or ""
    _reject_non_public_address(host)

    try:
        with httpx.Client(
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            headers=_HEADERS,
        ) as client:
            response = client.get(url)
    except httpx.HTTPError as error:
        raise FetchError(f"读取 {url} 失败：{type(error).__name__}") from error

    # 跳转后仍须落在白名单内，避免被重定向带出官方站点。
    final_url = str(response.url)
    if not is_official_url(final_url):
        raise FetchError(f"{url} 跳转到了非官方域名 {final_url}，已放弃")

    if response.status_code == 403:
        raise FetchError(f"{final_url} 拒绝了本次读取（403），该站点不接受程序访问")
    if response.status_code != 200:
        raise FetchError(f"{final_url} 返回 HTTP {response.status_code}")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise FetchError(f"{final_url} 响应体过大，已放弃")

    text = html_to_text(response.text)
    if len(text) < 200:
        raise FetchError(f"{final_url} 正文过短，可能需要浏览器渲染")

    return FetchedPage(
        url=final_url, text=text, captured_at=get_datetime_utc().isoformat()
    )
