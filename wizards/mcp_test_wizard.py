# -*- coding: utf-8 -*-
import json
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class McpTestWizard(models.TransientModel):
    """
    Wizard to test a provider or tool directly from the Odoo backend.

    Open via  MCP > Test  or from any provider/tool record's action button.
    """
    _name = 'mcp.test.wizard'
    _description = 'MCP Test Wizard'

    test_type = fields.Selection([
        ('provider', 'Test AI Provider'),
        ('tool', 'Test Tool'),
    ], default='provider', required=True)

    # Provider test
    provider_id = fields.Many2one('mcp.provider', string='Provider')
    prompt = fields.Text(
        string='Prompt',
        default='Say "Hello from Odoo MCP Gateway!" and nothing else.',
    )
    model_override = fields.Char(string='Model Override')

    # Tool test
    tool_id = fields.Many2one('mcp.tool', string='Tool')
    tool_arguments = fields.Text(
        string='Arguments (JSON)',
        default='{}',
        help='JSON object of arguments to pass to the tool.',
    )

    # Result
    result = fields.Text(string='Result', readonly=True)
    duration_ms = fields.Integer(string='Duration (ms)', readonly=True)

    def action_run_test(self):
        self.ensure_one()
        import time
        t0 = time.monotonic()

        if self.test_type == 'provider':
            if not self.provider_id:
                raise UserError(_('Please select a provider.'))
            messages = [{'role': 'user', 'content': self.prompt or 'Hi'}]
            reply = self.provider_id.complete(
                messages,
                model=self.model_override or None,
            )
            self.result = reply

        else:  # tool
            if not self.tool_id:
                raise UserError(_('Please select a tool.'))
            try:
                args = json.loads(self.tool_arguments or '{}')
            except Exception:
                raise UserError(_('Arguments must be valid JSON.'))
            result = self.tool_id.call(args)
            self.result = json.dumps(result, indent=2, ensure_ascii=False)

        self.duration_ms = int((time.monotonic() - t0) * 1000)

        # Re-open the wizard to show the result
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
