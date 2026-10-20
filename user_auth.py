#!/usr/bin/env python3
"""
TeleAgent OpenAI-Compatible Proxy —— 用户登录鉴权模块
=====================================================

本模块只做「纯逻辑」：账号、口令、会话。
- 不依赖 http.server，不 import openai_proxy；
- 因此可被单元测试直接驱动，也能在不改动 openai_proxy.py 的前提下先行落地；
- 路由接线、界面、文档分别由三条并行泳道负责，契约见 docs/user-login-api-contract.md。

设计要点（决策依据见 docs/adr-0001-user-login-auth-scheme.md）：
  1. 默认采用「服务端登录会话 + Cookie（tap_sid）」，不采用 JWT：
     控制台是同源浏览器 UI，Cookie 免去前端存储令牌与 CSRF 之外的一整套泄露面；
     服务端登录会话可即时吊销（登出/停用用户立即生效），而无状态 JWT 做不到。
  2. 凭据形态被隔离在 LoginSessionStore 之后。若日后改用 JWT，只需新增一个
     同接口的 JwtProvider 并替换 AuthManager 内部实现，路由与前端契约不变。
  3. 口令用 PBKDF2-HMAC-SHA256（标准库 hashlib）加盐存储，算法与迭代次数
     随哈希一起保存，便于日后平滑升级到更强的 KDF。
  4. 登录失败限流（按「用户名 + 来源 IP」锁定），降低在线爆破风险。
  5. 变更类请求需要 CSRF Token（双提交），配合 SameSite=Lax Cookie。

命令行（不依赖代理进程即可管理账号）：
    python user_auth.py --init-admin admin
    python user_auth.py --list-users
    python user_auth.py --set-mode required
    python user_auth.py --disable-user someone
"""

import argparse
import base64
import binascii
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time

# ============================================================
# 常量
# ============================================================

# 账号库文件（与 auth.json 同目录，运行期生成，禁止入库）
USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

# 会话 Cookie 名
SESSION_COOKIE_NAME = "tap_sid"

# 会话有效期（秒），默认 8 小时
DEFAULT_SESSION_TTL = 8 * 3600

# PBKDF2 迭代次数（SHA-256 下的推荐量级；实测单次约 0.1s，本机无压力）
DEFAULT_PBKDF2_ITERATIONS = 210000

# 口令策略：只约束长度，不做字符集规则（现代共识：长度 + 强度胜过复杂度拼凑）
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256

# 角色
ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_VIEWER)

# 用户状态
STATUS_ENABLED = "enabled"
STATUS_DISABLED = "disabled"

# 登录模式：
#   off       - 不启用登录校验（默认，首次上线时保持现网行为不变）
#   optional  - 校验登录，但本机来源（127.0.0.1）仍放行，便于灰度与回滚
#   required  - 全量强制登录
LOGIN_MODES = ("off", "optional", "required")

# 登录失败限流
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_ATTEMPT_WINDOW = 300     # 统计窗口（秒）
DEFAULT_LOCKOUT_SECONDS = 60     # 触发后的锁定时长（秒）

# 用户名规则：3-32 位，字母数字与 . _ -
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")

# 错误码（前端据此区分提示文案）
ERR_INVALID_CREDENTIALS = "invalid_credentials"
ERR_LOCKED_OUT = "locked_out"
ERR_USER_DISABLED = "user_disabled"
ERR_WEAK_PASSWORD = "weak_password"
ERR_INVALID_USERNAME = "invalid_username"
ERR_USER_EXISTS = "user_exists"
ERR_USER_NOT_FOUND = "user_not_found"
ERR_INVALID_MODE = "invalid_mode"
ERR_INVALID_ROLE = "invalid_role"
ERR_CSRF_FAILED = "csrf_failed"
ERR_NO_SESSION = "no_session"


class AuthError(Exception):
    """鉴权相关错误，携带稳定的错误码供前端分支处理。"""

    def __init__(self, code, message=None, retry_after=None):
        self.code = code
        self.message = message or code
        self.retry_after = retry_after
        super().__init__(self.message)

    def to_dict(self):
        d = {"error": {"message": self.message, "type": "invalid_request_error",
                       "param": None, "code": self.code}}
        if self.retry_after is not None:
            d["error"]["retry_after"] = self.retry_after
        return d


# ============================================================
# 口令哈希
# ============================================================

def hash_password(password, iterations=DEFAULT_PBKDF2_ITERATIONS):
    """生成自描述的口令哈希串。

    格式：pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
    自描述的好处：日后提高迭代次数或换算法时，老记录仍可被正确校验。
    """
    if not isinstance(password, str):
        raise AuthError(ERR_WEAK_PASSWORD, "口令必须是字符串")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(ERR_WEAK_PASSWORD,
                        "口令至少 %d 个字符" % MIN_PASSWORD_LENGTH)
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AuthError(ERR_WEAK_PASSWORD, "口令过长")
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations,
        _b64(salt),
        _b64(dk),
    )


def verify_password(password, stored):
    """校验口令。格式非法或用户不存在一律返回 False，不抛异常。"""
    if not isinstance(password, str) or not stored or not isinstance(stored, str):
        return False
    try:
        algo, iters_s, salt_s, hash_s = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iters_s)
        if iterations <= 0:
            return False
        salt = _unb64(salt_s)
        expected = _unb64(hash_s)
    except (ValueError, TypeError, binascii.Error):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text):
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# ============================================================
# 账号库
# ============================================================

class UserStore:
    """基于 JSON 文件的账号库（原子写 + 线程锁）。"""

    def __init__(self, path=USERS_FILE, iterations=DEFAULT_PBKDF2_ITERATIONS, clock=None):
        self.path = path
        self.iterations = iterations
        self._clock = clock or time.time
        self._lock = threading.RLock()

    # ---------- 内部 ----------

    def _default_config(self):
        return {"version": 1, "mode": "off", "users": []}

    def _load(self):
        cfg = self._default_config()
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    mode = loaded.get("mode")
                    if mode in LOGIN_MODES:
                        cfg["mode"] = mode
                    users = loaded.get("users")
                    if isinstance(users, list):
                        cfg["users"] = [u for u in users if isinstance(u, dict)]
        except Exception as e:
            print("[WARN] 读取账号库失败: %s" % e, file=sys.stderr)
        return cfg

    def _save(self, cfg):
        """原子写：先写临时文件再 os.replace，避免半截文件。"""
        tmp = self.path + ".tmp"
        directory = os.path.dirname(os.path.abspath(self.path))
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            print("[WARN] 保存账号库失败: %s" % e, file=sys.stderr)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    @staticmethod
    def _public(rec):
        """对外视图：不含口令哈希。"""
        return {
            "id": rec.get("id"),
            "username": rec.get("username"),
            "role": rec.get("role", ROLE_VIEWER),
            "status": rec.get("status", STATUS_ENABLED),
            "created_at": rec.get("created_at"),
            "updated_at": rec.get("updated_at"),
            "last_login_at": rec.get("last_login_at"),
        }

    @staticmethod
    def _normalize(username):
        if not isinstance(username, str):
            raise AuthError(ERR_INVALID_USERNAME, "用户名无效")
        name = username.strip()
        if not USERNAME_RE.match(name):
            raise AuthError(ERR_INVALID_USERNAME,
                            "用户名需为 3-32 位字母、数字或 . _ -")
        return name.lower()

    # ---------- 对外 ----------

    def get_mode(self):
        with self._lock:
            return self._load()["mode"]

    def set_mode(self, mode):
        if mode not in LOGIN_MODES:
            raise AuthError(ERR_INVALID_MODE, "未知模式: %s" % mode)
        with self._lock:
            cfg = self._load()
            cfg["mode"] = mode
            self._save(cfg)
        return mode

    def list_users(self):
        with self._lock:
            return [self._public(r) for r in self._load()["users"]]

    def get_user(self, username):
        """按用户名取对外视图（找不到返回 None）。"""
        try:
            name = self._normalize(username)
        except AuthError:
            return None
        with self._lock:
            for rec in self._load()["users"]:
                if rec.get("username") == name:
                    return self._public(rec)
        return None

    def get_user_by_id(self, user_id):
        with self._lock:
            for rec in self._load()["users"]:
                if rec.get("id") == user_id:
                    return self._public(rec)
        return None

    def count(self):
        with self._lock:
            return len(self._load()["users"])

    def create_user(self, username, password, role=ROLE_VIEWER,
                    status=STATUS_ENABLED):
        name = self._normalize(username)
        if role not in ROLES:
            raise AuthError(ERR_INVALID_ROLE, "未知角色: %s" % role)
        pwd_hash = hash_password(password, self.iterations)
        now = int(self._clock())
        with self._lock:
            cfg = self._load()
            for rec in cfg["users"]:
                if rec.get("username") == name:
                    raise AuthError(ERR_USER_EXISTS, "用户名已存在")
            rec = {
                "id": "u_" + secrets.token_hex(6),
                "username": name,
                "password": pwd_hash,
                "role": role,
                "status": status,
                "created_at": now,
                "updated_at": now,
                "last_login_at": None,
            }
            cfg["users"].append(rec)
            self._save(cfg)
        return self._public(rec)

    def set_password(self, username, password):
        name = self._normalize(username)
        pwd_hash = hash_password(password, self.iterations)
        with self._lock:
            cfg = self._load()
            for rec in cfg["users"]:
                if rec.get("username") == name:
                    rec["password"] = pwd_hash
                    rec["updated_at"] = int(self._clock())
                    self._save(cfg)
                    return True
        raise AuthError(ERR_USER_NOT_FOUND, "用户不存在")

    def set_status(self, username, status):
        name = self._normalize(username)
        with self._lock:
            cfg = self._load()
            for rec in cfg["users"]:
                if rec.get("username") == name:
                    rec["status"] = status
                    rec["updated_at"] = int(self._clock())
                    self._save(cfg)
                    return True
        raise AuthError(ERR_USER_NOT_FOUND, "用户不存在")

    def set_role(self, username, role):
        if role not in ROLES:
            raise AuthError(ERR_INVALID_ROLE, "未知角色: %s" % role)
        name = self._normalize(username)
        with self._lock:
            cfg = self._load()
            for rec in cfg["users"]:
                if rec.get("username") == name:
                    rec["role"] = role
                    rec["updated_at"] = int(self._clock())
                    self._save(cfg)
                    return True
        raise AuthError(ERR_USER_NOT_FOUND, "用户不存在")

    def delete_user(self, username):
        name = self._normalize(username)
        with self._lock:
            cfg = self._load()
            before = len(cfg["users"])
            cfg["users"] = [r for r in cfg["users"] if r.get("username") != name]
            if len(cfg["users"]) == before:
                raise AuthError(ERR_USER_NOT_FOUND, "用户不存在")
            self._save(cfg)
        return True

    def touch_login(self, user_id):
        with self._lock:
            cfg = self._load()
            for rec in cfg["users"]:
                if rec.get("id") == user_id:
                    rec["last_login_at"] = int(self._clock())
                    self._save(cfg)
                    return

    def verify(self, username, password):
        """校验口令，返回内部记录（找不到或口令错返回 None）。"""
        try:
            name = self._normalize(username)
        except AuthError:
            return None
        with self._lock:
            for rec in self._load()["users"]:
                if rec.get("username") == name:
                    if not verify_password(password, rec.get("password", "")):
                        return None
                    return rec
        return None


# ============================================================
# 会话
# ============================================================

class LoginSessionStore:
    """进程内**登录会话**表（不落盘：重启后需重新登录，这是可接受且更安全的默认）。

    命名说明：本仓库里 "session" 专指 super-agent 会话（create_session / /api/sessions），
    与「登录会话」同名不同物，故此处一律使用 LoginSession 前缀。
    """

    def __init__(self, ttl=DEFAULT_SESSION_TTL, clock=None, max_per_user=5,
                 sliding=True):
        self.ttl = ttl
        self.max_per_user = max_per_user
        self.sliding = sliding
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._sessions = {}

    def create(self, user_id, username, role):
        token = secrets.token_urlsafe(32)   # 256 位随机
        now = self._clock()
        sess = {
            "token": token,
            "user_id": user_id,
            "username": username,
            "role": role,
            "csrf_token": secrets.token_urlsafe(24),
            "created_at": now,
            "last_seen": now,
            "expires_at": now + self.ttl,
        }
        with self._lock:
            self._sessions[token] = sess
            self._enforce_max_per_user(user_id)
        return dict(sess)

    def get(self, token):
        if not token:
            return None
        with self._lock:
            sess = self._sessions.get(token)
            if not sess:
                return None
            now = self._clock()
            if sess["expires_at"] <= now:
                self._sessions.pop(token, None)
                return None
            sess["last_seen"] = now
            if self.sliding:
                sess["expires_at"] = now + self.ttl
            return dict(sess)

    def revoke(self, token):
        with self._lock:
            return self._sessions.pop(token, None) is not None

    def revoke_user(self, user_id):
        with self._lock:
            dead = [t for t, s in self._sessions.items() if s["user_id"] == user_id]
            for t in dead:
                self._sessions.pop(t, None)
            return len(dead)

    def purge_expired(self):
        with self._lock:
            now = self._clock()
            dead = [t for t, s in self._sessions.items() if s["expires_at"] <= now]
            for t in dead:
                self._sessions.pop(t, None)
            return len(dead)

    def _enforce_max_per_user(self, user_id):
        owned = [(s["created_at"], t) for t, s in self._sessions.items()
                 if s["user_id"] == user_id]
        owned.sort()
        while len(owned) > self.max_per_user:
            _, t = owned.pop(0)
            self._sessions.pop(t, None)


# ============================================================
# 登录限流
# ============================================================

class LoginThrottle:
    """按「用户名 + 来源 IP」统计失败次数，超阈值后短暂锁定。"""

    def __init__(self, max_attempts=DEFAULT_MAX_ATTEMPTS,
                 window=DEFAULT_ATTEMPT_WINDOW,
                 lockout=DEFAULT_LOCKOUT_SECONDS, clock=None):
        self.max_attempts = max_attempts
        self.window = window
        self.lockout = lockout
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._state = {}   # key -> {"count": n, "first": ts, "locked_until": ts}

    @staticmethod
    def make_key(username, client_ip):
        return "%s|%s" % ((username or "").strip().lower(), client_ip or "-")

    def check(self, key):
        """若处于锁定期，返回剩余秒数；否则 None。"""
        now = self._clock()
        with self._lock:
            st = self._state.get(key)
            if not st:
                return None
            if st.get("locked_until", 0) > now:
                return int(st["locked_until"] - now)
            if now - st.get("first", now) > self.window:
                self._state.pop(key, None)
            return None

    def fail(self, key):
        now = self._clock()
        with self._lock:
            st = self._state.get(key)
            if not st or now - st.get("first", now) > self.window:
                st = {"count": 0, "first": now, "locked_until": 0}
            st["count"] += 1
            if st["count"] >= self.max_attempts:
                st["locked_until"] = now + self.lockout
            self._state[key] = st

    def success(self, key):
        with self._lock:
            self._state.pop(key, None)


# ============================================================
# 鉴权门面
# ============================================================

class AuthManager:
    """账号 + 会话的门面。路由层只跟这个类打交道。"""

    def __init__(self, users_path=USERS_FILE, session_ttl=DEFAULT_SESSION_TTL,
                 clock=None, iterations=DEFAULT_PBKDF2_ITERATIONS):
        self._clock = clock or time.time
        self.users = UserStore(users_path, iterations=iterations, clock=self._clock)
        self.sessions = LoginSessionStore(ttl=session_ttl, clock=self._clock)
        self.throttle = LoginThrottle(clock=self._clock)

    # ---------- 模式 ----------

    def get_mode(self):
        return self.users.get_mode()

    def set_mode(self, mode):
        return self.users.set_mode(mode)

    def is_login_enforced(self):
        """是否要求「必须登录」。off / optional 都不强制。"""
        return self.get_mode() == "required"

    # ---------- 账号 ----------

    def list_users(self):
        return self.users.list_users()

    def get_user(self, username):
        return self.users.get_user(username)

    def create_user(self, username, password, role=ROLE_VIEWER):
        return self.users.create_user(username, password, role=role)

    def set_password(self, username, password):
        return self.users.set_password(username, password)

    def set_status(self, username, status):
        ok = self.users.set_status(username, status)
        if status == STATUS_DISABLED:
            self.sessions.revoke_user(self._user_id_of(username))
        return ok

    def set_role(self, username, role):
        return self.users.set_role(username, role)

    def delete_user(self, username):
        self.sessions.revoke_user(self._user_id_of(username))
        return self.users.delete_user(username)

    def _user_id_of(self, username):
        rec = self.users.get_user(username)
        return rec.get("id") if rec else None

    # ---------- 登录 ----------

    def login(self, username, password, client_ip=""):
        """登录成功返回 (user, session)；失败抛 AuthError。

        错误文案刻意不区分「用户不存在」与「口令错误」，避免用户枚举。
        """
        key = LoginThrottle.make_key(username, client_ip)
        remaining = self.throttle.check(key)
        if remaining is not None:
            raise AuthError(ERR_LOCKED_OUT,
                            "登录尝试过于频繁，请 %d 秒后重试" % remaining,
                            retry_after=remaining)

        rec = self.users.verify(username, password)
        if rec is None:
            self.throttle.fail(key)
            raise AuthError(ERR_INVALID_CREDENTIALS, "用户名或密码错误")

        if rec.get("status") != STATUS_ENABLED:
            self.throttle.fail(key)
            raise AuthError(ERR_USER_DISABLED, "该账号已被停用")

        self.throttle.success(key)
        self.users.touch_login(rec["id"])
        sess = self.sessions.create(rec["id"], rec["username"], rec.get("role", ROLE_VIEWER))
        return self.users._public(rec), sess

    def logout(self, token):
        return self.sessions.revoke(token)

    def authenticate(self, token):
        """校验会话令牌，返回用户对外视图；无效返回 None。"""
        sess = self.sessions.get(token)
        if not sess:
            return None
        user = self.users.get_user_by_id(sess["user_id"])
        if not user:
            self.sessions.revoke(token)
            return None
        if user.get("status") != STATUS_ENABLED:
            # 账号在登录后被停用：立即踢下线
            self.sessions.revoke(token)
            return None
        return user

    def session_info(self, token):
        return self.sessions.get(token)


# ============================================================
# HTTP 辅助（供路由层使用）
# ============================================================

def parse_cookies(header_value):
    """解析 Cookie 请求头，返回 {name: value}。"""
    cookies = {}
    if not header_value:
        return cookies
    for part in header_value.split(";"):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1]
        if name:
            cookies[name] = value
    return cookies


def build_set_cookie(name, value, max_age=None, path="/", http_only=True,
                     same_site="Lax", secure=False):
    """拼装 Set-Cookie 头值。"""
    parts = ["%s=%s" % (name, value), "Path=%s" % path]
    if max_age is not None:
        parts.append("Max-Age=%d" % int(max_age))
    if http_only:
        parts.append("HttpOnly")
    if same_site:
        parts.append("SameSite=%s" % same_site)
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def check_csrf(session, headers):
    """双提交 CSRF 校验：请求头 X-CSRF-Token 必须与会话中的令牌一致。"""
    if not session:
        return False
    sent = headers.get("X-CSRF-Token") or headers.get("x-csrf-token")
    expected = session.get("csrf_token") or ""
    if not sent or not expected:
        return False
    return hmac.compare_digest(sent, expected)


# ============================================================
# 命令行
# ============================================================

def _read_password(confirm=False, from_stdin=False):
    """读取口令。

    交互模式默认要求输入两遍确认；`--password-stdin` 模式只读一行
    （自动化调用方无法"再输一次"，确认意义不大，责任在调用方）。
    """
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    pwd = getpass.getpass("口令: ")
    if confirm:
        again = getpass.getpass("再输一次: ")
        if pwd != again:
            raise SystemExit("两次输入的口令不一致")
    return pwd


def _cli(argv=None):
    parser = argparse.ArgumentParser(description="TeleAgent 代理 —— 用户账号管理")
    parser.add_argument("--users-file", default=USERS_FILE, help="账号库路径")
    parser.add_argument("--init-admin", metavar="USERNAME", help="创建管理员账号")
    parser.add_argument("--create-user", metavar="USERNAME", help="创建普通用户")
    parser.add_argument("--role", default=ROLE_VIEWER, choices=list(ROLES), help="新用户角色")
    parser.add_argument("--set-password", metavar="USERNAME", help="重置口令")
    parser.add_argument("--disable-user", metavar="USERNAME", help="停用账号")
    parser.add_argument("--enable-user", metavar="USERNAME", help="启用账号")
    parser.add_argument("--delete-user", metavar="USERNAME", help="删除账号")
    parser.add_argument("--list-users", action="store_true", help="列出账号")
    parser.add_argument("--set-mode", choices=list(LOGIN_MODES), help="设置登录模式")
    parser.add_argument("--password-stdin", action="store_true", help="从标准输入读口令")
    args = parser.parse_args(argv)

    mgr = AuthManager(users_path=args.users_file)

    try:
        if args.init_admin:
            pwd = _read_password(confirm=True, from_stdin=args.password_stdin)
            rec = mgr.create_user(args.init_admin, pwd, role=ROLE_ADMIN)
            print("已创建管理员: %s (id=%s)" % (rec["username"], rec["id"]))
            if mgr.users.count() == 1:
                print("提示：这是首个账号，请把 'python user_auth.py --set-mode required' "
                      "纳入上线步骤。")
        elif args.create_user:
            pwd = _read_password(confirm=True, from_stdin=args.password_stdin)
            rec = mgr.create_user(args.create_user, pwd, role=args.role)
            print("已创建用户: %s (role=%s)" % (rec["username"], rec["role"]))
        elif args.set_password:
            pwd = _read_password(confirm=True, from_stdin=args.password_stdin)
            mgr.set_password(args.set_password, pwd)
            print("已重置口令: %s" % args.set_password)
        elif args.disable_user:
            mgr.set_status(args.disable_user, STATUS_DISABLED)
            print("已停用: %s" % args.disable_user)
        elif args.enable_user:
            mgr.set_status(args.enable_user, STATUS_ENABLED)
            print("已启用: %s" % args.enable_user)
        elif args.delete_user:
            mgr.delete_user(args.delete_user)
            print("已删除: %s" % args.delete_user)
        elif args.list_users:
            users = mgr.list_users()
            if not users:
                print("（账号库为空）")
            for u in users:
                print("%-20s %-8s %-9s created=%s last_login=%s" % (
                    u["username"], u["role"], u["status"],
                    u["created_at"], u["last_login_at"]))
        elif args.set_mode:
            print("登录模式已设为: %s" % mgr.set_mode(args.set_mode))
        else:
            parser.print_help()
    except AuthError as e:
        print("[ERROR] %s (%s)" % (e.message, e.code), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
