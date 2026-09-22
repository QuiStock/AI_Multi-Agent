"""MongoDB persistence adapter for conversation messages."""

from datetime import datetime, timezone

from pymongo.collection import Collection

from .contracts import (
    MAX_SUMMARY_RESULTS,
    ConversationDocument,
    ConversationListItem,
    ConversationSummary,
    ConversationSummarySnapshot,
    StoredMessage,
    SummaryCommit,
    VersionedConversationSummary,
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
        user_id: str,
        ended_at: datetime,
    ) -> datetime:
        """Close a conversation and return its stable closure timestamp."""
        if not conversation_id.strip() or not user_id.strip():
            raise ValueError("conversation_id e user_id são obrigatórios")
        if ended_at.tzinfo is None or ended_at.utcoffset() is None:
            raise ValueError("ended_at precisa incluir timezone")

        result = self._collection.update_one(
            {
                "_id": conversation_id,
                "user_id": user_id,
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
            {"_id": conversation_id, "user_id": user_id},
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
        user_id: str,
    ) -> ConversationSummarySnapshot:
        """Load the owned conversation and its current summary boundary."""
        if not conversation_id.strip() or not user_id.strip():
            raise ValueError("conversation_id e user_id são obrigatórios")

        document = self._collection.find_one(
            {"_id": conversation_id, "user_id": user_id},
            {
                "_id": 1,
                "user_id": 1,
                "title": 1,
                "status": 1,
                "summary": 1,
                "summary_version": 1,
                "summarized_through_message_id": 1,
                "messages": 1,
                "updated_at": 1,
            },
        )
        if document is None:
            raise ConversationNotFoundError(conversation_id)

        messages = []
        for stored in document.get("messages", []):
            message_data = dict(stored)
            message_data["created_at"] = _as_aware_utc(message_data.get("created_at"))
            messages.append(StoredMessage.model_validate(message_data))

        return ConversationSummarySnapshot(
            conversation_id=document["_id"],
            user_id=document["user_id"],
            title=document.get("title"),
            status=document["status"],
            summary=document.get("summary"),
            summary_version=document.get("summary_version", 0),
            summarized_through_message_id=document.get("summarized_through_message_id"),
            messages=messages,
            updated_at=_as_aware_utc(document.get("updated_at")),
        )

    def resume_conversation(
        self,
        *,
        conversation_id: str,
        user_id: str,
        resumed_at: datetime,
    ) -> list[StoredMessage]:
        """Reopen an owned ended conversation and return its ordered history."""
        if not conversation_id.strip() or not user_id.strip():
            raise ValueError("conversation_id e user_id são obrigatórios")
        if resumed_at.tzinfo is None or resumed_at.utcoffset() is None:
            raise ValueError("resumed_at precisa incluir timezone")

        result = self._collection.update_one(
            {
                "_id": conversation_id,
                "user_id": user_id,
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
                {"_id": conversation_id, "user_id": user_id},
                {"status": 1},
            )
            if existing is None:
                raise ConversationNotFoundError(conversation_id)
            raise ConversationNotEndedError(conversation_id)

        document = self._collection.find_one(
            {"_id": conversation_id, "user_id": user_id, "status": "active"},
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

    def list_ended_conversations(self, *, user_id: str) -> list[ConversationListItem]:
        """Return IDs and titles of this user's ended conversations for the API."""
        if not user_id.strip():
            raise ValueError("user_id é obrigatório")

        documents = self._collection.find(
            {"user_id": user_id, "status": "ended"},
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

    def save_summary_if_current(self, commit: SummaryCommit) -> bool:
        """Commit one summary version only if its source boundary is unchanged."""
        if not commit.summary.strip():
            raise ValueError("summary não pode estar vazio")
        if not commit.summarized_through_message_id.strip():
            raise ValueError("summarized_through_message_id é obrigatório")
        if commit.expected_summary_version < 0:
            raise ValueError("expected_summary_version não pode ser negativo")

        result = self._collection.update_one(
            {
                "_id": commit.conversation_id,
                "user_id": commit.user_id,
                "status": "ended",
                "summary_version": commit.expected_summary_version,
                "summarized_through_message_id": commit.expected_message_id,
            },
            {
                "$set": {
                    "summary": commit.summary,
                    "summary_version": commit.expected_summary_version + 1,
                    "summarized_through_message_id": (
                        commit.summarized_through_message_id
                    ),
                }
            },
        )
        return result.modified_count == 1

    def save_title_if_missing(
        self,
        *,
        conversation_id: str,
        user_id: str,
        expected_summary_version: int,
        title: str,
    ) -> bool:
        """Save a generated title only while its source summary is current."""
        if not title.strip():
            raise ValueError("title não pode estar vazio")
        if expected_summary_version < 1:
            raise ValueError("expected_summary_version deve ser positivo")

        result = self._collection.update_one(
            {
                "_id": conversation_id,
                "user_id": user_id,
                "status": "ended",
                "summary_version": expected_summary_version,
                "$or": [{"title": None}, {"title": {"$exists": False}}],
            },
            {"$set": {"title": title.strip()}},
        )
        return result.modified_count == 1

    def get_ended_summaries_by_ids(
        self,
        *,
        user_id: str,
        conversation_ids: list[str],
    ) -> dict[str, VersionedConversationSummary]:
        """Return authoritative summaries for owned, ended Qdrant candidates."""
        if not user_id.strip():
            raise ValueError("user_id é obrigatório")
        if not conversation_ids:
            return {}

        documents = self._collection.find(
            {
                "_id": {"$in": conversation_ids},
                "user_id": user_id,
                "status": "ended",
                "summary": {"$type": "string", "$ne": ""},
            },
            {"_id": 1, "title": 1, "summary": 1, "summary_version": 1, "updated_at": 1},
        )

        summaries: dict[str, VersionedConversationSummary] = {}
        for document in documents:
            conversation_id = document.get("_id")
            summary = document.get("summary")
            version = document.get("summary_version")
            title = document.get("title")
            updated_at = _as_timestamp(document.get("updated_at"))
            if not isinstance(conversation_id, str):
                continue
            if not isinstance(summary, str) or not summary.strip():
                continue
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                continue
            if title is not None and not isinstance(title, str):
                continue
            if updated_at is None:
                continue
            summaries[conversation_id] = {
                "conversation_id": conversation_id,
                "title": title,
                "summary": summary,
                "updated_at": updated_at,
                "summary_version": version,
            }

        return summaries

    def get_latest_ended_summaries(
        self,
        *,
        user_id: str,
        exclude_conversation_id: str,
        limit: int = 3,
    ) -> list[ConversationSummary]:
        """Return the user's most recently updated ended summaries."""
        if not user_id.strip():
            raise ValueError("user_id é obrigatório")
        if not 1 <= limit <= MAX_SUMMARY_RESULTS:
            raise ValueError("limit deve estar entre um e três")

        documents = (
            self._collection.find(
                {
                    "user_id": user_id,
                    "status": "ended",
                    "_id": {"$ne": exclude_conversation_id},
                    "summary": {"$type": "string", "$ne": ""},
                },
                {
                    "_id": 1,
                    "title": 1,
                    "summary": 1,
                    "updated_at": 1,
                },
            )
            .sort([("updated_at", -1), ("_id", -1)])
            .limit(limit)
        )

        summaries: list[ConversationSummary] = []
        for document in documents:
            conversation_id = document.get("_id")
            title = document.get("title")
            summary = document.get("summary")
            updated_at = _as_timestamp(document.get("updated_at"))
            if not isinstance(conversation_id, str):
                continue
            if title is not None and not isinstance(title, str):
                continue
            if not isinstance(summary, str) or not summary.strip():
                continue
            if updated_at is None:
                continue

            summaries.append(
                {
                    "conversation_id": conversation_id,
                    "title": title,
                    "summary": summary,
                    "updated_at": updated_at,
                }
            )

        return summaries

    def append_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        message: StoredMessage,
    ) -> bool:
        """Append one message atomically and idempotently.

        The first user message creates the conversation document. Assistant
        messages never create a conversation by themselves.
        """
        if message.role == "user":
            created = self._create_if_missing(
                conversation_id=conversation_id,
                user_id=user_id,
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
                "user_id": user_id,
                "status": "active",
            },
            append_pipeline,
        )
        if result.modified_count == 1:
            return True
        if result.matched_count == 1:
            return False

        conversation = self._collection.find_one(
            {"_id": conversation_id, "user_id": user_id},
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
        user_id: str,
        first_message: StoredMessage,
    ) -> bool:
        document: ConversationDocument = {
            "_id": conversation_id,
            "user_id": user_id,
            "started_at": first_message.created_at,
            "updated_at": first_message.created_at,
            "ended_at": None,
            "status": "active",
            "title": None,
            "summary": None,
            "summary_version": 0,
            "summarized_through_message_id": None,
            "messages": [first_message.model_dump(mode="python", exclude_none=True)],
            "total_turns": 0,
        }
        result = self._collection.update_one(
            {"_id": conversation_id},
            {"$setOnInsert": document},
            upsert=True,
        )
        return result.upserted_id is not None
