"""Recursive space tree reader — traverses Alkemio's 3-level hierarchy."""

from __future__ import annotations

import hashlib
import html as _html
import logging
import re

from core.domain.ingest_pipeline import Document, DocumentMetadata, DocumentType
from plugins.ingest_space.link_extractor import extract_text

logger = logging.getLogger(__name__)

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
) -> bool:
    """Append a Document if its stripped content is non-empty and new."""
    cleaned = _strip_html(content)
    if not cleaned:
        return False
    key = _content_key(cleaned)
    if key in seen:
        return False
    seen.add(key)
    documents.append(Document(
        content=cleaned,
        metadata=DocumentMetadata(
            document_id=document_id,
            source=source,
            type=doc_type,
            title=_strip_html(title) or title,
            uri=uri or None,
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
) -> None:
    """Process a space node and its children recursively."""
    profile = space.get("profile") or {}
    space_name = profile.get("displayName", "") or ""
    description = profile.get("description", "") or ""
    space_url = profile.get("url", "") or None

    if description:
        doc_type = DocumentType.SPACE if depth == 0 else DocumentType.SUBSPACE
        _append_unique(
            documents, seen,
            content=f"{space_name}\n\n{description}",
            document_id=space["id"],
            source=f"space:{space['id']}",
            doc_type=doc_type.value,
            title=space_name,
            uri=space_url,
        )

    # Process callouts
    collaboration = space.get("collaboration") or {}
    callouts_set = collaboration.get("calloutsSet") or {}
    for callout in callouts_set.get("callouts") or []:
        await _process_callout(
            callout, documents, seen,
            graphql_client=graphql_client, stats=stats,
        )

    # Recurse into subspaces
    for subspace in space.get("subspaces") or []:
        await _process_space(
            subspace, documents, seen,
            graphql_client=graphql_client, stats=stats, depth=depth + 1,
        )


async def _process_callout(
    callout: dict,
    documents: list[Document],
    seen: set[str],
    *,
    graphql_client,
    stats: dict,
) -> None:
    """Process a callout and its contributions."""
    framing = (callout.get("framing") or {}).get("profile") or {}
    callout_name = framing.get("displayName", "") or ""
    callout_desc = framing.get("description", "") or ""
    callout_url = framing.get("url", "") or None

    if callout_desc:
        _append_unique(
            documents, seen,
            content=f"{callout_name}\n\n{callout_desc}",
            document_id=callout["id"],
            source=f"callout:{callout['id']}",
            doc_type=DocumentType.CALLOUT.value,
            title=callout_name,
            uri=callout_url,
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
                )
