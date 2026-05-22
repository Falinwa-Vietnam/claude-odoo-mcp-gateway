# -*- coding: utf-8 -*-
{
    'name': 'MCP AI Gateway',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Model Context Protocol (MCP) server and multi-provider AI gateway for Odoo',
    'description': """
MCP AI Gateway
==============
Provides a full MCP-compliant server endpoint directly inside Odoo, plus a
unified AI provider abstraction so you can route prompts to:

  - Anthropic Claude (claude-opus-4, sonnet, haiku, …)
  - OpenAI / ChatGPT (gpt-4o, o1, …)
  - Google Gemini
  - Ollama / self-hosted (any OpenAI-compatible endpoint)
  - Custom HTTP providers

Key capabilities
----------------
* MCP JSON-RPC 2.0 endpoint  ``/mcp/v1``  (tools/list, tools/call, ping)
* Tool registry  – register Odoo methods as MCP tools with JSON-Schema
* Provider registry – manage credentials & routing from Odoo backend UI
* Conversation log – full request/response audit trail
* API-key auth + optional IP allowlist
* Wizard to test providers & tools from the backend
    """,
    'author': 'Your Company',
    'website': 'https://yourcompany.com',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/mcp_security.xml',
        'security/ir.model.access.csv',
        'views/mcp_provider_views.xml',
        'views/mcp_tool_views.xml',
        'views/mcp_conversation_views.xml',
        'views/mcp_api_key_views.xml',
        'views/mcp_menu.xml',
        'wizards/mcp_test_wizard_views.xml',
        'data/mcp_provider_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mcp_ai_gateway/static/src/css/mcp.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'images': [],
}
