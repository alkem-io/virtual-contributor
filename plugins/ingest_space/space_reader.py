"""Recursive space tree reader — traverses Alkemio's 3-level hierarchy."""

from __future__ import annotations

import logging
from typing import Any

from core.domain.ingest_pipeline import Document, DocumentMetadata, DocumentType

logger = logging.getLogger(__name__)

# GraphQL query for space tree
SPACE_TREE_QUERY = """
query SpaceTree($spaceId: UUID!) {
  lookup {
    space(ID: $spaceId) {
      id
      profile { displayName description }
      collaboration {
        callouts {
          id
          type
          framing { profile { displayName description } }
          contributions {
            post { id profile { displayName description } }
            whiteboard { id profile { displayName } content }
            link { id profile { displayName } uri }
          }
        }
      }
      subspaces {
        id
        profile { displayName description }
        collaboration {
          callouts {
            id
            type
            framing { profile { displayName description } }
            contributions {
              post { id profile { displayName description } }
              whiteboard { id profile { displayName } content }
              link { id profile { displayName } uri }
            }
          }
        }
        subspaces {
          id
          profile { displayName description }
          collaboration {
            callouts {
              id
              type
              framing { profile { displayName description } }
              contributions {
                post { id profile { displayName description } }
                whiteboard { id profile { displayName } content }
                link { id profile { displayName } uri }
              }
            }
          }
        }
      }
    }
  }
}
"""


async def read_space_tree(graphql_client, space_id: str) -> list[Document]:
    """Read the full space tree and convert to Documents."""
    data = await graphql_client.query(SPACE_TREE_QUERY, {"spaceId": space_id})
    space = data.get("lookup", {}).get("space")
    if not space:
        return []

    documents: list[Document] = []
    _process_space(space, documents, depth=0)
    return documents


def _process_space(space: dict, documents: list[Document], depth: int) -> None:
    """Process a space node and its children recursively."""
    profile = space.get("profile", {})
    space_name = profile.get("displayName", "")
    description = profile.get("description", "")

    if description:
        doc_type = DocumentType.SPACE if depth == 0 else DocumentType.SUBSPACE
        documents.append(Document(
            content=f"{space_name}\n\n{description}",
            metadata=DocumentMetadata(
                document_id=space["id"],
                source=f"space:{space['id']}",
                type=doc_type.value,
                title=space_name,
            ),
        ))

    # Process callouts
    collaboration = space.get("collaboration", {})
    for callout in collaboration.get("callouts", []):
        _process_callout(callout, documents)

    # Recurse into subspaces
    for subspace in space.get("subspaces", []):
        _process_space(subspace, documents, depth + 1)


def _process_callout(callout: dict, documents: list[Document]) -> None:
    """Process a callout and its contributions."""
    framing = callout.get("framing", {}).get("profile", {})
    callout_name = framing.get("displayName", "")
    callout_desc = framing.get("description", "")

    if callout_desc:
        documents.append(Document(
            content=f"{callout_name}\n\n{callout_desc}",
            metadata=DocumentMetadata(
                document_id=callout["id"],
                source=f"callout:{callout['id']}",
                type=DocumentType.CALLOUT.value,
                title=callout_name,
            ),
        ))

    for contrib in callout.get("contributions", []):
        # Posts
        post = contrib.get("post")
        if post:
            post_profile = post.get("profile", {})
            content = post_profile.get("description", "")
            if content:
                documents.append(Document(
                    content=content,
                    metadata=DocumentMetadata(
                        document_id=post["id"],
                        source=f"post:{post['id']}",
                        type=DocumentType.POST.value,
                        title=post_profile.get("displayName", ""),
                    ),
                ))

        # Whiteboards
        whiteboard = contrib.get("whiteboard")
        if whiteboard:
            wb_content = whiteboard.get("content", "")
            if wb_content:
                documents.append(Document(
                    content=wb_content,
                    metadata=DocumentMetadata(
                        document_id=whiteboard["id"],
                        source=f"whiteboard:{whiteboard['id']}",
                        type=DocumentType.WHITEBOARD.value,
                        title=whiteboard.get("profile", {}).get("displayName", ""),
                    ),
                ))

        # Links
        link = contrib.get("link")
        if link:
            uri = link.get("uri", "")
            if uri:
                documents.append(Document(
                    content=f"Link: {uri}",
                    metadata=DocumentMetadata(
                        document_id=link["id"],
                        source=f"link:{link['id']}",
                        type=DocumentType.LINK.value,
                        title=link.get("profile", {}).get("displayName", ""),
                    ),
                ))
