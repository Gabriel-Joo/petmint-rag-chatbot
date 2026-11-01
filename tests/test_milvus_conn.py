"""
test_milvus_conn.py
data/milvus_conn.ResilientMilvusClient — 실패하면 연결을 새로 만들어 한 번 더 부르고, 모든 호출에 timeout을 넣는다.
pymilvus MilvusClient를 가짜로 바꿔 Milvus 없이 돈다.

실행: python -m unittest tests.test_milvus_conn -v   (GPU·Milvus 안 씀)
"""

import unittest
from unittest import mock

from pymilvus.exceptions import MilvusException

from data import milvus_conn


class FakeClient:
    made = []                       # 만들어진 순서대로

    def __init__(self, uri, timeout=None, dedicated=False):
        self.uri, self.timeout, self.dedicated = uri, timeout, dedicated
        self.closed = False
        self.fail_next = 0           # 다음 N번 호출을 실패시킨다
        self.calls = []
        FakeClient.made.append(self)

    def query(self, collection_name, filter="", limit=10, timeout=None, **kwargs):
        self.calls.append(("query", timeout))
        if self.fail_next:
            self.fail_next -= 1
            raise MilvusException(message="channel dead")
        return [{"id": 1}]

    def get_server_type(self):      # timeout을 받지 않는 메서드
        return "milvus"

    def close(self):
        self.closed = True


class ResilientMilvusClientTest(unittest.TestCase):
    def setUp(self):
        FakeClient.made = []
        patcher = mock.patch.object(milvus_conn, "MilvusClient", FakeClient)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_connects_dedicated_with_timeout(self):
        c = milvus_conn.ResilientMilvusClient("http://x:19530", timeout=7)
        (made,) = FakeClient.made
        self.assertTrue(made.dedicated)                  # 공유 핸들러(죽은 연결)를 돌려받지 않는다
        self.assertEqual(made.timeout, 7)
        self.assertEqual(c.query("col"), [{"id": 1}])
        self.assertEqual(made.calls, [("query", 7)])     # timeout을 안 넘겨도 기본값이 들어간다

    def test_explicit_timeout_wins(self):
        c = milvus_conn.ResilientMilvusClient("http://x:19530", timeout=7)
        c.query("col", timeout=2)
        self.assertEqual(FakeClient.made[0].calls, [("query", 2)])

    def test_method_without_timeout_param_untouched(self):
        c = milvus_conn.ResilientMilvusClient("http://x:19530")
        self.assertEqual(c.get_server_type(), "milvus")  # timeout을 넣으면 TypeError가 났을 것

    def test_failure_reconnects_once_and_retries(self):
        c = milvus_conn.ResilientMilvusClient("http://x:19530")
        first = FakeClient.made[0]
        first.fail_next = 1
        self.assertEqual(c.query("col"), [{"id": 1}])
        self.assertEqual(len(FakeClient.made), 2)
        self.assertTrue(first.closed)                    # 죽은 연결은 반납, 새 연결로 다시
        self.assertEqual(FakeClient.made[1].calls, [("query", milvus_conn.CALL_TIMEOUT_SEC)])

    def test_second_failure_raises_instead_of_looping(self):
        c = milvus_conn.ResilientMilvusClient("http://x:19530")
        FakeClient.made[0].fail_next = 1
        orig_connect = c._connect

        def connect_failing():
            cl = orig_connect()
            cl.fail_next = 1
            return cl

        c._connect = connect_failing
        with self.assertRaises(MilvusException):
            c.query("col")
        self.assertEqual(len(FakeClient.made), 2)        # 한 번만 다시 붙는다

    def test_stale_reconnect_skipped_when_already_replaced(self):
        c = milvus_conn.ResilientMilvusClient("http://x:19530")
        stale = FakeClient.made[0]
        c._reconnect(stale)                              # 갈아 끼움
        c._reconnect(stale)                              # 다른 스레드가 같은 낡은 연결로 또 부름 → 무시
        self.assertEqual(len(FakeClient.made), 2)


if __name__ == "__main__":
    unittest.main()
