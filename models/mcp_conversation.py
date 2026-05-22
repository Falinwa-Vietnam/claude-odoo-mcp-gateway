# -*- coding: utf-8 -*-
import json
from odoo import api, fields, models, _


class McpConversation(models.Model):
    """
    Full audit trail for every MCP tool call and AI completion request.

    Every inbound JSON-RPC request handled by McpController creates one
    record here, including the raw request, the response, latency, the
    API key used, and any error that occurred.
    """
    _name = 'mcp.conversation'
    _description = 'MCP Conversation Log'
    _order = 'create_date desc'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name', store=True)

    # Caller identity
    api_key_id = fields.Many2one('mcp.api.key', string='API Key', ondelete='set null')
    caller_ip = fields.Char(string='Caller IP')

    # MCP request
    jsonrpc_method = fields.Char(string='JSON-RPC Method')   # e.g. tools/call
    tool_id = fields.Many2one('mcp.tool', string='Tool', ondelete='set null')
    tool_name = fields.Char(string='Tool Name')
    request_payload = fields.Text(string='Request (JSON)')
    response_payload = fields.Text(string='Response (JSON)')

    # AI completion (optional – filled when a provider was involved)
    provider_id = fields.Many2one('mcp.provider', string='AI Provider', ondelete='set null')
    model_used = fields.Char(string='Model Used')
    prompt_tokens = fields.Integer()
    completion_tokens = fields.Integer()

    # Outcome
    status = fields.Selection([
        ('ok', 'OK'),
        ('error', 'Error'),
    ], default='ok')
    error_message = fields.Text()
    duration_ms = fields.Integer(string='Duration (ms)')

    @api.depends('jsonrpc_method', 'tool_name', 'create_date')
    def _compute_display_name(self):
        for rec in self:
            ts = rec.create_date.strftime('%Y-%m-%d %H:%M:%S') if rec.create_date else ''
            rec.display_name = f'[{ts}] {rec.jsonrpc_method or "?"} – {rec.tool_name or ""}'

    # ----------------------------------------------------------------- helpers
    @api.model
    def log(
        self,
        *,
        method,
        request_payload,
        response_payload=None,
        tool_id=None,
        tool_name=None,
        api_key_id=None,
        caller_ip=None,
        provider_id=None,
        model_used=None,
        status='ok',
        error_message=None,
        duration_ms=None,
    ):
        """Convenience factory used by the controller."""
        def _ser(val):
            if val is None:
                return None
            if isinstance(val, str):
                return val
            return json.dumps(val, ensure_ascii=False, indent=2)

        self.sudo().create({
            'jsonrpc_method': method,
            'request_payload': _ser(request_payload),
            'response_payload': _ser(response_payload),
            'tool_id': tool_id,
            'tool_name': tool_name,
            'api_key_id': api_key_id,
            'caller_ip': caller_ip,
            'provider_id': provider_id,
            'model_used': model_used,
            'status': status,
            'error_message': error_message,
            'duration_ms': duration_ms,
        })
