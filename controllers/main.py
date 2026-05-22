# -*- coding: utf-8 -*-
"""
MCP JSON-RPC 2.0 controller
============================
Endpoint:  POST /mcp/v1

Authentication
--------------
Pass the API key in the  ``Authorization: Bearer <key>``  header or as
``X-MCP-Key: <key>``.

Supported methods
-----------------
- ``ping``                 – liveness check
- ``tools/list``           – enumerate available tools
- ``tools/call``           – invoke a named tool
- ``providers/list``       – list configured AI providers  (manager only)
- ``completion``           – send a prompt to an AI provider

JSON-RPC error codes (subset)
-----------------------------
-32700  Parse error
-32600  Invalid request
-32601  Method not found
-32602  Invalid params
-32000  Application error (tool raised, provider error, auth failure, …)
"""

import json
import logging
import time

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ constants
_JSONRPC_PARSE_ERROR    = -32700
_JSONRPC_INVALID_REQ    = -32600
_JSONRPC_METHOD_MISSING = -32601
_JSONRPC_INVALID_PARAMS = -32602
_JSONRPC_APP_ERROR      = -32000


class McpController(http.Controller):

    # ---------------------------------------------------------------- routing
    @http.route(
        '/mcp/v1',
        auth='public',
        methods=['POST'],
        type='json',
        csrf=False,
        cors='*',
    )
    def mcp_endpoint(self, **_kwargs):
        """
        Main MCP JSON-RPC 2.0 entry point.

        The Odoo JSON dispatcher already parses the body; ``request.jsonrequest``
        contains the decoded payload.
        """
        t0 = time.monotonic()
        payload = request.jsonrequest or {}
        req_id = payload.get('id')

        # ---- basic JSON-RPC validation
        if payload.get('jsonrpc') != '2.0' or 'method' not in payload:
            return self._error(req_id, _JSONRPC_INVALID_REQ, 'Invalid JSON-RPC 2.0 request')

        method = payload['method']
        params = payload.get('params') or {}

        # ---- authentication
        api_key_record = None
        try:
            raw_key = (
                request.httprequest.headers.get('X-MCP-Key')
                or self._bearer(request.httprequest.headers.get('Authorization', ''))
            )
            api_key_record = request.env['mcp.api.key'].authenticate(raw_key)
        except Exception as e:
            return self._error(req_id, _JSONRPC_APP_ERROR, str(e))

        # ---- dispatch
        handler = getattr(self, f'_method_{method.replace("/", "_")}', None)
        if handler is None:
            return self._error(req_id, _JSONRPC_METHOD_MISSING, f'Method not found: {method}')

        try:
            result = handler(params, api_key_record)
            duration_ms = int((time.monotonic() - t0) * 1000)
            request.env['mcp.conversation'].log(
                method=method,
                request_payload=params,
                response_payload=result,
                api_key_id=api_key_record.id,
                caller_ip=request.httprequest.remote_addr,
                duration_ms=duration_ms,
            )
            return self._ok(req_id, result)

        except Exception as e:
            _logger.exception('MCP method %s raised an error', method)
            duration_ms = int((time.monotonic() - t0) * 1000)
            request.env['mcp.conversation'].log(
                method=method,
                request_payload=params,
                api_key_id=api_key_record.id if api_key_record else None,
                caller_ip=request.httprequest.remote_addr,
                status='error',
                error_message=str(e),
                duration_ms=duration_ms,
            )
            return self._error(req_id, _JSONRPC_APP_ERROR, str(e))

    # ---------------------------------------------------------------- methods
    def _method_ping(self, params, api_key):
        return {'status': 'ok', 'server': 'Odoo MCP Gateway'}

    def _method_tools_list(self, params, api_key):
        tools = request.env['mcp.tool'].get_tools_list()
        # Filter by key permissions
        if api_key.allowed_tools:
            allowed_names = {t.name for t in api_key.allowed_tools}
            tools = [t for t in tools if t['name'] in allowed_names]
        return {'tools': tools}

    def _method_tools_call(self, params, api_key):
        tool_name = params.get('name')
        arguments = params.get('arguments') or {}

        if not tool_name:
            return self._param_error('tools/call requires "name"')

        tool = request.env['mcp.tool'].search(
            [('name', '=', tool_name), ('active', '=', True)], limit=1
        )
        if not tool:
            return self._param_error(f'Unknown tool: {tool_name}')
        if not api_key.is_tool_allowed(tool):
            return self._param_error(f'API key is not permitted to call: {tool_name}')

        result = tool.call(arguments)
        return {'content': result}

    def _method_providers_list(self, params, api_key):
        """List providers – requires the mcp_manager group."""
        if not request.env.user.has_group('odoo_mcp.group_mcp_manager'):
            raise PermissionError('providers/list requires MCP Manager role')
        providers = request.env['mcp.provider'].search([('active', '=', True)])
        return {
            'providers': [
                {
                    'id': p.id,
                    'name': p.name,
                    'provider_type': p.provider_type,
                    'model': p.model,
                    'is_default': p.is_default,
                }
                for p in providers
            ]
        }

    def _method_completion(self, params, api_key):
        """
        Send a chat-completion request to an AI provider.

        params::

            {
              "messages": [{"role": "user", "content": "Hello"}],
              "provider_id": 3,     // optional – defaults to default provider
              "model": "gpt-4o",   // optional – overrides provider default
              ...                  // any extra kwargs forwarded to provider
            }
        """
        messages = params.get('messages')
        if not messages or not isinstance(messages, list):
            return self._param_error('"messages" must be a non-empty list')

        provider_id = params.get('provider_id')
        if provider_id:
            provider = request.env['mcp.provider'].browse(int(provider_id))
            if not provider.exists() or not provider.active:
                return self._param_error(f'Provider {provider_id} not found or inactive')
        else:
            provider = request.env['mcp.provider'].get_default_provider()

        model = params.get('model')
        extra = {k: v for k, v in params.items()
                 if k not in ('messages', 'provider_id', 'model')}

        reply = provider.complete(messages, model=model, **extra)
        return {
            'content': reply,
            'provider': provider.name,
            'model': model or provider.model,
        }

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _ok(req_id, result):
        return {'jsonrpc': '2.0', 'id': req_id, 'result': result}

    @staticmethod
    def _error(req_id, code, message):
        return {
            'jsonrpc': '2.0',
            'id': req_id,
            'error': {'code': code, 'message': message},
        }

    @staticmethod
    def _param_error(msg):
        raise ValueError(msg)

    @staticmethod
    def _bearer(auth_header: str) -> str:
        if auth_header.lower().startswith('bearer '):
            return auth_header[7:].strip()
        return ''
