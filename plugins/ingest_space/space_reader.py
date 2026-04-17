"""Recursive space tree reader — traverses Alkemio's 3-level hierarchy."""

from __future__ import annotations

import hashlib
import html as _html
import logging
import re

from core.domain.ingest_pipeline import Document, DocumentMetadata, DocumentType

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
  framing { profile { displayName description } }
  contributions {
    post { id profile { displayName description } }
    whiteboard { id profile { displayName } content }
    link { id profile { displayName description } uri }
  }
"""

SPACE_TREE_QUERY = f"""
query SpaceTree($spaceId: UUID!) {{
  lookup {{
    space(ID: $spaceId) {{
      id
      profile {{ displayName description }}
      collaboration {{
        calloutsSet {{
          callouts {{ {_CALLOUT_FIELDS} }}
        }}
      }}
      subspaces {{
        id
        profile {{ displayName description }}
        collaboration {{
          calloutsSet {{
            callouts {{ {_CALLOUT_FIELDS} }}
          }}
        }}
        subspaces {{
          id
          profile {{ displayName description }}
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
    _process_space(space, documents, seen, depth=0)
    logger.info("Space tree: emitted %d unique documents", len(documents))
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
        ),
    ))
    return True


def _process_space(
    space: dict,
    documents: list[Document],
    seen: set[str],
    depth: int,
) -> None:
    """Process a space node and its children recursively."""
    profile = space.get("profile") or {}
    space_name = profile.get("displayName", "") or ""
    description = profile.get("description", "") or ""

    if description:
        doc_type = DocumentType.SPACE if depth == 0 else DocumentType.SUBSPACE
        _append_unique(
            documents, seen,
            content=f"{space_name}\n\n{description}",
            document_id=space["id"],
            source=f"space:{space['id']}",
            doc_type=doc_type.value,
            title=space_name,
        )

    # Process callouts
    collaboration = space.get("collaboration") or {}
    callouts_set = collaboration.get("calloutsSet") or {}
    for callout in callouts_set.get("callouts") or []:
        _process_callout(callout, documents, seen)

    # Recurse into subspaces
    for subspace in space.get("subspaces") or []:
        _process_space(subspace, documents, seen, depth + 1)


def _process_callout(
    callout: dict,
    documents: list[Document],
    seen: set[str],
) -> None:
    """Process a callout and its contributions."""
    framing = (callout.get("framing") or {}).get("profile") or {}
    callout_name = framing.get("displayName", "") or ""
    callout_desc = framing.get("description", "") or ""

    if callout_desc:
        _append_unique(
            documents, seen,
            content=f"{callout_name}\n\n{callout_desc}",
            document_id=callout["id"],
            source=f"callout:{callout['id']}",
            doc_type=DocumentType.CALLOUT.value,
            title=callout_name,
        )

    for contrib in callout.get("contributions") or []:
        # Posts
        post = contrib.get("post")
        if post:
            post_profile = post.get("profile") or {}
            content = post_profile.get("description", "") or ""
            if content:
                _append_unique(
                    documents, seen,
                    content=content,
                    document_id=post["id"],
                    source=f"post:{post['id']}",
                    doc_type=DocumentType.POST.value,
                    title=post_profile.get("displayName", "") or "",
                )

        # Whiteboards
        whiteboard = contrib.get("whiteboard")
        if whiteboard:
            wb_content = whiteboard.get("content", "") or ""
            if wb_content:
                _append_unique(
                    documents, seen,
                    content=wb_content,
                    document_id=whiteboard["id"],
                    source=f"whiteboard:{whiteboard['id']}",
                    doc_type=DocumentType.WHITEBOARD.value,
                    title=(whiteboard.get("profile") or {}).get("displayName", "") or "",
                )

        # Links
        link = contrib.get("link")
        if link:
            uri = link.get("uri", "") or ""
            link_profile = link.get("profile") or {}
            link_title = link_profile.get("displayName", "") or ""
            link_desc = link_profile.get("description", "") or ""
            if uri or link_title or link_desc:
                parts = [p for p in (link_title, link_desc) if p]
                parts.append(f"URL: {uri}" if uri else "")
                content = "\n\n".join(p for p in parts if p)
                _append_unique(
                    documents, seen,
                    content=content,
                    document_id=link["id"],
                    source=f"link:{link['id']}",
                    doc_type=DocumentType.LINK.value,
                    title=link_title,
                )
