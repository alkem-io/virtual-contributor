"""Recursive space tree reader — traverses Alkemio's 3-level hierarchy."""

from __future__ import annotations

import hashlib
import html as _html
import logging
import re
from dataclasses import dataclass, replace

from core.domain.ingest_pipeline import Document, DocumentMetadata, DocumentType
from plugins.ingest_space.link_extractor import extract_text

logger = logging.getLogger(__name__)

# Wire-format values of IngestBodyOfKnowledge.type — must match what the
# Alkemio server publishes on the ingest queue.
BOK_TYPE_SPACE = "alkemio-space"
BOK_TYPE_KNOWLEDGE_BASE = "alkemio-knowledge-base"

# HTML cleanup ----------------------------------------------------------------

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK_TAGS_RE = re.compile(
    r"</?(br|p|div|li|tr|h[1-6]|hr|blockquote|pre)(\s[^>]*)?/?>",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_HORIZONTAL_WS_RE = re.compile(r"[ \t]+")
_EXCESS_NEWLINES_RE = re.compile(r"\n[ \t]*\n[ \t]*\n+")


def _strip_html(text: str) -> str:
    """Strip HTML tags and decode entities, preserving paragraph breaks."""
    if not text:
        return text
    # Remove <script>/<style> blocks entirely, including contents.
    text = _SCRIPT_STYLE_RE.sub("", text)
    # Turn block-level tags into newlines so structure survives.
    text = _BLOCK_TAGS_RE.sub("\n", text)
    # Drop all remaining tags (iframes, spans, strongs, etc.).
    text = _TAG_RE.sub("", text)
    # Decode entities (&amp;, &lt;, &nbsp;, …).
    text = _html.unescape(text)
    # Normalise whitespace.
    text = _HORIZONTAL_WS_RE.sub(" ", text)
    text = _EXCESS_NEWLINES_RE.sub("\n\n", text)
    return text.strip()


def _content_key(content: str) -> str:
    """Whitespace-insensitive hash used for deduplication."""
    normalised = re.sub(r"\s+", " ", content).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

# GraphQL query for space tree
_CALLOUT_FIELDS = """
  id
  framing { profile { displayName description url } }
  contributions {
    post { id profile { displayName description url } }
    whiteboard { id profile { displayName url } content }
    link { id profile { displayName description url } uri }
  }
"""

SPACE_TREE_QUERY = f"""
query SpaceTree($spaceId: UUID!) {{
  lookup {{
    space(ID: $spaceId) {{
      id
      profile {{ displayName description url }}
      collaboration {{
        calloutsSet {{
          callouts {{ {_CALLOUT_FIELDS} }}
        }}
      }}
      subspaces {{
        id
        profile {{ displayName description url }}
        collaboration {{
          calloutsSet {{
            callouts {{ {_CALLOUT_FIELDS} }}
          }}
        }}
        subspaces {{
          id
          profile {{ displayName description url }}
          collaboration {{
            calloutsSet {{
              callouts {{ {_CALLOUT_FIELDS} }}
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""

# Knowledge bases are flat: a profile and a single calloutsSet, no subspaces.
KNOWLEDGE_BASE_QUERY = f"""
query KnowledgeBaseTree($kbId: UUID!) {{
  lookup {{
    knowledgeBase(ID: $kbId) {{
      id
      profile {{ displayName description url }}
      calloutsSet {{
        callouts {{ {_CALLOUT_FIELDS} }}
      }}
    }}
  }}
}}
"""


async def read_space_tree(graphql_client, space_id: str) -> list[Document]:
    """Read the full space tree and convert to Documents."""
    data = await graphql_client.query(SPACE_TREE_QUERY, {"spaceId": space_id})
    space = (data.get("lookup") or {}).get("space")
    if not space:
        return []

    documents: list[Document] = []
    seen: set[str] = set()
    stats = {"fetched": 0, "skipped": 0}
    await _process_space(
        space, documents, seen, graphql_client=graphql_client,
        stats=stats, depth=0,
    )
    logger.info(
        "Space tree: emitted %d unique documents "
        "(link bodies fetched=%d, skipped=%d)",
        len(documents), stats["fetched"], stats["skipped"],
    )
    return documents


async def read_knowledge_base_tree(graphql_client, kb_id: str) -> list[Document]:
    """Read a knowledge base and convert its callouts to Documents."""
    data = await graphql_client.query(KNOWLEDGE_BASE_QUERY, {"kbId": kb_id})
    kb = (data.get("lookup") or {}).get("knowledgeBase")
    if not kb:
        return []

    # Reshape into the dict layout _process_space expects: a synthetic
    # `collaboration.calloutsSet` wrapper and no `subspaces`.
    space_shaped = {
        **kb,
        "collaboration": {"calloutsSet": kb.get("calloutsSet")},
        "subspaces": [],
    }

    documents: list[Document] = []
    seen: set[str] = set()
    stats = {"fetched": 0, "skipped": 0}
    await _process_space(
        space_shaped, documents, seen,
        graphql_client=graphql_client, stats=stats, depth=0,
        top_doc_type=DocumentType.KNOWLEDGE.value,
    )
    logger.info(
        "Knowledge base tree: emitted %d unique documents "
        "(link bodies fetched=%d, skipped=%d)",
        len(documents), stats["fetched"], stats["skipped"],
    )
    return documents


async def read_body_of_knowledge(
    graphql_client, bok_id: str, bok_type: str,
) -> list[Document]:
    """Dispatch to the correct reader based on the BoK type.

    Unknown types fall back to the space reader, which matches the dominant
    case on the platform today.
    """
    if bok_type == BOK_TYPE_KNOWLEDGE_BASE:
        return await read_knowledge_base_tree(graphql_client, bok_id)
    return await read_space_tree(graphql_client, bok_id)


#: Display names are capped before storage — they are provenance labels, not
#: content, and the store keeps every metadata value small (FR-011/FR-012).
_NAME_MAX_CHARS = 200

#: Tier assigned to contributions (posts, whiteboards, links), which sit below
#: whichever node owns their callout.
_CONTRIBUTION_DEPTH = 3


def _clean_name(raw: str | None) -> str | None:
    """HTML-strip and cap a display name; blank becomes unknown (``None``)."""
    if not raw:
        return None
    cleaned = _strip_html(raw) or raw
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    return cleaned[:_NAME_MAX_CHARS]


@dataclass(frozen=True)
class _Position:
    """Where a document sits in the space tree.

    ``subspace_*`` always names the **nearest containing** subspace, so a
    second-level subspace's own content reports itself, not its first-level
    ancestor. ``depth`` is the tier of the owning node; contributions override
    it to ``_CONTRIBUTION_DEPTH``.
    """

    space_id: str | None = None
    space_name: str | None = None
    subspace_id: str | None = None
    subspace_name: str | None = None
    callout_id: str | None = None
    depth: int = 0

    def for_node(self, node_id: str, node_name: str | None, depth: int) -> _Position:
        """Descend to a tree node: the root sets space, deeper sets subspace."""
        name = _clean_name(node_name)
        if depth == 0:
            return replace(
                self, space_id=node_id, space_name=name, depth=0,
            )
        return replace(
            self, subspace_id=node_id, subspace_name=name, depth=depth,
        )

    def for_callout(self, callout_id: str) -> _Position:
        """A callout keeps its owner's tier and names itself (FR-005)."""
        return replace(self, callout_id=callout_id)

    def for_contribution(self) -> _Position:
        """A contribution keeps its callout and drops to the leaf tier."""
        return replace(self, depth=_CONTRIBUTION_DEPTH)


def _append_unique(
    documents: list[Document],
    seen: set[str],
    *,
    content: str,
    document_id: str,
    source: str,
    doc_type: str,
    title: str,
    uri: str | None = None,
    position: _Position | None = None,
) -> bool:
    """Append a Document if its stripped content is non-empty and new."""
    cleaned = _strip_html(content)
    if not cleaned:
        return False
    key = _content_key(cleaned)
    if key in seen:
        return False
    seen.add(key)
    pos = position or _Position()
    documents.append(Document(
        content=cleaned,
        metadata=DocumentMetadata(
            document_id=document_id,
            source=source,
            type=doc_type,
            title=_strip_html(title) or title,
            uri=uri or None,
            space_id=pos.space_id,
            space_name=pos.space_name,
            subspace_id=pos.subspace_id,
            subspace_name=pos.subspace_name,
            callout_id=pos.callout_id,
            depth=pos.depth,
        ),
    ))
    return True


async def _process_space(
    space: dict,
    documents: list[Document],
    seen: set[str],
    *,
    graphql_client,
    stats: dict,
    depth: int,
    top_doc_type: str | None = None,
    position: _Position | None = None,
) -> None:
    """Process a space node and its children recursively.

    `top_doc_type` overrides the doc type used for the depth-0 document
    (so knowledge bases can be tagged as KNOWLEDGE instead of SPACE).

    `position` accumulates the tree position: the depth-0 node becomes the
    space, each deeper node becomes the nearest containing subspace.
    """
    profile = space.get("profile") or {}
    space_name = profile.get("displayName", "") or ""
    description = profile.get("description", "") or ""
    space_url = profile.get("url", "") or None

    node_position = (position or _Position()).for_node(
        space["id"], space_name, depth,
    )

    if description:
        if depth == 0 and top_doc_type is not None:
            doc_type_value = top_doc_type
        else:
            doc_type_value = (
                DocumentType.SPACE.value if depth == 0
                else DocumentType.SUBSPACE.value
            )
        _append_unique(
            documents, seen,
            content=f"{space_name}\n\n{description}",
            document_id=space["id"],
            source=f"space:{space['id']}",
            doc_type=doc_type_value,
            title=space_name,
            uri=space_url,
            position=node_position,
        )

    # Process callouts
    collaboration = space.get("collaboration") or {}
    callouts_set = collaboration.get("calloutsSet") or {}
    for callout in callouts_set.get("callouts") or []:
        await _process_callout(
            callout, documents, seen,
            graphql_client=graphql_client, stats=stats,
            position=node_position,
        )

    # Recurse into subspaces
    for subspace in space.get("subspaces") or []:
        await _process_space(
            subspace, documents, seen,
            graphql_client=graphql_client, stats=stats, depth=depth + 1,
            position=node_position,
        )


async def _process_callout(
    callout: dict,
    documents: list[Document],
    seen: set[str],
    *,
    graphql_client,
    stats: dict,
    position: _Position | None = None,
) -> None:
    """Process a callout and its contributions.

    The callout keeps the tier of the node that owns it and names itself;
    its contributions inherit that and drop to the contribution tier.
    """
    framing = (callout.get("framing") or {}).get("profile") or {}
    callout_name = framing.get("displayName", "") or ""
    callout_desc = framing.get("description", "") or ""
    callout_url = framing.get("url", "") or None

    callout_position = (position or _Position()).for_callout(callout["id"])
    contribution_position = callout_position.for_contribution()

    if callout_desc:
        _append_unique(
            documents, seen,
            content=f"{callout_name}\n\n{callout_desc}",
            document_id=callout["id"],
            source=f"callout:{callout['id']}",
            doc_type=DocumentType.CALLOUT.value,
            title=callout_name,
            uri=callout_url,
            position=callout_position,
        )

    # Build callout context to prepend to contributions
    context_parts = [callout_name] if callout_name else []
    if callout_desc:
        short_desc = _strip_html(callout_desc)[:400]
        if short_desc:
            context_parts.append(short_desc)
    callout_context = "\n\n".join(context_parts)

    for contrib in callout.get("contributions") or []:
        # Posts
        post = contrib.get("post")
        if post:
            post_profile = post.get("profile") or {}
            post_title = post_profile.get("displayName", "") or ""
            content = post_profile.get("description", "") or ""
            if content:
                enriched_parts = []
                if callout_context:
                    enriched_parts.append(callout_context)
                if post_title:
                    enriched_parts.append(f"# {post_title}")
                enriched_parts.append(content)
                enriched_content = "\n\n".join(enriched_parts)
                _append_unique(
                    documents, seen,
                    content=enriched_content,
                    document_id=post["id"],
                    source=f"post:{post['id']}",
                    doc_type=DocumentType.POST.value,
                    title=post_title,
                    uri=post_profile.get("url") or None,
                    position=contribution_position,
                )

        # Whiteboards
        whiteboard = contrib.get("whiteboard")
        if whiteboard:
            wb_content = whiteboard.get("content", "") or ""
            if wb_content:
                wb_profile = whiteboard.get("profile") or {}
                wb_title = wb_profile.get("displayName", "") or ""
                enriched_parts = []
                if callout_context:
                    enriched_parts.append(callout_context)
                if wb_title:
                    enriched_parts.append(f"# {wb_title}")
                enriched_parts.append(wb_content)
                enriched_content = "\n\n".join(enriched_parts)
                _append_unique(
                    documents, seen,
                    content=enriched_content,
                    document_id=whiteboard["id"],
                    source=f"whiteboard:{whiteboard['id']}",
                    doc_type=DocumentType.WHITEBOARD.value,
                    title=wb_title,
                    uri=wb_profile.get("url") or None,
                    position=contribution_position,
                )

        # Links — fetch the body and extract text so the actual
        # referenced document becomes searchable, not just its URL.
        link = contrib.get("link")
        if link:
            uri = link.get("uri", "") or ""
            link_profile = link.get("profile") or {}
            link_title = link_profile.get("displayName", "") or ""
            link_desc = link_profile.get("description", "") or ""
            if uri or link_title or link_desc:
                fetched_text: str | None = None
                if uri:
                    fetched = await graphql_client.fetch_url(uri)
                    if fetched is not None:
                        body, content_type = fetched
                        fetched_text = extract_text(body, content_type)
                        if fetched_text:
                            stats["fetched"] += 1
                            logger.info(
                                "Extracted %d chars from %s (%s)",
                                len(fetched_text), uri, content_type or "?",
                            )
                        else:
                            stats["skipped"] += 1
                    else:
                        stats["skipped"] += 1

                parts = []
                if fetched_text:
                    # We have the real document body — the callout
                    # context would just mislead the answer LLM into
                    # treating the PDF as part of the parent callout.
                    # Keep a short title header for readability.
                    if link_title:
                        parts.append(f"# {link_title}")
                    if link_desc:
                        parts.append(link_desc)
                    parts.append(fetched_text)
                else:
                    # No body fetched — fall back to lightweight
                    # metadata enriched with callout context so the
                    # fact that the link exists is still retrievable.
                    if callout_context:
                        parts.append(callout_context)
                    if link_title:
                        parts.append(f"# {link_title}")
                    if link_desc:
                        parts.append(link_desc)
                    if uri:
                        parts.append(f"URL: {uri}")
                content = "\n\n".join(p for p in parts if p)
                _append_unique(
                    documents, seen,
                    content=content,
                    document_id=link["id"],
                    source=f"link:{link['id']}",
                    doc_type=DocumentType.LINK.value,
                    title=link_title,
                    uri=uri or link_profile.get("url") or None,
                    position=contribution_position,
                )
