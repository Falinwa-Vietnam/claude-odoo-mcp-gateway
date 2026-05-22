# -*- coding: utf-8 -*-
import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class McpTool(models.Model):
    """
    Registry of MCP tools exposed via the /mcp/v1 endpoint.

    Each tool record describes one callable function that an AI agent can
    invoke.  The actual implementation lives in an Odoo model method, called
    via ``env[model].sudo().<method>(**arguments)``.

    How to register your own tool
    --------------------------------
    Option A – Database record (no code):
        Create an ``mcp.tool`` record pointing to any public model method.

    Option B – Python decorator (recommended for module developers)::

        from odoo.addons.odoo_mcp.models.mcp_tool import mcp_tool

        @mcp_tool(
            name='crm_create_lead',
            description='Create a CRM lead and return its ID.',
            input_schema={
                'type': 'object',
                'properties': {
                    'name':        {'type': 'string', 'description': 'Lead title'},
                    'partner_name':{'type': 'string'},
                    'email_from':  {'type': 'string'},
                },
                'required': ['name'],
            },
        )
        def _mcp_create_lead(self, name, partner_name=None, email_from=None):
            lead = self.env['crm.lead'].create({
                'name': name,
                'partner_name': partner_name,
                'email_from': email_from,
            })
            return {'id': lead.id, 'name': lead.name}

        # Attach to the model that will own the method
        from odoo.addons.crm.models.crm_lead import Lead
        Lead._mcp_create_lead = _mcp_create_lead
    """
    _name = 'mcp.tool'
    _description = 'MCP Tool'
    _order = 'sequence, name'

    name = fields.Char(required=True, help='Tool name as exposed to AI agents (snake_case recommended).')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(required=True, help='Natural-language description shown to the AI.')

    # Implementation
    model_name = fields.Char(
        string='Odoo Model',
        help='Technical model name, e.g. res.partner',
    )
    method_name = fields.Char(
        string='Method Name',
        help='Public method on the model that implements this tool.',
    )
    input_schema = fields.Text(
        string='Input JSON Schema',
        default='{"type": "object", "properties": {}, "required": []}',
        help='JSON Schema describing the arguments accepted by this tool.',
    )

    # Auth
    require_mcp_auth = fields.Boolean(default=True, string='Require MCP Auth')
    allowed_groups = fields.Many2many(
        'res.groups',
        string='Allowed Groups',
        help='If set, only API keys belonging to users in these groups may call this tool.',
    )

    # Stats
    total_calls = fields.Integer(readonly=True)
    total_errors = fields.Integer(readonly=True)
    last_called = fields.Datetime(readonly=True)

    # ---------------------------------------------------------------- constraints
    @api.constrains('input_schema')
    def _check_input_schema(self):
        for rec in self:
            if rec.input_schema:
                try:
                    json.loads(rec.input_schema)
                except Exception:
                    raise ValidationError(_('Input JSON Schema must be valid JSON.'))

    _sql_constraints = [
        ('name_unique', 'UNIQUE(name)', 'Tool name must be unique.'),
    ]

    # ---------------------------------------------------------------- public API
    def get_schema_dict(self):
        """Return the tool description in MCP/Anthropic tool-calling format."""
        self.ensure_one()
        return {
            'name': self.name,
            'description': self.description,
            'input_schema': json.loads(self.input_schema or '{}'),
        }

    def call(self, arguments: dict, env=None):
        """
        Execute this tool with the given arguments.

        :param arguments: dict of kwargs passed to the implementation method
        :param env:       optional env override (defaults to self.env)
        :returns:         JSON-serialisable result
        """
        self.ensure_one()
        _env = env or self.env

        if not self.model_name or not self.method_name:
            raise UserError(_('Tool "%s" has no implementation configured.') % self.name)

        model_obj = _env[self.model_name].sudo()
        method = getattr(model_obj, self.method_name, None)
        if method is None:
            raise UserError(
                _('Method %s.%s not found.') % (self.model_name, self.method_name)
            )

        try:
            result = method(**arguments)
            self.sudo().write({
                'total_calls': self.total_calls + 1,
                'last_called': fields.Datetime.now(),
            })
            return result
        except Exception as e:
            self.sudo().write({'total_errors': self.total_errors + 1})
            _logger.exception('MCP tool %s raised an error', self.name)
            raise

    @api.model
    def get_tools_list(self):
        """Return all active tools in MCP list format."""
        tools = self.search([('active', '=', True)])
        return [t.get_schema_dict() for t in tools]

    @api.model
    def dispatch(self, tool_name: str, arguments: dict, env=None):
        """Find a tool by name and call it."""
        tool = self.search([('name', '=', tool_name), ('active', '=', True)], limit=1)
        if not tool:
            raise UserError(_('Unknown tool: %s') % tool_name)
        return tool.call(arguments, env=env)


# ---------------------------------------------------------------------------
# Decorator helper – lets other modules register tools without database records
# ---------------------------------------------------------------------------
_REGISTERED_TOOLS: dict = {}


def mcp_tool(name: str, description: str, input_schema: dict):
    """
    Decorator that registers an Odoo model method as an MCP tool.

    The decorated function becomes the tool implementation.  On module
    installation the ``mcp.tool`` record is created (or updated) automatically
    via ``_sync_decorated_tools()``.

    Usage::

        @mcp_tool('my_tool', 'Does something useful', {
            'type': 'object',
            'properties': {'value': {'type': 'string'}},
            'required': ['value'],
        })
        def _mcp_my_tool(self, value):
            return {'result': value.upper()}
    """
    def decorator(fn):
        _REGISTERED_TOOLS[name] = {
            'description': description,
            'input_schema': json.dumps(input_schema),
            'fn': fn,
        }
        fn._mcp_tool_name = name
        return fn
    return decorator


class McpToolSync(models.Model):
    """Mixin that auto-syncs decorator-registered tools on install/upgrade."""
    _inherit = 'mcp.tool'

    @api.model
    def _sync_decorated_tools(self):
        """Called from post_init_hook / _auto_init to sync decorated tools."""
        for name, meta in _REGISTERED_TOOLS.items():
            existing = self.search([('name', '=', name)], limit=1)
            vals = {
                'name': name,
                'description': meta['description'],
                'input_schema': meta['input_schema'],
            }
            if existing:
                existing.write(vals)
            else:
                self.create(vals)
