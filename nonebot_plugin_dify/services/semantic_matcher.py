import os
import random
from typing import Set
from nonebot import logger
from ..config import config


class SemanticMatcher:
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SemanticMatcher, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        # Lazy loading handled in methods
        pass

    def _load_model(self):
        """Lazy load the sentence transformer model"""
        if self._model is not None:
            return

        try:
            logger.info("Loading proactive semantic model (FastEmbed)...")

            # Set HF mirror if configured
            if config.proactive_hf_mirror:
                os.environ["HF_ENDPOINT"] = config.proactive_hf_mirror
                logger.debug(f"Set HF_ENDPOINT to {config.proactive_hf_mirror}")

            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=config.proactive_model_name)
            logger.info(f"Successfully loaded model: {config.proactive_model_name}")

        except Exception as e:
            logger.error(f"Failed to load semantic model: {e}")
            raise

    def get_similarity(self, text: str, interests: Set[str]) -> float:
        """
        Calculate the maximum cosine similarity between text and interest topics.
        """
        if not interests:
            return 0.0

        if not text or len(text.strip()) < 2:
            return 0.0

        try:
            self._load_model()

            # Encode text and interests
            # fastembed returns generators, so we listify them
            # normalize_embeddings=True by default for TextEmbedding, making dot product == cosine similarity
            text_embeddings = list(self._model.embed([text]))[0]  # Get first (and only) embedding
            interest_embeddings = list(self._model.embed(list(interests)))

            import numpy as np

            # Calculate cosine similarities (dot product since normalized)
            scores = [np.dot(text_embeddings, interest_emb) for interest_emb in interest_embeddings]

            # Get maximum similarity
            max_score = float(max(scores)) if scores else 0.0
            logger.debug(f"Semantic similarity score: {max_score:.4f} (Text: {text[:20]}...)")

            return max_score

        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            return 0.0

    def check_relevance(self, text: str) -> bool:
        """
        Check if text is relevant enough to trigger proactive intervention.
        """
        if not config.proactive_mode_enable:
            return False

        # 1. Semantic Threshold Check
        similarity = self.get_similarity(text, config.proactive_interests)
        if similarity < config.proactive_semantic_threshold:
            return False

        # 2. Random Likelihood Check
        if random.random() > config.proactive_likelihood:
            logger.debug(f"Proactive trigger skipped by probability check (Score: {similarity:.4f})")
            return False

        return True


semantic_matcher = SemanticMatcher.get_instance()
