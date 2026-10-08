"""MongoDB persistence adapter for conversation messages."""

from datetime import datetime, timezone
from typing import Any, Literal

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from .contracts import (
    ConversationListItem,
    ConversationMetadata,
    ConversationSummarySnapshot,
    ConversationTurn,
    StoredMessage,
)

CONVERSATIONS_COLLECTION_NAME = "conversations"


def _as_timestamp(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value
    return None


def _as_aware_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("timestamp MongoDB inválido")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ConversationNotFoundError(Exception):
    """Raised when the conversation does not belong to the supplied user."""


class ConversationClosedError(Exception):
    """Raised when a new message is appended to an ended conversation."""


class SummaryUpdateConflictError(Exception):
    """Raised when the conversation changed during summary generation."""


class ConversationNotEndedError(Exception):
    """Raised when a conversation selected for resumption is not ended."""


class MongoConversationRepository:
    """Append messages to one MongoDB document per conversation."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection
        self._email_index_ready = False
        self._observability_indexes_ready = False

    def list_observability_conversations(
        self,
        *,
        consumer_id: str | None = None,
        conversation_id: str | None = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        status: Literal["active", "ended"] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List conversation metadata without loading embedded message history."""
        if not 1 <= limit <= 200:
            raise ValueError("limit precisa estar entre 1 e 200")
        if not 0 <= offset <= 100_000:
            raise ValueError("offset precisa estar entre 0 e 100000")
        if consumer_id is not None and not consumer_id.strip():
            raise ValueError("consumer_id não pode estar vazio")
        if conversation_id is not None and not conversation_id.strip():
            raise ValueError("conversation_id não pode estar vazio")

        self._ensure_observability_indexes()
        query: dict[str, Any] = {
            "status": status if status is not None else {"$in": ["active", "ended"]}
        }
        if consumer_id is not None:
            query["email"] = consumer_id.strip()
        if conversation_id is not None:
            query["_id"] = conversation_id.strip()

        updated_filter: dict[str, datetime] = {}
        if updated_from is not None:
            updated_filter["$gte"] = self._query_timestamp(updated_from, "updated_from")
        if updated_to is not None:
            updated_filter["$lte"] = self._query_timestamp(updated_to, "updated_to")
        if updated_from is not None and updated_to is not None:
            if updated_filter["$gte"] > updated_filter["$lte"]:
                raise ValueError("updated_from não pode ser posterior a updated_to")
        if updated_filter:
            query["updated_at"] = updated_filter

        projection = {
            "_id": 1,
            "title": 1,
            "status": 1,
            "started_at": 1,
            "updated_at": 1,
            "ended_at": 1,
        }
        cursor = (
            self._collection.find(query, projection)
            .sort([("updated_at", DESCENDING), ("_id", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )
        conversations = []
        for document in cursor:
            conversation_id_value = document.get("_id")
            started_at = document.get("started_at")
            updated_at = document.get("updated_at")
            if not isinstance(conversation_id_value, str):
                continue
            if not isinstance(started_at, datetime) or not isinstance(
                updated_at, datetime
            ):
                continue
            ended_at = document.get("ended_at")
            conversations.append(
                {
                    "conversation_id": conversation_id_value,
                    "title": document.get("title"),
                    "status": document.get("status"),
                    "started_at": _as_aware_utc(started_at),
                    "updated_at": _as_aware_utc(updated_at),
                    "ended_at": (
                        _as_aware_utc(ended_at)
                        if isinstance(ended_at, datetime)
                        else None
                    ),
                }
            )
        return conversations, int(self._collection.count_documents(query))

    def get_observability_conversation(
        self,
        *,
        conversation_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any] | None:
        """Read one conversation and a bounded, insertion-ordered message page."""
        if not conversation_id.strip():
            raise ValueError("conversation_id é obrigatório")
        if not 1 <= limit <= 200:
            raise ValueError("limit precisa estar entre 1 e 200")
        if not 0 <= offset <= 100_000:
            raise ValueError("offset precisa estar entre 0 e 100000")

        self._ensure_observability_indexes()
        document = self._collection.find_one(
            {
                "_id": conversation_id.strip(),
                "status": {"$in": ["active", "ended"]},
            },
            {
                "_id": 1,
                "title": 1,
                "status": 1,
                "started_at": 1,
                "updated_at": 1,
                "ended_at": 1,
                "messages": {"$slice": [offset, limit + 1]},
            },
        )
        if document is None:
            return None

        raw_messages = document.get("messages", [])
        if not isinstance(raw_messages, list):
            raw_messages = []
        has_more = len(raw_messages) > limit
        messages: list[dict[str, Any]] = []
        for raw_message in raw_messages[:limit]:
            if not isinstance(raw_message, dict):
                continue
            message = dict(raw_message)
            created_at = message.get("created_at")
            if isinstance(created_at, datetime):
                message["created_at"] = _as_aware_utc(created_at)
            messages.append(message)

        started_at = document.get("started_at")
        updated_at = document.get("updated_at")
        if not isinstance(started_at, datetime) or not isinstance(updated_at, datetime):
            raise ValueError("Metadados de data da conversa estão incompletos")
        ended_at = document.get("ended_at")
        return {
            "conversation_id": str(document["_id"]),
            "title": document.get("title"),
            "status": document.get("status"),
            "started_at": _as_aware_utc(started_at),
            "updated_at": _as_aware_utc(updated_at),
            "ended_at": (
                _as_aware_utc(ended_at) if isinstance(ended_at, datetime) else None
            ),
            "messages": messages,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "next_offset": offset + len(messages) if has_more else None,
        }

    def _ensure_observability_indexes(self) -> None:
        if self._observability_indexes_ready:
            return
        self._collection.create_index(
            [("updated_at", DESCENDING), ("_id", DESCENDING)],
            name="ix_conversations_updated_at",
        )
        self._collection.create_index(
            [("email", ASCENDING), ("updated_at", DESCENDING), ("_id", DESCENDING)],
            name="ix_conversations_email_updated_at",
        )
        self._collection.create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING), ("_id", DESCENDING)],
            name="ix_conversations_status_updated_at",
        )
        self._observability_indexes_ready = True

    @staticmethod
    def _query_timestamp(value: datetime, field_name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} precisa incluir timezone")
        return value.astimezone(timezone.utc)

    def list_conversation_ids_for_email(self, *, email: str) -> list[str]:
        """Resolve an operator's consumer filter without copying email into traces."""
        normalized_email = email.strip()
        if not normalized_email:
            raise ValueError("email é obrigatório")
        if not self._email_index_ready:
            self._collection.create_index(
                [("email", ASCENDING)],
                name="ix_conversations_email",
            )
            self._email_index_ready = True
        cursor = self._collection.find(
            {"email": normalized_email},
            {"_id": 1},
        )
        return [str(document["_id"]) for document in cursor]

    def mark_ended(
        self,
        *,
        conversation_id: str,
        email: str,
        ended_at: datetime,
    ) -> datetime:
        """Close a conversation and return its stable closure timestamp."""
        if not conversation_id.strip() or not email.strip():
            raise ValueError("conversation_id e email são obrigatórios")
        if ended_at.tzinfo is None or ended_at.utcoffset() is None:
            raise ValueError("ended_at precisa incluir timezone")

        result = self._collection.update_one(
            {
                "_id": conversation_id,
                "email": email,
                "status": "active",
            },
            {
                "$set": {
                    "status": "ended",
                    "ended_at": ended_at,
                }
            },
        )
        if result.matched_count == 1:
            return ended_at

        existing = self._collection.find_one(
            {"_id": conversation_id, "email": email},
            {"status": 1, "ended_at": 1},
        )
        if existing is None:
            raise ConversationNotFoundError(conversation_id)
        if existing.get("status") != "ended":
            raise ConversationNotFoundError(conversation_id)
        return _as_aware_utc(existing.get("ended_at"))

    def get_summary_snapshot(
        self,
        *,
        conversation_id: str,
        email: str,
        summary: str | None = None,
        summary_version: int = 0,
        summarized_through_message_id: str | None = None,
    ) -> ConversationSummarySnapshot:
        """Assemble runtime summary state from Mongo messages and Qdrant data."""
        if not conversation_id.strip() or not email.strip():
            raise ValueError("conversation_id e email são obrigatórios")

        document = self._collection.find_one(
            {"_id": conversation_id, "email": email},
            {
                "_id": 1,
                "email": 1,
                "title": 1,
                "status": 1,
                "messages": 1,
                "updated_at": 1,
            },
        )
        if document is None:
            raise ConversationNotFoundError(conversation_id)
        if document.get("status") != "ended":
            raise ConversationNotEndedError(conversation_id)

        messages = []
        for stored in document.get("messages", []):
            message_data = dict(stored)
            message_data["created_at"] = _as_aware_utc(message_data.get("created_at"))
            messages.append(StoredMessage.model_validate(message_data))

        return ConversationSummarySnapshot(
            conversation_id=document["_id"],
            email=document["email"],
            title=document.get("title"),
            status=document["status"],
            summary=summary,
            summary_version=summary_version,
            summarized_through_message_id=summarized_through_message_id,
            messages=messages,
            updated_at=_as_aware_utc(document.get("updated_at")),
        )

    def resume_conversation(
        self,
        *,
        conversation_id: str,
        email: str,
        resumed_at: datetime,
    ) -> list[StoredMessage]:
        """Reopen an owned ended conversation and return its ordered history."""
        if not conversation_id.strip() or not email.strip():
            raise ValueError("conversation_id e email são obrigatórios")
        if resumed_at.tzinfo is None or resumed_at.utcoffset() is None:
            raise ValueError("resumed_at precisa incluir timezone")

        result = self._collection.update_one(
            {
                "_id": conversation_id,
                "email": email,
                "status": "ended",
            },
            {
                "$set": {
                    "status": "active",
                    "ended_at": None,
                    "updated_at": resumed_at,
                }
            },
        )
        if result.matched_count != 1:
            existing = self._collection.find_one(
                {"_id": conversation_id, "email": email},
                {"status": 1},
            )
            if existing is None:
                raise ConversationNotFoundError(conversation_id)
            raise ConversationNotEndedError(conversation_id)

        document = self._collection.find_one(
            {"_id": conversation_id, "email": email, "status": "active"},
            {"messages": 1},
        )
        if document is None:
            raise ConversationNotFoundError(conversation_id)

        messages: list[StoredMessage] = []
        for stored in document.get("messages", []):
            message_data = dict(stored)
            message_data["created_at"] = _as_aware_utc(message_data.get("created_at"))
            messages.append(StoredMessage.model_validate(message_data))

        return sorted(messages, key=lambda message: message.created_at)

    def list_ended_conversations(self, *, email: str) -> list[ConversationListItem]:
        """Return IDs and titles of this user's ended conversations for the API."""
        if not email.strip():
            raise ValueError("email é obrigatório")

        documents = self._collection.find(
            {"email": email, "status": "ended"},
            {"_id": 1, "title": 1, "updated_at": 1},
        ).sort([("updated_at", -1), ("_id", -1)])
        conversations: list[ConversationListItem] = []
        for document in documents:
            conversation_id = document.get("_id")
            title = document.get("title")
            updated_at = _as_timestamp(document.get("updated_at"))
            if not isinstance(conversation_id, str):
                continue
            if title is not None and not isinstance(title, str):
                continue
            if updated_at is None:
                continue
            conversations.append(
                {
                    "conversation_id": conversation_id,
                    "title": title,
                    "updated_at": updated_at,
                }
            )
        return conversations

    def list_ended_summary_snapshots(
        self, *, limit: int = 100
    ) -> list[ConversationSummarySnapshot]:
        if limit < 1:
            raise ValueError("limit precisa ser positivo")
        documents = (
            self._collection.find(
                {"status": "ended"},
                {
                    "_id": 1,
                    "email": 1,
                    "title": 1,
                    "status": 1,
                    "messages": 1,
                    "updated_at": 1,
                },
            )
            .sort([("updated_at", -1), ("_id", -1)])
            .limit(limit)
        )
        snapshots: list[ConversationSummarySnapshot] = []
        for document in documents:
            messages = [
                StoredMessage.model_validate(
                    {
                        **stored,
                        "created_at": _as_aware_utc(stored.get("created_at")),
                    }
                )
                for stored in document.get("messages", [])
            ]
            snapshots.append(
                ConversationSummarySnapshot(
                    conversation_id=document["_id"],
                    email=document["email"],
                    title=document.get("title"),
                    status="ended",
                    summary=None,
                    summary_version=0,
                    summarized_through_message_id=None,
                    messages=messages,
                    updated_at=_as_aware_utc(document.get("updated_at")),
                )
            )
        return snapshots

    def list_conversation_states(self, *, limit: int = 100) -> dict[str, str]:
        if limit < 1:
            raise ValueError("limit precisa ser positivo")
        documents = self._collection.find({}, {"_id": 1, "status": 1}).limit(limit)
        return {
            str(document["_id"]): str(document.get("status", ""))
            for document in documents
            if document.get("_id") is not None
        }

    def save_title_if_missing(
        self,
        *,
        conversation_id: str,
        email: str,
        title: str,
    ) -> bool:
        """Save a generated title only while its source summary is current."""
        if not title.strip():
            raise ValueError("title não pode estar vazio")
        result = self._collection.update_one(
            {
                "_id": conversation_id,
                "email": email,
                "status": "ended",
                "$or": [{"title": None}, {"title": {"$exists": False}}],
            },
            {"$set": {"title": title.strip()}},
        )
        return result.modified_count == 1

    def get_ended_conversation_metadata_by_ids(
        self,
        *,
        email: str,
        conversation_ids: list[str],
    ) -> dict[str, ConversationMetadata]:
        """Validate ownership/status and return metadata, never summary text."""
        if not email.strip():
            raise ValueError("email é obrigatório")
        if not conversation_ids:
            return {}

        documents = self._collection.find(
            {
                "_id": {"$in": conversation_ids},
                "email": email,
                "status": "ended",
            },
            {"_id": 1, "title": 1, "updated_at": 1},
        )

        metadata: dict[str, ConversationMetadata] = {}
        for document in documents:
            conversation_id = document.get("_id")
            title = document.get("title")
            updated_at = _as_timestamp(document.get("updated_at"))
            if not isinstance(conversation_id, str):
                continue
            if title is not None and not isinstance(title, str):
                continue
            if updated_at is None:
                continue
            metadata[conversation_id] = {
                "conversation_id": conversation_id,
                "title": title,
                "updated_at": updated_at,
            }

        return metadata

    def mark_deleting(self, *, conversation_id: str, email: str) -> bool:
        """Transition an owned conversation to deleting before cross-store cleanup."""
        result = self._collection.update_one(
            {
                "_id": conversation_id,
                "email": email,
                "status": {"$in": ["active", "ended", "deleting"]},
            },
            {"$set": {"status": "deleting"}},
        )
        return result.matched_count == 1

    def delete_conversation(self, *, conversation_id: str, email: str) -> bool:
        result = self._collection.delete_one(
            {"_id": conversation_id, "email": email, "status": "deleting"}
        )
        return result.deleted_count == 1

    def append_turn(
        self,
        *,
        conversation_id: str,
        email: str,
        turn: ConversationTurn,
    ) -> None:
        """Append a complete user/assistant turn with one atomic Mongo operation."""
        if not conversation_id.strip() or not email.strip():
            raise ValueError("conversation_id e email são obrigatórios")

        user_message = turn.user_message.model_dump(mode="python", exclude_none=True)
        assistant_message = turn.assistant_message.model_dump(
            mode="python", exclude_none=True
        )
        user_id = turn.user_message.message_id
        assistant_id = turn.assistant_message.message_id
        user_created_at = turn.user_message.created_at
        assistant_created_at = turn.assistant_message.created_at

        def message_ids_expression() -> dict[str, object]:
            return {
                "$map": {
                    "input": {"$ifNull": ["$messages", []]},
                    "as": "message",
                    "in": "$$message.message_id",
                }
            }

        update_pipeline: list[dict[str, object]] = [
            {
                "$set": {
                    "_turn_is_new": {"$eq": [{"$type": "$email"}, "missing"]},
                    "_turn_can_append": {
                        "$or": [
                            {"$eq": [{"$type": "$email"}, "missing"]},
                            {
                                "$and": [
                                    {"$eq": ["$email", {"$literal": email}]},
                                    {"$eq": ["$status", "active"]},
                                ]
                            },
                        ]
                    },
                    "_turn_has_user_message": {
                        "$in": [{"$literal": user_id}, message_ids_expression()]
                    },
                    "_turn_has_assistant_message": {
                        "$in": [
                            {"$literal": assistant_id},
                            message_ids_expression(),
                        ]
                    },
                }
            },
            {
                "$set": {
                    "email": {
                        "$cond": ["$_turn_is_new", {"$literal": email}, "$email"]
                    },
                    "status": {"$cond": ["$_turn_is_new", "active", "$status"]},
                    "started_at": {
                        "$cond": [
                            "$_turn_is_new",
                            {"$literal": user_created_at},
                            "$started_at",
                        ]
                    },
                    "ended_at": {"$cond": ["$_turn_is_new", None, "$ended_at"]},
                    "title": {"$cond": ["$_turn_is_new", None, "$title"]},
                    "messages": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_turn_can_append",
                                    {"$not": ["$_turn_has_user_message"]},
                                    {"$not": ["$_turn_has_assistant_message"]},
                                ]
                            },
                            {
                                "$concatArrays": [
                                    {"$ifNull": ["$messages", []]},
                                    {
                                        "$literal": [
                                            user_message,
                                            assistant_message,
                                        ]
                                    },
                                ]
                            },
                            {"$ifNull": ["$messages", []]},
                        ]
                    },
                    "updated_at": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_turn_can_append",
                                    {"$not": ["$_turn_has_user_message"]},
                                    {"$not": ["$_turn_has_assistant_message"]},
                                ]
                            },
                            {
                                "$max": [
                                    {"$ifNull": ["$updated_at", user_created_at]},
                                    {"$literal": user_created_at},
                                    {"$literal": assistant_created_at},
                                ]
                            },
                            "$updated_at",
                        ]
                    },
                    "total_turns": {
                        "$cond": [
                            "$_turn_is_new",
                            1,
                            {
                                "$add": [
                                    {"$ifNull": ["$total_turns", 0]},
                                    {
                                        "$cond": [
                                            {
                                                "$and": [
                                                    "$_turn_can_append",
                                                    {
                                                        "$not": [
                                                            "$_turn_has_user_message"
                                                        ]
                                                    },
                                                    {
                                                        "$not": [
                                                            "$_turn_has_assistant_message"
                                                        ]
                                                    },
                                                ]
                                            },
                                            1,
                                            0,
                                        ]
                                    },
                                ]
                            },
                        ]
                    },
                }
            },
            {
                "$unset": [
                    "_turn_is_new",
                    "_turn_can_append",
                    "_turn_has_user_message",
                    "_turn_has_assistant_message",
                ]
            },
        ]

        conversation = self._collection.find_one_and_update(
            {"_id": conversation_id},
            update_pipeline,
            upsert=True,
            return_document=ReturnDocument.AFTER,
            projection={"email": 1, "status": 1, "messages.message_id": 1},
        )

        if conversation is None or conversation.get("email") != email:
            raise ConversationNotFoundError(conversation_id)
        existing_message_ids = {
            message.get("message_id")
            for message in conversation.get("messages", [])
            if isinstance(message, dict)
        }
        if {user_id, assistant_id}.issubset(existing_message_ids):
            return
        if conversation.get("status") != "active":
            if conversation.get("status") == "ended":
                raise ConversationClosedError(conversation_id)
            raise ConversationNotFoundError(conversation_id)
        raise RuntimeError(
            "O turno já possui uma das mensagens persistida; "
            "a gravação atômica foi interrompida"
        )
