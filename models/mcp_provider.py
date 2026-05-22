# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

PROVIDER_TYPES = [
    ('anthropic', 'Anthropic Claude'),
    ('openai', 'OpenAI / ChatGPT'),
    ('gemini', 'Google Gemini'),
    ('ollama', 'Ollama (self-hosted)'),
    ('openai_compat', 'OpenAI-compatible endpoint'),
    ('custom', 'Custom HTTP'),
]


class McpProvider(models.Model):
    """
    Represents one LLM provider connection.

    Each provider stores credentials, the base URL, default model, and
    any extra headers/params needed.  The ``complete()`` method sends a
    standard chat-completion request and returns the assistant text.

    You can add your own provider type by:
      1. Adding an entry to PROVIDER_TYPES above.
      2. Adding a branch in ``_complete_<type>`` style or overriding
         ``_dispatch_completion()``.
    """
    _name = 'mcp.provider'
    _description = 'MCP AI Provider'
    _order = 'sequence, name'

    # ------------------------------------------------------------------ fields
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    provider_type = fields.Selection(PROVIDER_TYPES, required=True, string='Provider')
    is_default = fields.Boolean(string='Default Provider')

    # Connection
    base_url = fields.Char(
        string='Base URL',
        help='Override the default endpoint. Leave blank to use the provider default.',
    )
    api_key = fields.Char(string='API Key', groups='odoo_mcp.group_mcp_manager')
    model = fields.Char(string='Default Model', required=True, default='gpt-4o')
    timeout = fields.Integer(default=60, string='Timeout (s)')

    # Extra config stored as JSON
    extra_headers = fields.Text(
        string='Extra Headers (JSON)',
        default='{}',
        help='Additional HTTP headers sent with every request, as a JSON object.',
    )
    extra_params = fields.Text(
        string='Extra Params (JSON)',
        default='{}',
        help='Extra body params merged into every completion request.',
    )

    # Stats
    total_calls = fields.Integer(readonly=True)
    total_errors = fields.Integer(readonly=True)
    last_used = fields.Datetime(readonly=True)

    # ---------------------------------------------------------------- defaults
    _PROVIDER_DEFAULTS = {
        'anthropic':    {'base_url': 'https://api.anthropic.com/v1',      'model': 'claude-sonnet-4-20250514'},
        'openai':       {'base_url': 'https://api.openai.com/v1',         'model': 'gpt-4o'},
        'gemini':       {'base_url': 'https://generativelanguage.googleapis.com', 'model': 'gemini-2.0-flash'},
        'ollama':       {'base_url': 'http://localhost:11434/v1',          'model': 'llama3'},
        'openai_compat':{'base_url': '',                                   'model': ''},
        'custom':       {'base_url': '',                                   'model': ''},
    }

    @api.onchange('provider_type')
    def _onchange_provider_type(self):
        defaults = self._PROVIDER_DEFAULTS.get(self.provider_type, {})
        if not self.base_url:
            self.base_url = defaults.get('base_url', '')
        if not self.model:
            self.model = defaults.get('model', '')

    @api.constrains('extra_headers', 'extra_params')
    def _check_json_fields(self):
        for rec in self:
            for fname in ('extra_headers', 'extra_params'):
                val = getattr(rec, fname)
                if val:
                    try:
                        json.loads(val)
                    except Exception:
                        raise ValidationError(_('%s must be valid JSON.') % fname)

    # ----------------------------------------------------------------- public API
    def complete(self, messages, model=None, **kwargs):
        """
        Send a chat-completion request to this provider.

        :param messages: list of  {'role': ..., 'content': ...}  dicts
        :param model:    override the provider's default model
        :param kwargs:   extra params forwarded to the underlying call
        :return:         assistant reply as a string
        :raises UserError: on HTTP / provider errors
        """
        self.ensure_one()
        model = model or self.model
        extra = json.loads(self.extra_params or '{}')
        extra.update(kwargs)

        try:
            result = self._dispatch_completion(messages, model, extra)
            self.sudo().write({
                'total_calls': self.total_calls + 1,
                'last_used': fields.Datetime.now(),
            })
            return result
        except Exception as e:
            self.sudo().write({'total_errors': self.total_errors + 1})
            raise

    def _dispatch_completion(self, messages, model, extra):
        """Route to the correct provider implementation."""
        dispatch = {
            'anthropic':     self._complete_anthropic,
            'openai':        self._complete_openai_compat,
            'gemini':        self._complete_gemini,
            'ollama':        self._complete_openai_compat,
            'openai_compat': self._complete_openai_compat,
            'custom':        self._complete_custom,
        }
        fn = dispatch.get(self.provider_type)
        if not fn:
            raise UserError(_('Unknown provider type: %s') % self.provider_type)
        return fn(messages, model, extra)

    # ---------------------------------------------------------------- providers
    def _get_headers(self, extra=None):
        """Merge stored extra_headers with caller-supplied headers."""
        h = json.loads(self.extra_headers or '{}')
        if extra:
            h.update(extra)
        return h

    def _complete_anthropic(self, messages, model, extra):
        """Anthropic Messages API."""
        base = (self.base_url or 'https://api.anthropic.com/v1').rstrip('/')
        url = f'{base}/messages'
        headers = self._get_headers({
            'x-api-key': self.api_key or '',
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        })
        # Anthropic separates system messages
        system_parts = [m['content'] for m in messages if m['role'] == 'system']
        user_messages = [m for m in messages if m['role'] != 'system']
        payload = {
            'model': model,
            'max_tokens': extra.pop('max_tokens', 4096),
            'messages': user_messages,
        }
        if system_parts:
            payload['system'] = '\n\n'.join(system_parts)
        payload.update(extra)
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        self._raise_for_status(resp)
        data = resp.json()
        return data['content'][0]['text']

    def _complete_openai_compat(self, messages, model, extra):
        """OpenAI-compatible chat/completions endpoint (OpenAI, Ollama, LM Studio, etc.)."""
        base = (self.base_url or 'https://api.openai.com/v1').rstrip('/')
        url = f'{base}/chat/completions'
        headers = self._get_headers({
            'Authorization': f'Bearer {self.api_key or ""}',
            'Content-Type': 'application/json',
        })
        payload = {'model': model, 'messages': messages}
        payload.update(extra)
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        self._raise_for_status(resp)
        data = resp.json()
        return data['choices'][0]['message']['content']

    def _complete_gemini(self, messages, model, extra):
        """Google Gemini generateContent API."""
        base = (self.base_url or 'https://generativelanguage.googleapis.com').rstrip('/')
        url = f'{base}/v1beta/models/{model}:generateContent?key={self.api_key or ""}'
        headers = self._get_headers({'Content-Type': 'application/json'})
        # Convert to Gemini parts format
        contents = []
        for m in messages:
            role = 'user' if m['role'] in ('user', 'system') else 'model'
            contents.append({'role': role, 'parts': [{'text': m['content']}]})
        payload = {'contents': contents}
        payload.update(extra)
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        self._raise_for_status(resp)
        data = resp.json()
        return data['candidates'][0]['content']['parts'][0]['text']

    def _complete_custom(self, messages, model, extra):
        """
        Generic fallback for fully custom endpoints.
        Sends an OpenAI-style payload; override this method for bespoke formats.
        """
        return self._complete_openai_compat(messages, model, extra)

    @staticmethod
    def _raise_for_status(resp):
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise UserError(
                _('Provider returned HTTP %s:\n%s') % (resp.status_code, json.dumps(detail, indent=2))
            )

    # ----------------------------------------------------------------- actions
    def action_set_default(self):
        self.search([]).write({'is_default': False})
        self.write({'is_default': True})

    def action_test_connection(self):
        """Quick ping: send a minimal message and show the result."""
        self.ensure_one()
        try:
            reply = self.complete([{'role': 'user', 'content': 'Say "OK" and nothing else.'}])
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection OK'),
                    'message': reply[:200],
                    'type': 'success',
                },
            }
        except Exception as e:
            raise UserError(str(e))

    @api.model
    def get_default_provider(self):
        provider = self.search([('is_default', '=', True), ('active', '=', True)], limit=1)
        if not provider:
            provider = self.search([('active', '=', True)], limit=1)
        if not provider:
            raise UserError(_('No active AI provider configured. Please add one in MCP > Providers.'))
        return provider
