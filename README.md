# MCP AI Gateway — Odoo 19 Module

A production-ready **Model Context Protocol (MCP) server** and **multi-provider AI gateway** built as a native Odoo 19 module.

---

## What it does

| Feature | Details |
|---|---|
| **MCP endpoint** | `POST /mcp/v1` — full JSON-RPC 2.0 server |
| **AI providers** | Anthropic Claude, OpenAI/ChatGPT, Google Gemini, Ollama, any OpenAI-compat endpoint, custom HTTP |
| **Tool registry** | Register any Odoo method as a callable MCP tool with JSON Schema |
| **API key auth** | Bearer token auth, per-key tool restrictions, IP allowlist, expiry |
| **Audit log** | Every request/response stored in `mcp.conversation` |
| **Test wizard** | Test providers and tools directly from the Odoo UI |
| **Extensible** | `@mcp_tool` decorator lets other modules register tools in Python |

---

## Installation

1. Copy the `mcp_ai_gateway/` folder into your Odoo addons path.
2. Restart Odoo.
3. Go to **Apps**, search for *MCP AI Gateway* and install.
4. Navigate to **MCP AI Gateway > Configuration > AI Providers** and add your API keys.

---

## MCP Endpoint Reference

```
POST /mcp/v1
Content-Type: application/json
Authorization: Bearer <your-mcp-api-key>
```

All requests follow JSON-RPC 2.0:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "<method>",
  "params": { ... }
}
```

### Methods

#### `ping`
```json
// request params: {}
// response
{ "status": "ok", "server": "Odoo MCP Gateway" }
```

#### `tools/list`
```json
// response
{
  "tools": [
    {
      "name": "my_tool",
      "description": "Does something useful",
      "input_schema": { "type": "object", "properties": {} }
    }
  ]
}
```

#### `tools/call`
```json
// params
{ "name": "my_tool", "arguments": { "key": "value" } }

// response
{ "content": <tool return value> }
```

#### `completion`
```json
// params
{
  "messages": [{ "role": "user", "content": "Hello!" }],
  "provider_id": 1,   // optional
  "model": "gpt-4o"  // optional override
}

// response
{ "content": "Hello! How can I help?", "provider": "OpenAI GPT-4o", "model": "gpt-4o" }
```

#### `providers/list`  *(MCP Manager role required)*
```json
// response
{
  "providers": [
    { "id": 1, "name": "Anthropic Claude", "provider_type": "anthropic", "model": "claude-sonnet-4-20250514", "is_default": true }
  ]
}
```

---

## Adding Your Own Tools

### Option A — Database record (no code needed)

1. Go to **MCP AI Gateway > Configuration > Tools**.
2. Create a record:
   - **Name**: `crm_create_lead`
   - **Odoo Model**: `crm.lead`
   - **Method Name**: `mcp_create_lead`  *(you implement this method on the model)*
   - **Input JSON Schema**: describe the arguments

### Option B — Python decorator (for module developers)

```python
# In your own module's model file
from odoo import models
from odoo.addons.mcp_ai_gateway.models.mcp_tool import mcp_tool

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    @mcp_tool(
        name='crm_create_lead',
        description='Create a new CRM lead and return its ID and name.',
        input_schema={
            'type': 'object',
            'properties': {
                'name':         {'type': 'string', 'description': 'Lead title'},
                'partner_name': {'type': 'string'},
                'email_from':   {'type': 'string', 'format': 'email'},
            },
            'required': ['name'],
        },
    )
    def mcp_create_lead(self, name, partner_name=None, email_from=None):
        lead = self.create({
            'name': name,
            'partner_name': partner_name,
            'email_from': email_from,
        })
        return {'id': lead.id, 'name': lead.name}
```

---

## Connecting Claude Desktop (MCP client)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo": {
      "command": "curl",
      "args": ["-s", "-X", "POST", "https://your-odoo.com/mcp/v1"],
      "env": {
        "MCP_KEY": "mcp_your_api_key_here"
      }
    }
  }
}
```

Or use any MCP-compatible client / SDK that speaks JSON-RPC 2.0 over HTTP.

---

## Supported Providers

| Provider | `provider_type` | Default model |
|---|---|---|
| Anthropic Claude | `anthropic` | `claude-sonnet-4-20250514` |
| OpenAI / ChatGPT | `openai` | `gpt-4o` |
| Google Gemini | `gemini` | `gemini-2.0-flash` |
| Ollama | `ollama` | `llama3` |
| OpenAI-compat (LM Studio, vLLM, …) | `openai_compat` | *(you set it)* |
| Custom HTTP | `custom` | *(you set it)* |

---

## Security Model

- **MCP User** — can call tools, view logs, run test wizard.
- **MCP Manager** — full CRUD on providers (including API keys), tools, MCP API keys.
- Provider API keys are stored encrypted and only visible to MCP Managers.
- Each MCP API key can be restricted to specific tools and/or IP ranges.

---

## File Structure

```
mcp_ai_gateway/
├── __manifest__.py
├── __init__.py
├── models/
│   ├── mcp_provider.py     ← AI provider abstraction + all HTTP adapters
│   ├── mcp_tool.py         ← Tool registry + @mcp_tool decorator
│   ├── mcp_conversation.py ← Audit log
│   └── mcp_api_key.py      ← API key management & auth
├── controllers/
│   └── main.py             ← JSON-RPC 2.0 HTTP endpoint /mcp/v1
├── wizards/
│   └── mcp_test_wizard.py  ← Backend test UI
├── views/                  ← All Odoo UI views & menus
├── security/               ← Groups, ACLs
├── data/
│   └── mcp_provider_data.xml  ← Seed provider records
└── static/src/css/mcp.css
```
