#!/usr/bin/env python3
"""user_auth 模块单元测试（标准库 unittest，零第三方依赖）。

运行：
    python -m unittest discover -s tests -v
    # 或
    python tests/test_user_auth.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import user_auth  # noqa: E402


class FakeClock(object):
    """可推进的时钟，用于测试会话过期与限流锁定。"""

    def __init__(self, now=1_700_000_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return self.now


class BaseCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="tap-users-")
        self.users_path = os.path.join(self.tmpdir, "users.json")
        self.clock = FakeClock()
        # 测试用低迭代次数，保证整套用例秒级跑完；
        # 生产默认值由 test_default_iterations_recorded 单独守住。
        self.mgr = user_auth.AuthManager(users_path=self.users_path, clock=self.clock,
                                         iterations=1000)

    def tearDown(self):
        for name in os.listdir(self.tmpdir):
            try:
                os.remove(os.path.join(self.tmpdir, name))
            except OSError:
                pass
        os.rmdir(self.tmpdir)


class TestPasswordHashing(unittest.TestCase):

    def test_roundtrip(self):
        stored = user_auth.hash_password("correct-horse-battery")
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertTrue(user_auth.verify_password("correct-horse-battery", stored))

    def test_wrong_password(self):
        stored = user_auth.hash_password("correct-horse-battery")
        self.assertFalse(user_auth.verify_password("wrong-horse-battery", stored))

    def test_random_salt(self):
        a = user_auth.hash_password("same-password-1")
        b = user_auth.hash_password("same-password-1")
        self.assertNotEqual(a, b)
        self.assertTrue(user_auth.verify_password("same-password-1", a))
        self.assertTrue(user_auth.verify_password("same-password-1", b))

    def test_unicode_password(self):
        stored = user_auth.hash_password("密码-口令-12345")
        self.assertTrue(user_auth.verify_password("密码-口令-12345", stored))

    def test_malformed_stored_value_returns_false(self):
        for bad in ("", "nope", "pbkdf2_sha256$abc$x$y", "md5$1$a$b", None, 123):
            self.assertFalse(user_auth.verify_password("whatever", bad))

    def test_weak_password_rejected(self):
        with self.assertRaises(user_auth.AuthError) as ctx:
            user_auth.hash_password("short")
        self.assertEqual(ctx.exception.code, user_auth.ERR_WEAK_PASSWORD)


class TestUserStore(BaseCase):

    def test_create_and_list(self):
        rec = self.mgr.create_user("alice", "alice-password-1")
        self.assertEqual(rec["username"], "alice")
        self.assertEqual(rec["role"], user_auth.ROLE_VIEWER)
        self.assertEqual(rec["status"], user_auth.STATUS_ENABLED)
        self.assertEqual(len(self.mgr.list_users()), 1)

    def test_public_view_has_no_password(self):
        self.mgr.create_user("alice", "alice-password-1")
        rec = self.mgr.get_user("alice")
        self.assertNotIn("password", rec)
        self.assertNotIn("password", rec.get("password", ""))

    def test_duplicate_username(self):
        self.mgr.create_user("alice", "alice-password-1")
        with self.assertRaises(user_auth.AuthError) as ctx:
            self.mgr.create_user("ALICE", "another-password-1")
        self.assertEqual(ctx.exception.code, user_auth.ERR_USER_EXISTS)

    def test_invalid_username(self):
        for bad in ("ab", "a" * 33, "bad name", "bad/name", ""):
            with self.assertRaises(user_auth.AuthError) as ctx:
                self.mgr.create_user(bad, "some-password-1")
            self.assertEqual(ctx.exception.code, user_auth.ERR_INVALID_USERNAME)

    def test_persistence_roundtrip(self):
        self.mgr.create_user("alice", "alice-password-1", role=user_auth.ROLE_ADMIN)
        other = user_auth.AuthManager(users_path=self.users_path, clock=self.clock)
        users = other.list_users()
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["username"], "alice")
        self.assertEqual(users[0]["role"], user_auth.ROLE_ADMIN)

    def test_atomic_write_leaves_no_tmp_file(self):
        self.mgr.create_user("alice", "alice-password-1")
        self.assertTrue(os.path.exists(self.users_path))
        self.assertFalse(os.path.exists(self.users_path + ".tmp"))

    def test_set_password_and_status_and_role(self):
        self.mgr.create_user("alice", "alice-password-1")
        self.mgr.set_password("alice", "brand-new-password")
        self.assertTrue(user_auth.verify_password(
            "brand-new-password", self.mgr.users.verify("alice", "brand-new-password")["password"]))
        self.mgr.set_status("alice", user_auth.STATUS_DISABLED)
        self.assertEqual(self.mgr.get_user("alice")["status"], user_auth.STATUS_DISABLED)
        self.mgr.set_role("alice", user_auth.ROLE_ADMIN)
        self.assertEqual(self.mgr.get_user("alice")["role"], user_auth.ROLE_ADMIN)

    def test_delete_user(self):
        self.mgr.create_user("alice", "alice-password-1")
        self.mgr.delete_user("alice")
        self.assertEqual(self.mgr.list_users(), [])
        with self.assertRaises(user_auth.AuthError):
            self.mgr.delete_user("alice")

    def test_mode_roundtrip(self):
        self.assertEqual(self.mgr.get_mode(), "off")
        self.mgr.set_mode("required")
        self.assertEqual(self.mgr.get_mode(), "required")
        with self.assertRaises(user_auth.AuthError):
            self.mgr.set_mode("nope")

    def test_default_iterations_recorded(self):
        """生产默认迭代次数必须写进哈希串，便于日后平滑升级。"""
        stored = user_auth.hash_password("production-password-1")
        algo, iters, salt, digest = stored.split("$")
        self.assertEqual(algo, "pbkdf2_sha256")
        self.assertEqual(int(iters), user_auth.DEFAULT_PBKDF2_ITERATIONS)
        self.assertTrue(salt and digest)


class TestLogin(BaseCase):

    def setUp(self):
        BaseCase.setUp(self)
        self.mgr.create_user("alice", "alice-password-1", role=user_auth.ROLE_ADMIN)

    def test_login_success(self):
        user, sess = self.mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")
        self.assertEqual(user["username"], "alice")
        self.assertEqual(sess["role"], user_auth.ROLE_ADMIN)
        self.assertTrue(sess["token"])
        self.assertTrue(sess["csrf_token"])

    def test_login_wrong_password(self):
        with self.assertRaises(user_auth.AuthError) as ctx:
            self.mgr.login("alice", "wrong-password-1", client_ip="10.0.0.5")
        self.assertEqual(ctx.exception.code, user_auth.ERR_INVALID_CREDENTIALS)

    def test_login_unknown_user_same_message(self):
        """未知用户与错误口令返回同样的文案，避免用户枚举。"""
        with self.assertRaises(user_auth.AuthError) as ctx:
            self.mgr.login("nobody", "whatever-password", client_ip="10.0.0.5")
        self.assertEqual(ctx.exception.code, user_auth.ERR_INVALID_CREDENTIALS)

    def test_lockout_after_repeated_failures(self):
        for _ in range(user_auth.DEFAULT_MAX_ATTEMPTS):
            with self.assertRaises(user_auth.AuthError):
                self.mgr.login("alice", "wrong-password-1", client_ip="10.0.0.5")
        with self.assertRaises(user_auth.AuthError) as ctx:
            self.mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")
        self.assertEqual(ctx.exception.code, user_auth.ERR_LOCKED_OUT)
        self.assertIsNotNone(ctx.exception.retry_after)

    def test_lockout_expires(self):
        for _ in range(user_auth.DEFAULT_MAX_ATTEMPTS):
            with self.assertRaises(user_auth.AuthError):
                self.mgr.login("alice", "wrong-password-1", client_ip="10.0.0.5")
        self.clock.advance(user_auth.DEFAULT_LOCKOUT_SECONDS + 1)
        user, _ = self.mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")
        self.assertEqual(user["username"], "alice")

    def test_disabled_user_cannot_login(self):
        self.mgr.set_status("alice", user_auth.STATUS_DISABLED)
        with self.assertRaises(user_auth.AuthError) as ctx:
            self.mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")
        self.assertEqual(ctx.exception.code, user_auth.ERR_USER_DISABLED)

    def test_disabling_user_kills_existing_session(self):
        _, sess = self.mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")
        self.assertIsNotNone(self.mgr.authenticate(sess["token"]))
        self.mgr.set_status("alice", user_auth.STATUS_DISABLED)
        self.assertIsNone(self.mgr.authenticate(sess["token"]))

    def test_last_login_at_recorded(self):
        self.mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")
        self.assertIsNotNone(self.mgr.get_user("alice")["last_login_at"])


class TestSession(BaseCase):

    def setUp(self):
        BaseCase.setUp(self)
        self.mgr.create_user("alice", "alice-password-1")

    def test_authenticate_valid_session(self):
        _, sess = self.mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")
        user = self.mgr.authenticate(sess["token"])
        self.assertEqual(user["username"], "alice")

    def test_authenticate_invalid_token(self):
        self.assertIsNone(self.mgr.authenticate("not-a-real-token"))
        self.assertIsNone(self.mgr.authenticate(""))
        self.assertIsNone(self.mgr.authenticate(None))

    def test_session_expires(self):
        _, sess = self.mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")
        self.clock.advance(user_auth.DEFAULT_SESSION_TTL + 10)
        self.assertIsNone(self.mgr.authenticate(sess["token"]))

    def test_sliding_renewal_extends_session(self):
        mgr = user_auth.AuthManager(users_path=self.users_path, clock=self.clock)
        _, sess = mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")
        self.clock.advance(user_auth.DEFAULT_SESSION_TTL - 60)
        self.assertIsNotNone(mgr.authenticate(sess["token"]))
        self.clock.advance(120)
        self.assertIsNotNone(mgr.authenticate(sess["token"]))

    def test_logout_revokes(self):
        _, sess = self.mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")
        self.assertTrue(self.mgr.logout(sess["token"]))
        self.assertIsNone(self.mgr.authenticate(sess["token"]))

    def test_max_sessions_per_user(self):
        tokens = [self.mgr.login("alice", "alice-password-1", client_ip="10.0.0.5")[1]["token"]
                  for _ in range(8)]
        alive = [t for t in tokens if self.mgr.authenticate(t)]
        self.assertLessEqual(len(alive), self.mgr.sessions.max_per_user)


class TestHttpHelpers(unittest.TestCase):

    def test_parse_cookies(self):
        got = user_auth.parse_cookies("tap_sid=abc123; other=1; quoted=\"x\"")
        self.assertEqual(got["tap_sid"], "abc123")
        self.assertEqual(got["other"], "1")
        self.assertEqual(got["quoted"], "x")

    def test_parse_cookies_empty(self):
        self.assertEqual(user_auth.parse_cookies(""), {})
        self.assertEqual(user_auth.parse_cookies(None), {})

    def test_build_set_cookie(self):
        cookie = user_auth.build_set_cookie("tap_sid", "v1", max_age=3600)
        self.assertIn("tap_sid=v1", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Max-Age=3600", cookie)
        self.assertIn("Path=/", cookie)

    def test_build_set_cookie_delete(self):
        cookie = user_auth.build_set_cookie("tap_sid", "", max_age=0)
        self.assertIn("Max-Age=0", cookie)

    def test_check_csrf(self):
        sess = {"csrf_token": "tok-123"}
        self.assertTrue(user_auth.check_csrf(sess, {"X-CSRF-Token": "tok-123"}))
        self.assertFalse(user_auth.check_csrf(sess, {"X-CSRF-Token": "wrong"}))
        self.assertFalse(user_auth.check_csrf(sess, {}))
        self.assertFalse(user_auth.check_csrf(None, {"X-CSRF-Token": "tok-123"}))


class TestCliHelpers(unittest.TestCase):

    def test_read_password_from_stdin_reads_single_line(self):
        """--password-stdin 只读一行：自动化调用方不会传第二行。"""
        import io

        original = sys.stdin
        sys.stdin = io.StringIO("only-one-line\n")
        try:
            got = user_auth._read_password(confirm=True, from_stdin=True)
        finally:
            sys.stdin = original
        self.assertEqual(got, "only-one-line")

    def test_cli_init_admin_and_list(self):
        import io
        import json

        tmpdir = tempfile.mkdtemp(prefix="tap-cli-")
        users_path = os.path.join(tmpdir, "users.json")
        original = sys.stdin
        sys.stdin = io.StringIO("admin-password-123\n")
        try:
            rc = user_auth._cli(["--users-file", users_path,
                                 "--init-admin", "admin", "--password-stdin"])
        finally:
            sys.stdin = original
        self.assertEqual(rc, 0)
        with open(users_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(len(cfg["users"]), 1)
        self.assertEqual(cfg["users"][0]["username"], "admin")
        self.assertEqual(cfg["users"][0]["role"], "admin")
        # 口令只存哈希，不存明文
        self.assertNotIn("admin-password-123", json.dumps(cfg))
        self.assertTrue(cfg["users"][0]["password"].startswith("pbkdf2_sha256$"))
        for name in os.listdir(tmpdir):
            os.remove(os.path.join(tmpdir, name))
        os.rmdir(tmpdir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
