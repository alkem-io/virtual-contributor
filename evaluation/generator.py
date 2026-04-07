"""Synthetic test pair generation from indexed content using RAGAS TestsetGenerator."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from evaluation.dataset import TestCase, write_test_cases

logger = logging.getLogger(__name__)


def _write_synthetic_cases(cases: list[TestCase], output: Path) -> None:
    """Write synthetic test cases to JSONL (shared helper for testing)."""
    write_test_cases(cases, output)


async def generate_synthetic_test_set(
    collection: str,
    count: int,
    output: Path,
) -> None:
    """Generate synthetic QA pairs from a ChromaDB collection.

    Uses RAGAS TestsetGenerator with the pipeline's local LLM and embeddings
    to create diverse test cases (simple, multi-context, reasoning).
    """
    from core.config import BaseConfig
    from core.adapters.chromadb import ChromaDBAdapter
    from core.provider_factory import create_llm_adapter
    from langchain_openai import OpenAIEmbeddings
    from langchain_core.documents import Document

    config = BaseConfig()

    # Create LLM adapter to get the LangChain chat model
    llm_adapter = create_llm_adapter(config)
    chat_model = llm_adapter._llm

    # Create embeddings
    embeddings = OpenAIEmbeddings(
        openai_api_key=config.embeddings_api_key,
        openai_api_base=config.embeddings_endpoint,
        model=config.embeddings_model_name or "text-embedding-3-small",
    )

    # Fetch source documents from ChromaDB
    ks = ChromaDBAdapter(
        host=config.vector_db_host or "localhost",
        port=config.vector_db_port,
        credentials=config.vector_db_credentials,
    )

    click.echo(f"Synthetic Generation: {collection}")

    # Get all documents from the collection (use a broad query)
    result = await ks.query(
        collection=collection,
        query_texts=[""],
        n_results=min(500, count * 10),
    )

    if not result.documents or not result.documents[0]:
        click.echo("Error: No documents found in collection", err=True)
        return

    docs = result.documents[0]
    metadatas = result.metadatas[0] if result.metadatas else [{}] * len(docs)

    click.echo(f"Source documents: {len(docs)} chunks")

    # Convert to LangChain documents
    lc_documents = [
        Document(
            page_content=doc,
            metadata=meta,
        )
        for doc, meta in zip(docs, metadatas)
    ]

    # Generate using RAGAS TestsetGenerator
    from ragas.testset import TestsetGenerator

    generator = TestsetGenerator(llm=chat_model, embedding_model=embeddings)

    click.echo(f"Generating {count} test cases...")
    testset = generator.generate_with_langchain_docs(
        documents=lc_documents,
        testset_size=count,
    )

    # Convert RAGAS testset to our TestCase format
    cases: list[TestCase] = []
    for sample in testset.samples:
        # Extract source documents from the sample's reference contexts
        relevant_docs = []
        if hasattr(sample, "reference_contexts") and sample.reference_contexts:
            for ctx in sample.reference_contexts:
                if isinstance(ctx, str) and ctx.startswith("http"):
                    relevant_docs.append(ctx)
        if not relevant_docs:
            relevant_docs = [collection]

        cases.append(TestCase(
            question=sample.user_input or "",
            expected_answer=sample.reference or sample.response or "",
            relevant_documents=relevant_docs,
        ))

    # Filter out empty cases
    cases = [c for c in cases if c.question and c.expected_answer]

    _write_synthetic_cases(cases, output)

    click.echo(f"\nGenerated: {output} ({len(cases)} cases)")
    click.echo("Review these before merging into the golden test set.")
