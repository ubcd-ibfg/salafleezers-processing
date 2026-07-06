"""Tests for SessionManager eviction (TTL + LRU cap)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from salafleezers.web.sessions import SessionManager


class TestLRUEviction:
    def test_oldest_session_evicted_when_full(self):
        mgr = SessionManager(max_sessions=3, ttl_seconds=None)
        s1 = mgr.create()
        mgr.create()
        mgr.create()

        # Creating a 4th session should evict the least-recently-accessed one.
        mgr.create()

        assert len(mgr.list_ids()) == 3
        with pytest.raises(KeyError):
            mgr.get(s1.session_id)

    def test_get_refreshes_recency_and_protects_from_eviction(self):
        mgr = SessionManager(max_sessions=3, ttl_seconds=None)
        s1 = mgr.create()
        s2 = mgr.create()
        s3 = mgr.create()

        # Touch s1 so it's no longer the least-recently-accessed.
        mgr.get(s1.session_id)

        mgr.create()  # should evict s2, the now-oldest by access time

        assert mgr.get(s1.session_id) is s1
        with pytest.raises(KeyError):
            mgr.get(s2.session_id)
        assert mgr.get(s3.session_id) is s3


class TestTTLEviction:
    def test_expired_session_evicted_on_next_create(self):
        mgr = SessionManager(max_sessions=None, ttl_seconds=60)
        s1 = mgr.create()
        s1.last_accessed = datetime.now() - timedelta(seconds=61)

        mgr.create()  # triggers _evict_expired()

        with pytest.raises(KeyError):
            mgr.get(s1.session_id)

    def test_unexpired_session_survives(self):
        mgr = SessionManager(max_sessions=None, ttl_seconds=3600)
        s1 = mgr.create()
        mgr.create()

        assert mgr.get(s1.session_id) is s1

    def test_ttl_none_disables_expiry(self):
        mgr = SessionManager(max_sessions=None, ttl_seconds=None)
        s1 = mgr.create()
        s1.last_accessed = datetime.now() - timedelta(days=365)

        mgr.create()

        assert mgr.get(s1.session_id) is s1
