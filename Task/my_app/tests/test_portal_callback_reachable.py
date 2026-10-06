"""æ— ç½‘ç»œæµ‹è¯•ï¼šé—¨æˆ·å›žè°ƒã€Œä¸å¯è¾¾ã€å¿…é¡»ä¸Žã€Œtoken æ— æ•ˆã€åŒºåˆ†å¼€ï¼ˆ2026-10-06 ä¿®å¤çš„å›žå½’å®ˆå«ï¼‰ã€‚

èƒŒæ™¯ï¼šmy_app çš„ç™»å½•æ˜¯ã€Œæ‹¿é—¨æˆ· token å›žè°ƒé—¨æˆ· /meã€æ¢å–ä¼šè¯ã€‚ä¿®å¤å‰
`verify_portal_token()` æŠŠä¸¤ç±»å¤±è´¥éƒ½æ”¶æ•›æˆè¿”å›ž Noneï¼š

  - é—¨æˆ·æ˜Žç¡®å›ž 401/403 â†’ token çœŸçš„æ— æ•ˆï¼ˆç”¨æˆ·è¯¥é‡æ–°ç™»å½•ï¼‰ï¼›
  - è¿žæŽ¥è¢«æ‹’/DNS å¤±è´¥/è¶…æ—¶ â†’ **é…ç½®æˆ–éƒ¨ç½²é—®é¢˜**ï¼ˆUNIPLAM_ME_URL æŒ‡é”™äº†æœºå™¨ï¼‰ã€‚

äºŽæ˜¯è°ƒç”¨æ–¹ä¸€å¾‹å›ž 401ã€Œè¯·å…ˆåœ¨é—¨æˆ·ç™»å½•åŽé‡è¯•ã€ï¼Œç”¨æˆ·åå¤ç™»å½•ä¹Ÿæ²¡ç”¨ï¼ŒçœŸæ­£çš„ç—…å› 
ï¼ˆå›žè°ƒåœ°å€ä¸å¯¹ï¼‰åªç•™åœ¨æ—¥å¿—çš„ä¸€è¡Œ warning é‡Œã€‚å…¸åž‹è§¦å‘åœºæ™¯æ˜¯ my_app ä¸Žé—¨æˆ·
**åˆ†æœºéƒ¨ç½²**ï¼Œè€Œ UNIPLAM_ME_URL é»˜è®¤å€¼ `http://127.0.0.1:9267/...` æŒ‡å‘çš„æ˜¯
my_app è‡ªå·±é‚£å°æœºå™¨ã€‚

æœ¬æµ‹è¯•é”å®šï¼šä¸å¯è¾¾ â†’ æŠ› PortalUnreachableï¼›è¢«æ˜Žç¡®æ‹’ç» â†’ è¿”å›ž Noneã€‚
"""

import httpx
import pytest

from backend.services import portal_auth as pa


@pytest.fixture
def anyio_backend():
    """只跑 asyncio 后端（本机未装 trio；anyio 默认会尝试两者）。"""
    return "asyncio"


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    """æ›¿èº«ï¼šæŒ‰éœ€è¿”å›žå“åº”æˆ–æŠ›å¼‚å¸¸ï¼Œæ¨¡æ‹Ÿ httpx.AsyncClient çš„ async with ç”¨æ³•ã€‚"""

    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, *args, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._resp


def _patch_client(monkeypatch, **kwargs):
    monkeypatch.setattr(pa.httpx, "AsyncClient", lambda *a, **k: _FakeClient(**kwargs))


# ============================================================================
# ä¸å¯è¾¾ -> å¿…é¡»æŠ› PortalUnreachableï¼ˆè€Œä¸æ˜¯é™é»˜è¿”å›ž Noneï¼‰
# ============================================================================

@pytest.mark.anyio
async def test_connection_refused_raises_unreachable(monkeypatch):
    """é—¨æˆ·æ‰€åœ¨æœºå™¨æ²¡ç›‘å¬ 9267 â€”â€” è¿™æ­£æ˜¯åˆ†æœºéƒ¨ç½²æ—¶çš„çœŸå®žæ•…éšœå½¢æ€ã€‚"""
    _patch_client(monkeypatch, exc=httpx.ConnectError("connection refused"))
    with pytest.raises(pa.PortalUnreachable):
        await pa.verify_portal_token("any-token")


@pytest.mark.anyio
async def test_timeout_raises_unreachable(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.ConnectTimeout("timed out"))
    with pytest.raises(pa.PortalUnreachable):
        await pa.verify_portal_token("any-token")


# ============================================================================
# é—¨æˆ·æ˜Žç¡®æ‹’ç» -> è¿”å›ž Noneï¼ˆå±žæ­£å¸¸ä¸šåŠ¡ç»“æžœï¼Œä¸èƒ½æŠ¥æˆ"æœåŠ¡ä¸å¯ç”¨"ï¼‰
# ============================================================================

@pytest.mark.anyio
async def test_rejected_token_returns_none_not_unreachable(monkeypatch):
    _patch_client(monkeypatch, resp=_Resp(401))
    assert await pa.verify_portal_token("expired-token") is None


@pytest.mark.anyio
async def test_200_without_user_returns_none(monkeypatch):
    """é—¨æˆ·å›žäº† 200 ä½†ç»“æž„é‡Œæ²¡æœ‰ user â€”â€” è§†ä¸ºæ— æ•ˆï¼Œä¸æŠ›ä¸å¯è¾¾ã€‚"""
    _patch_client(monkeypatch, resp=_Resp(200, {"nope": 1}))
    assert await pa.verify_portal_token("token") is None


@pytest.mark.anyio
async def test_200_with_user_returns_user(monkeypatch):
    _patch_client(monkeypatch, resp=_Resp(200, {"user": {"username": "alice", "role": "admin"}}))
    assert await pa.verify_portal_token("token") == {"username": "alice", "role": "admin"}


# ============================================================================
# å¯åŠ¨è‡ªæ£€ probe_portal_reachable
# ============================================================================

@pytest.mark.anyio
async def test_probe_returns_none_on_any_http_response(monkeypatch):
    """èƒ½è¿žä¸Šå°±ç®—é€šè¿‡ï¼š/me ä¸å¸¦ token æ­£å¸¸å°±æ˜¯ 401ï¼Œä¸èƒ½å› æ­¤æŠ¥é…ç½®é”™è¯¯ã€‚"""
    _patch_client(monkeypatch, resp=_Resp(401))
    assert await pa.probe_portal_reachable() is None


@pytest.mark.anyio
async def test_probe_reports_reason_when_unreachable(monkeypatch):
    _patch_client(monkeypatch, exc=httpx.ConnectError("connection refused"))
    reason = await pa.probe_portal_reachable()
    assert reason is not None and "refused" in reason


@pytest.mark.anyio
async def test_probe_flags_server_error(monkeypatch):
    """5xx è¯´æ˜Žåœ°å€é€šäº†ä½†é—¨æˆ·è‡ªèº«å¼‚å¸¸ï¼ŒåŒæ ·å€¼å¾—å‘Šè­¦ã€‚"""
    _patch_client(monkeypatch, resp=_Resp(503))
    reason = await pa.probe_portal_reachable()
    assert reason is not None and "503" in reason
