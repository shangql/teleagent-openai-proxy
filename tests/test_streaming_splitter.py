#!/usr/bin/env python3
"""流式正文拆分器（_StreamingTextSplitter）单元测试。

覆盖要点：
- 普通正文按增量切分，拼接后与原文一致（不丢字、不重复）
- [TOOL_CALL] 标记被剥离，正文照常增量发出
- 标记被拆到多个增量块里也能正确识别（不泄漏到正文）
- 多个标记按顺序编号 call_0 / call_1
- 残缺标记、非法标记按旧实现语义原样回显

运行：
    python -m unittest discover -s tests -v
    # 或
    python tests/test_streaming_splitter.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openai_proxy  # noqa: E402


def split_all(chunks):
    """把一组增量块喂给拆分器，返回 (text, tool_calls) 两路结果。"""
    splitter = openai_proxy._StreamingTextSplitter()
    text_parts = []
    tool_calls = []
    for chunk in chunks:
        for kind, payload in splitter.feed(chunk):
            if kind == "text":
                text_parts.append(payload)
            else:
                tool_calls.extend(payload)
    for kind, payload in splitter.flush():
        if kind == "text":
            text_parts.append(payload)
        else:
            tool_calls.extend(payload)
    return "".join(text_parts), tool_calls


def split_all_stepwise(chunks):
    """同 split_all，但保留每一步的事件切分，用于验证「确实是增量的」。"""
    splitter = openai_proxy._StreamingTextSplitter()
    events = []
    for chunk in chunks:
        events.extend(splitter.feed(chunk))
    events.extend(splitter.flush())
    return events


class TestPlainText(unittest.TestCase):
    """没有工具调用标记的普通正文。"""

    def test_single_chunk(self):
        text, calls = split_all(["你好，世界"])
        self.assertEqual(text, "你好，世界")
        self.assertEqual(calls, [])

    def test_concatenation_is_lossless(self):
        chunks = ["你好", "，", "世界", "！"]
        text, calls = split_all(chunks)
        self.assertEqual(text, "".join(chunks))
        self.assertEqual(calls, [])

    def test_text_is_emitted_incrementally(self):
        """正文必须分多次吐出，而不是攒到最后一次性吐出。"""
        chunks = ["第一段文字，", "第二段文字，", "第三段文字。"]
        events = split_all_stepwise(chunks)
        text_events = [e for e in events if e[0] == "text"]
        self.assertGreaterEqual(len(text_events), 2, "正文没有增量吐出")
        self.assertEqual("".join(p for _, p in text_events), "".join(chunks))

    def test_short_chunks_are_held_until_window_fills(self):
        """压住窗口 = len("[TOOL_CALL]") - 1 个字符：短增量先攒着，攒过窗口才吐。"""
        hold = openai_proxy._StreamingTextSplitter._HOLD
        self.assertEqual(hold, len("[TOOL_CALL]") - 1)

        splitter = openai_proxy._StreamingTextSplitter()
        # 攒到正好等于窗口长度：仍然不吐
        splitter.feed("a" * hold)
        self.assertEqual(splitter.feed(""), [])

        # 再来一个字符就超过窗口，把窗口之外的部分吐出去
        self.assertEqual(splitter.feed("b"), [("text", "a")])
        self.assertEqual(splitter.flush(), [("text", "a" * (hold - 1) + "b")])

    def test_empty_input(self):
        splitter = openai_proxy._StreamingTextSplitter()
        self.assertEqual(splitter.feed(""), [])
        self.assertEqual(splitter.flush(), [])

    def test_flush_returns_residual(self):
        """不足压住长度的尾巴在 flush 时交出。"""
        splitter = openai_proxy._StreamingTextSplitter()
        splitter.feed("abc")
        self.assertEqual(splitter.flush(), [("text", "abc")])


class TestToolCallMarker(unittest.TestCase):
    """[TOOL_CALL] 标记的剥离与转换。"""

    MARKER = '[TOOL_CALL]{"name": "read", "arguments": {"path": "a.txt"}}[/TOOL_CALL]'

    def test_marker_is_stripped_from_text(self):
        text, calls = split_all(["我来读一下这个文件", self.MARKER])
        self.assertNotIn("[TOOL_CALL]", text)
        self.assertNotIn("[/TOOL_CALL]", text)
        self.assertEqual(text, "我来读一下这个文件")

    def test_tool_call_payload(self):
        text, calls = split_all(["读文件", self.MARKER])
        self.assertEqual(len(calls), 1)
        tc = calls[0]
        self.assertEqual(tc["type"], "function")
        self.assertEqual(tc["id"], "call_0")
        self.assertEqual(tc["function"]["name"], "read")
        self.assertEqual(json.loads(tc["function"]["arguments"]), {"path": "a.txt"})

    def test_marker_split_across_chunks(self):
        """标记被拆成多块时仍要正确识别，且不能泄漏到正文。"""
        pieces = ["我来读一下", "[TOOL", "_CALL]{", '"name": "read", ',
                  '"arguments": {"path": "a.txt"}}', "[/TOOL_CALL]"]
        text, calls = split_all(pieces)
        self.assertNotIn("[TOOL_CALL]", text)
        self.assertNotIn("[/TOOL_CALL]", text)
        self.assertNotIn("[TOOL", text)
        self.assertEqual(text, "我来读一下")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "read")

    def test_marker_prefix_split_at_every_offset(self):
        """标记前缀可能落在任意位置，逐个偏移量验证都不漏判。"""
        marker = '[TOOL_CALL]{"name": "read", "arguments": {}}[/TOOL_CALL]'
        for cut in range(1, len(marker)):
            text, calls = split_all(["前文", marker[:cut], marker[cut:]])
            self.assertNotIn("TOOL_CALL", text, "偏移 %d 泄漏了标记" % cut)
            self.assertEqual(text, "前文", "偏移 %d 正文被吞" % cut)
            self.assertEqual(len(calls), 1, "偏移 %d 漏掉了 tool call" % cut)

    def test_multiple_markers_get_sequential_ids(self):
        m1 = '[TOOL_CALL]{"name": "read", "arguments": {}}[/TOOL_CALL]'
        m2 = '[TOOL_CALL]{"name": "write", "arguments": {}}[/TOOL_CALL]'
        text, calls = split_all([m1, m2])
        self.assertEqual(len(calls), 2)
        self.assertEqual([c["id"] for c in calls], ["call_0", "call_1"])
        self.assertEqual([c["function"]["name"] for c in calls], ["read", "write"])
        self.assertEqual(text, "")

    def test_text_between_markers_is_kept(self):
        m1 = '[TOOL_CALL]{"name": "read", "arguments": {}}[/TOOL_CALL]'
        m2 = '[TOOL_CALL]{"name": "write", "arguments": {}}[/TOOL_CALL]'
        text, calls = split_all(["前", m1, "中", m2, "后"])
        self.assertEqual(text, "前中后")
        self.assertEqual(len(calls), 2)

    def test_marker_with_empty_arguments(self):
        marker = '[TOOL_CALL]{"name": "list", "arguments": {}}[/TOOL_CALL]'
        text, calls = split_all([marker])
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {})


class TestMalformedMarker(unittest.TestCase):
    """非法 / 残缺标记按旧实现语义处理。"""

    def test_incomplete_marker_is_echoed_verbatim(self):
        """标记没闭合：旧实现把全文当正文，这里同样原样回显。"""
        broken = '[TOOL_CALL]{"name": "read"'
        text, calls = split_all(["前面", broken])
        self.assertEqual(text, "前面" + broken)
        self.assertEqual(calls, [])

    def test_invalid_json_marker_is_echoed_verbatim(self):
        """标记闭合但内容不是合法 JSON：旧实现当普通正文，这里同样回显。"""
        broken = "[TOOL_CALL]not json[/TOOL_CALL]"
        text, calls = split_all(["前面", broken])
        self.assertEqual(text, "前面" + broken)
        self.assertEqual(calls, [])

    def test_malformed_and_valid_markers_coexist(self):
        """坏标记回显、好标记照常转 tool_calls。"""
        bad = "[TOOL_CALL]oops[/TOOL_CALL]"
        good = '[TOOL_CALL]{"name": "read", "arguments": {}}[/TOOL_CALL]'
        text, calls = split_all([bad, good])
        self.assertIn(bad, text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "read")


class TestParityWithOldParser(unittest.TestCase):
    """与旧的全量解析结果保持一致（正文 + tool_calls 集合）。"""

    def _old_parse(self, text):
        return openai_proxy._parse_tool_calls_from_text(text)

    def _new_parse(self, text):
        splitter = openai_proxy._StreamingTextSplitter()
        events = splitter.feed(text) + splitter.flush()
        out_text = "".join(p for k, p in events if k == "text")
        out_calls = [tc for k, p in events if k == "tool_calls" for tc in p]
        return out_text, out_calls

    def test_parity_on_samples(self):
        samples = [
            "普通回复，没有任何工具。",
            '好的[TOOL_CALL]{"name": "read", "arguments": {"path": "x"}}[/TOOL_CALL]',
            '[TOOL_CALL]{"name": "read", "arguments": {}}[/TOOL_CALL]',
            '前文[TOOL_CALL]{"name": "a", "arguments": {}}[/TOOL_CALL]中[TOOL_CALL]{"name": "b", "arguments": {}}[/TOOL_CALL]后',
            "[TOOL_CALL]残缺",
            "[TOOL_CALL]oops[/TOOL_CALL]",
        ]
        for sample in samples:
            old_text, old_calls = self._old_parse(sample)
            new_text, new_calls = self._new_parse(sample)
            self.assertEqual(old_text.strip(), new_text.strip(),
                             "正文不一致: %r" % sample)
            self.assertEqual(
                [c["function"] for c in old_calls],
                [c["function"] for c in new_calls],
                "tool_calls 不一致: %r" % sample,
            )


class TestChunkedParity(unittest.TestCase):
    """同一段文本，无论怎么切块，结果都应一致。"""

    def _all_splits(self, text, max_pieces=6):
        """把文本切成若干种切法：等分若干份，以及逐字符。"""
        cuts = []
        n = len(text)
        for parts in range(1, max_pieces + 1):
            step = max(1, n // parts)
            cuts.append([text[i:i + step] for i in range(0, n, step)])
        cuts.append(list(text))
        return cuts

    def test_result_is_independent_of_chunking(self):
        text = '好的，我来处理。[TOOL_CALL]{"name": "read", "arguments": {"path": "a.txt"}}[/TOOL_CALL]稍等。'
        baseline = None
        for chunks in self._all_splits(text):
            got_text, got_calls = split_all(chunks)
            key = (got_text, [c["function"]["name"] for c in got_calls])
            if baseline is None:
                baseline = key
                self.assertEqual(got_text, "好的，我来处理。稍等。")
                self.assertEqual(len(got_calls), 1)
            else:
                self.assertEqual(key, baseline, "切块方式 %r 导致结果不一致" % (chunks,))

    def test_single_character_chunks(self):
        text = 'a[TOOL_CALL]{"name": "read", "arguments": {}}[/TOOL_CALL]b'
        got_text, got_calls = split_all(list(text))
        self.assertEqual(got_text, "ab")
        self.assertEqual(len(got_calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
