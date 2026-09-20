# Workflow Monitor Templates

This directory stores YAML templates for the CygnusX workflow monitor dashboard.

- `templates/default.yaml`: default user/admin dashboard.
- `templates/user.yaml`: user-focused dashboard.
- `templates/admin.yaml`: admin-focused dashboard.

Templates describe dashboard layout and widgets only. Runtime data comes from
`/api/v1/workflow-monitor/*` APIs and WebSocket events.
