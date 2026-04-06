"""纯 HTTP 协议登录 labs.google — 走 NextAuth + Google OAuth 流程"""
import json
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from .config import config
from .logger import logger
from .proxy_utils import parse_proxy


# labs.google / NextAuth Google OAuth 所需的 cookie 名称
_GOOGLE_COOKIE_NAMES = ("SID", "HSID", "SSID", "APISID", "SAPISID")


def _parse_google_cookies(raw: str) -> Dict[str, str]:
    """解析 Google cookies 输入，支持 JSON 和纯文本格式"""
    text = (raw or "").strip()
    if not text:
        return {}

    # 尝试 JSON
    try:
        data = json.loads(text)
        if isinstance(data, list):
            result = {}
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name", "")
                    value = item.get("value", "")
                    if name and value:
                        result[name] = value
            return result
        if isinstance(data, dict):
            # 可能是 {"cookies": [...]} 或 {"SID": "...", ...}
            cookies_list = data.get("cookies")
            if isinstance(cookies_list, list):
                result = {}
                for item in cookies_list:
                    if isinstance(item, dict):
                        name = item.get("name", "")
                        value = item.get("value", "")
                        if name and value:
                            result[name] = value
                return result
            # 扁平 key=value
            return {k: v for k, v in data.items() if isinstance(v, str) and v}
    except (json.JSONDecodeError, ValueError):
        pass

    # 纯文本格式：name=value; name2=value2
    result = {}
    for part in text.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            name = name.strip()
            value = value.strip()
            if name and value:
                result[name] = value
    return result


def _build_cookie_header(cookies: Dict[str, str]) -> str:
    """构建 Cookie 请求头"""
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _extract_session_token_from_headers(response: httpx.Response) -> Optional[str]:
    """从响应的 Set-Cookie 头提取 session token"""
    cookie_name = config.session_cookie_name
    for header_value in response.headers.get_list("set-cookie"):
        # 格式：__Secure-next-auth.session-token=xxx; Path=/; ...
        if header_value.startswith(f"{cookie_name}="):
            token = header_value.split("=", 1)[1].split(";")[0]
            return token.strip()
    return None


def _extract_all_session_tokens(response: httpx.Response) -> Dict[str, str]:
    """从响应的所有 Set-Cookie 头提取所有 cookie"""
    result = {}
    for header_value in response.headers.get_list("set-cookie"):
        parts = header_value.split(";")[0]
        if "=" in parts:
            name, _, value = parts.partition("=")
            result[name.strip()] = value.strip()
    return result


class ProtocolLogin:
    """纯 HTTP 协议登录 labs.google"""

    LABS_BASE = "https://labs.google/fx"

    def _get_proxy_url(self, proxy_str: Optional[str]) -> Optional[str]:
        """将代理配置转为 httpx 可用的 URL"""
        if not proxy_str:
            return None
        proxy_config = parse_proxy(proxy_str)
        if not proxy_config:
            return None
        scheme = proxy_config.get("scheme", "http")
        host = proxy_config.get("host", "")
        port = proxy_config.get("port", "")
        username = proxy_config.get("username", "")
        password = proxy_config.get("password", "")
        if not host:
            return None
        auth = f"{username}:{password}@" if username and password else ""
        return f"{scheme}://{auth}{host}:{port}"

    async def login(
        self,
        google_cookies_raw: str,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        纯 HTTP 协议登录。

        输入：Google cookies（JSON 或纯文本格式）
        输出：{"success": bool, "session_token": str, "error": str}
        """
        google_cookies = _parse_google_cookies(google_cookies_raw)

        # 检查是否有关键 cookie
        has_required = any(name in google_cookies for name in _GOOGLE_COOKIE_NAMES)
        if not has_required:
            return {
                "success": False,
                "error": "未找到有效的 Google cookie（需要 SID/HSID/SSID/APISID/SAPISID 中的至少一个）",
            }

        proxy_url = self._get_proxy_url(proxy)
        common_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=30,
            follow_redirects=False,
            headers=common_headers,
        ) as client:
            try:
                # 步骤1：获取 CSRF token
                logger.info("[协议登录] 获取 CSRF token...")
                csrf_resp = await client.get(f"{self.LABS_BASE}/api/auth/csrf")
                if csrf_resp.status_code != 200:
                    return {"success": False, "error": f"获取 CSRF 失败: HTTP {csrf_resp.status_code}"}

                csrf_data = csrf_resp.json()
                csrf_token = csrf_data.get("csrfToken")
                if not csrf_token:
                    return {"success": False, "error": "CSRF 响应中无 csrfToken"}

                # 同时拿到 labs 的初始 cookies
                labs_cookies = {}
                for cookie_header in csrf_resp.headers.get_list("set-cookie"):
                    parts = cookie_header.split(";")[0]
                    if "=" in parts:
                        name, _, value = parts.partition("=")
                        labs_cookies[name.strip()] = value.strip()

                # 步骤2：POST signin/google
                logger.info("[协议登录] 请求 Google OAuth URL...")
                signin_resp = await client.post(
                    f"{self.LABS_BASE}/api/auth/signin/google",
                    data={
                        "csrfToken": csrf_token,
                        "callbackUrl": "https://labs.google/fx",
                        "json": "true",
                    },
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": f"{self.LABS_BASE}",
                        "Origin": "https://labs.google",
                        "Cookie": _build_cookie_header(labs_cookies) if labs_cookies else "",
                    },
                )

                if signin_resp.status_code != 200:
                    return {"success": False, "error": f"Signin 请求失败: HTTP {signin_resp.status_code}"}

                # 合并 signin 响应的 cookies
                for cookie_header in signin_resp.headers.get_list("set-cookie"):
                    parts = cookie_header.split(";")[0]
                    if "=" in parts:
                        name, _, value = parts.partition("=")
                        labs_cookies[name.strip()] = value.strip()

                signin_data = signin_resp.json()
                redirect_url = signin_data.get("redirect") or signin_data.get("url")
                if not redirect_url:
                    return {
                        "success": False,
                        "error": f"Signin 响应中无重定向 URL: {json.dumps(signin_data)[:200]}",
                    }

                # 步骤3：用 Google cookies 访问 OAuth URL
                logger.info("[协议登录] 跟随 Google OAuth 重定向...")
                google_cookie_header = _build_cookie_header(google_cookies)
                oauth_resp = await client.get(
                    redirect_url,
                    headers={
                        "Cookie": google_cookie_header,
                        "Referer": "https://labs.google/",
                    },
                )

                # Google 可能返回多次 302 重定向
                max_redirects = 10
                callback_url = None
                current_resp = oauth_resp
                for _ in range(max_redirects):
                    location = current_resp.headers.get("location")
                    if not location:
                        return {
                            "success": False,
                            "error": f"Google OAuth 未返回重定向（HTTP {current_resp.status_code}）",
                        }

                    # 检查是否回到了 labs.google callback
                    if "labs.google/fx/api/auth/callback/google" in location:
                        callback_url = location
                        break

                    # 跟随重定向
                    if current_resp.status_code not in (301, 302, 303, 307, 308):
                        return {
                            "success": False,
                            "error": f"Google OAuth 意外状态码 {current_resp.status_code}",
                        }

                    # 继续跟随 Google 内部重定向
                    logger.info(f"[协议登录] 重定向到: {location[:100]}...")
                    current_resp = await client.get(
                        location,
                        headers={
                            "Cookie": google_cookie_header,
                            "Referer": "https://accounts.google.com/",
                        },
                    )

                if not callback_url:
                    return {"success": False, "error": "Google OAuth 流程中未获得 callback URL"}

                # 步骤4：访问 callback URL，换取 session cookie
                logger.info("[协议登录] 交换 auth code 换取 session...")
                callback_resp = await client.get(
                    callback_url,
                    headers={
                        "Cookie": _build_cookie_header(labs_cookies),
                        "Referer": "https://accounts.google.com/",
                    },
                )

                # callback 可能也会重定向
                session_token = _extract_session_token_from_headers(callback_resp)

                # 跟随 callback 的重定向
                max_cb_redirects = 5
                current_cb = callback_resp
                for _ in range(max_cb_redirects):
                    if session_token:
                        break
                    location = current_cb.headers.get("location")
                    if not location or current_cb.status_code not in (301, 302, 303, 307, 308):
                        break

                    # 合并 cookies
                    for cookie_header in current_cb.headers.get_list("set-cookie"):
                        session_token = session_token or _extract_session_token_from_headers(
                            type("FakeResp", (), {"headers": type("H", (), {"get_list": lambda s, n: [cookie_header]})()})()
                        )
                        # 直接解析
                        parts = cookie_header.split(";")[0]
                        if "=" in parts:
                            name, _, value = parts.partition("=")
                            if name.strip() == config.session_cookie_name:
                                session_token = value.strip()

                    # 跟随重定向
                    all_cookies = dict(labs_cookies)
                    for cookie_header in current_cb.headers.get_list("set-cookie"):
                        parts = cookie_header.split(";")[0]
                        if "=" in parts:
                            name, _, value = parts.partition("=")
                            all_cookies[name.strip()] = value.strip()

                    current_cb = await client.get(
                        location,
                        headers={"Cookie": _build_cookie_header(all_cookies)},
                    )

                    # 检查这次响应的 set-cookie
                    for cookie_header in current_cb.headers.get_list("set-cookie"):
                        parts = cookie_header.split(";")[0]
                        if "=" in parts:
                            name, _, value = parts.partition("=")
                            if name.strip() == config.session_cookie_name:
                                session_token = value.strip()

                if not session_token:
                    return {
                        "success": False,
                        "error": "未获取到 session token，Google session 可能已过期或需要重新授权",
                    }

                logger.info("[协议登录] 登录成功")
                return {
                    "success": True,
                    "session_token": session_token,
                }

            except httpx.TimeoutException:
                return {"success": False, "error": "请求超时，可能是代理或网络问题"}
            except httpx.ConnectError as e:
                return {"success": False, "error": f"连接失败: {e}"}
            except Exception as e:
                logger.error(f"[协议登录] 异常: {e}")
                return {"success": False, "error": str(e)}


protocol_loginer = ProtocolLogin()
