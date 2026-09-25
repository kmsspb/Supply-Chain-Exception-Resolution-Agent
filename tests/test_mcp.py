import asyncio

from fastapi.testclient import TestClient
from mcp import Client

from app.mcp_server import create_mcp_server, validate_http_bind
from app.mcp_smoke import smoke


def test_mcp_discovery_annotations_schemas_and_structured_calls():
    async def run():
        async with Client(create_mcp_server()) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == [
                "get_erp_order", "get_logistics_status", "get_shipment_note",
            ]
            for tool in listed.tools:
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
                assert tool.annotations.idempotent_hint is True
                assert tool.annotations.open_world_hint is True
                assert tool.output_schema["type"] == "object"
            result = await client.call_tool("get_erp_order", {"order_id": "SO-1001"})
            assert result.is_error is False
            assert result.structured_content["order_id"] == "SO-1001"
            missing = await client.call_tool("get_erp_order", {"order_id": "missing"})
            assert missing.is_error is True
            assert "missing_evidence" in missing.content[0].text
    asyncio.run(run())


def test_in_process_smoke_calls_all_tools():
    result = asyncio.run(smoke("in-process"))
    assert set(result["tools"]) == set(result["results"]) == {
        "get_erp_order", "get_logistics_status", "get_shipment_note",
    }


def test_stdio_smoke_calls_all_tools():
    result = asyncio.run(smoke("stdio"))
    assert result["results"]["get_shipment_note"]["shipment_id"] == "SHP-9001"


def test_streamable_http_asgi_and_loopback_policy():
    server = create_mcp_server()
    application = server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True, host="127.0.0.1",
    )
    with TestClient(application) as client:
        assert client.get("/not-mcp").status_code == 404
        assert client.post("/mcp", content=b"{}").status_code != 404
    for host in ("127.0.0.1", "localhost", "::1"):
        validate_http_bind(host)
    try:
        validate_http_bind("0.0.0.0")
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback MCP bind was accepted")
