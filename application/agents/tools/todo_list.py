from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from .base import Tool
from application.core.mongo_db import MongoDB
from application.core.settings import settings


class TodoListTool(Tool):
    """Todo List

    Manages todo items for users. Supports creating, viewing, updating, and deleting todos.
    """

    def __init__(self, tool_config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> None:
        """Initialize the tool.

        Args:
            tool_config: Optional tool configuration. Should include:
                - tool_id: Unique identifier for this todo list tool instance (from user_tools._id)
                           This ensures each user's tool configuration has isolated todos
            user_id: The authenticated user's id (should come from decoded_token["sub"]).
        """
        self.user_id: Optional[str] = user_id

        # Get tool_id from configuration (passed from user_tools._id in production)
        # In production, tool_id is the MongoDB ObjectId string from user_tools collection
        if tool_config and "tool_id" in tool_config:
            self.tool_id = tool_config["tool_id"]
        elif user_id:
            # Fallback for backward compatibility or testing
            self.tool_id = f"default_{user_id}"
        else:
            # Last resort fallback (shouldn't happen in normal use)
            self.tool_id = str(uuid.uuid4())

        db = MongoDB.get_client()[settings.MONGO_DB_NAME]
        self.collection = db["todos"]

    # -----------------------------
    # Action implementations
    # -----------------------------
    def execute_action(self, action_name: str, **kwargs: Any) -> Any:
        """Execute an action by name.

        Args:
            action_name: One of list, create, get, update, complete, delete.
            **kwargs: Parameters for the action.

        Returns:
            A dictionary result with status_code and relevant data.
        """
        if not self.user_id:
            return {"status_code": 400, "error": "TodoListTool requires a valid user_id."}

        # Strip "todo_" prefix if present (tests use this convention)
        if action_name.startswith("todo_"):
            action_name = action_name[5:]

        if action_name == "list":
            return self._list()

        if action_name == "create":
            return self._create(
                title=kwargs.get("title", ""),
                description=kwargs.get("description", "")
            )

        if action_name == "get":
            return self._get(kwargs.get("todo_id"))

        if action_name == "update":
            return self._update(
                todo_id=kwargs.get("todo_id"),
                updates=kwargs.get("updates", {})
            )

        if action_name == "complete":
            return self._complete(kwargs.get("todo_id"))

        if action_name == "delete":
            return self._delete(kwargs.get("todo_id"))

        return {"status_code": 400, "error": f"Unknown action: {action_name}"}

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Return JSON metadata describing supported actions for tool schemas."""
        return [
            {
                "name": "list",
                "description": "List all todos for the user.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "create",
                "description": "Create a new todo item.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Title of the todo item."
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the todo item."
                        }
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "get",
                "description": "Get a specific todo by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todo_id": {
                            "type": "integer",
                            "description": "The ID of the todo to retrieve."
                        }
                    },
                    "required": ["todo_id"],
                },
            },
            {
                "name": "update",
                "description": "Update a todo's title by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todo_id": {
                            "type": "integer",
                            "description": "The ID of the todo to update."
                        },
                        "title": {
                            "type": "string",
                            "description": "The new title for the todo."
                        }
                    },
                    "required": ["todo_id", "title"],
                },
            },
            {
                "name": "complete",
                "description": "Mark a todo as completed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todo_id": {
                            "type": "integer",
                            "description": "The ID of the todo to mark as completed."
                        }
                    },
                    "required": ["todo_id"],
                },
            },
            {
                "name": "delete",
                "description": "Delete a specific todo by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todo_id": {
                            "type": "integer",
                            "description": "The ID of the todo to delete."
                        }
                    },
                    "required": ["todo_id"],
                },
            },
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        """Return configuration requirements."""
        return {}

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _coerce_todo_id(self, value: Optional[Any]) -> Optional[int]:
        """Convert todo identifiers to sequential integers."""
        if value is None:
            return None

        if isinstance(value, int):
            return value if value > 0 else None

        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                numeric_value = int(stripped)
                return numeric_value if numeric_value > 0 else None

        return None

    def _get_next_todo_id(self) -> int:
        """Get the next sequential todo_id for this user and tool.

        Returns a simple integer (1, 2, 3, ...) scoped to this user/tool.
        With 5-10 todos max, scanning is negligible.
        """
        # Find all todos for this user/tool and get their IDs
        todos = list(self.collection.find(
            {"user_id": self.user_id, "tool_id": self.tool_id},
            {"todo_id": 1}
        ))

        # Find the maximum todo_id
        max_id = 0
        for todo in todos:
            todo_id = self._coerce_todo_id(todo.get("todo_id"))
            if todo_id is not None:
                max_id = max(max_id, todo_id)

        return max_id + 1

    def _list(self) -> Dict[str, Any]:
        """List all todos for the user."""
        cursor = self.collection.find({"user_id": self.user_id, "tool_id": self.tool_id})
        todos = list(cursor)

        if not todos:
            return {"status_code": 200, "todos": []}

        # Format todo items for the response
        result_todos = []
        for doc in todos:
            result_todos.append({
                "todo_id": doc.get("todo_id"),
                "title": doc.get("title", "Untitled"),
                "description": doc.get("description", ""),
                "status": doc.get("status", "open"),
            })

        return {"status_code": 200, "todos": result_todos}

    def _create(self, title: str = "", description: str = "") -> Dict[str, Any]:
        """Create a new todo item."""
        title = (title or "").strip()
        if not title:
            return {"status_code": 400, "error": "Title is required."}

        now = datetime.now()
        todo_id = self._get_next_todo_id()

        doc = {
            "todo_id": todo_id,
            "user_id": self.user_id,
            "tool_id": self.tool_id,
            "title": title,
            "description": description,
            "status": "open",
            "created_at": now,
            "updated_at": now,
        }
        self.collection.insert_one(doc)
        return {"status_code": 201, "todo_id": todo_id}

    def _get(self, todo_id: Optional[Any]) -> Dict[str, Any]:
        """Get a specific todo by ID."""
        parsed_todo_id = self._coerce_todo_id(todo_id)
        if parsed_todo_id is None:
            return {"status_code": 400, "error": "todo_id must be a positive integer."}

        doc = self.collection.find_one({
            "user_id": self.user_id,
            "tool_id": self.tool_id,
            "todo_id": parsed_todo_id
        })

        if not doc:
            return {"status_code": 404}

        return {
            "status_code": 200,
            "todo": {
                "todo_id": doc.get("todo_id"),
                "title": doc.get("title", "Untitled"),
                "description": doc.get("description", ""),
                "status": doc.get("status", "open"),
            }
        }

    def _update(self, todo_id: Optional[Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update a todo's fields by ID."""
        parsed_todo_id = self._coerce_todo_id(todo_id)
        if parsed_todo_id is None:
            return {"status_code": 400, "error": "todo_id must be a positive integer."}

        if not updates:
            return {"status_code": 400, "error": "No updates provided."}

        # Build the $set update document
        set_fields = dict(updates)
        set_fields["updated_at"] = datetime.now()

        result = self.collection.update_one(
            {"user_id": self.user_id, "tool_id": self.tool_id, "todo_id": parsed_todo_id},
            {"$set": set_fields}
        )

        if result.matched_count == 0:
            return {"status_code": 404, "error": f"Todo with ID {parsed_todo_id} not found."}

        return {"status_code": 200}

    def _complete(self, todo_id: Optional[Any]) -> Dict[str, Any]:
        """Mark a todo as completed."""
        parsed_todo_id = self._coerce_todo_id(todo_id)
        if parsed_todo_id is None:
            return {"status_code": 400, "error": "todo_id must be a positive integer."}

        result = self.collection.update_one(
            {"user_id": self.user_id, "tool_id": self.tool_id, "todo_id": parsed_todo_id},
            {"$set": {"status": "completed", "updated_at": datetime.now()}}
        )

        if result.matched_count == 0:
            return {"status_code": 404, "error": f"Todo with ID {parsed_todo_id} not found."}

        return {"status_code": 200}

    def _delete(self, todo_id: Optional[Any]) -> Dict[str, Any]:
        """Delete a specific todo by ID."""
        parsed_todo_id = self._coerce_todo_id(todo_id)
        if parsed_todo_id is None:
            return {"status_code": 400, "error": "todo_id must be a positive integer."}

        result = self.collection.delete_one({
            "user_id": self.user_id,
            "tool_id": self.tool_id,
            "todo_id": parsed_todo_id
        })

        if result.deleted_count == 0:
            return {"status_code": 404, "error": f"Todo with ID {parsed_todo_id} not found."}

        return {"status_code": 200}
