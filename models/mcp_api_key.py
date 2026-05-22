# -*- coding: utf-8 -*-
import secrets
import hashlib
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class McpApiKey(models.Model):
    """
    API keys that authenticate inbound MCP requests.

    The raw key is shown only once on creation; only its SHA-256 hash is
    stored in the database, matching common security practice.
    """
    _name = 'mcp.api.key'
    _description = 'MCP API Key'
    _order = 'name'

    name = fields.Char(required=True, string='Key Name / Description')
    active = fields.Boolean(default=True)
    key_hash = fields.Char(string='Key Hash (SHA-256)', readonly=True, copy=False)
    key_prefix = fields.Char(string='Prefix', readonly=True, copy=False,
                              help='First 8 chars of the raw key – for identification.')

    # Permissions
    user_id = fields.Many2one('res.users', string='Owner', default=lambda s: s.env.user)
    allowed_tools = fields.Many2many(
        'mcp.tool',
        string='Allowed Tools',
        help='Leave empty to allow all active tools.',
    )
    ip_allowlist = fields.Text(
        string='IP Allowlist',
        help='Newline-separated list of allowed IPs/CIDRs. Leave blank to allow any.',
    )

    # Stats
    total_requests = fields.Integer(readonly=True)
    last_used = fields.Datetime(readonly=True)
    expires_at = fields.Datetime(string='Expires At')

    # ----------------------------------------------------------------- actions
    def action_generate_key(self):
        """Generate a new random key and display it once."""
        self.ensure_one()
        raw = 'mcp_' + secrets.token_urlsafe(32)
        self.write({
            'key_hash': hashlib.sha256(raw.encode()).hexdigest(),
            'key_prefix': raw[:8],
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('New API Key Generated'),
                'message': _(
                    'Your new key (shown once only):\n\n%s\n\n'
                    'Copy it now – it cannot be retrieved again.'
                ) % raw,
                'type': 'warning',
                'sticky': True,
            },
        }

    # ----------------------------------------------------------------- auth
    @api.model
    def authenticate(self, raw_key: str):
        """
        Verify a raw API key and return the matching record.

        :raises UserError: if invalid, expired, or inactive.
        """
        if not raw_key:
            raise UserError(_('No API key provided.'))
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        record = self.sudo().search([
            ('key_hash', '=', key_hash),
            ('active', '=', True),
        ], limit=1)
        if not record:
            raise UserError(_('Invalid or inactive API key.'))
        now = fields.Datetime.now()
        if record.expires_at and record.expires_at < now:
            raise UserError(_('API key has expired.'))
        record.write({
            'total_requests': record.total_requests + 1,
            'last_used': now,
        })
        return record

    def is_tool_allowed(self, tool):
        """Return True if this key may call the given mcp.tool record."""
        self.ensure_one()
        if not self.allowed_tools:
            return True   # no restriction → allow all
        return tool in self.allowed_tools
