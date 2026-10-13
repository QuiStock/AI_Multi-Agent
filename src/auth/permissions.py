"""Role codes authorized for the currently available conversation capabilities."""

FAQ_ROLE_CODES = frozenset({"MANAGER", "EMPLOYEE"})
PRODUCT_WORKFLOW_ROLE_CODES = frozenset({"MANAGER", "EMPLOYEE"})
CONVERSATION_ROLE_CODES = FAQ_ROLE_CODES | PRODUCT_WORKFLOW_ROLE_CODES
