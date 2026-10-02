"""MongoDB persistence adapter for conversation messages."""

from datetime import datetime, timezone

from pymongo.collection import Collection

from .contracts import (
    ConversationDocument,
    ConversationListItem,
    ConversationMetadata,
    ConversationSummarySnapshot,
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

    def append_message(
        self,
        *,
        conversation_id: str,
        email: str,
        message: StoredMessage,
    ) -> bool:
        """Append one message atomically and idempotently.

        The first user message creates the conversation document. Assistant
        messages never create a conversation by themselves.
        """
        if message.role == "user":
            created = self._create_if_missing(
                conversation_id=conversation_id,
                email=email,
                first_message=message,
            )
            if created:
                return True

        message_doc = message.model_dump(mode="python", exclude_none=True)
        message_ids = {
            "$map": {
                "input": {"$ifNull": ["$messages", []]},
                "as": "message",
                "in": "$$message.message_id",
            }
        }
        already_saved = {"$in": [{"$literal": message.message_id}, message_ids]}
        append_pipeline = [
            {
                "$set": {
                    "messages": {
                        "$cond": [
                            already_saved,
                            {"$ifNull": ["$messages", []]},
                            {
                                "$concatArrays": [
                                    {"$ifNull": ["$messages", []]},
                                    [{"$literal": message_doc}],
                                ]
                            },
                        ]
                    },
                    "updated_at": {
                        "$cond": [
                            already_saved,
                            "$updated_at",
                            {
                                "$max": [
                                    "$updated_at",
                                    {"$literal": message.created_at},
                                ]
                            },
                        ]
                    },
                    "total_turns": {
                        "$add": [
                            {"$ifNull": ["$total_turns", 0]},
                            {
                                "$cond": [
                                    {
                                        "$and": [
                                            {"$not": [already_saved]},
                                            {
                                                "$eq": [
                                                    {"$literal": message.role},
                                                    "assistant",
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
                }
            }
        ]

        result = self._collection.update_one(
            {
                "_id": conversation_id,
                "email": email,
                "status": "active",
            },
            append_pipeline,
        )
        if result.modified_count == 1:
            return True
        if result.matched_count == 1:
            return False

        conversation = self._collection.find_one(
            {"_id": conversation_id, "email": email},
            {"status": 1, "messages.message_id": 1},
        )
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)

        if any(
            saved.get("message_id") == message.message_id
            for saved in conversation.get("messages", [])
        ):
            return False

        if conversation.get("status") != "active":
            raise ConversationClosedError(conversation_id)

        raise RuntimeError("A conversa mudou durante a persistência da mensagem")

    def _create_if_missing(
        self,
        *,
        conversation_id: str,
        email: str,
        first_message: StoredMessage,
    ) -> bool:
        document: ConversationDocument = {
            "_id": conversation_id,
            "email": email,
            "started_at": first_message.created_at,
            "updated_at": first_message.created_at,
            "ended_at": None,
            "status": "active",
            "title": None,
            "messages": [first_message.model_dump(mode="python", exclude_none=True)],
            "total_turns": 0,
        }
        result = self._collection.update_one(
            {"_id": conversation_id},
            {"$setOnInsert": document},
            upsert=True,
        )
        return result.upserted_id is not None
